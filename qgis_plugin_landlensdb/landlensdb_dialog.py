# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LandlensdbDialog
                                 A QGIS plugin
 Graphical interface to add Postgis layers to QGIS
 ***************************************************************************/
"""

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtGui import QIcon

import os

from .tabs.import_tab import ImportTab
from .tabs.overview_tab import OverviewTab
from .tabs.query_tab import QueryTab
from .tabs.setup_tab import SetupTab
from .tabs.view_tab import ViewTab


class LandlensdbDialog(QtWidgets.QDialog):
    def __init__(self, iface, parent=None):
        super(LandlensdbDialog, self).__init__(parent)
        self.setAttribute(QtCore.Qt.WA_WindowPropagation)
        self.iface = iface
        self.setWindowTitle('Landlensdb')
        self.setWindowIcon(
            QIcon(os.path.join(os.path.dirname(__file__), 'landlensdb.png'))
        )
        self.resize(1120, 780)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.tab_widget = QtWidgets.QTabWidget(self)
        layout.addWidget(self.tab_widget)

        self.overview_tab = OverviewTab(self)
        self.setup_tab = SetupTab(iface, self)
        self.import_tab = ImportTab(iface, self)
        self.query_tab = QueryTab(iface, self)
        self.view_tab = ViewTab(iface, self)
        self.view_tab.set_host_tab_widget(self.tab_widget)
        self.view_tab.addImagesRequested.connect(self.query_tab.add_image_urls_to_map)

        self.tab_widget.addTab(self.overview_tab, 'Overview')
        self.tab_widget.addTab(self.setup_tab, 'Setup')
        self.tab_widget.addTab(self.import_tab, 'Import')
        self.tab_widget.addTab(self.query_tab, 'Query')
        self.tab_widget.addTab(self.view_tab, 'View')

        self.setup_tab.connectionSaved.connect(self.query_tab.reload_connection_settings)
        self.query_tab.connectionSaved.connect(self.setup_tab.set_connection_values)
        self.setup_tab.connectionSaved.connect(self.import_tab.reload_connection_settings)
        self.query_tab.connectionSaved.connect(self.import_tab.reload_connection_settings)
        self.setup_tab.connectionSaved.connect(self.view_tab.reload_connection_settings)
        self.query_tab.connectionSaved.connect(self.view_tab.reload_connection_settings)
        self.tab_widget.currentChanged.connect(self._handle_tab_changed)
        self._handle_tab_changed(self.tab_widget.currentIndex())

    def _handle_tab_changed(self, index):
        self.view_tab.set_active(self.tab_widget.widget(index) is self.view_tab)

    def hideEvent(self, event):
        self.view_tab.set_active(False)
        super(LandlensdbDialog, self).hideEvent(event)

    def closeEvent(self, event):
        self.query_tab._finish_bbox_selection(show_window=False)
        super(LandlensdbDialog, self).closeEvent(event)

    def showEvent(self, event):
        super(LandlensdbDialog, self).showEvent(event)
        self._handle_tab_changed(self.tab_widget.currentIndex())
