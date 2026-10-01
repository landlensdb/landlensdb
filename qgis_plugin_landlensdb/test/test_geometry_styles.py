"""Check point styling through the shared Query/View layer creation path."""

from pathlib import Path

import pytest
from qgis.PyQt import QtCore
from qgis.core import QgsSvgMarkerSymbolLayer, QgsVectorLayer

from ..tabs import query_tab as module
from .utilities import get_qgis_app

QGIS_APP = get_qgis_app()


@pytest.fixture
def tab():
    settings = QtCore.QSettings()
    key = module.QueryTab.POINT_STYLE_KEY
    previous = settings.value(key)
    settings.remove(key)
    widget = module.QueryTab(None)
    yield widget
    widget.close()
    widget.deleteLater()
    if previous is None:
        settings.remove(key)
    else:
        settings.setValue(key, previous)


def test_style_menu_placement_choices_and_saved_point_selection(tab):
    assert tab.buttonLayout.indexOf(tab.geometry_style_button) + 1 == (
        tab.buttonLayout.indexOf(tab.query_button)
    )
    categories = tab.geometry_style_button.menu().actions()
    assert [action.text() for action in categories] == ["Point", "Polygon"]
    points = categories[0].menu().actions()
    assert [action.text() for action in points] == ["Camera direction icon", "Point"]
    assert [action.isChecked() for action in points] == [True, False]
    polygons = categories[1].menu().actions()
    assert [action.text() for action in polygons] == ["Polygon"]
    polygons[0].trigger()
    assert polygons[0].isChecked()
    assert points[0].isChecked()

    points[1].trigger()
    assert [action.isChecked() for action in points] == [False, True]
    reopened = module.QueryTab(None)
    try:
        assert reopened.point_style_group.checkedAction().data() == "point"
    finally:
        reopened.close()
        reopened.deleteLater()


@pytest.mark.parametrize(
    "geometry,uses_camera",
    [
        ("Point", True),
        ("MultiPoint", True),
        ("PointZ", True),
        ("Polygon", False),
        ("MultiPolygon", False),
        ("LineString", False),
    ],
)
def test_layer_creation_styles_only_point_geometries(
    tab, monkeypatch, geometry, uses_camera
):
    layer = QgsVectorLayer(
        f"{geometry}?crs=EPSG:4326&field=image_url:string", "geometry", "memory"
    )
    original_renderer = layer.renderer()
    monkeypatch.setattr(module, "QgsVectorLayer", lambda *args: layer)
    created = tab._create_vector_layer("SELECT * FROM images", "geometry", "geometry")
    assert created is layer
    if uses_camera:
        symbol = layer.renderer().symbol()
        assert symbol.symbolLayerCount() == 1
        marker = symbol.symbolLayer(0)
        assert isinstance(marker, QgsSvgMarkerSymbolLayer)
        assert Path(marker.path()).is_file()
        assert Path(marker.path()).name == "camera_upward_direction_marker.svg"
        assert marker.size() == 6
    else:
        assert layer.renderer() is original_renderer
    assert layer.customProperty("landlensdb/query_text") == "SELECT * FROM images"
    assert any(action.name() == "Open Image" for action in layer.actions().actions())


def test_plain_point_preserves_original_renderer(tab, monkeypatch):
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "geometry", "memory")
    original_renderer = layer.renderer()
    tab.point_style_group.actions()[1].trigger()
    monkeypatch.setattr(module, "QgsVectorLayer", lambda *args: layer)
    assert tab._create_vector_layer("SELECT * FROM images", "geometry", "geometry") is layer
    assert layer.renderer() is original_renderer


def test_unknown_saved_style_falls_back_to_camera(tab):
    QtCore.QSettings().setValue(tab.POINT_STYLE_KEY, "removed-style")
    reopened = module.QueryTab(None)
    try:
        assert reopened.point_style_group.checkedAction().data() == "camera"
    finally:
        reopened.close()
        reopened.deleteLater()
