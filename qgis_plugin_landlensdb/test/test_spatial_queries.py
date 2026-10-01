"""Exercise native map rectangle selection and spatial SQL insertion in QGIS."""

import json
import re
from unittest.mock import Mock

import pytest
from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry, QgsRectangle
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapToolExtent, QgsMapToolPan

from ..tabs.query_tab import QueryTab
from .utilities import get_qgis_app

QGIS_APP = get_qgis_app()


@pytest.fixture
def query():
    canvas = QgsMapCanvas()
    canvas.resize(500, 400)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    canvas.setExtent(QgsRectangle(0, 0, 1000, 800))
    previous_tool = QgsMapToolPan(canvas)
    canvas.setMapTool(previous_tool)
    iface = Mock()
    iface.mapCanvas.return_value = canvas
    window = QtWidgets.QDialog()
    tab = QueryTab(iface, window)
    tab._metadata_loaded = True
    layout = QtWidgets.QVBoxLayout(window)
    layout.addWidget(tab)
    tab.sql_input.setPlainText('SELECT * FROM "public"."images" WHERE')
    cursor = tab.sql_input.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    tab.sql_input.setTextCursor(cursor)
    window.show()
    canvas.show()
    QtWidgets.QApplication.processEvents()
    yield tab, canvas, window, previous_tool
    tab._finish_bbox_selection(show_window=False)
    window.close()
    canvas.close()
    window.deleteLater()
    canvas.deleteLater()


def mouse_event(canvas, kind, point, button=QtCore.Qt.LeftButton):
    return QgsMapMouseEvent(canvas, kind, point, button, button, QtCore.Qt.NoModifier)


def test_query_buttons_and_file_dialog_cancel(query, monkeypatch):
    tab, _, _, _ = query
    assert [
        tab.row_five_layout.itemAt(index).widget().text() for index in range(3)
    ] == ["File Spatial Query", "Select Bbox Query", "Metadata Query"]
    chooser = Mock(return_value=("", ""))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", chooser)
    initial_sql = tab.sql_input.toPlainText()
    tab.file_spatial_query_button.click()
    chooser.assert_called_once()
    assert tab.sql_input.toPlainText() == initial_sql


def test_drag_inserts_bbox_once_and_restores_window_and_previous_tool(query):
    tab, canvas, window, previous = query
    initial_sql = tab.sql_input.toPlainText()
    tab.bbox_query_button.click()
    tool = tab._bbox_tool
    assert isinstance(tool, QgsMapToolExtent)
    assert canvas.mapTool() is tool
    assert not window.isVisible()
    start, end = QtCore.QPoint(50, 60), QtCore.QPoint(350, 300)
    expected = QgsRectangle(tool.toMapCoordinates(start), tool.toMapCoordinates(end))
    tool.canvasPressEvent(mouse_event(canvas, QtCore.QEvent.MouseButtonPress, start))
    tool.canvasMoveEvent(mouse_event(canvas, QtCore.QEvent.MouseMove, end))
    assert tab.sql_input.toPlainText() == initial_sql
    tool.canvasReleaseEvent(mouse_event(canvas, QtCore.QEvent.MouseButtonRelease, end))

    sql = tab.sql_input.toPlainText()
    assert sql.startswith(initial_sql + " ST_Intersects(geometry, ST_Transform(")
    assert sql.count("ST_Intersects") == 1
    assert ", 3857), ST_SRID(geometry)))" in sql
    selected = QgsGeometry.fromWkt(
        re.search(r"ST_GeomFromText\('([^']+)'", sql).group(1)
    )
    assert selected.boundingBox() == expected
    assert tab._bbox_tool is None
    assert canvas.mapTool() is previous
    assert window.isVisible()


@pytest.mark.parametrize("method", ["escape", "right_click", "switch_tool"])
def test_cancel_preserves_sql_and_restores_dialog(query, method):
    tab, canvas, window, previous = query
    original = tab.sql_input.toPlainText()
    tab.bbox_query_button.click()
    tool = tab._bbox_tool
    expected_tool = previous
    if method == "escape":
        tool.keyPressEvent(
            QtGui.QKeyEvent(
                QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier
            )
        )
    elif method == "right_click":
        tool.canvasPressEvent(
            mouse_event(
                canvas,
                QtCore.QEvent.MouseButtonPress,
                QtCore.QPoint(20, 20),
                QtCore.Qt.RightButton,
            )
        )
    else:
        expected_tool = QgsMapToolPan(canvas)
        canvas.setMapTool(expected_tool)
    assert tab._bbox_tool is None
    assert canvas.mapTool() is expected_tool
    assert tab.sql_input.toPlainText() == original
    assert window.isVisible()


def test_click_without_drag_waits_for_a_real_bbox(query):
    tab, canvas, window, _ = query
    original = tab.sql_input.toPlainText()
    tab.bbox_query_button.click()
    tool = tab._bbox_tool
    point = QtCore.QPoint(20, 20)
    tool.canvasPressEvent(mouse_event(canvas, QtCore.QEvent.MouseButtonPress, point))
    tool.canvasReleaseEvent(
        mouse_event(canvas, QtCore.QEvent.MouseButtonRelease, point)
    )
    assert tab._bbox_tool is tool
    assert tab.sql_input.toPlainText() == original
    assert not window.isVisible()


def test_repeated_selections_do_not_leave_old_signal_handlers(query):
    tab, _, _, previous = query
    for _ in range(2):
        tab.bbox_query_button.click()
        tab._bbox_tool.extentChanged.emit(QgsRectangle(0, 0, 1, 1))
    assert tab.sql_input.toPlainText().count("ST_Intersects") == 2
    assert tab._bbox_canvas.mapTool() is previous


def test_selection_without_previous_tool_can_be_cancelled(query):
    tab, canvas, window, previous = query
    canvas.unsetMapTool(previous)
    tab.bbox_query_button.click()
    tab._bbox_tool.cancelled.emit()
    assert tab._bbox_tool is None
    assert canvas.mapTool() is None
    assert window.isVisible()


@pytest.mark.parametrize(
    "geometry, function",
    [
        ({"type": "Point", "coordinates": [10, 20]}, "ST_DWithin"),
        (
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "ST_Intersects",
        ),
    ],
)
def test_file_spatial_query_uses_shared_spatial_condition(
    query, tmp_path, monkeypatch, geometry, function
):
    tab, _, _, _ = query
    path = tmp_path / "source.geojson"
    path.write_text(
        json.dumps({"type": "Feature", "geometry": geometry, "properties": {}})
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (str(path), "")
    )
    tab.file_spatial_query_button.click()
    sql = tab.sql_input.toPlainText()
    assert function + "(geometry, ST_Transform(" in sql
    assert ", 4326), ST_SRID(geometry))" in sql
    if function == "ST_DWithin":
        assert sql.endswith(", 0)")


def test_no_canvas_reports_error_without_changing_sql(query):
    tab, _, _, _ = query
    tab.iface = None
    original = tab.sql_input.toPlainText()
    tab.bbox_query_button.click()
    assert "map canvas is required" in tab.status_output.toPlainText()
    assert tab.sql_input.toPlainText() == original


def test_invalid_map_crs_does_not_start_selection(query):
    tab, canvas, window, previous = query
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem())
    tab.bbox_query_button.click()
    assert tab._bbox_tool is None
    assert canvas.mapTool() is previous
    assert window.isVisible()
    assert "coordinate reference system" in tab.status_output.toPlainText()


def test_cleanup_does_not_reopen_window_when_plugin_closes(query):
    tab, canvas, window, previous = query
    tab.bbox_query_button.click()
    tab._finish_bbox_selection(show_window=False)
    assert not window.isVisible()
    assert canvas.mapTool() is previous
