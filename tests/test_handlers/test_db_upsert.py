"""Exercise scoped database write statements without a live PostgreSQL server."""

from copy import deepcopy
from unittest.mock import MagicMock, Mock

import pytest
from geoalchemy2 import Geometry
from pyproj import CRS
from shapely.geometry import Point
from sqlalchemy import Column, MetaData, Table, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from landlensdb.handlers import db as module


@pytest.fixture
def writer(monkeypatch):
    table = Table(
        "images",
        MetaData(),
        Column("image_url", Text),
        Column("geometry", Geometry(geometry_type="POINT", srid=3857)),
        Column("input_sha", Text),
        Column("fingerprint", Text),
        Column("thumbnail", Text),
        Column("metadata", JSONB),
    )
    monkeypatch.setattr(module, "Table", lambda *args, **kwargs: table)
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.rowcount = 0
    connection.execute.return_value.first.return_value = ("photo.jpg",)
    database = module.Postgres(engine)
    database._thumbnail_to_gdal_raster = Mock(return_value=b"raster")
    record = {
        "image_url": "photo.jpg",
        "geometry": Point(10, 20),
        "input_sha": "group-a",
        "fingerprint": None,
        "thumbnail": "thumbnail",
    }
    frame = Mock(crs=CRS.from_epsg(3857))
    frame.to_dict.side_effect = lambda **kwargs: [deepcopy(record)]
    return database, connection, frame, record


def statements(connection):
    return [
        call.args[0].compile(dialect=postgresql.dialect())
        for call in connection.execute.call_args_list
    ]


def test_projected_import_preserves_srid_when_widening_geometry_type(writer):
    database, connection, frame, _ = writer
    database.upsert_images(frame, "images")
    compiled = statements(connection)
    assert "geometry(Geometry, 3857)" in str(compiled[0])
    assert "ST_SetSRID" not in str(compiled[0])
    insert = next(
        statement for statement in compiled if str(statement).startswith("INSERT")
    )
    assert insert.params["geometry"] == "SRID=3857;POINT (10 20)"


@pytest.mark.parametrize("conflict", ["nothing", "update"])
def test_skipped_insert_or_other_group_never_updates_thumbnail(writer, conflict):
    database, connection, frame, _ = writer
    connection.execute.return_value.first.return_value = None
    database.upsert_images(frame, "images", conflict=conflict, input_sha="group-a")
    database._thumbnail_to_gdal_raster.assert_not_called()
    assert not any(
        "ST_FromGDALRaster" in str(statement) for statement in statements(connection)
    )


def test_group_scope_limits_fingerprint_and_path_updates(writer):
    database, connection, frame, record = writer
    record["fingerprint"] = "same-content"
    database.upsert_images(frame, "images", input_sha="group-a")
    compiled = statements(connection)
    fingerprint_update = next(
        statement
        for statement in compiled
        if "WHERE images.fingerprint" in str(statement)
    )
    assert "AND images.input_sha =" in str(fingerprint_update)
    assert "group-a" in fingerprint_update.params.values()
    insert = next(
        statement for statement in compiled if str(statement).startswith("INSERT")
    )
    assert "WHERE images.input_sha =" in str(insert)
    assert "RETURNING images.image_url" in str(insert)


def test_added_image_receives_thumbnail_when_insert_succeeds(writer):
    database, connection, frame, _ = writer
    database.upsert_images(frame, "images", conflict="nothing")
    database._thumbnail_to_gdal_raster.assert_called_once_with("thumbnail")
    assert any(
        "ST_FromGDALRaster" in str(statement) for statement in statements(connection)
    )


def test_upsert_keeps_import_parameters_as_nested_json_object(writer):
    database, connection, frame, record = writer
    record["metadata"] = {"sensor": "test", "import_params": {"file_glob": "./*.tif"}}
    database.upsert_images(frame, "images")
    insert = next(
        item for item in statements(connection) if str(item).startswith("INSERT")
    )
    assert insert.params["metadata"] == record["metadata"]
    assert isinstance(insert.params["metadata"]["import_params"], dict)
    assert "import_params" not in insert.params
