# -*- coding: utf-8 -*-

import platform

from qgis.PyQt import QtCore, QtWidgets

from ..shared.connection_utils import (
    load_connection_settings,
    save_connection_settings,
    test_connection_values,
)


class SetupTab(QtWidgets.QWidget):
    connectionSaved = QtCore.pyqtSignal(dict)

    def __init__(self, iface, parent=None):
        super(SetupTab, self).__init__(parent)
        self.iface = iface
        self.connection_values = load_connection_settings()

        self._build_ui()
        self._wire_signals()
        self._apply_server_mode()
        self._refresh_connection_summary()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        server_section = QtWidgets.QWidget()
        server_section_layout = QtWidgets.QVBoxLayout(server_section)
        server_section_layout.setContentsMargins(0, 0, 0, 0)
        server_section_layout.setSpacing(6)

        server_header = QtWidgets.QHBoxLayout()
        server_title = QtWidgets.QLabel('Create PostgreSQL Server')
        server_header.addWidget(server_title)
        server_header.addStretch()
        server_section_layout.addLayout(server_header)

        self.server_group = QtWidgets.QFrame()
        self.server_group.setFrameShape(QtWidgets.QFrame.StyledPanel)
        server_layout = QtWidgets.QVBoxLayout(self.server_group)
        server_layout.setSpacing(10)

        self.server_installer_radio = QtWidgets.QRadioButton('Installer Package')
        self.server_homebrew_radio = QtWidgets.QRadioButton('Homebrew')
        self.server_windows_radio = QtWidgets.QRadioButton('Windows')
        self.server_conda_radio = QtWidgets.QRadioButton('Conda')
        self.server_conda_radio.setChecked(True)

        server_radio_row = QtWidgets.QHBoxLayout()
        server_radio_row.addWidget(self.server_installer_radio)
        server_radio_row.addWidget(self.server_homebrew_radio)
        server_radio_row.addWidget(self.server_windows_radio)
        server_radio_row.addWidget(self.server_conda_radio)
        server_radio_row.addStretch()
        server_layout.addLayout(server_radio_row)

        self.server_stack = QtWidgets.QStackedWidget()
        self.server_stack.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        server_layout.addWidget(self.server_stack)
        self.server_stack.addWidget(
            self._build_server_panel(
                'PostgreSQL can be installed from the official installer package. '
                'PostGIS must be installed after PostgreSQL, and GDAL raster drivers '
                'must be enabled in the database before raster queries will work.',
                'https://www.postgresql.org/download/',
            )
        )
        self.server_stack.addWidget(
            self._build_server_panel(
                'Install PostgreSQL/PostGIS with Homebrew and enable GDAL raster drivers for landlens_test.',
                self._homebrew_server_command(),
            )
        )
        self.server_stack.addWidget(
            self._build_server_panel(
                'Install PostgreSQL from Windows package manager. PostGIS must still be installed separately and GDAL drivers enabled in the database.',
                'winget install PostgreSQL.PostgreSQL',
            )
        )
        self.server_stack.addWidget(
            self._build_server_panel(
                'Install PostgreSQL/PostGIS into a conda environment and enable GDAL raster drivers for landlens_test.',
                self._conda_server_command(),
            )
        )
        server_section_layout.addWidget(self.server_group)

        self.server_requirements_label = QtWidgets.QLabel(
            '<b>Server requirements</b>'
            '<ul>'
            '<li>PostgreSQL 14+ running and reachable</li>'
            '<li>PostGIS and postgis_raster installed and activated</li>'
            '<li>PostGIS GDAL raster drivers enabled</li>'
            '<li>Login can use the database/schema and create tables</li>'
            '</ul>'
        )
        self.server_requirements_label.setTextFormat(QtCore.Qt.RichText)
        self.server_requirements_label.setWordWrap(True)
        server_section_layout.addWidget(self.server_requirements_label)
        layout.addWidget(server_section)

        connection_section = QtWidgets.QWidget()
        connection_section_layout = QtWidgets.QVBoxLayout(connection_section)
        connection_section_layout.setContentsMargins(0, 0, 0, 0)
        connection_section_layout.setSpacing(6)

        connection_header = QtWidgets.QHBoxLayout()
        connection_title = QtWidgets.QLabel('Connect to PostgreSQL')
        connection_header.addWidget(connection_title)
        connection_header.addStretch()
        connection_section_layout.addLayout(connection_header)

        self.connection_group = QtWidgets.QFrame()
        self.connection_group.setFrameShape(QtWidgets.QFrame.StyledPanel)
        connection_layout = QtWidgets.QVBoxLayout(self.connection_group)
        connection_layout.setSpacing(10)

        connection_grid = QtWidgets.QGridLayout()
        self.connection_name_input = QtWidgets.QLineEdit()
        self.connection_service_input = QtWidgets.QLineEdit()
        self.connection_host_input = QtWidgets.QLineEdit()
        self.connection_port_input = QtWidgets.QLineEdit()
        self.connection_database_input = QtWidgets.QLineEdit()
        self.connection_schema_input = QtWidgets.QLineEdit()
        self.connection_user_input = QtWidgets.QLineEdit()
        self.connection_password_input = QtWidgets.QLineEdit()
        self.connection_password_input.setEchoMode(QtWidgets.QLineEdit.Password)

        connection_fields = [
            ('Name', self.connection_name_input, 0, 0),
            ('Service', self.connection_service_input, 0, 1),
            ('Host', self.connection_host_input, 0, 2),
            ('Port', self.connection_port_input, 0, 3),
            ('Database', self.connection_database_input, 1, 0),
            ('Schema', self.connection_schema_input, 1, 1),
            ('User', self.connection_user_input, 1, 2),
            ('Password', self.connection_password_input, 1, 3),
        ]
        for label_text, widget, row, column in connection_fields:
            field_layout = QtWidgets.QVBoxLayout()
            field_layout.addWidget(QtWidgets.QLabel(label_text))
            field_layout.addWidget(widget)
            connection_grid.addLayout(field_layout, row, column)
        connection_layout.addLayout(connection_grid)

        connection_test_row = QtWidgets.QHBoxLayout()
        self.connection_test_button = QtWidgets.QPushButton('Set Connection')
        self.reset_connection_button = QtWidgets.QPushButton('Reset')
        self.connection_feedback = QtWidgets.QLabel('')
        self.connection_feedback.setWordWrap(True)
        connection_test_row.addWidget(self.connection_test_button)
        connection_test_row.addWidget(self.reset_connection_button)
        connection_test_row.addWidget(self.connection_feedback, 1)
        connection_test_row.addStretch()
        connection_layout.addLayout(connection_test_row)
        connection_section_layout.addWidget(self.connection_group)
        layout.addWidget(connection_section)
        layout.addStretch()

    def _build_server_panel(self, description, command):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setSpacing(8)

        label = QtWidgets.QLabel(description)
        label.setWordWrap(True)
        layout.addWidget(label)

        command_input = QtWidgets.QPlainTextEdit(command)
        command_input.setReadOnly(True)
        command_input.setMaximumHeight(78)
        layout.addWidget(command_input)
        return widget

    def _wire_signals(self):
        self.reset_connection_button.clicked.connect(self._reset_connection_defaults)
        self.connection_test_button.clicked.connect(self._test_connection_form)

        self.server_installer_radio.toggled.connect(self._apply_server_mode)
        self.server_homebrew_radio.toggled.connect(self._apply_server_mode)
        self.server_windows_radio.toggled.connect(self._apply_server_mode)
        self.server_conda_radio.toggled.connect(self._apply_server_mode)

    def set_connection_values(self, values=None):
        self.connection_values = dict(values or load_connection_settings())
        self._refresh_connection_summary()

    def _test_connection_values(self, values):
        success, message = test_connection_values(values)
        if success:
            self.connection_values = dict(values)
            save_connection_settings(self.connection_values)
            self._refresh_connection_summary()
            self.connectionSaved.emit(dict(self.connection_values))
        return success, message

    def _refresh_connection_summary(self):
        self.connection_name_input.blockSignals(True)
        self.connection_service_input.blockSignals(True)
        self.connection_host_input.blockSignals(True)
        self.connection_port_input.blockSignals(True)
        self.connection_database_input.blockSignals(True)
        self.connection_schema_input.blockSignals(True)
        self.connection_user_input.blockSignals(True)
        self.connection_password_input.blockSignals(True)

        self.connection_name_input.setText(self.connection_values.get('name', ''))
        self.connection_service_input.setText(self.connection_values.get('service', ''))
        self.connection_host_input.setText(self.connection_values.get('host', ''))
        self.connection_port_input.setText(self.connection_values.get('port', '5432'))
        self.connection_database_input.setText(
            self.connection_values.get('database', 'landlensdb')
        )
        self.connection_schema_input.setText(
            self.connection_values.get('schema', 'public')
        )
        self.connection_user_input.setText(self.connection_values.get('user', ''))
        self.connection_password_input.setText(self.connection_values.get('password', ''))

        self.connection_name_input.blockSignals(False)
        self.connection_service_input.blockSignals(False)
        self.connection_host_input.blockSignals(False)
        self.connection_port_input.blockSignals(False)
        self.connection_database_input.blockSignals(False)
        self.connection_schema_input.blockSignals(False)
        self.connection_user_input.blockSignals(False)
        self.connection_password_input.blockSignals(False)

    def _apply_server_mode(self):
        if self.server_installer_radio.isChecked():
            self.server_stack.setCurrentIndex(0)
        elif self.server_homebrew_radio.isChecked():
            self.server_stack.setCurrentIndex(1)
        elif self.server_windows_radio.isChecked():
            self.server_stack.setCurrentIndex(2)
        else:
            self.server_stack.setCurrentIndex(3)
        self._shrink_stack(self.server_stack)

    def _shrink_stack(self, stack):
        current = stack.currentWidget()
        if current is None:
            return
        height = current.sizeHint().height()
        stack.setMinimumHeight(height)
        stack.setMaximumHeight(height)

    def _store_connection_form(self):
        self.connection_values = {
            'name': self.connection_name_input.text().strip(),
            'service': self.connection_service_input.text().strip(),
            'host': self.connection_host_input.text().strip() or 'localhost',
            'port': self.connection_port_input.text().strip() or '5432',
            'database': self.connection_database_input.text().strip() or 'landlensdb',
            'schema': self.connection_schema_input.text().strip() or 'public',
            'user': self.connection_user_input.text().strip(),
            'password': self.connection_password_input.text(),
        }

    def _test_connection_form(self):
        self._store_connection_form()
        success, message = self._test_connection_values(self.connection_values)
        color = '#1b8a3a' if success else '#b42318'
        self.connection_feedback.setText(message)
        self.connection_feedback.setStyleSheet(
            'color: {}; font-weight: 600;'.format(color)
        )

    def _reset_server_defaults(self):
        if platform.system() == 'Windows':
            self.server_windows_radio.setChecked(True)
        elif platform.system() == 'Darwin':
            self.server_homebrew_radio.setChecked(True)
        else:
            self.server_conda_radio.setChecked(True)

    def _reset_connection_defaults(self):
        self.connection_values = {
            'name': '',
            'service': '',
            'host': 'localhost',
            'port': '5432',
            'database': 'landlensdb',
            'schema': 'public',
            'user': '',
            'password': '',
        }
        save_connection_settings(self.connection_values)
        self._refresh_connection_summary()
        self.connection_feedback.setText('')
        self.connectionSaved.emit(dict(self.connection_values))

    def _homebrew_server_command(self):
        return (
            "brew install postgresql postgis && "
            "export POSTGIS_GDAL_ENABLED_DRIVERS=ENABLE_ALL && "
            "psql -d landlens_test -c \"ALTER DATABASE landlens_test SET postgis.gdal_enabled_drivers = 'ENABLE_ALL';\""
        )

    def _conda_server_command(self):
        return (
            "conda run -n landlensdb_pg true >/dev/null 2>&1 ||\n"
            "  conda create -y -n landlensdb_pg -c conda-forge \"postgresql>=14\" \"postgis>=3.5\"\n\n"
            "conda activate landlensdb_pg\n"
            "export PGDATA=\"$CONDA_PREFIX/var/lib/postgresql\" POSTGIS_GDAL_ENABLED_DRIVERS=ENABLE_ALL\n\n"
            "[ -f \"$PGDATA/PG_VERSION\" ] || { mkdir -p \"$PGDATA\"; initdb -D \"$PGDATA\"; }\n"
            "pg_ctl -D \"$PGDATA\" status >/dev/null 2>&1 ||\n"
            "  pg_ctl -D \"$PGDATA\" -l /tmp/landlensdb-postgres.log start\n\n"
            "createdb -h localhost landlensdb 2>/dev/null || :\n"
            "psql -h localhost -d landlensdb -c \\\n"
            "  \"CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS postgis_raster; ALTER DATABASE landlensdb SET postgis.gdal_enabled_drivers='ENABLE_ALL';\" &&\n"
            "printf '\\nHost: localhost\\nPort: 5432\\nDatabase: landlensdb\\nSchema: public\\nUser: %s\\nPassword: (none)\\n' \"$(id -un)\""
        )
