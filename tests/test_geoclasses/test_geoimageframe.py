from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from landlensdb.geoclasses.geoimageframe import (
    GeoImageFrame,
    _generate_arrow_icon,
    _generate_arrow_svg,
)
from landlensdb.handlers.db import Postgres
from landlensdb.handlers.importer import import_local_images


def test_generate_arrow_icon():
    icon = _generate_arrow_icon(90)
    assert icon is not None, "Icon should not be None"


def test_generate_arrow_svg():
    svg_str = _generate_arrow_svg(45)
    assert svg_str is not None, "SVG string should not be None"


def test_geoimageframe_initialization(sample_data):
    gdf = GeoImageFrame(sample_data)
    assert gdf is not None, "GeoImageFrame should not be None"


def test_verify_structure(sample_geoimageframe):
    # Testing if structure is verified without error
    sample_geoimageframe._verify_structure()


def test_incomplete_projection_uses_base_frame(sample_geoimageframe):
    tabular_projection = sample_geoimageframe[["name"]]
    geospatial_projection = sample_geoimageframe[["name", "geometry"]]

    assert type(tabular_projection) is pd.DataFrame
    assert type(geospatial_projection) is gpd.GeoDataFrame


def test_complete_operations_preserve_geoimageframe(sample_geoimageframe):
    assert type(sample_geoimageframe.copy()) is GeoImageFrame
    assert type(sample_geoimageframe.head()) is GeoImageFrame


def test_wide_geoimageframe_repr(sample_geoimageframe):
    wide_frame = sample_geoimageframe.assign(
        **{f"extra_{index}": index for index in range(20)}
    )

    assert "image_url" in repr(wide_frame)


def test_explicit_incomplete_construction_still_fails():
    with pytest.raises(ValueError, match="required column 'image_url'"):
        GeoImageFrame({"name": ["Sample"], "geometry": [Point(0, 0)]})


def test_mapping_uses_current_metadata_heading_and_upstream_colors(tmp_path):
    import base64
    from PIL import Image

    image = tmp_path / "photo.jpg"
    Image.new("RGB", (600, 300), "red").save(image)
    frame = GeoImageFrame(
        {
            "name": ["Photo"],
            "image_url": [str(image)],
            "geometry": [Point(1, 2)],
            "metadata": [{"sensor": {"compass_angle": 45}}],
        },
        index=[7],
        crs="EPSG:4326",
    )
    html = (
        frame.map(marker_color="#123456", additional_properties=["absent_column"])
        .get_root()
        .render()
    )
    expected = base64.b64encode(
        _generate_arrow_svg(45, color="#123456").encode()
    ).decode()
    assert expected in html
    assert "data:image/jpeg;base64," in frame._popup_html(7, str(image), [])


def test_to_dict_records(sample_geoimageframe):
    records = sample_geoimageframe.to_dict_records()
    assert isinstance(records, list), "Should return a list"


def test_geoimageframe_accepts_metadata_column():
    gdf = GeoImageFrame(
        {
            "image_url": ["http://example.com/image.jpg"],
            "name": ["Sample"],
            "metadata": [{"source": {"path": "http://example.com/image.jpg"}}],
            "geometry": [Point(0, 0)],
        }
    )
    assert isinstance(gdf.at[0, "metadata"], dict)


def test_geotagged_image_loads_metadata_and_thumbnail_columns():
    images = import_local_images(
        {
            "file_glob": str(Path("test_data/local").resolve() / "**/*.jpg"),
            "name": "file.name",
            "image_url": "file.path",
            "geometry": "point_from_exif",
            "thumbnail": {"enabled": False},
        }
    )

    assert "metadata" in images.columns
    assert "thumbnail" in images.columns
    assert isinstance(images.iloc[0]["metadata"], dict)
    assert images.iloc[0]["thumbnail"] is None


def test_import_images_builds_user_defined_metadata():
    images = import_local_images(
        {
            "file_glob": str(Path("test_data/local").resolve() / "**/*.jpg"),
            "name": "file.name",
            "image_url": "file.path",
            "geometry": "point_from_exif",
            "metadata": {"camera": {"model": "exif.Model"}},
            "thumbnail": {"enabled": False},
        }
    )

    assert len(images) > 0
    assert "camera" in images.iloc[0]["metadata"]


def test_to_postgis_delegates_to_postgres_upsert_images(
    monkeypatch, sample_geoimageframe
):
    captured = {}
    fake_engine = type(
        "FakeEngine",
        (),
        {"connect": lambda self: None},
    )()

    def fake_upsert(
        self, gif, table_name, conflict="update", if_exists="upsert", *args, **kwargs
    ):
        captured["gif"] = gif
        captured["table_name"] = table_name
        captured["if_exists"] = if_exists
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(Postgres, "upsert_images", fake_upsert)

    result = sample_geoimageframe.to_postgis(
        "images", fake_engine, if_exists="append", chunksize=100
    )

    assert result == "ok"
    assert captured["gif"] is sample_geoimageframe
    assert captured["table_name"] == "images"
    assert captured["if_exists"] == "append"
    assert captured["kwargs"] == {"chunksize": 100}
