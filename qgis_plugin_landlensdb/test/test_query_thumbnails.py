"""Exercise Query thumbnail actions and native PostGIS raster URI handling."""

from unittest.mock import MagicMock, Mock

import pytest
from osgeo import gdal, osr
from qgis.core import QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsVectorLayer

from ..tabs import query_tab as module
from .utilities import get_qgis_app

QGIS_APP = get_qgis_app()


@pytest.fixture
def tab(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(module.psycopg2, "connect", connect)
    widget = module.QueryTab(None)
    widget.connection_values = {
        "host": "localhost",
        "port": "5432",
        "database": "test",
        "schema": "survey",
    }
    widget._show_error = Mock()
    widget._show_info = Mock()
    yield widget
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().layerTreeRoot().removeAllChildren()
    widget.close()
    widget.deleteLater()


@pytest.mark.parametrize(
    "statement,schema,table",
    [
        (
            "SELECT * FROM images WHERE name = 'scene'",
            "survey",
            "images",
        ),
        ("SELECT * FROM public.images", "public", "images"),
        ("SELECT * FROM IMAGES", "survey", "images"),
        ('SELECT * FROM "Survey"."Image"', "Survey", "Image"),
        ('SELECT * FROM "im""ages"', "survey", 'im"ages'),
        (
            "SELECT * FROM images AS i WHERE i.name = 'scene'",
            "survey",
            "images",
        ),
    ],
)
def test_source_detection_supports_unqualified_tables_and_aliases(
    tab, statement, schema, table
):
    expected = {"schema": schema, "table": table}
    assert tab._parse_query_source(statement) == expected


def test_raster_uri_round_trips_exact_image_path_and_ignores_query_alias(tab):
    image_url = "/images/O'Brien $lldb$ scene.jpg"
    source = {"schema": 'sur"vey', "table": "images", "where": "i.name = 'scene'"}
    uri = QgsDataSourceUri(
        tab._build_postgres_raster_uri(
            source, "thumbnail", tab._build_thumbnail_row_filter(image_url)
        )
    )
    assert uri.schema() == 'sur"vey'
    assert uri.table() == "images"
    assert uri.geometryColumn() == "thumbnail"
    assert uri.keyColumn() == "image_url"
    assert (
        uri.sql()
        == "(\"image_url\" = '/images/O''Brien $lldb$ scene.jpg') AND \"thumbnail\" IS NOT NULL"
    )
    assert "i.name" not in uri.sql()


def test_preview_uses_physical_raster_column_when_select_aliases_it(tab, monkeypatch):
    tab.sql_input.setPlainText(
        "SELECT i.image_url, i.thumbnail AS preview FROM images i WHERE i.name = 'scene'"
    )
    columns = Mock(
        side_effect=[
            [
                {"name": "image_url", "udt_name": "text"},
                {"name": "preview", "udt_name": "raster"},
            ],
            [
                {"name": "image_url", "udt_name": "text"},
                {"name": "thumbnail", "udt_name": "raster"},
            ],
        ]
    )
    monkeypatch.setattr(tab, "_get_column_info", columns)
    monkeypatch.setattr(tab, "_get_row_count", lambda *args: 1)
    monkeypatch.setattr(tab, "_get_preview_rows", lambda *args: [])
    tab._run_query_preview(add_to_history=False)
    assert tab._last_query_state["raster_source"]["table"] == "images"
    assert tab._last_query_state["raster_columns"] == ["thumbnail"]
    assert "i.name" not in columns.call_args_list[1].args[1]
    tab._show_error.assert_not_called()


@pytest.mark.parametrize("source_srid", [None, 4326, 3857])
@pytest.mark.parametrize(
    "action,grouped",
    [
        ("Add Thumbnail", False),
        ("Add Both", False),
        ("Add Thumbnail", True),
        ("Add Both", True),
    ],
)
def test_add_actions_register_rasters_in_project_and_thumbnail_group(
    tab, monkeypatch, tmp_path, action, grouped, source_srid
):
    path = tmp_path / "thumbnail.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 4, 4, 3, gdal.GDT_Byte)
    if source_srid is not None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(source_srid)
        dataset.SetProjection(srs.ExportToWkt())
    dataset.SetGeoTransform((-158, 0.1, 0, 22, 0, -0.1))
    for band in range(1, 4):
        dataset.GetRasterBand(band).Fill(60 * band)
    dataset = None
    statement = "SELECT * FROM images"
    tab.sql_input.setPlainText(statement)
    tab._last_query_state = {
        "sql_text": statement,
        "query_name": "Test thumbnails",
        "live_query": statement,
        "column_names": (
            ["image_url", "category"] if grouped else ["image_url", "geometry"]
        ),
        "column_info": [
            {"name": "image_url", "udt_name": "_text" if grouped else "text"}
        ],
        "raster_source": {"schema": "survey", "table": "images", "where": ""},
        "raster_columns": ["thumbnail"],
        "vector_column": "geometry",
    }
    tab._update_add_buttons_state()
    monkeypatch.setattr(tab, "_fetch_add_image_urls", lambda: ["/images/scene.tif"])
    monkeypatch.setattr(
        tab,
        "_fetch_group_rows",
        lambda **kwargs: [{"category": "group", "image_url": ["/images/scene.tif"]}],
    )
    cursor = (
        module.psycopg2.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    )
    cursor.fetchall.return_value = [("/images/scene.tif",)]
    calls = []

    def raster_factory(uri, name, provider):
        calls.append((QgsDataSourceUri(uri), provider))
        # Prevent QGIS's global CRS picker in this headless test only.
        options = QgsRasterLayer.LayerOptions()
        options.skipCrsValidation = True
        return QgsRasterLayer(str(path), name, "gdal", options)

    monkeypatch.setattr(module, "QgsRasterLayer", raster_factory)
    monkeypatch.setattr(tab, "_get_geometry_types", lambda *args: ["ST_Polygon"])
    monkeypatch.setattr(
        tab,
        "_create_vector_layer",
        lambda *args: QgsVectorLayer("Polygon?crs=EPSG:4326", "geometry", "memory"),
    )
    root = QgsProject.instance().layerTreeRoot()
    root.addGroup("Existing layers")
    next(
        item for item in tab.add_menu_button.menu().actions() if item.text() == action
    ).trigger()
    project = QgsProject.instance()
    assert [child.name() for child in root.children()] == [
        "Test thumbnails",
        "Existing layers",
    ]
    layers = list(project.mapLayers().values())
    assert len(layers) == (2 if action == "Add Both" else 1)
    assert len(calls) == 1
    assert calls[0][1] == "postgresraster"
    assert calls[0][0].geometryColumn() == "thumbnail"
    rasters = [layer for layer in layers if isinstance(layer, QgsRasterLayer)]
    assert len(rasters) == 1 and rasters[0].isValid()
    assert rasters[0].crs().authid() == (
        "EPSG:{}".format(source_srid) if source_srid else ""
    )
    node = project.layerTreeRoot().findLayer(rasters[0].id())
    assert node.parent().name() == "thumbnail"
    assert node.isVisible()
    tab._show_error.assert_not_called()


def test_missing_thumbnails_do_not_create_invalid_layers(tab, monkeypatch):
    tab._last_query_state = {
        "raster_source": {"schema": "survey", "table": "images"},
        "raster_columns": ["thumbnail"],
    }
    monkeypatch.setattr(tab, "_get_thumbnail_image_urls", lambda *args: [])
    create = Mock()
    monkeypatch.setattr(tab, "_create_raster_layer", create)
    group = QgsProject.instance().layerTreeRoot().addGroup("thumbnail")
    assert tab._add_thumbnail_layers_for_image_urls(group, ["missing.jpg"]) == []
    create.assert_not_called()


def test_missing_raster_crs_is_not_invented(tab, monkeypatch):
    layer = Mock()
    layer.isValid.return_value = True
    layer.crs.return_value.isValid.return_value = False
    factory = Mock(return_value=layer)
    monkeypatch.setattr(module, "QgsRasterLayer", factory)
    result = tab._create_raster_layer(
        {"schema": "survey", "table": "images"},
        "thumbnail",
        "image_url = 'image'",
        "image",
    )
    assert result is layer
    layer.setCrs.assert_not_called()
    tab._show_error.assert_not_called()
