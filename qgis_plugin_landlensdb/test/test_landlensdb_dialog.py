# coding=utf-8
"""Dialog test."""

__author__ = "cankanoa@gmail.com"
__date__ = "2026-03-13"
__copyright__ = "Copyright 2026, Kanoa Lindiwe LLC"

import json
import unittest

from qgis.PyQt import QtCore, QtGui, QtWidgets

from ..landlensdb_dialog import LandlensdbDialog
from ..landlensdb.import_config import load_example_import_json, load_import_presets
from ..shared.import_settings import (
    IMPORT_PARAMETERS_KEY,
    load_import_parameters,
    save_import_parameters,
)
from ..shared.json_editor import ImportJsonDialog
from ..tabs.view_tab import ImageCanvas, ImageScrollArea
from .utilities import get_qgis_app

QGIS_APP = get_qgis_app()


def import_config_json(file_glob):
    return json.dumps(
        {
            "file_glob": file_glob,
            "name": "file.name",
            "image_url": "file.path",
            "geometry": "point_from_exif",
        }
    )


class LandlensdbDialogTest(unittest.TestCase):
    """Test top-level tabs and query widgets exist."""

    def setUp(self):
        """Runs before each test."""
        self.dialog = LandlensdbDialog(None)

    def tearDown(self):
        """Runs after each test."""
        self.dialog = None

    def test_dialog_has_tabs_and_query_controls(self):
        """The tabbed dialog and query workflow widgets should be available."""
        self.assertEqual(self.dialog.tab_widget.count(), 5)
        self.assertEqual(self.dialog.tab_widget.tabText(0), "Overview")
        self.assertEqual(self.dialog.tab_widget.tabText(1), "Setup")
        self.assertEqual(self.dialog.tab_widget.tabText(2), "Import")
        self.assertEqual(self.dialog.tab_widget.tabText(3), "Query")
        self.assertEqual(self.dialog.tab_widget.tabText(4), "View")

        query_tab = self.dialog.query_tab
        self.assertFalse(hasattr(query_tab, "connection_button"))
        self.assertEqual(query_tab.commands_toggle_button.text(), "Commands")
        self.assertEqual(query_tab.history_menu_button.text(), "History")
        self.assertEqual(query_tab.star_menu_button.text(), "Star")
        self.assertEqual(query_tab.query_button.text(), "Query")
        self.assertEqual(query_tab.add_button.text(), "Add")
        self.assertEqual(query_tab.close_button.text(), "Close")
        query_tab._populate_copy_menu()
        self.assertNotIn(
            "Fetch Metadata Structure",
            [action.text() for action in query_tab.copy_menu.actions()],
        )
        self.assertFalse(hasattr(query_tab, "additional_metadata_refresh_button"))

        setup_tab = self.dialog.setup_tab
        self.assertTrue(setup_tab.server_conda_radio.isChecked())
        self.assertEqual(setup_tab.server_stack.currentIndex(), 3)
        requirements = setup_tab.server_requirements_label.text()
        self.assertIn("PostgreSQL 14+", requirements)
        self.assertIn("postgis_raster", requirements)
        self.assertIn("GDAL raster drivers", requirements)

    def test_view_outer_area_ignores_wheel_but_keeps_scrollbar(self):
        class WheelEvent:
            def __init__(self):
                self.accepted = False

            def accept(self):
                self.accepted = True

        scroll_area = ImageScrollArea()
        scrollbar = scroll_area.verticalScrollBar()
        scrollbar.setRange(0, 100)
        scrollbar.setValue(40)

        event = WheelEvent()
        scroll_area.wheelEvent(event)

        self.assertTrue(event.accepted)
        self.assertEqual(scrollbar.value(), 40)
        scrollbar.setValue(60)
        self.assertEqual(scrollbar.value(), 60)

    def test_image_canvas_consumes_wheel_and_zooms(self):
        class WheelEvent:
            def __init__(self):
                self.accepted = False

            def angleDelta(self):
                return QtCore.QPoint(0, 120)

            def accept(self):
                self.accepted = True

        canvas = ImageCanvas()
        canvas.resize(300, 220)
        pixmap = QtGui.QPixmap(1200, 800)
        pixmap.fill(QtGui.QColor("black"))
        canvas.set_pixmap(pixmap)
        initial_scale = canvas._current_scale

        event = WheelEvent()
        canvas.wheelEvent(event)

        self.assertTrue(event.accepted)
        self.assertGreater(canvas._current_scale, initial_scale)

    def test_import_rows_are_grouped_by_input_sha(self):
        """The import tab displays one row for each canonical input SHA."""
        import_tab = self.dialog.import_tab
        first_json = import_config_json("/photos/first/**/*.jpg")
        second_json = import_config_json("/photos/second/**/*.tif")
        import_tab.load_records(
            [
                {
                    "input_sha": "a" * 64,
                    "row_count": 2,
                    "import_params": first_json,
                },
                {
                    "input_sha": "b" * 64,
                    "row_count": 3,
                    "import_params": second_json,
                },
            ]
        )

        self.assertEqual(import_tab.import_table.rowCount(), 2)
        self.assertEqual(
            import_tab.import_table.item(0, import_tab.COUNT_COLUMN).text(), "2"
        )
        self.assertEqual(
            import_tab.import_table.item(1, import_tab.COUNT_COLUMN).text(), "3"
        )
        self.assertEqual(
            import_tab.import_table.item(0, import_tab.COUNT_COLUMN).data(
                QtCore.Qt.UserRole
            ),
            "a" * 64,
        )
        self.assertEqual(
            import_tab.import_table.item(0, import_tab.FILE_GLOB_COLUMN).text(),
            "/photos/first/**/*.jpg",
        )
        self.assertEqual(
            [
                import_tab.import_table.horizontalHeaderItem(column).text()
                for column in range(import_tab.import_table.columnCount())
            ],
            ["Rows", "file_glob", "import_params", "Actions"],
        )
        params_button = import_tab.import_table.cellWidget(
            0, import_tab.IMPORT_PARAMS_COLUMN
        )
        self.assertEqual(params_button.text(), "View JSON")
        opened_json = []
        import_tab._fetch_first_import_params = lambda input_sha: (
            first_json if input_sha == "a" * 64 else None
        )
        import_tab._show_group_import_parameters = opened_json.append
        params_button.click()
        self.assertEqual(opened_json, [first_json])
        self.assertEqual(import_tab.open_json_button.text(), "Import Parameters…")
        self.assertFalse(hasattr(import_tab, "connection_button"))
        self.assertFalse(hasattr(import_tab, "skip_existing_input"))
        expected_actions = [
            "Update",
            "Update New",
            "Drop Old",
            "Drop All",
            "Fetch Metadata Structure",
        ]
        self.assertEqual(
            [action.text() for action in import_tab.actions_button.menu().actions()],
            expected_actions,
        )
        row_actions = import_tab.import_table.cellWidget(0, import_tab.ACTIONS_COLUMN)
        self.assertEqual(
            [action.text() for action in row_actions.menu().actions()],
            expected_actions
            + [
                "Folder Update",
                "Folder Update New",
                "Folder Drop Old",
                "Folder Drop All",
            ],
        )
        fetched = []
        import_tab.fetch_metadata = fetched.append
        for button in (import_tab.actions_button, row_actions):
            next(
                action
                for action in button.menu().actions()
                if action.text() == "Fetch Metadata Structure"
            ).trigger()
        self.assertEqual(fetched, ["all", "a" * 64])

    def test_import_editor_saves_one_settings_document(self):
        settings = QtCore.QSettings()
        had_original = settings.contains(IMPORT_PARAMETERS_KEY)
        original = settings.value(IMPORT_PARAMETERS_KEY) if had_original else None
        try:
            save_import_parameters(import_config_json("/tmp/*.jpg"))
            self.assertEqual(
                load_import_parameters("default"),
                import_config_json("/tmp/*.jpg"),
            )
            dialog = ImportJsonDialog(
                load_example_import_json(),
                lambda value: value,
            )
            self.assertEqual(dialog.save_button.text(), "Save")
            self.assertEqual(dialog.copy_button.text(), "Copy")
            dialog.copy_button.click()
            self.assertEqual(
                QtWidgets.QApplication.clipboard().text(), dialog.json_text()
            )
            self.assertFalse(hasattr(dialog, "reset_button"))
            self.assertFalse(hasattr(dialog, "normalize_button"))
            self.assertEqual(
                [action.text() for action in dialog.preset_menu.actions()],
                list(load_import_presets()),
            )
        finally:
            if had_original:
                settings.setValue(IMPORT_PARAMETERS_KEY, original)
            else:
                settings.remove(IMPORT_PARAMETERS_KEY)

    def test_dialog_buttons_follow_parent_palette_when_theme_changes(self):
        host = QtWidgets.QWidget()
        dialog = LandlensdbDialog(None, host)
        popup = ImportJsonDialog(
            load_example_import_json(), lambda value: value, parent=dialog.import_tab
        )
        self.addCleanup(host.close)
        self.addCleanup(dialog.close)
        self.addCleanup(popup.close)
        for foreground, background in (("#eeeeee", "#252525"), ("#111111", "#eeeeee")):
            palette = QtGui.QPalette(host.style().standardPalette())
            for role in (
                QtGui.QPalette.ButtonText,
                QtGui.QPalette.WindowText,
                QtGui.QPalette.Text,
            ):
                palette.setColor(role, QtGui.QColor(foreground))
            for role in (
                QtGui.QPalette.Button,
                QtGui.QPalette.Window,
                QtGui.QPalette.Base,
            ):
                palette.setColor(role, QtGui.QColor(background))
            host.setPalette(palette)
            for button in dialog.findChildren(QtWidgets.QAbstractButton):
                # Table corner buttons have their own internal Qt style palette.
                if type(button) is QtWidgets.QAbstractButton:
                    continue
                self.assertEqual(button.styleSheet(), "")
                self.assertEqual(
                    button.palette().color(
                        QtGui.QPalette.Active, QtGui.QPalette.ButtonText
                    ),
                    palette.color(QtGui.QPalette.Active, QtGui.QPalette.ButtonText),
                    button.objectName() or button.text(),
                )
        self.assertEqual(
            dialog.view_tab.previous_button.arrowType(), QtCore.Qt.LeftArrow
        )
        self.assertEqual(dialog.view_tab.next_button.arrowType(), QtCore.Qt.RightArrow)


if __name__ == "__main__":
    suite = unittest.makeSuite(LandlensdbDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
