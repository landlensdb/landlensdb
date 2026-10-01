"""Simple search glob form with an optional full JSON import editor."""

import json

from qgis.PyQt import QtCore, QtGui, QtWidgets

from ..landlensdb import import_config
from .glob_builder import choose_file_glob
from .import_settings import save_import_parameters


class JsonHighlighter(QtGui.QSyntaxHighlighter):
    """Highlight the JSON constructs used by import parameter files."""

    def __init__(self, document):
        super(JsonHighlighter, self).__init__(document)
        self.rules = []
        self._add_rule(r"\b(?:true|false|null)\b", "#7c3aed", bold=True)
        self._add_rule(r"\b[-+]?(?:\d+\.?\d*|\.\d+)\b", "#b45309")
        self._add_rule(r'"(?:\\.|[^"\\])*"', "#15803d")
        self._add_rule(r'"(?:\\.|[^"\\])*"(?=\s*:)', "#2563eb", bold=True)

    def _add_rule(self, pattern, color, bold=False, italic=False):
        expression = QtCore.QRegularExpression(pattern)
        text_format = QtGui.QTextCharFormat()
        text_format.setForeground(QtGui.QColor(color))
        if bold:
            text_format.setFontWeight(QtGui.QFont.Bold)
        text_format.setFontItalic(italic)
        self.rules.append((expression, text_format))

    def highlightBlock(self, text):
        for expression, text_format in self.rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(
                    match.capturedStart(),
                    match.capturedLength(),
                    text_format,
                )


class ImportGroupJsonDialog(QtWidgets.QDialog):
    """View a group's JSON and optionally use it as the current import settings."""

    update_requested = QtCore.pyqtSignal(str)

    def __init__(self, json_text, normalizer, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_WindowPropagation)
        self.setWindowTitle("View JSON")
        self.resize(880, 600)
        self.normalizer = normalizer
        layout = QtWidgets.QVBoxLayout(self)
        self.editor = QtWidgets.QPlainTextEdit(self)
        self.editor.setFont(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        )
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.editor.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.editor.setPlainText(json_text)
        self.highlighter = JsonHighlighter(self.editor.document())
        layout.addWidget(self.editor, 1)
        self.validation_label = QtWidgets.QLabel(self)
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.copy_button = QtWidgets.QPushButton("Copy", self)
        self.update_button = QtWidgets.QPushButton("Update Import Text", self)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.update_button)
        layout.addLayout(buttons)
        self.close_button.clicked.connect(self.reject)
        self.copy_button.clicked.connect(self.copy_json)
        self.update_button.clicked.connect(self.request_update)

    def json_text(self):
        return self.editor.toPlainText()

    def copy_json(self):
        QtWidgets.QApplication.clipboard().setText(self.json_text())

    def request_update(self):
        try:
            self.normalizer(self.json_text())
        except (ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return
        self.update_requested.emit(self.json_text())

    def show_error(self, message):
        self.validation_label.setText(message)
        self.validation_label.show()


class ImportJsonDialog(QtWidgets.QDialog):
    """Edit the current configuration using templates as read-only starting points."""

    def __init__(self, json_text, normalizer, parent=None):
        super(ImportJsonDialog, self).__init__(parent)
        self.setAttribute(QtCore.Qt.WA_WindowPropagation)
        self.normalizer = normalizer
        self.presets = {}
        self.setWindowTitle("Import Parameters")
        self.resize(880, 240)

        layout = QtWidgets.QVBoxLayout(self)
        preset_row = QtWidgets.QHBoxLayout()
        self.preset_input = QtWidgets.QPushButton("Apply Template", self)
        self.preset_menu = QtWidgets.QMenu(self.preset_input)
        self.preset_input.setMenu(self.preset_menu)
        self.preset_input.setToolTip(
            "Choose a template to replace the current configuration."
        )
        preset_row.addWidget(self.preset_input, 1)
        self.open_template_folder_button = QtWidgets.QPushButton(
            "Open Template Folder", self
        )
        preset_row.addWidget(self.open_template_folder_button)
        self.advanced_settings_checkbox = QtWidgets.QCheckBox("Advanced settings", self)
        preset_row.addWidget(self.advanced_settings_checkbox)
        layout.addLayout(preset_row)

        self.mode_stack = QtWidgets.QStackedWidget(self)
        self.simple_page = QtWidgets.QWidget(self)
        simple_layout = QtWidgets.QVBoxLayout(self.simple_page)
        simple_layout.setContentsMargins(0, 0, 0, 0)
        glob_row = QtWidgets.QHBoxLayout()
        glob_label = QtWidgets.QLabel("Search Glob:", self)
        glob_row.addWidget(glob_label)
        self.file_glob_input = QtWidgets.QLineEdit(self)
        glob_label.setBuddy(self.file_glob_input)
        glob_row.addWidget(self.file_glob_input, 1)
        self.create_glob_button = QtWidgets.QPushButton("Select", self)
        self.create_glob_button.clicked.connect(self.create_file_glob)
        glob_row.addWidget(self.create_glob_button)
        simple_layout.addLayout(glob_row)
        self.mode_stack.addWidget(self.simple_page)
        self.editor = QtWidgets.QPlainTextEdit(self)
        self.editor.setPlainText(json_text)
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.editor.setFont(font)
        self.highlighter = JsonHighlighter(self.editor.document())
        self.mode_stack.addWidget(self.editor)
        layout.addWidget(self.mode_stack, 1)

        self.settings_hint = QtWidgets.QLabel(self)
        self.settings_hint.setWordWrap(True)
        layout.addWidget(self.settings_hint)

        self.validation_label = QtWidgets.QLabel(self)
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        buttons = QtWidgets.QHBoxLayout()
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.copy_button = QtWidgets.QPushButton("Copy", self)
        self.save_button = QtWidgets.QPushButton("Save", self)
        self.save_button.setDefault(True)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.open_template_folder_button.clicked.connect(self.open_template_folder)
        self.advanced_settings_checkbox.toggled.connect(self.set_advanced_settings)
        self.file_glob_input.textEdited.connect(self.update_file_glob)
        self.close_button.clicked.connect(self.reject)
        self.copy_button.clicked.connect(self.copy_json)
        self.save_button.clicked.connect(self.validate_and_accept)
        self.reload_presets()
        self.set_advanced_settings(False)

    def showEvent(self, event):
        self.reload_presets()
        super().showEvent(event)

    def reload_presets(self):
        self.presets = import_config.load_import_presets()
        self.preset_menu.clear()
        for name in self.presets:
            self.preset_menu.addAction(
                name, lambda checked=False, name=name: self.load_selected_preset(name)
            )
        self.preset_input.setEnabled(bool(self.presets))

    def json_text(self):
        return self.editor.toPlainText()

    def load_selected_preset(self, name):
        if name in self.presets:
            self.editor.setPlainText(self.presets[name])
            self.validation_label.clear()
            self.validation_label.hide()
            self.set_advanced_settings(self.advanced_settings_checkbox.isChecked())

    def set_advanced_settings(self, advanced):
        if not advanced:
            try:
                self.normalizer(self.json_text())
                config = json.loads(self.json_text())
                self.file_glob_input.setText(config["file_glob"])
            except (ValueError, TypeError, KeyError) as exc:
                # Keep invalid drafts visible so switching modes cannot discard them.
                self.advanced_settings_checkbox.setChecked(True)
                self._show_error(
                    "Fix the JSON before using Search Glob: {}".format(exc)
                )
                return
        self.mode_stack.setCurrentWidget(self.editor if advanced else self.simple_page)
        self.settings_hint.setText(
            "Save keeps the current configuration for future imports. Template files are unchanged."
        )
        self.settings_hint.setVisible(advanced)
        if advanced:
            self.mode_stack.setMinimumHeight(0)
            self.mode_stack.setMaximumHeight(16777215)
            self.resize(self.width(), 720)
        else:
            self.mode_stack.setFixedHeight(self.simple_page.sizeHint().height())
            self._resize_simple_mode()

    def _resize_simple_mode(self):
        if not self.advanced_settings_checkbox.isChecked():
            self.layout().activate()
            self.resize(self.width(), self.layout().sizeHint().height())

    def create_file_glob(self):
        file_glob = choose_file_glob(self)
        if file_glob is None:
            return
        self.file_glob_input.setText(file_glob)
        self.update_file_glob(file_glob)

    def update_file_glob(self, file_glob):
        """Change only the glob in the loaded configuration and persist valid edits."""
        try:
            config = json.loads(self.json_text())
            config["file_glob"] = file_glob
            json_text = json.dumps(config, indent=2, ensure_ascii=False)
            self.editor.setPlainText(json_text)
            self.normalizer(json_text)
        except (ValueError, TypeError) as exc:
            self._show_error(str(exc))
            return
        save_import_parameters(json_text)
        self.validation_label.clear()
        self.validation_label.hide()
        self._resize_simple_mode()

    def open_template_folder(self):
        url = QtCore.QUrl.fromLocalFile(str(import_config.IMPORT_TEMPLATE_DIRECTORY))
        if not QtGui.QDesktopServices.openUrl(url):
            self._show_error("Could not open the template folder.")

    def copy_json(self):
        """Copy the complete JSON document to the system clipboard."""
        QtWidgets.QApplication.clipboard().setText(self.json_text())
        self.validation_label.setStyleSheet("color: #15803d;")
        self.validation_label.setText("Import parameter JSON copied.")
        self.validation_label.show()
        self._resize_simple_mode()

    def validate_editor(self):
        try:
            self.normalizer(self.json_text())
        except Exception as exc:
            self._show_error(str(exc))
            return False
        self.validation_label.setStyleSheet("color: #15803d;")
        self.validation_label.setText("Valid import parameter JSON.")
        return True

    def validate_and_accept(self):
        if self.validate_editor():
            self.accept()

    def _show_error(self, message):
        self.validation_label.setStyleSheet("color: #b91c1c;")
        self.validation_label.setText(message)
        self.validation_label.show()
        self._resize_simple_mode()
