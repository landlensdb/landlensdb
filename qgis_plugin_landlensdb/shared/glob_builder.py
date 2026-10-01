"""Folder and extension selection for an import search glob."""

import os

from qgis.PyQt import QtCore, QtWidgets

# Image extensions in the bundled templates; no template parsing is needed.
FILE_EXTENSIONS = "jpg png jpeg tif tiff vrt img jp2 til"


def build_file_glob(folder, extensions, recursive=False):
    if not extensions:
        raise ValueError("Choose at least one extension.")
    variants = [
        variant
        for extension in extensions
        for variant in (extension, extension.upper())
    ]
    parts = ["**"] if recursive else []
    return os.path.join(
        os.path.normpath(folder), *parts, "*.@({})".format("|".join(variants))
    )


def choose_image_folder(parent=None):
    """Choose an image folder, returning None when cancelled."""
    return (
        QtWidgets.QFileDialog.getExistingDirectory(parent, "Choose Image Folder")
        or None
    )


def choose_folder_filter(parent=None):
    """Choose a folder, extensions, and recursion, or return None on cancellation."""
    folder = choose_image_folder(parent)
    if not folder:
        return None
    dialog = GlobExtensionsDialog(parent)
    if not dialog.exec_():
        return None
    return (folder, dialog.selected_extensions(), dialog.recursive_checkbox.isChecked())


def choose_file_glob(parent=None):
    """Choose a folder and extensions, returning None when either dialog is cancelled."""
    selection = choose_folder_filter(parent)
    return build_file_glob(*selection) if selection is not None else None


class GlobExtensionsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_WindowPropagation)
        self.setWindowTitle("Choose Extensions")
        layout = QtWidgets.QVBoxLayout(self)
        grid = QtWidgets.QGridLayout()
        self.extension_inputs = {}
        for index, extension in enumerate(FILE_EXTENSIONS.split()):
            checkbox = QtWidgets.QCheckBox(
                "{} / {}".format(extension, extension.upper()), self
            )
            checkbox.toggled.connect(self.update_okay_button)
            self.extension_inputs[extension] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        layout.addLayout(grid)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.recursive_checkbox = QtWidgets.QCheckBox("Recursive", self)
        buttons.addWidget(self.recursive_checkbox)
        self.okay_button = QtWidgets.QPushButton("Okay", self)
        self.okay_button.setDefault(True)
        self.okay_button.clicked.connect(self.accept)
        buttons.addWidget(self.okay_button)
        layout.addLayout(buttons)
        self.update_okay_button()

    def selected_extensions(self):
        return [
            extension
            for extension, checkbox in self.extension_inputs.items()
            if checkbox.isChecked()
        ]

    def update_okay_button(self):
        self.okay_button.setEnabled(bool(self.selected_extensions()))
