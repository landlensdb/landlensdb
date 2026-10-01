"""QGIS settings storage for the current import parameters document."""

from qgis.PyQt import QtCore

IMPORT_PARAMETERS_KEY = "Landlensdb/import_config_json"


def has_saved_import_parameters():
    """Return whether the user has explicitly saved an import document."""
    return QtCore.QSettings().contains(IMPORT_PARAMETERS_KEY)


def load_import_parameters(default_text):
    """Return the last saved JSON document or the supplied default."""
    value = QtCore.QSettings().value(IMPORT_PARAMETERS_KEY, default_text, type=str)
    return value or default_text


def save_import_parameters(json_text):
    """Persist the current JSON document for subsequent import actions."""
    QtCore.QSettings().setValue(IMPORT_PARAMETERS_KEY, json_text)
