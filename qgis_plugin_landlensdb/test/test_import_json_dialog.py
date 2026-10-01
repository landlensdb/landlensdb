"""Template loading and settings persistence for the import editor."""

import json
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt import QtCore, QtGui, QtWidgets

from ..landlensdb.import_config import (
    IMPORT_TEMPLATE_DIRECTORY,
    load_import_presets,
    normalize_import_json,
)
from ..shared.import_settings import load_import_parameters, save_import_parameters
from ..shared.json_editor import ImportJsonDialog
from ..shared import json_editor


class ImportJsonDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.presets = load_import_presets()
        config = json.loads(self.presets["geotagged_photos.json"])
        config["file_glob"] = "/photos/current/**/*.jpg"
        self.current_json = json.dumps(config)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        settings = QtCore.QSettings(
            directory + "/imports.ini", QtCore.QSettings.IniFormat
        )
        self.enterContext(
            patch(
                "qgis_plugin_landlensdb.shared.import_settings.QtCore.QSettings",
                return_value=settings,
            )
        )
        save_import_parameters(self.current_json)
        self.dialog = self.make_dialog(self.current_json)
        self.addCleanup(self.dialog.close)

    def make_dialog(self, json_text):
        return ImportJsonDialog(json_text, normalize_import_json)

    def activate_template(self, index):
        self.dialog.preset_menu.actions()[index].trigger()

    def test_opening_preserves_current_configuration_until_template_activation(self):
        self.assertEqual(self.dialog.json_text(), self.current_json)
        self.assertEqual(self.dialog.preset_input.text(), "Apply Template")
        self.assertFalse(hasattr(self.dialog, "apply_preset_button"))
        self.assertFalse(self.dialog.advanced_settings_checkbox.isChecked())
        self.assertIs(self.dialog.mode_stack.currentWidget(), self.dialog.simple_page)
        self.assertEqual(self.dialog.file_glob_input.text(), "/photos/current/**/*.jpg")
        header = self.dialog.layout().itemAt(0).layout()
        self.assertEqual(
            [header.itemAt(index).widget() for index in range(header.count())],
            [
                self.dialog.preset_input,
                self.dialog.open_template_folder_button,
                self.dialog.advanced_settings_checkbox,
            ],
        )

        for index, template_json in enumerate(self.presets.values()):
            self.activate_template(index)
            self.assertEqual(self.dialog.preset_input.text(), "Apply Template")
            self.assertEqual(self.dialog.json_text(), template_json)
            self.assertEqual(
                self.dialog.file_glob_input.text(),
                json.loads(template_json)["file_glob"],
            )
        self.assertEqual(load_import_parameters("default"), self.current_json)

    def edit_glob(self, value):
        self.dialog.file_glob_input.setText(value)
        self.dialog.file_glob_input.textEdited.emit(value)

    def test_select_uses_shared_folder_picker_and_preserves_other_parameters(self):
        file_glob = "/selected/*.@(jpg|JPG)"
        with patch.object(json_editor, "choose_file_glob", return_value=file_glob):
            self.dialog.create_glob_button.click()
        expected = json.loads(self.current_json)
        expected["file_glob"] = file_glob
        self.assertEqual(json.loads(self.dialog.json_text()), expected)
        self.assertEqual(json.loads(load_import_parameters("default")), expected)
        with patch.object(json_editor, "choose_file_glob", return_value=None):
            self.dialog.create_glob_button.click()
        self.assertEqual(json.loads(self.dialog.json_text()), expected)

    def test_search_glob_saves_only_that_field_and_reopens_without_save(self):
        self.edit_glob("/new photos/**/*.@(jpg|jpeg|png)")
        expected = json.loads(self.current_json)
        expected["file_glob"] = "/new photos/**/*.@(jpg|jpeg|png)"
        self.assertEqual(json.loads(self.dialog.json_text()), expected)
        self.assertEqual(json.loads(load_import_parameters("default")), expected)
        self.dialog.close_button.click()
        reopened = self.make_dialog(load_import_parameters("default"))
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.file_glob_input.text(), expected["file_glob"])
        self.assertEqual(json.loads(reopened.json_text()), expected)
        self.assertEqual(load_import_presets(), self.presets)

    def test_mode_switches_preserve_edits(self):
        self.edit_glob("/new/**/*.png")
        self.dialog.advanced_settings_checkbox.setChecked(True)
        self.assertIs(self.dialog.mode_stack.currentWidget(), self.dialog.editor)
        config = json.loads(self.dialog.json_text())
        self.assertEqual(config["file_glob"], "/new/**/*.png")
        config["file_glob"] = "/advanced/**/*.jpeg"
        config["metadata"]["survey"] = "Keep my advanced edits"
        self.dialog.editor.setPlainText(json.dumps(config))
        self.dialog.advanced_settings_checkbox.setChecked(False)
        self.assertEqual(self.dialog.file_glob_input.text(), "/advanced/**/*.jpeg")
        self.dialog.advanced_settings_checkbox.setChecked(True)
        self.assertEqual(json.loads(self.dialog.json_text()), config)

    def test_invalid_json_cannot_be_hidden_by_simple_mode(self):
        self.dialog.advanced_settings_checkbox.setChecked(True)
        self.dialog.editor.setPlainText('{"file_glob":')
        self.dialog.advanced_settings_checkbox.setChecked(False)
        self.assertTrue(self.dialog.advanced_settings_checkbox.isChecked())
        self.assertIs(self.dialog.mode_stack.currentWidget(), self.dialog.editor)
        self.assertEqual(self.dialog.json_text(), '{"file_glob":')
        self.assertTrue(self.dialog.validation_label.text())
        self.assertEqual(load_import_parameters("default"), self.current_json)

    def test_empty_glob_does_not_replace_valid_saved_config(self):
        self.edit_glob("")
        self.assertTrue(self.dialog.validation_label.text())
        self.assertEqual(load_import_parameters("default"), self.current_json)
        self.edit_glob("/fixed/*.png")
        self.assertEqual(self.dialog.validation_label.text(), "")
        self.assertEqual(
            json.loads(load_import_parameters("default"))["file_glob"], "/fixed/*.png"
        )

    def test_open_template_folder_uses_the_actual_template_directory(self):
        with patch.object(
            QtGui.QDesktopServices, "openUrl", return_value=True
        ) as opener:
            self.dialog.open_template_folder_button.click()
        url = opener.call_args.args[0]
        self.assertTrue(url.isLocalFile())
        self.assertEqual(url.toLocalFile(), str(IMPORT_TEMPLATE_DIRECTORY))
        self.assertTrue(IMPORT_TEMPLATE_DIRECTORY.is_dir())

    def test_reselecting_template_replaces_edits_and_clears_validation_error(self):
        index = list(self.presets).index("geotagged_photos.json")
        self.activate_template(index)
        self.dialog.advanced_settings_checkbox.setChecked(True)
        self.dialog.editor.setPlainText("invalid: [")
        self.dialog.save_button.click()
        self.assertTrue(self.dialog.validation_label.text())
        self.assertEqual(self.dialog.result(), QtWidgets.QDialog.Rejected)

        self.activate_template(index)
        self.assertEqual(self.dialog.json_text(), self.presets["geotagged_photos.json"])
        self.assertEqual(self.dialog.validation_label.text(), "")

    def test_saved_edits_reopen_without_modifying_template_files(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QtCore.QSettings(
                directory + "/imports.ini", QtCore.QSettings.IniFormat
            )
            with patch(
                "qgis_plugin_landlensdb.shared.import_settings.QtCore.QSettings",
                return_value=settings,
            ):
                save_import_parameters(self.current_json)
                # The caller persists only accepted documents, as the import tab does.
                self.dialog.accepted.connect(
                    lambda: save_import_parameters(self.dialog.json_text())
                )
                self.activate_template(1)
                self.dialog.advanced_settings_checkbox.setChecked(True)
                config = json.loads(self.dialog.json_text())
                config["metadata"]["survey"] = "My import settings"
                edited_json = json.dumps(config, indent=2)
                self.dialog.editor.setPlainText(edited_json)
                self.assertEqual(load_import_parameters("default"), self.current_json)
                self.dialog.save_button.click()
                self.assertEqual(self.dialog.result(), QtWidgets.QDialog.Accepted)

                reopened = self.make_dialog(load_import_parameters("default"))
                self.addCleanup(reopened.close)
                self.assertEqual(reopened.json_text(), edited_json)
                self.assertEqual(reopened.preset_input.text(), "Apply Template")
                self.assertEqual(load_import_presets(), self.presets)

    def test_reopening_rescans_added_removed_and_edited_json_files(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = folder / "First.json"
            first.write_text(self.current_json)
            with patch.object(
                json_editor.import_config, "IMPORT_TEMPLATE_DIRECTORY", folder
            ):
                self.dialog.show()
                self.app.processEvents()
                self.assertEqual(list(self.dialog.presets), ["First.json"])
                self.assertEqual(self.dialog.json_text(), self.current_json)
                self.dialog.hide()
                first.unlink()
                second = folder / "New template.JSON"
                edited = json.loads(self.current_json)
                edited["metadata"]["survey"] = "Added from folder"
                second.write_text(json.dumps(edited))
                (folder / "ignore.txt").write_text("not a template")
                (folder / "directory.json").mkdir()
                self.dialog.show()
                self.app.processEvents()
                self.assertEqual(list(self.dialog.presets), ["New template.JSON"])
                self.assertEqual(self.dialog.json_text(), self.current_json)
                self.activate_template(0)
                self.assertEqual(json.loads(self.dialog.json_text()), edited)
                self.dialog.hide()
                edited["metadata"]["survey"] = "Edited on disk"
                second.write_text(json.dumps(edited))
                self.dialog.show()
                self.app.processEvents()
                self.activate_template(0)
                self.assertEqual(json.loads(self.dialog.json_text()), edited)
                self.assertEqual(load_import_parameters("default"), self.current_json)
                self.dialog.hide()
                second.unlink()
                self.dialog.show()
                self.app.processEvents()
                self.assertFalse(self.dialog.preset_input.isEnabled())
                self.assertEqual(json.loads(self.dialog.json_text()), edited)


if __name__ == "__main__":
    unittest.main()
