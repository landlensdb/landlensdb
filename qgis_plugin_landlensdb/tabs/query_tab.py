# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QueryTab
                                 A QGIS plugin
 Query workflow for loading PostGIS layers into QGIS
 ***************************************************************************/
"""

import os
import re
import csv
import io
import json
from datetime import datetime

from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from qgis.PyQt.QtWidgets import QAbstractItemView
from qgis.core import (
    Qgis,
    QgsAction,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDataSourceUri,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsSvgMarkerSymbolLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..shared.bbox_selection import BboxSelectionTool
from ..shared.connection_utils import (
    connection_kwargs,
    fetch_base_tables,
    load_connection_settings,
    save_connection_settings,
    validate_connection_values,
)
from ..shared.metadata_settings import load_metadata_tree
from .query_components import (
    QueryHistoryController,
    ResultsController,
    SqlBuilderController,
)

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:  # pragma: no cover - depends on QGIS runtime
    psycopg2 = None
    sql = None


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "..", "landlensdb_dialog_base.ui")
)


class QueryTab(QtWidgets.QWidget, FORM_CLASS):
    connectionSaved = QtCore.pyqtSignal(dict)

    HISTORY_KEY = "Landlensdb/query_history"
    STAR_KEY = "Landlensdb/starred_queries"
    NAME_KEY = "Landlensdb/query_names"
    PREVIEW_LIMIT = 10
    HISTORY_LIMIT = 25
    KEY_COLUMN = "__lldb_rowid__"
    SHARED_COMMENT_KEY = "landlensdb"
    SHARED_QUERY_KEY = "shared_queries"
    SHARED_TABLE_KEY = "Landlensdb/shared_query_table"
    POINT_STYLE_KEY = "Landlensdb/point_style"
    CAMERA_MARKER_PATH = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "assets",
            "camera_upward_direction_marker.svg",
        )
    )
    SOURCE_TABLE_RE = re.compile(
        r'\bFROM\s+(?:(?P<schema>"(?:[^"]|"")+"|[\w]+)\s*\.\s*)?'
        r'(?P<table>"(?:[^"]|"")+"|[\w]+)',
        re.IGNORECASE,
    )
    STATIC_ROW_ONE = [
        "SELECT",
        "FROM",
        "WHERE",
        "JOIN",
        "LEFT JOIN",
        "RIGHT JOIN",
        "GROUP BY",
        "ORDER BY",
        "LIMIT",
    ]
    STATIC_ROW_TWO = [
        "*",
        "DISTINCT",
        "COUNT(*)",
        "SUM()",
        "AVG()",
        "MIN()",
        "MAX()",
        "AND",
        "OR",
        "NOT",
        "IN ()",
        "LIKE",
        "IS NULL",
        "IS NOT NULL",
    ]
    STATIC_ROW_THREE = [
        "ST_Intersects()",
        "ST_Within()",
        "ST_Contains()",
        "ST_DWithin()",
        "ST_Touches()",
        "ST_Crosses()",
        "::geometry",
        "::geography",
    ]
    QUERY_EXAMPLE = (
        "image_url is the unique identifier per GeoImage. This sql statement must return the following:\n"
        'No grouping (image_url column must be one string per row):  SELECT  *  FROM  "<shema>"."<table>"\n'
        "Grouping (image_url must be a list of strings):\n"
        "SELECT   metadata::jsonb->'captured_at'->>'year' ,  array_agg(image_url) AS image_url  FROM  "
        "\"<shema>\".\"<table>\"   GROUP BY metadata::jsonb->'captured_at'->>'year' "
    )

    def __init__(self, iface, parent=None):
        super(QueryTab, self).__init__(parent)
        self.iface = iface
        self.setupUi(self)
        # Use the inherited QGIS palette throughout the loaded form, including
        # containers which install their own palette during setup.
        for widget in self.findChildren(QtWidgets.QWidget):
            if widget.testAttribute(QtCore.Qt.WA_SetPalette):
                widget.setPalette(QtGui.QPalette())

        self.connection_values = {}
        self._metadata_loaded = False
        self._last_query_state = None
        self._staged_metadata_items = []
        self._bbox_tool = None
        self._additional_metadata_schema = load_metadata_tree()
        self._shared_table_name = (
            QtCore.QSettings().value(self.SHARED_TABLE_KEY, "", type=str) or ""
        )

        self.query_button.clicked.connect(self.run_query)
        self.close_button.clicked.connect(self._close_parent_dialog)
        self.commands_toggle_button.toggled.connect(self._toggle_commands)
        self.history_menu_button.clicked.connect(self._show_history_menu)
        self.star_menu_button.clicked.connect(self._show_star_menu)
        self.sql_input.textChanged.connect(self._update_add_buttons_state)

        self.results_table.setColumnCount(0)
        self.results_table.setRowCount(0)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.results_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.add_button.setEnabled(False)
        self._setup_add_menu()
        self._setup_copy_menu()
        self._setup_geometry_style_menu()

        self.builder_controller = SqlBuilderController(
            self,
            self.sql_input,
            self.commands_frame,
            self.commands_toggle_button,
            self.commands_content_widget,
        )
        self.builder_controller.prepare_ui()

        self.history_controller = QueryHistoryController(
            self,
            self.sql_input,
            self.history_menu_button,
            self.star_menu_button,
            self.HISTORY_KEY,
            self.STAR_KEY,
            self.NAME_KEY,
            self.HISTORY_LIMIT,
        )
        self.results_controller = ResultsController(
            self,
            self.results_tab,
            self.results_tab_layout,
            self.results_label,
            self.results_table,
            self.PREVIEW_LIMIT,
            self._update_results_preview,
        )
        self.results_controller.setup()
        self._prepare_workbench_ui()
        self._add_shared_menu_button()
        self._add_builder_help_button()

        self._load_settings()
        self._populate_static_buttons()
        self._build_history_menu()
        self._build_star_menu()
        self._render_dynamic_buttons([], [])
        self._set_results_label(0, 0)
        self._update_add_buttons_state()

    def showEvent(self, event):
        super(QueryTab, self).showEvent(event)
        self.sql_input.setFocus()
        if not self._metadata_loaded:
            self._refresh_schema_buttons(silent=True)
            self._metadata_loaded = True

    def reload_connection_settings(self, values=None):
        self.connection_values = dict(values or load_connection_settings())
        self._refresh_schema_buttons(silent=False)

    def _load_settings(self):
        self.connection_values = load_connection_settings()
        self.history_controller.load()

    def _save_settings(self):
        save_connection_settings(self.connection_values)
        self.history_controller.save()

    def _append_status(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_output.appendPlainText("[{}] {}".format(timestamp, message))

    def _show_error(self, message):
        self._append_status(message)
        self.bottom_tabs.setCurrentWidget(self.logs_tab)
        if self.iface is not None:
            self.iface.messageBar().pushMessage(
                "Landlensdb", message, level=Qgis.Critical, duration=8
            )

    def _show_info(self, message):
        self._append_status(message)
        if self.iface is not None:
            self.iface.messageBar().pushMessage(
                "Landlensdb", message, level=Qgis.Info, duration=5
            )

    def _close_parent_dialog(self):
        window = self.window()
        if isinstance(window, QtWidgets.QDialog):
            window.close()

    def _update_add_buttons_state(self):
        has_sql = bool(self.sql_input.toPlainText().strip())
        self.add_menu_button.setEnabled(has_sql)

    def _setup_add_menu(self):
        add_menu = QtWidgets.QMenu(self.add_button)
        add_both_action = add_menu.addAction("Add Both")
        add_both_action.triggered.connect(
            lambda: self.add_last_query_to_map(add_thumbnail=True, add_geometry=True)
        )
        add_thumbnail_action = add_menu.addAction("Add Thumbnail")
        add_thumbnail_action.triggered.connect(
            lambda: self.add_last_query_to_map(add_thumbnail=True, add_geometry=False)
        )
        add_geometry_action = add_menu.addAction("Add Geometry")
        add_geometry_action.triggered.connect(
            lambda: self.add_last_query_to_map(add_thumbnail=False, add_geometry=True)
        )

        self.add_menu_button = QtWidgets.QPushButton("Add", self)
        self.add_menu_button.setText("Add")
        self.add_menu_button.setMenu(add_menu)
        self.add_menu_button.setEnabled(False)

        if hasattr(self, "buttonLayout"):
            index = self.buttonLayout.indexOf(self.add_button)
            if index >= 0:
                self.buttonLayout.insertWidget(index, self.add_menu_button)
                self.buttonLayout.removeWidget(self.add_button)
                self.add_button.hide()

    def _setup_copy_menu(self):
        self.copy_menu = QtWidgets.QMenu(self)
        self.copy_menu.aboutToShow.connect(self._populate_copy_menu)

        self.copy_menu_button = QtWidgets.QPushButton("Copy", self)
        self.copy_menu_button.setMenu(self.copy_menu)

        if hasattr(self, "buttonLayout"):
            index = self.buttonLayout.indexOf(self.add_menu_button)
            if index >= 0:
                self.buttonLayout.insertWidget(index + 1, self.copy_menu_button)

    def _populate_copy_menu(self):
        self.copy_menu.clear()

        select_menu = self.copy_menu.addMenu("Select")
        self._populate_metadata_sections(select_menu, self._stage_metadata_item)

        staged_menu = self.copy_menu.addMenu("Staged")
        if not self._staged_metadata_items:
            empty_action = staged_menu.addAction("No staged items")
            empty_action.setEnabled(False)
        else:
            for staged_item in self._staged_metadata_items:
                action = staged_menu.addAction(staged_item["label"])
                action.triggered.connect(
                    lambda _checked=False, item=staged_item[
                        "label"
                    ]: self._unstage_metadata_item(item)
                )

        self.copy_menu.addSeparator()
        copy_action = self.copy_menu.addAction("Copy")
        copy_action.setEnabled(bool(self._staged_metadata_items))
        copy_action.triggered.connect(self.copy_last_query_to_csv)

    def _setup_geometry_style_menu(self):
        self._point_style = QtCore.QSettings().value(
            self.POINT_STYLE_KEY, "camera", type=str
        )
        if self._point_style not in ("camera", "point"):
            self._point_style = "camera"

        self.geometry_style_button = QtWidgets.QPushButton("Geometry style", self)
        self.geometry_style_button.setToolTip(
            "Choose styles for geometry layers added from Query or View."
        )
        menu = QtWidgets.QMenu(self.geometry_style_button)
        point_menu = menu.addMenu("Point")
        self.point_style_group = QtWidgets.QActionGroup(point_menu)
        self.point_style_group.setExclusive(True)
        for style, label in (("camera", "Camera direction icon"), ("point", "Point")):
            action = point_menu.addAction(label)
            action.setData(style)
            action.setCheckable(True)
            self.point_style_group.addAction(action)
            action.setChecked(style == self._point_style)
            if style == "camera":
                action.setIcon(QtGui.QIcon(self.CAMERA_MARKER_PATH))
        self.point_style_group.triggered.connect(self._set_point_style)

        polygon_menu = menu.addMenu("Polygon")
        polygon_group = QtWidgets.QActionGroup(polygon_menu)
        polygon_group.setExclusive(True)
        polygon_action = polygon_menu.addAction("Polygon")
        polygon_action.setCheckable(True)
        polygon_group.addAction(polygon_action)
        polygon_action.setChecked(True)

        self.geometry_style_button.setMenu(menu)
        self.buttonLayout.insertWidget(
            self.buttonLayout.indexOf(self.query_button), self.geometry_style_button
        )

    def _set_point_style(self, action):
        self._point_style = action.data()
        QtCore.QSettings().setValue(self.POINT_STYLE_KEY, self._point_style)

    def _stage_metadata_item(self, section_label, path_parts):
        label = self._metadata_stage_label(section_label, path_parts)
        for item in self._staged_metadata_items:
            if item["label"] == label:
                return
        self._staged_metadata_items.append(
            {
                "label": label,
                "section": section_label,
                "path": tuple(path_parts),
            }
        )

    def _unstage_metadata_item(self, label):
        self._staged_metadata_items = [
            item for item in self._staged_metadata_items if item["label"] != label
        ]

    def _metadata_stage_label(self, section_label, path_parts):
        display_parts = list(path_parts)
        if (
            section_label == "AdditionalMetadata"
            and display_parts
            and display_parts[0] == "additional_files_and_metadata"
        ):
            display_parts = display_parts[1:]
        return "{}.{}".format(section_label, ".".join(display_parts))

    def copy_last_query_to_csv(self):
        sql_text = self.sql_input.toPlainText().strip().rstrip(";")
        if not sql_text:
            self._show_error("Missing required fields: SQL")
            return
        if not self._staged_metadata_items:
            self._show_error("Select at least one metadata item to copy.")
            return
        if (
            not self._last_query_state
            or self._last_query_state.get("sql_text") != sql_text
        ):
            self._run_query_preview(add_to_history=False)
        if not self._last_query_state:
            return
        if "image_url" not in self._last_query_state.get("column_names", []):
            self._show_error(
                'Copy requires an "image_url" column in the query results.'
            )
            return

        query_rows = self._fetch_query_rows()
        if not query_rows:
            self._show_error("The query returned no rows to copy.")
            return

        formatted_query_rows = self._fetch_query_rows(formatted=True)
        entries = self._build_grouped_entries(
            query_rows, display_rows=formatted_query_rows
        )
        metadata_by_image_url = self._fetch_metadata_by_image_url(
            [image_url for entry in entries for image_url in entry["image_urls"]]
        )
        csv_text = self._build_copy_output(entries, metadata_by_image_url)
        if not csv_text.strip():
            self._show_error("Nothing was available to copy from the current query.")
            return

        QtWidgets.QApplication.clipboard().setText(csv_text)
        self._show_info(
            "Copied {} staged metadata item(s) to the clipboard.".format(
                len(self._staged_metadata_items)
            )
        )

    def _prepare_workbench_ui(self):
        if hasattr(self, "headerLayout"):
            while self.headerLayout.count():
                item = self.headerLayout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        if hasattr(self, "verticalLayout"):
            self.verticalLayout.setContentsMargins(18, 18, 18, 18)
            self.verticalLayout.setSpacing(10)
        if hasattr(self, "commands_frame"):
            self.commands_frame.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.commands_frame.setLineWidth(0)
        if hasattr(self, "commands_frame_layout"):
            self.commands_frame_layout.setContentsMargins(0, 0, 0, 0)
            self.commands_frame_layout.setSpacing(6)
        if hasattr(self, "commandsHeaderLayout"):
            self.commandsHeaderLayout.setContentsMargins(0, 0, 0, 0)
            self.commandsHeaderLayout.setSpacing(6)
        if hasattr(self, "commandsContentLayout"):
            self.commandsContentLayout.setContentsMargins(0, 0, 0, 0)
            self.commandsContentLayout.setSpacing(4)
        if hasattr(self, "commands_scroll_layout"):
            self.commands_scroll_layout.setContentsMargins(0, 0, 0, 0)
            self.commands_scroll_layout.setSpacing(4)
        if hasattr(self, "commands_scroll"):
            self.commands_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.sql_input.setPlaceholderText(self._sql_placeholder_text())
        self.commands_toggle_button.setStyleSheet("")
        self.history_menu_button.setStyleSheet("")
        self.star_menu_button.setStyleSheet("")
        if hasattr(self, "shared_menu_button"):
            self.shared_menu_button.setStyleSheet("")

    def _add_shared_menu_button(self):
        if not hasattr(self, "commandsHeaderLayout"):
            return
        self.shared_menu_button = QtWidgets.QToolButton(self)
        self.shared_menu_button.setText("Shared")
        self.shared_menu_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.shared_menu_button.setArrowType(QtCore.Qt.DownArrow)
        self.shared_menu_button.clicked.connect(self._show_shared_menu)
        self.commandsHeaderLayout.insertWidget(4, self.shared_menu_button)

    def _add_builder_help_button(self):
        if not hasattr(self, "commandsHeaderLayout"):
            return
        self.builder_help_button = QtWidgets.QToolButton(self)
        self.builder_help_button.setText("?")
        self.builder_help_button.setAutoRaise(True)
        self.builder_help_button.setToolTip("How the builder works")
        self.builder_help_button.clicked.connect(self._show_builder_help)
        self.commandsHeaderLayout.insertWidget(0, self.builder_help_button)

    def _show_builder_help(self):
        QtWidgets.QMessageBox.information(self, "Builder", self._builder_help_text())

    def _sql_placeholder_text(self):
        return self.QUERY_EXAMPLE

    def _builder_help_text(self):
        return (
            "Use the builder buttons to help write SQL, then click Query to preview "
            "the returned rows. Add requires an image_url column. If image_url is a "
            "string, each row is added directly. If image_url is a list, each item is "
            "treated as a grouped GeoImage entry.\n\n"
            "Example:\n{}".format(self._sql_placeholder_text())
        )

    def _toggle_commands(self, checked):
        self.builder_controller.toggle_commands(checked)

    def _layout_for_name(self, name):
        return getattr(self, name)

    def _clear_layout(self, layout):
        self.builder_controller.clear_layout(layout)

    def _make_insert_button(self, label, insert_text=None):
        return self.builder_controller.make_insert_button(label, insert_text)

    def _set_row_buttons(self, layout_name, items):
        layout = self._layout_for_name(layout_name)
        self.builder_controller.set_row_buttons(layout, items)

    def _populate_static_buttons(self):
        self._set_row_buttons(
            "row_one_layout", [(item, item) for item in self.STATIC_ROW_ONE]
        )
        self._set_row_buttons(
            "row_two_layout", [(item, item) for item in self.STATIC_ROW_TWO]
        )
        self._set_row_buttons(
            "row_three_layout", [(item, item) for item in self.STATIC_ROW_THREE]
        )
        actions = (
            (
                "File Spatial Query",
                "file_spatial_query_button",
                self._open_spatial_query_dialog,
            ),
            ("Select Bbox Query", "bbox_query_button", self._start_bbox_query),
            ("Metadata Query", "metadata_query_button", self._open_metadata_query_menu),
        )
        self._clear_layout(self.row_five_layout)
        for label, attribute, callback in actions:
            button = QtWidgets.QPushButton(label, self)
            button.setMinimumHeight(30)
            button.clicked.connect(callback)
            self.row_five_layout.addWidget(button)
            setattr(self, attribute, button)
        self.row_five_layout.addStretch()

    def _render_dynamic_buttons(self, tables, columns):
        table_items = [(table, table) for table in tables] or [("No tables", None)]
        column_items = [(column, column) for column in columns] or [
            ("No columns", None)
        ]
        self._set_row_buttons("row_four_layout", table_items + column_items)
        layout = self._layout_for_name("row_four_layout")
        if (
            layout.count() > 1
            and layout.itemAt(0).widget()
            and layout.itemAt(0).widget().text().startswith("No ")
        ):
            layout.itemAt(0).widget().setEnabled(False)

    def _insert_sql(self, token):
        self.builder_controller.insert_sql(token)

    def _build_history_menu(self):
        menu = QtWidgets.QMenu(self)
        history = self.history_controller.query_history
        if not history:
            empty_action = menu.addAction("No history yet")
            empty_action.setEnabled(False)
        else:
            clear_action = menu.addAction("Clear All")
            clear_action.triggered.connect(self.clear_history)
            menu.addSeparator()
            for index, query in enumerate(history):
                submenu = menu.addMenu(self._query_title(query))
                self._populate_local_query_submenu(
                    submenu,
                    query,
                    history_index=index,
                    include_star=True,
                )
        self.history_menu = menu

    def _show_history_menu(self):
        self._build_history_menu()
        self.history_menu.exec_(
            self.history_menu_button.mapToGlobal(
                QtCore.QPoint(0, self.history_menu_button.height())
            )
        )

    def _build_star_menu(self):
        menu = QtWidgets.QMenu(self)
        starred = self.history_controller.starred_queries
        if not starred:
            empty_action = menu.addAction("No starred queries yet")
            empty_action.setEnabled(False)
        else:
            clear_action = menu.addAction("Clear All")
            clear_action.triggered.connect(self.clear_starred)
            menu.addSeparator()
            for index, query in enumerate(starred):
                submenu = menu.addMenu(self._query_title(query))
                self._populate_local_query_submenu(
                    submenu,
                    query,
                    starred_index=index,
                    include_unstar=True,
                )
        self.star_menu = menu

    def _show_star_menu(self):
        self._build_star_menu()
        self.star_menu.exec_(
            self.star_menu_button.mapToGlobal(
                QtCore.QPoint(0, self.star_menu_button.height())
            )
        )

    def _build_shared_menu(self):
        menu = QtWidgets.QMenu(self)
        self._populate_shared_table_menu(menu)
        menu.addSeparator()
        shared_queries = self._load_shared_queries()
        if not shared_queries:
            empty_action = menu.addAction("No shared queries yet")
            empty_action.setEnabled(False)
        else:
            clear_action = menu.addAction("Clear All")
            clear_action.triggered.connect(self.clear_shared_queries)
            menu.addSeparator()
            for index, entry in enumerate(shared_queries):
                query = entry.get("sql", "")
                submenu = menu.addMenu(self._shared_query_title(entry))
                use_action = submenu.addAction("Use")
                use_action.triggered.connect(
                    lambda _=False, sql_text=query: self.sql_input.setPlainText(
                        sql_text
                    )
                )
                rename_action = submenu.addAction("Rename")
                rename_action.triggered.connect(
                    lambda _=False, i=index: self._rename_shared_query(i)
                )
                if entry.get("name"):
                    unname_action = submenu.addAction("Unname")
                    unname_action.triggered.connect(
                        lambda _=False, i=index: self._unname_shared_query(i)
                    )
                move_to_star_action = submenu.addAction("Move to Star")
                move_to_star_action.triggered.connect(
                    lambda _=False, i=index: self._move_shared_to_star(i)
                )
                delete_action = submenu.addAction("Delete")
                delete_action.triggered.connect(
                    lambda _=False, i=index: self._unshare_query(i)
                )
        self.shared_menu = menu

    def _show_shared_menu(self):
        self._build_shared_menu()
        self.shared_menu.exec_(
            self.shared_menu_button.mapToGlobal(
                QtCore.QPoint(0, self.shared_menu_button.height())
            )
        )

    def _populate_local_query_submenu(
        self,
        submenu,
        query,
        history_index=None,
        starred_index=None,
        include_star=False,
        include_unstar=False,
    ):
        has_shared_table = bool(self._shared_table_name)
        use_action = submenu.addAction("Use")
        use_action.triggered.connect(
            lambda _=False, sql_text=query: self.sql_input.setPlainText(sql_text)
        )
        rename_action = submenu.addAction("Rename")
        rename_action.triggered.connect(
            lambda _=False, sql_text=query: self._rename_query(sql_text)
        )
        if query in self.history_controller.query_names:
            unname_action = submenu.addAction("Unname")
            unname_action.triggered.connect(
                lambda _=False, sql_text=query: self._unname_query(sql_text)
            )
        if history_index is not None:
            shared_action = submenu.addAction("Move to Shared")
            shared_action.setEnabled(has_shared_table)
            shared_action.triggered.connect(
                lambda _=False, i=history_index: self._move_history_to_shared(i)
            )
        if include_star and history_index is not None:
            star_action = submenu.addAction("Move to Star")
            star_action.triggered.connect(
                lambda _=False, i=history_index: self._move_history_to_star(i)
            )
        if include_unstar and starred_index is not None:
            shared_from_star_action = submenu.addAction("Move to Shared")
            shared_from_star_action.setEnabled(has_shared_table)
            shared_from_star_action.triggered.connect(
                lambda _=False, i=starred_index: self._move_star_to_shared(i)
            )
        delete_action = submenu.addAction("Delete")
        if history_index is not None:
            delete_action.triggered.connect(
                lambda _=False, i=history_index: self._remove_history_item(i)
            )
        elif starred_index is not None:
            delete_action.triggered.connect(
                lambda _=False, i=starred_index: self._remove_star_item(i)
            )

    def _query_title(self, query):
        return self.history_controller.query_title(query)

    def _shared_query_title(self, entry):
        shared_name = (entry.get("name") or "").strip()
        if shared_name:
            return shared_name
        query = (entry.get("sql") or "").replace("\n", " ").strip()
        return query[:80]

    def _refresh_saved_query_menus(self):
        self._build_history_menu()
        self._build_star_menu()
        self._build_shared_menu()

    def _local_queries(self, category):
        if category == "history":
            return self.history_controller.query_history
        if category == "star":
            return self.history_controller.starred_queries
        return []

    def _add_local_query(self, category, query):
        queries = self._local_queries(category)
        normalized = query.strip()
        if normalized in queries:
            queries.remove(normalized)
        queries.insert(0, normalized)
        if category == "history":
            del queries[self.HISTORY_LIMIT :]
        self.history_controller.save()

    def _remove_local_query(self, category, index):
        queries = self._local_queries(category)
        if 0 <= index < len(queries):
            del queries[index]
            self.history_controller.save()
            return True
        return False

    def _move_local_query(self, index, source_category, target_category):
        queries = self._local_queries(source_category)
        if 0 <= index < len(queries):
            query = queries[index]
            self._add_local_query(target_category, query)
            self._remove_local_query(source_category, index)
            self._refresh_saved_query_menus()
            return True
        return False

    def _rename_query(self, query):
        self.history_controller.rename_query(query)
        self._refresh_saved_query_menus()

    def _unname_query(self, query):
        self.history_controller.unname_query(query)
        self._refresh_saved_query_menus()

    def _add_history_item(self, sql_text):
        self.history_controller.add_history_item(sql_text)
        self._refresh_saved_query_menus()

    def _remove_history_item(self, index):
        self.history_controller.remove_history_item(index)
        self._refresh_saved_query_menus()

    def clear_history(self):
        self.history_controller.clear_history()
        self._refresh_saved_query_menus()

    def _star_history_item(self, index):
        if 0 <= index < len(self.history_controller.query_history):
            self._add_local_query("star", self.history_controller.query_history[index])
            self._refresh_saved_query_menus()

    def _move_history_to_star(self, index):
        self._move_local_query(index, "history", "star")

    def _move_history_to_shared(self, index):
        if 0 <= index < len(self.history_controller.query_history):
            query = self.history_controller.query_history[index]
            if self._share_query(query, silent=True):
                self.history_controller.remove_history_item(index)
                self._build_history_menu()
                self._build_star_menu()

    def _move_star_to_shared(self, index):
        if 0 <= index < len(self.history_controller.starred_queries):
            query = self.history_controller.starred_queries[index]
            if self._share_query(query, silent=True):
                self.history_controller.remove_star_item(index)
                self._build_history_menu()
                self._build_star_menu()

    def _move_shared_to_star(self, index):
        shared_queries = self._load_shared_queries()
        if 0 <= index < len(shared_queries):
            query = shared_queries[index].get("sql", "")
            self._add_local_query("star", query)
            self._unshare_query(index, silent=True)
            self._refresh_saved_query_menus()

    def _unstar_item(self, index):
        self._remove_local_query("star", index)
        self._refresh_saved_query_menus()

    def _remove_star_item(self, index):
        self._remove_local_query("star", index)
        self._refresh_saved_query_menus()

    def clear_starred(self):
        self.history_controller.clear_starred()
        self._refresh_saved_query_menus()

    def _populate_shared_table_menu(self, menu):
        current_table = self._shared_table_name
        label = (
            "Select Table"
            if not current_table
            else "Change table from: {}".format(current_table)
        )
        table_menu = menu.addMenu(label)
        tables = self._fetch_schema_table_names()
        if not tables:
            empty_action = table_menu.addAction("No tables found")
            empty_action.setEnabled(False)
            return
        for table_name in tables:
            table_menu.addAction(
                table_name,
                lambda _checked=False, name=table_name: self._set_shared_table(name),
            )

    def _set_shared_table(self, table_name):
        self._shared_table_name = table_name or ""
        settings = QtCore.QSettings()
        settings.setValue(self.SHARED_TABLE_KEY, self._shared_table_name)

    def _fetch_schema_table_names(self):
        return fetch_base_tables(self.connection_values)

    def _current_shared_query_source(self):
        if not self._shared_table_name:
            return None
        return {
            "schema": self.connection_values.get("schema", "public").strip()
            or "public",
            "table": self._shared_table_name,
        }

    def _load_shared_queries(self):
        query_source = self._current_shared_query_source()
        if not query_source:
            return []
        payload = self._read_table_comment_payload(query_source)
        return list(payload.get(self.SHARED_QUERY_KEY, []))

    def _read_table_comment_payload(self, query_source):
        valid, message = self._validate_connection_values(self.connection_values)
        if not valid:
            self._show_error(message)
            return {}

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        comment_text = ""
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        """
                        SELECT pg_catalog.obj_description(
                            %s::regclass,
                            'pg_class'
                        )
                        """,
                        (
                            '"{}"."{}"'.format(
                                query_source["schema"], query_source["table"]
                            ),
                        ),
                    )
                    result = cursor.fetchone()
                    comment_text = result[0] if result else ""
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not load shared queries: {}".format(exc))
            return {}

        if not comment_text:
            return {}
        try:
            payload = json.loads(comment_text)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        container = payload.get(self.SHARED_COMMENT_KEY, {})
        return container if isinstance(container, dict) else {}

    def _write_table_comment_payload(self, query_source, payload):
        valid, message = self._validate_connection_values(self.connection_values)
        if not valid:
            self._show_error(message)
            return False

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        comment_text = json.dumps(
            {self.SHARED_COMMENT_KEY: payload},
            indent=2,
            sort_keys=True,
        )
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(
                            sql.Identifier(query_source["schema"]),
                            sql.Identifier(query_source["table"]),
                            sql.Literal(comment_text),
                        )
                    )
                connection.commit()
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not save shared queries: {}".format(exc))
            return False
        return True

    def _share_query(self, query, silent=False):
        query_source = self._current_shared_query_source()
        if not query_source:
            if not silent:
                self._show_error("Shared queries require a selected shared table.")
            return False
        payload = self._read_table_comment_payload(query_source)
        shared_queries = list(payload.get(self.SHARED_QUERY_KEY, []))
        shared_name = self.history_controller.query_names.get(query, "")
        shared_entry = {"sql": query}
        if shared_name:
            shared_entry["name"] = shared_name
        shared_queries = [
            entry for entry in shared_queries if entry.get("sql") != query
        ]
        shared_queries.insert(0, shared_entry)
        payload[self.SHARED_QUERY_KEY] = shared_queries
        if not self._write_table_comment_payload(query_source, payload):
            return False
        self._refresh_saved_query_menus()
        if not silent:
            self._show_info(
                'Query shared to "{}"."{}".'.format(
                    query_source["schema"], query_source["table"]
                )
            )
        return True

    def _update_shared_query(self, index, entry):
        query_source = self._current_shared_query_source()
        if not query_source:
            self._show_error("Shared queries require a selected shared table.")
            return False
        payload = self._read_table_comment_payload(query_source)
        shared_queries = list(payload.get(self.SHARED_QUERY_KEY, []))
        if not (0 <= index < len(shared_queries)):
            return False
        shared_queries[index] = entry
        payload[self.SHARED_QUERY_KEY] = shared_queries
        return self._write_table_comment_payload(query_source, payload)

    def _rename_shared_query(self, index):
        shared_queries = self._load_shared_queries()
        if not (0 <= index < len(shared_queries)):
            return
        current_name = shared_queries[index].get("name", "")
        new_name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Rename Shared Query",
            "Name",
            text=current_name,
        )
        if accepted and new_name.strip():
            shared_queries[index]["name"] = new_name.strip()
            if self._update_shared_query(index, shared_queries[index]):
                self._build_shared_menu()
                self._show_info("Shared query renamed.")

    def _unname_shared_query(self, index):
        shared_queries = self._load_shared_queries()
        if not (0 <= index < len(shared_queries)):
            return
        shared_queries[index].pop("name", None)
        if self._update_shared_query(index, shared_queries[index]):
            self._build_shared_menu()
            self._show_info("Shared query name removed.")

    def _unshare_query(self, index, silent=False):
        query_source = self._current_shared_query_source()
        if not query_source:
            if not silent:
                self._show_error("Shared queries require a selected shared table.")
            return
        payload = self._read_table_comment_payload(query_source)
        shared_queries = list(payload.get(self.SHARED_QUERY_KEY, []))
        if not (0 <= index < len(shared_queries)):
            return
        del shared_queries[index]
        payload[self.SHARED_QUERY_KEY] = shared_queries
        if self._write_table_comment_payload(query_source, payload):
            if not silent:
                self._show_info("Shared query removed.")
            self._build_shared_menu()

    def clear_shared_queries(self):
        query_source = self._current_shared_query_source()
        if not query_source:
            self._show_error("Shared queries require a selected shared table.")
            return
        payload = self._read_table_comment_payload(query_source)
        payload[self.SHARED_QUERY_KEY] = []
        if self._write_table_comment_payload(query_source, payload):
            self._show_info("Cleared shared queries.")
            self._build_shared_menu()

    def _validate_connection_values(self, values):
        return validate_connection_values(values)

    def _connection_kwargs(self, values=None):
        return connection_kwargs(values or self.connection_values)

    def _refresh_schema_buttons(self, silent):
        valid, message = self._validate_connection_values(self.connection_values)
        if not valid:
            if not silent:
                self._show_error(message)
            self._render_dynamic_buttons([], [])
            return

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = %s AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """,
                        (schema_name,),
                    )
                    tables = ['"{}"'.format(row[0]) for row in cursor.fetchall()]
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s
                        ORDER BY table_name, ordinal_position
                        """,
                        (schema_name,),
                    )
                    columns = ['"{}"'.format(row[0]) for row in cursor.fetchall()]
        except Exception as exc:  # pragma: no cover - depends on external DB
            if not silent:
                self._show_error("Could not load schema metadata: {}".format(exc))
            return

        self._render_dynamic_buttons(tables, columns)

    def run_query(self):
        self._run_query_preview(add_to_history=True)

    def _run_query_preview(self, add_to_history):
        start_row, end_row = self._validated_preview_range()
        if end_row == start_row:
            self._show_error("Results range must span at least one row.")
            return

        valid, message = self._validate_connection_values(self.connection_values)
        if not valid:
            self._show_error(message)
            return

        sql_text = self.sql_input.toPlainText().strip().rstrip(";")
        if not sql_text:
            self._show_error("Missing required fields: SQL")
            return

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        query_name = "Query {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        live_query = self._build_live_query(sql_text)
        query_source = self._parse_query_source(sql_text)
        source_column_info = []

        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    column_info = self._get_column_info(cursor, live_query)
                    row_count = self._get_row_count(cursor, live_query)
                    preview_rows = self._get_preview_rows(
                        cursor,
                        live_query,
                        column_info,
                        start_row,
                        end_row,
                    )
                    if query_source:
                        source_query = self._build_source_query_from_source(
                            query_source
                        )
                        source_column_info = self._get_column_info(cursor, source_query)
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Query failed: {}".format(exc))
            return

        vector_column = self._find_first_column(column_info, {"geometry", "geography"})
        source_vector_column = self._find_first_column(
            source_column_info, {"geometry", "geography"}
        )
        self._populate_preview(column_info, preview_rows, row_count)
        if add_to_history:
            self._add_history_item(sql_text)
        self._last_query_state = {
            "query_name": query_name,
            "sql_text": sql_text,
            "live_query": live_query,
            "query_source": query_source,
            "column_info": column_info,
            "column_names": [column["name"] for column in column_info],
            "raster_source": query_source,
            "vector_column": vector_column,
            "source_vector_column": source_vector_column,
            "raster_columns": [
                column["name"]
                for column in source_column_info
                if column["udt_name"] == "raster"
            ],
            "row_count": row_count,
        }
        self._update_add_buttons_state()
        self.bottom_tabs.setCurrentWidget(self.results_tab)
        self._show_info(
            "Previewed {} row(s). Click Add to load layers into the map.".format(
                row_count
            )
        )

    def add_image_urls_to_map(
        self, source_query, image_urls, add_thumbnail=True, add_geometry=True
    ):
        """Run a query for checked View images through the normal Query workflow."""
        if not image_urls:
            self._show_error("Select at least one image to add.")
            return
        source = self._parse_query_source(source_query)
        if not source:
            self._show_error("Could not identify the source table for these images.")
            return
        base_query = "SELECT * FROM {}.{}".format(
            self._quote_identifier(source["schema"]),
            self._quote_identifier(source["table"]),
        )
        query = self._build_image_url_query(image_urls, base_query=base_query)
        self.sql_input.setPlainText(query)
        self._last_query_state = None
        self._run_query_preview(add_to_history=True)
        if self._last_query_state is not None:
            self.add_last_query_to_map(
                add_thumbnail=add_thumbnail, add_geometry=add_geometry
            )

    def add_last_query_to_map(self, add_thumbnail=True, add_geometry=True):
        sql_text = self.sql_input.toPlainText().strip().rstrip(";")
        if not sql_text:
            self._show_error("Missing required fields: SQL")
            return
        if (
            not self._last_query_state
            or self._last_query_state.get("sql_text") != sql_text
        ):
            self._run_query_preview(add_to_history=False)
        if not self._last_query_state:
            return
        if "image_url" not in self._last_query_state.get("column_names", []):
            self._show_error('Add requires an "image_url" column in the query results.')
            return
        if not add_thumbnail and not add_geometry:
            self._show_error("Select at least one layer type to add.")
            return

        query_name = self._last_query_state["query_name"]
        root_group = self._ensure_query_group(query_name)
        added_layers = []
        if self._is_grouped_add_query():
            added_layers.extend(
                self._add_grouped_query_layers(
                    root_group,
                    add_thumbnail=add_thumbnail,
                    add_geometry=add_geometry,
                )
            )
        else:
            added_layers.extend(
                self._add_non_grouped_query_layers(
                    root_group,
                    add_thumbnail=add_thumbnail,
                    add_geometry=add_geometry,
                )
            )

        if added_layers:
            self._show_info(
                'Loaded {} layer(s) for "{}".'.format(
                    len(added_layers),
                    query_name,
                )
            )
        else:
            self._show_error("Nothing was added to the map from the current preview.")

    def _is_grouped_add_query(self):
        for column in self._last_query_state.get("column_info", []):
            if column["name"] == "image_url":
                return column.get("udt_name", "").startswith("_")
        return False

    def _group_column_names(self):
        return [
            column_name
            for column_name in self._last_query_state.get("column_names", [])
            if column_name not in ("image_url", self.KEY_COLUMN)
        ]

    def _add_non_grouped_query_layers(
        self, root_group, add_thumbnail=True, add_geometry=True
    ):
        added_layers = []
        if add_thumbnail:
            thumbnail_group = self._ensure_child_group(root_group, "thumbnail")
            image_urls = self._fetch_add_image_urls()
            added_layers.extend(
                self._add_thumbnail_layers_for_image_urls(thumbnail_group, image_urls)
            )
        if add_geometry:
            vector_column = self._last_query_state.get("vector_column")
            if vector_column:
                geometry_group = self._ensure_child_group(root_group, "geometry")
                added_layers.extend(
                    self._add_geometry_layers_for_query(
                        geometry_group,
                        self._last_query_state["live_query"],
                        vector_column,
                    )
                )
        return added_layers

    def _add_grouped_query_layers(
        self, root_group, add_thumbnail=True, add_geometry=True
    ):
        group_columns = self._group_column_names()
        group_rows = self._fetch_group_rows(include_image_urls=add_thumbnail)
        if not group_rows:
            return []

        added_layers = []
        for group_row in group_rows:
            raw_group_values = tuple(
                group_row.get(column_name) for column_name in group_columns
            )
            group_labels = tuple("{}".format(value) for value in raw_group_values)
            parent_group = root_group
            for part in group_labels:
                parent_group = self._ensure_child_group(parent_group, part)
            if add_thumbnail:
                thumbnail_group = self._ensure_child_group(parent_group, "thumbnail")
                image_urls = self._normalize_image_urls(group_row.get("image_url"))
                added_layers.extend(
                    self._add_thumbnail_layers_for_image_urls(
                        thumbnail_group, image_urls
                    )
                )
            if add_geometry:
                geometry_group = self._ensure_child_group(parent_group, "geometry")
                geometry_query, geometry_column = self._build_group_geometry_query(
                    group_columns,
                    raw_group_values,
                )
                if geometry_query and geometry_column:
                    added_layers.extend(
                        self._add_geometry_layers_for_query(
                            geometry_group,
                            geometry_query,
                            geometry_column,
                        )
                    )
        return added_layers

    def _fetch_add_image_urls(self):
        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        image_urls = []
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        sql.SQL(
                            "SELECT q.image_url FROM ({}) AS q WHERE q.image_url IS NOT NULL"
                        ).format(sql.SQL(self._last_query_state["live_query"]))
                    )
                    image_urls = [row[0] for row in cursor.fetchall() if row and row[0]]
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not load image URLs: {}".format(exc))
        return image_urls

    def _fetch_group_rows(self, include_image_urls):
        group_columns = self._group_column_names()
        if not group_columns and not include_image_urls:
            return []

        select_items = [
            sql.SQL("q.{}").format(sql.Identifier(column_name))
            for column_name in group_columns
        ]
        if include_image_urls:
            select_items.append(sql.SQL("q.image_url"))

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        rows = []
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        sql.SQL("SELECT {} FROM ({}) AS q").format(
                            sql.SQL(", ").join(select_items),
                            sql.SQL(self._last_query_state["live_query"]),
                        )
                    )
                    rows = cursor.fetchall()
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not load grouped query rows: {}".format(exc))
            return []

        column_names = list(group_columns)
        if include_image_urls:
            column_names.append("image_url")
        return [dict(zip(column_names, row)) for row in rows]

    def _fetch_query_rows(self, formatted=False):
        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        rows = []
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    select_items = self._build_query_select_items(formatted=formatted)
                    cursor.execute(
                        sql.SQL("SELECT {} FROM ({}) AS q").format(
                            select_items,
                            sql.SQL(self._last_query_state["live_query"]),
                        )
                    )
                    rows = cursor.fetchall()
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not load query rows: {}".format(exc))
        return rows

    def _build_grouped_entries(self, query_rows, display_rows=None):
        grouped_entries = {}
        column_names = self._last_query_state["column_names"]
        image_url_index = column_names.index("image_url")
        if display_rows is None:
            display_rows = query_rows

        for row, display_row in zip(query_rows, display_rows):
            image_url_value = row[image_url_index]
            image_urls = self._normalize_image_urls(image_url_value)
            if not image_urls:
                continue

            is_grouped_row = isinstance(image_url_value, (list, tuple)) or (
                isinstance(image_url_value, str)
                and image_url_value.startswith("{")
                and image_url_value.endswith("}")
            )
            if is_grouped_row:
                group_columns = tuple(
                    column_name
                    for column_name in column_names
                    if column_name not in ("image_url", self.KEY_COLUMN)
                )
                group_values = tuple(
                    "{}".format(value)
                    for column_name, value in zip(column_names, row)
                    if column_name not in ("image_url", self.KEY_COLUMN)
                )
            else:
                group_columns = tuple()
                group_values = tuple()

            field_values = {
                column_name: value
                for column_name, value in zip(column_names, display_row)
                if column_name not in ("image_url", self.KEY_COLUMN)
            }
            entry = grouped_entries.setdefault(
                group_values,
                {
                    "group_columns": group_columns,
                    "group_values": group_values,
                    "image_urls": [],
                    "rows": [],
                },
            )
            entry["rows"].append(
                {
                    "field_values": field_values,
                    "image_urls": image_urls,
                }
            )
            for image_url in image_urls:
                if image_url not in entry["image_urls"]:
                    entry["image_urls"].append(image_url)

        return list(grouped_entries.values())

    def _normalize_image_urls(self, value):
        if isinstance(value, (list, tuple)):
            return [item for item in value if item]
        if not value:
            return []
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            stripped = value[1:-1].strip()
            if not stripped:
                return []
            return [
                item.strip().strip('"') for item in stripped.split(",") if item.strip()
            ]
        return [str(value)]

    def _ensure_child_group(self, parent_group, label):
        for child in parent_group.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == label:
                child.setExpanded(False)
                return child
        child_group = parent_group.addGroup(label)
        if isinstance(child_group, QgsLayerTreeGroup):
            child_group.setExpanded(False)
        return child_group

    def _add_group_layers(
        self, parent_group, entry, add_thumbnail=True, add_geometry=True
    ):
        added_layers = []
        if add_thumbnail:
            thumbnail_group = self._ensure_child_group(parent_group, "thumbnail")
            added_layers.extend(self._add_thumbnail_layers(thumbnail_group, entry))
        if add_geometry:
            geometry_group = self._ensure_child_group(parent_group, "geometry")
            added_layers.extend(self._add_geometry_layers(geometry_group, entry))
        return added_layers

    def _add_thumbnail_layers(self, group, entry):
        return self._add_thumbnail_layers_for_image_urls(group, entry["image_urls"])

    def _add_thumbnail_layers_for_image_urls(self, group, image_urls):
        added_layers = []
        raster_source = self._last_query_state.get("raster_source")
        raster_columns = self._last_query_state.get("raster_columns") or []
        if not raster_source or not raster_columns:
            self._show_error(
                "Could not identify a source table with thumbnails for this query."
            )
            return added_layers

        supported_image_urls = self._get_thumbnail_image_urls(image_urls)
        for image_url in supported_image_urls:
            row_filter = self._build_thumbnail_row_filter(image_url)
            for raster_column in raster_columns:
                raster_layer = self._create_raster_layer(
                    raster_source,
                    raster_column,
                    row_filter,
                    os.path.basename(image_url) or image_url,
                )
                if raster_layer is not None:
                    added_layers.append(raster_layer.name())
                    self._add_layer_to_group(group, raster_layer, insert_at_top=True)
        return added_layers

    def _build_thumbnail_row_filter(self, image_url):
        return '"image_url" = {}'.format(self._sql_literal(image_url))

    def _add_geometry_layers(self, group, entry):
        filtered_query = self._build_entry_layer_query(entry)
        vector_column = self._last_query_state.get(
            "source_vector_column"
        ) or self._last_query_state.get("vector_column")
        return self._add_geometry_layers_for_query(group, filtered_query, vector_column)

    def _add_geometry_layers_for_query(self, group, filtered_query, vector_column):
        added_layers = []
        if not filtered_query or not vector_column:
            return added_layers

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        geometry_types = []
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    geometry_types = self._get_geometry_types(
                        cursor, filtered_query, vector_column
                    )
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not inspect geometry types: {}".format(exc))
            return added_layers

        geometry_families = self._geometry_families(geometry_types)
        if len(geometry_families) <= 1:
            layer = self._create_vector_layer(filtered_query, vector_column, "geometry")
            if layer is not None:
                added_layers.append(layer.name())
                self._add_layer_to_group(group, layer)
            return added_layers

        for family in geometry_families:
            family_query = self._build_geometry_family_query(
                filtered_query, vector_column, family
            )
            layer = self._create_vector_layer(family_query, vector_column, family)
            if layer is not None:
                added_layers.append(layer.name())
                self._add_layer_to_group(group, layer)
        return added_layers

    def _build_group_geometry_query(self, group_columns, group_values):
        source_vector_column = self._last_query_state.get("source_vector_column")
        if source_vector_column:
            group_query = self._build_group_filter_query(group_columns, group_values)
            return (
                "SELECT src.* FROM ({}) AS src "
                "JOIN ({}) AS grp ON src.image_url = ANY(grp.image_url)"
            ).format(
                self._build_source_query(),
                group_query,
            ), source_vector_column

        vector_column = self._last_query_state.get("vector_column")
        return (
            self._build_group_filter_query(group_columns, group_values),
            vector_column,
        )

    def _build_entry_layer_query(self, entry):
        if not entry["group_columns"]:
            query_source = self._last_query_state.get("query_source")
            if query_source and self._last_query_state.get("source_vector_column"):
                return self._build_image_url_query(entry["image_urls"])
            return self._last_query_state["live_query"]

        group_query = self._build_group_entry_query(entry)
        return (
            "SELECT src.* FROM ({}) AS src "
            "JOIN ({}) AS grp ON src.image_url = ANY(grp.image_url)"
        ).format(
            self._build_source_query(),
            group_query,
        )

    def _build_group_entry_query(self, entry):
        return self._build_group_filter_query(
            entry["group_columns"], entry["group_values"]
        )

    def _build_group_filter_query(self, group_columns, group_values):
        filters = []
        for column_name, value in zip(group_columns, group_values):
            column_sql = "grp.{}".format(self._quote_identifier(column_name))
            if value is None:
                filters.append("{} IS NULL".format(column_sql))
            else:
                filters.append(
                    "{} = {}".format(
                        column_sql,
                        self._sql_literal(value),
                    )
                )
        base_query = "SELECT * FROM ({}) AS grp".format(
            self._last_query_state["live_query"]
        )
        if not filters:
            return base_query
        return "{} WHERE {}".format(base_query, " AND ".join(filters))

    def _build_image_url_query(self, image_urls, *, base_query=None):
        values = ", ".join(self._sql_literal(url) for url in dict.fromkeys(image_urls))
        return "SELECT * FROM ({}) AS q WHERE {}".format(
            base_query if base_query is not None else self._build_source_query(),
            "q.image_url IN ({})".format(values) if values else "FALSE",
        )

    def _geometry_families(self, geometry_types):
        families = []
        for geometry_type in geometry_types:
            normalized = geometry_type.upper()
            if "POINT" in normalized:
                family = "points"
            elif "POLYGON" in normalized:
                family = "polygons"
            elif "LINE" in normalized:
                family = "lines"
            else:
                family = normalized.replace("ST_", "").lower()
            if family not in families:
                families.append(family)
        return families

    def _build_geometry_family_query(self, filtered_query, geometry_column, family):
        if family == "points":
            match = "LIKE 'ST_%Point'"
        elif family == "polygons":
            match = "LIKE 'ST_%Polygon'"
        elif family == "lines":
            match = "LIKE 'ST_%LineString'"
        else:
            match = "= '{}'".format(family)
        return "SELECT * FROM ({}) AS q WHERE ST_GeometryType(q.{}) {}".format(
            filtered_query,
            self._quote_identifier(geometry_column),
            match,
        )

    def _build_live_query(self, sql_text):
        return "SELECT row_number() OVER () AS {key}, src.* FROM ({sql}) AS src".format(
            key=self.KEY_COLUMN,
            sql=sql_text,
        )

    def _parse_query_source(self, sql_text):
        match = self.SOURCE_TABLE_RE.search(sql_text)
        if not match:
            return None
        source = {
            key: (
                value[1:-1].replace('""', '"')
                if value.startswith('"')
                else value.lower()
            )
            for key, value in match.groupdict().items()
            if value
        }
        source.setdefault(
            "schema", self.connection_values.get("schema", "public").strip() or "public"
        )
        return source

    def _build_source_query_from_source(self, query_source):
        base_query = 'SELECT * FROM "{}"."{}"'.format(
            query_source["schema"].replace('"', '""'),
            query_source["table"].replace('"', '""'),
        )
        return self._build_live_query(base_query)

    def _build_source_query(self):
        query_source = self._last_query_state.get("query_source")
        if not query_source:
            return self._last_query_state["live_query"]
        return self._build_source_query_from_source(query_source)

    def _open_spatial_query_dialog(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Vector File",
            "",
            "Vector files (*.gpkg *.geojson *.json *.shp *.kml);;All files (*)",
        )
        if not file_path:
            return

        layer = QgsVectorLayer(file_path, "spatial_query_source", "ogr")
        if not layer.isValid():
            self._show_error("Could not open the selected vector file.")
            return

        feature = next(layer.getFeatures(QgsFeatureRequest().setLimit(1)), None)
        if feature is None or not feature.hasGeometry():
            self._show_error("The selected vector file has no geometry.")
            return

        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            self._show_error("The selected vector geometry is empty.")
            return

        self._insert_spatial_query(geometry, layer.crs())

    def _insert_spatial_query(self, geometry, crs):
        """Use the same CRS-aware condition for file and map selections."""
        if not crs.isValid():
            self._show_error(
                "The spatial query source has no valid coordinate reference system."
            )
            return
        geometry = QgsGeometry(geometry)
        srid = crs.postgisSrid()
        if srid <= 0:
            try:
                geometry.transform(
                    QgsCoordinateTransform(
                        crs,
                        QgsCoordinateReferenceSystem("EPSG:4326"),
                        QgsProject.instance(),
                    )
                )
            except Exception as exc:
                self._show_error(
                    "Could not transform the spatial query geometry: {}".format(exc)
                )
                return
            srid = 4326
        source = "ST_Transform(ST_GeomFromText('{}', {}), ST_SRID(geometry))".format(
            geometry.asWkt().replace("'", "''"), srid
        )
        if geometry.type() == QgsWkbTypes.PointGeometry:
            snippet = "ST_DWithin(geometry, {}, 0)".format(source)
        else:
            snippet = "ST_Intersects(geometry, {})".format(source)
        self._insert_sql(snippet)
        self._show_info("Spatial query text inserted. Adjust it if needed.")

    def _start_bbox_query(self):
        if self._bbox_tool is not None:
            return
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            self._show_error("A QGIS map canvas is required to select a bounding box.")
            return
        if not canvas.mapSettings().destinationCrs().isValid():
            self._show_error(
                "Set the map's coordinate reference system before selecting a bounding box."
            )
            return
        self._bbox_canvas = canvas
        self._bbox_previous_tool = canvas.mapTool()
        self._bbox_window = self.window()
        self._bbox_restore_window = (
            self._bbox_window is not canvas.window() and self._bbox_window.isVisible()
        )
        self._bbox_tool = BboxSelectionTool(canvas)
        self._bbox_tool.extentChanged.connect(self._bbox_selected)
        self._bbox_tool.cancelled.connect(self._finish_bbox_selection)
        canvas.mapToolSet.connect(self._bbox_map_tool_changed)
        canvas.setMapTool(self._bbox_tool)
        self._show_info(
            "Drag a rectangle on the map. Press Escape or right-click to cancel."
        )
        if self._bbox_restore_window:
            self._bbox_window.hide()
        canvas.setFocus()

    def _bbox_selected(self, rectangle):
        if rectangle.isEmpty():
            self._show_info("Drag a rectangle with a nonzero width and height.")
            return
        crs = self._bbox_canvas.mapSettings().destinationCrs()
        self._finish_bbox_selection()
        self._insert_spatial_query(QgsGeometry.fromRect(rectangle), crs)

    def _bbox_map_tool_changed(self, tool, _previous_tool):
        if self._bbox_tool is not None and tool is not self._bbox_tool:
            self._finish_bbox_selection()

    def _finish_bbox_selection(self, show_window=True):
        tool = self._bbox_tool
        if tool is None:
            return
        self._bbox_tool = None
        canvas = self._bbox_canvas
        canvas.mapToolSet.disconnect(self._bbox_map_tool_changed)
        if canvas.mapTool() is tool:
            if self._bbox_previous_tool is not None:
                canvas.setMapTool(self._bbox_previous_tool)
            else:
                canvas.unsetMapTool(tool)
        tool.clearRubberBand()
        tool.deleteLater()
        if show_window and self._bbox_restore_window:
            self._bbox_window.show()
            self._bbox_window.raise_()
            self._bbox_window.activateWindow()
            self.sql_input.setFocus()

    def _open_metadata_query_menu(self):
        button = getattr(self, "metadata_query_button", None)
        if button is None:
            return

        menu = QtWidgets.QMenu(button)
        self._populate_metadata_sections(
            menu,
            lambda _section, path: self._insert_sql(
                self._metadata_sql_expression(path)
            ),
        )
        menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

    def _populate_metadata_sections(self, menu, leaf_callback):
        self._additional_metadata_schema = load_metadata_tree()
        if self._additional_metadata_schema:
            submenu = menu.addMenu("Metadata")
            self._populate_metadata_submenu(
                submenu,
                self._additional_metadata_schema,
                [],
                "Metadata",
                leaf_callback,
            )
        else:
            action = menu.addAction("Use Import tab to fetch metadata structure")
            action.setEnabled(False)

    def _strip_additional_metadata_section(self, metadata):
        if not isinstance(metadata, dict):
            return metadata
        return {
            key: value
            for key, value in metadata.items()
            if key != "additional_files_and_metadata"
        }

    def _metadata_schema_intersection(self, schemas):
        if not schemas:
            return {}

        first_schema = schemas[0]
        shared = {}
        for key, value in first_schema.items():
            if not all(
                isinstance(schema, dict) and key in schema for schema in schemas[1:]
            ):
                continue
            other_values = [schema[key] for schema in schemas[1:]]
            if isinstance(value, dict) and all(
                isinstance(other, dict) for other in other_values
            ):
                nested_shared = self._metadata_schema_intersection(
                    [value] + other_values
                )
                if nested_shared:
                    shared[key] = nested_shared
            else:
                shared[key] = value
        return shared

    def _metadata_schema_difference(self, schema, base_schema):
        if not isinstance(schema, dict):
            return schema

        difference = {}
        for key, value in schema.items():
            if key not in base_schema:
                difference[key] = value
                continue
            base_value = base_schema[key]
            if isinstance(value, dict) and isinstance(base_value, dict):
                nested_difference = self._metadata_schema_difference(value, base_value)
                if nested_difference:
                    difference[key] = nested_difference
        return difference

    def _merge_schema_values(self, current, value):
        if isinstance(value, dict):
            merged = dict(current or {})
            for key, item in value.items():
                merged[key] = self._merge_schema_values(merged.get(key), item)
            return merged
        if isinstance(value, list):
            return None
        return None

    def _populate_metadata_submenu(
        self, menu, metadata, path_parts, section_label, leaf_callback
    ):
        for key, value in metadata.items():
            current_path = path_parts + [key]
            if isinstance(value, dict):
                submenu = menu.addMenu(key)
                self._populate_metadata_submenu(
                    submenu,
                    value,
                    current_path,
                    section_label,
                    leaf_callback,
                )
                continue
            action = menu.addAction(key)
            action.triggered.connect(
                lambda _checked=False, path=current_path, section=section_label: leaf_callback(
                    section,
                    path,
                )
            )

    def _metadata_sql_expression(self, path_parts):
        if not path_parts:
            return "metadata"
        sql_parts = ["metadata::jsonb"]
        for key in path_parts[:-1]:
            sql_parts.append("->'{}'".format(key.replace("'", "''")))
        sql_parts.append("->>'{}'".format(path_parts[-1].replace("'", "''")))
        return "".join(sql_parts)

    def _fetch_metadata_by_image_url(self, image_urls):
        if not image_urls:
            return {}

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        metadata_by_image_url = {}
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        sql.SQL(
                            "SELECT q.image_url, q.metadata FROM ({}) AS q WHERE q.image_url = ANY(%s)"
                        ).format(sql.SQL(self._build_source_query())),
                        (list(image_urls),),
                    )
                    for image_url, metadata in cursor.fetchall():
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except Exception:
                                metadata = {}
                        metadata_by_image_url[image_url] = metadata or {}
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not load metadata rows: {}".format(exc))
        return metadata_by_image_url

    def _build_copy_output(self, entries, metadata_by_image_url):
        query_headers = []
        if entries:
            query_headers = list(entries[0]["group_columns"])
        metadata_headers = self._metadata_copy_headers(query_headers)
        entry_blocks = []
        for entry in entries:
            rows = []
            for row_info in entry["rows"]:
                for image_url in row_info["image_urls"]:
                    row_values = [
                        row_info["field_values"].get(column_name)
                        for column_name in query_headers
                    ]
                    metadata = metadata_by_image_url.get(image_url, {})
                    for item in self._staged_metadata_items:
                        row_values.append(
                            self._extract_metadata_value(metadata, item["path"])
                        )
                    rows.append(row_values)
            if rows:
                entry_blocks.append((entry, rows))

        if not entry_blocks:
            return ""

        header_row = query_headers + metadata_headers
        if not any(entry["group_columns"] for entry, _rows in entry_blocks):
            return self._csv_block(
                header_row,
                [row for _entry, rows in entry_blocks for row in rows],
            )

        blocks = []
        for entry, rows in entry_blocks:
            heading = self._group_heading(entry)
            csv_block = self._csv_block(header_row, rows)
            blocks.append("{}\n{}".format(heading, csv_block) if heading else csv_block)
        return "\n\n".join(blocks)

    def _metadata_copy_headers(self, query_headers):
        headers = []
        used = set(header.lower() for header in query_headers)
        for item in self._staged_metadata_items:
            header = self._pretty_metadata_header(item["path"])
            if header.lower() in used:
                header = item["label"].split(".", 1)[-1]
            headers.append(header)
            used.add(header.lower())
        return headers

    def _pretty_metadata_header(self, path_parts):
        if not path_parts:
            return "Metadata"
        return path_parts[-1].replace("_", " ").title()

    def _extract_metadata_value(self, metadata, path_parts):
        value = metadata or {}
        for path_part in path_parts:
            if not isinstance(value, dict):
                return None
            value = value.get(path_part)
        return value

    def _group_heading(self, entry):
        return ".".join(
            "{}={}".format(
                column_name.replace("_", " ").title(),
                value,
            )
            for column_name, value in zip(entry["group_columns"], entry["group_values"])
        )

    def _csv_block(self, headers, rows):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
        return stream.getvalue().strip()

    def _set_search_path(self, cursor, schema_name):
        cursor.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
        )

    def _get_column_info(self, cursor, query_text):
        cursor.execute(
            sql.SQL("SELECT * FROM ({}) AS q LIMIT 0").format(sql.SQL(query_text))
        )
        descriptions = list(cursor.description or [])
        type_oids = [description.type_code for description in descriptions]
        type_names = {}
        if type_oids:
            cursor.execute(
                "SELECT oid, typname FROM pg_type WHERE oid = ANY(%s)", (type_oids,)
            )
            type_names = {oid: name for oid, name in cursor.fetchall()}
        return [
            {
                "name": description.name,
                "udt_name": type_names.get(description.type_code, ""),
            }
            for description in descriptions
        ]

    def _build_query_select_items(self, formatted=False):
        if not formatted:
            return sql.SQL(", ").join(
                sql.SQL("q.{}").format(sql.Identifier(column_name))
                for column_name in self._last_query_state["column_names"]
            )

        select_items = []
        for column in self._last_query_state["column_info"]:
            column_name = sql.Identifier(column["name"])
            if column["udt_name"] in ("geometry", "geography"):
                select_items.append(
                    sql.SQL("ST_AsText(q.{}) AS {}").format(column_name, column_name)
                )
            elif column["udt_name"] == "raster":
                select_items.append(sql.SQL("'[raster]' AS {}").format(column_name))
            else:
                select_items.append(sql.SQL("q.{}").format(column_name))
        return sql.SQL(", ").join(select_items)

    def _get_preview_rows(self, cursor, query_text, column_info, start_row, end_row):
        select_items = []
        for column in column_info:
            column_name = sql.Identifier(column["name"])
            if column["udt_name"] in ("geometry", "geography"):
                select_items.append(
                    sql.SQL("ST_AsText(q.{}) AS {}").format(column_name, column_name)
                )
            elif column["udt_name"] == "raster":
                select_items.append(sql.SQL("'[raster]' AS {}").format(column_name))
            else:
                select_items.append(sql.SQL("q.{}").format(column_name))
        limit_value = max(0, end_row - start_row)
        cursor.execute(
            sql.SQL("SELECT {} FROM ({}) AS q OFFSET {} LIMIT {}").format(
                sql.SQL(", ").join(select_items),
                sql.SQL(query_text),
                sql.Literal(start_row),
                sql.Literal(limit_value),
            )
        )
        return cursor.fetchall()

    def _get_row_count(self, cursor, query_text):
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM ({}) AS q").format(sql.SQL(query_text))
        )
        return cursor.fetchone()[0]

    def _find_first_column(self, column_info, udt_names):
        for column in column_info:
            if column["udt_name"] in udt_names:
                return column["name"]
        return None

    def _get_geometry_types(self, cursor, query_text, geometry_column):
        cursor.execute(
            sql.SQL(
                """
                SELECT DISTINCT ST_GeometryType(q.{geometry_column})
                FROM ({query_text}) AS q
                WHERE q.{geometry_column} IS NOT NULL
                """
            ).format(
                geometry_column=sql.Identifier(geometry_column),
                query_text=sql.SQL(query_text),
            )
        )
        return [row[0] for row in cursor.fetchall() if row and row[0]]

    def _get_thumbnail_image_urls(self, image_urls):
        raster_source = self._last_query_state.get("raster_source")
        raster_columns = self._last_query_state.get("raster_columns") or []
        if not raster_source or not raster_columns or not image_urls:
            return []

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        try:
            with psycopg2.connect(**self._connection_kwargs()) as connection:
                with connection.cursor() as cursor:
                    if schema_name:
                        self._set_search_path(cursor, schema_name)
                    cursor.execute(
                        sql.SQL(
                            """
                            SELECT image_url
                            FROM {}.{}
                            WHERE image_url = ANY(%s)
                              AND ({})
                            """
                        ).format(
                            sql.Identifier(raster_source["schema"]),
                            sql.Identifier(raster_source["table"]),
                            sql.SQL(" OR ").join(
                                sql.SQL("{} IS NOT NULL").format(sql.Identifier(column))
                                for column in raster_columns
                            ),
                        ),
                        (list(dict.fromkeys(image_urls)),),
                    )
                    return [row[0] for row in cursor.fetchall() if row and row[0]]
        except Exception as exc:  # pragma: no cover - depends on external DB
            self._show_error("Could not inspect thumbnail rows: {}".format(exc))
            return []

    def _preview_start_value(self):
        return self.results_controller.preview_range()[0]

    def _preview_end_value(self):
        return self.results_controller.preview_range()[1]

    def _validated_preview_range(self):
        return self.results_controller.preview_range()

    def _update_results_preview(self):
        self._run_query_preview(add_to_history=False)

    def _set_results_label(self, preview_count, total_count):
        _ = preview_count
        self.results_controller.set_label(total_count)

    def _populate_preview(self, column_info, rows, total_count):
        self.results_controller.populate_preview(column_info, rows, total_count)

    def _create_uri(self):
        uri = QgsDataSourceUri()
        kwargs = self._connection_kwargs()
        service = kwargs.get("service", "")
        user = kwargs.get("user", "")
        password = kwargs.get("password", "")
        if service:
            uri.setConnection(service, kwargs["dbname"], user, password)
        else:
            uri.setConnection(
                kwargs.get("host", ""),
                kwargs.get("port", ""),
                kwargs["dbname"],
                user,
                password,
            )
        schema_name = self.connection_values.get("schema", "").strip()
        if schema_name and hasattr(uri, "setParam"):
            uri.setParam("options", "-c search_path={},public".format(schema_name))
        return uri

    def _build_postgres_raster_uri(self, raster_source, raster_column, row_filter):
        uri = self._create_uri()
        # image_urls already come from the complete query, including its filters.
        # Reapplying its WHERE here can refer to aliases absent from this table.
        uri.setDataSource(
            raster_source["schema"],
            raster_source["table"],
            raster_column,
            "({}) AND {} IS NOT NULL".format(
                row_filter, self._quote_identifier(raster_column)
            ),
            "image_url",
        )
        return uri.uri(False)

    def _create_vector_layer(self, query_text, geometry_column, layer_name):
        uri = self._create_uri()
        uri.setDataSource(
            "", "({})".format(query_text), geometry_column, "", "image_url"
        )
        layer = QgsVectorLayer(uri.uri(False), layer_name, "postgres")
        if layer.isValid():
            layer.setCustomProperty("landlensdb/query_text", query_text)
            layer.setCustomProperty("landlensdb/geometry_column", geometry_column)
            self._apply_geometry_style(layer)
            self._add_open_image_action(layer)
        return layer if layer.isValid() else None

    def _apply_geometry_style(self, layer):
        if (
            layer.geometryType() == QgsWkbTypes.PointGeometry
            and self._point_style == "camera"
        ):
            # QGIS caches this unrotated SVG as an image for map rendering,
            # while retaining vector detail for enlarged and printed symbols.
            symbol = QgsMarkerSymbol(
                [QgsSvgMarkerSymbolLayer(self.CAMERA_MARKER_PATH, 6)]
            )
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _add_open_image_action(self, layer):
        field_names = [field.name() for field in layer.fields()]
        if "image_url" not in field_names:
            return
        actions = layer.actions()
        for action in actions.actions():
            if action.name() == "Open Image":
                return
        actions.addAction(
            QgsAction(
                Qgis.AttributeActionType.OpenUrl,
                "Open Image",
                '[% "image_url" %]',
                False,
            )
        )

    def _quote_identifier(self, value):
        return '"{}"'.format(value.replace('"', '""'))

    def _sql_literal(self, value):
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return "'{}'".format(str(value).replace("'", "''"))

    def _create_raster_layer(
        self, raster_source, raster_column, row_filter, layer_name
    ):
        layer = QgsRasterLayer(
            self._build_postgres_raster_uri(raster_source, raster_column, row_filter),
            layer_name,
            "postgresraster",
        )
        if not layer.isValid():
            error_summary = (
                layer.error().summary()
                if layer.error()
                else "unknown raster provider error"
            )
            self._show_error(
                'Raster layer could not be created from "{}" filter {}: {}'.format(
                    raster_column, row_filter, error_summary
                )
            )
            return None
        return layer

    def _ensure_query_group(self, query_name):
        root = QgsProject.instance().layerTreeRoot()
        group = root.insertGroup(0, query_name)
        if isinstance(group, QgsLayerTreeGroup):
            group.setExpanded(False)
        return group if isinstance(group, QgsLayerTreeGroup) else root

    def _add_layer_to_group(self, group, layer, insert_at_top=False):
        project = QgsProject.instance()
        project.addMapLayer(layer, False)
        if insert_at_top:
            group.insertLayer(0, layer)
        else:
            group.addLayer(layer)
