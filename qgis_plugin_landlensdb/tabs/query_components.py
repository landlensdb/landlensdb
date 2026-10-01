# -*- coding: utf-8 -*-
"""Reusable UI helpers for SQL-style workbench tabs."""

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QTableWidgetItem


class SqlBuilderController(object):
    def __init__(self, owner, sql_input, commands_frame, commands_toggle_button, commands_content_widget):
        self.owner = owner
        self.sql_input = sql_input
        self.commands_frame = commands_frame
        self.commands_toggle_button = commands_toggle_button
        self.commands_content_widget = commands_content_widget

    def prepare_ui(self):
        if self.commands_frame is not None:
            self.commands_frame.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.commands_frame.setLineWidth(0)

    def toggle_commands(self, checked):
        self.commands_content_widget.setVisible(checked)
        self.commands_toggle_button.setArrowType(
            QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
        )

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self.clear_layout(child_layout)

    def make_insert_button(self, label, insert_text=None):
        button = QtWidgets.QPushButton(label, self.owner)
        button.setMinimumHeight(30)
        button.clicked.connect(lambda: self.insert_sql(insert_text or label))
        return button

    def set_row_buttons(self, layout, items):
        self.clear_layout(layout)
        for label, insert_text in items:
            layout.addWidget(self.make_insert_button(label, insert_text))
        layout.addStretch()

    def insert_sql(self, token):
        if not token:
            return
        cursor = self.sql_input.textCursor()
        prefix = '' if cursor.atBlockStart() else ' '
        suffix = '' if token.endswith(' ') or token.endswith(')') else ' '
        cursor.insertText(prefix + token + suffix)
        self.sql_input.setTextCursor(cursor)
        self.sql_input.setFocus()


class QueryHistoryController(object):
    def __init__(
        self,
        owner,
        sql_input,
        history_button,
        star_button,
        history_key,
        star_key,
        name_key,
        history_limit=25,
    ):
        self.owner = owner
        self.sql_input = sql_input
        self.history_button = history_button
        self.star_button = star_button
        self.history_key = history_key
        self.star_key = star_key
        self.name_key = name_key
        self.history_limit = history_limit
        self.query_history = []
        self.starred_queries = []
        self.query_names = {}
        self.history_menu = QtWidgets.QMenu(owner)
        self.star_menu = QtWidgets.QMenu(owner)

    def load(self):
        settings = QtCore.QSettings()
        history = settings.value(self.history_key, [])
        stars = settings.value(self.star_key, [])
        names = settings.value(self.name_key, {})
        self.query_history = list(history) if isinstance(history, list) else []
        self.starred_queries = list(stars) if isinstance(stars, list) else []
        self.query_names = dict(names) if isinstance(names, dict) else {}
        self.build_history_menu()
        self.build_star_menu()

    def save(self):
        settings = QtCore.QSettings()
        settings.setValue(self.history_key, self.query_history)
        settings.setValue(self.star_key, self.starred_queries)
        settings.setValue(self.name_key, self.query_names)

    def query_title(self, query):
        return self.query_names.get(query, query.replace('\n', ' ')[:80])

    def show_history_menu(self):
        self.history_menu.exec_(
            self.history_button.mapToGlobal(QtCore.QPoint(0, self.history_button.height()))
        )

    def show_star_menu(self):
        self.star_menu.exec_(
            self.star_button.mapToGlobal(QtCore.QPoint(0, self.star_button.height()))
        )

    def build_history_menu(self):
        menu = QtWidgets.QMenu(self.owner)
        if not self.query_history:
            empty_action = menu.addAction('No history yet')
            empty_action.setEnabled(False)
        else:
            clear_action = menu.addAction('Clear All')
            clear_action.triggered.connect(self.clear_history)
            menu.addSeparator()
            for index, query in enumerate(self.query_history):
                submenu = menu.addMenu(self.query_title(query))
                use_action = submenu.addAction('Use')
                use_action.triggered.connect(
                    lambda _=False, sql_text=query: self.sql_input.setPlainText(sql_text)
                )
                rename_action = submenu.addAction('Rename')
                rename_action.triggered.connect(
                    lambda _=False, sql_text=query: self.rename_query(sql_text)
                )
                if query in self.query_names:
                    unname_action = submenu.addAction('Unname')
                    unname_action.triggered.connect(
                        lambda _=False, sql_text=query: self.unname_query(sql_text)
                    )
                star_action = submenu.addAction('Star')
                star_action.triggered.connect(lambda _=False, i=index: self.star_history_item(i))
                delete_action = submenu.addAction('Trash')
                delete_action.triggered.connect(lambda _=False, i=index: self.remove_history_item(i))
        self.history_menu = menu

    def build_star_menu(self):
        menu = QtWidgets.QMenu(self.owner)
        if not self.starred_queries:
            empty_action = menu.addAction('No starred queries yet')
            empty_action.setEnabled(False)
        else:
            clear_action = menu.addAction('Clear All')
            clear_action.triggered.connect(self.clear_starred)
            menu.addSeparator()
            for index, query in enumerate(self.starred_queries):
                submenu = menu.addMenu(self.query_title(query))
                use_action = submenu.addAction('Use')
                use_action.triggered.connect(
                    lambda _=False, sql_text=query: self.sql_input.setPlainText(sql_text)
                )
                rename_action = submenu.addAction('Rename')
                rename_action.triggered.connect(
                    lambda _=False, sql_text=query: self.rename_query(sql_text)
                )
                if query in self.query_names:
                    unname_action = submenu.addAction('Unname')
                    unname_action.triggered.connect(
                        lambda _=False, sql_text=query: self.unname_query(sql_text)
                    )
                unstar_action = submenu.addAction('Unstar')
                unstar_action.triggered.connect(lambda _=False, i=index: self.unstar_item(i))
                delete_action = submenu.addAction('Trash')
                delete_action.triggered.connect(lambda _=False, i=index: self.remove_star_item(i))
        self.star_menu = menu

    def rename_query(self, query):
        current_name = self.query_names.get(query, '')
        new_name, accepted = QtWidgets.QInputDialog.getText(
            self.owner,
            'Rename Query',
            'Name',
            text=current_name,
        )
        if accepted and new_name.strip():
            self.query_names[query] = new_name.strip()
            self.save()
            self.build_history_menu()
            self.build_star_menu()

    def unname_query(self, query):
        if query in self.query_names:
            del self.query_names[query]
            self.save()
            self.build_history_menu()
            self.build_star_menu()

    def add_history_item(self, sql_text):
        normalized = sql_text.strip()
        if normalized in self.query_history:
            self.query_history.remove(normalized)
        self.query_history.insert(0, normalized)
        self.query_history = self.query_history[:self.history_limit]
        self.save()
        self.build_history_menu()
        self.build_star_menu()

    def remove_history_item(self, index):
        if 0 <= index < len(self.query_history):
            del self.query_history[index]
            self.save()
            self.build_history_menu()
            self.build_star_menu()

    def clear_history(self):
        self.query_history = []
        self.save()
        self.build_history_menu()
        self.build_star_menu()

    def star_history_item(self, index):
        if 0 <= index < len(self.query_history):
            query = self.query_history.pop(index)
            if query in self.starred_queries:
                self.starred_queries.remove(query)
            self.starred_queries.insert(0, query)
            self.save()
            self.build_history_menu()
            self.build_star_menu()

    def unstar_item(self, index):
        if 0 <= index < len(self.starred_queries):
            query = self.starred_queries.pop(index)
            if query in self.query_history:
                self.query_history.remove(query)
            self.query_history.insert(0, query)
            self.query_history = self.query_history[:self.history_limit]
            self.save()
            self.build_history_menu()
            self.build_star_menu()

    def remove_star_item(self, index):
        if 0 <= index < len(self.starred_queries):
            del self.starred_queries[index]
            self.save()
            self.build_star_menu()

    def clear_starred(self):
        self.starred_queries = []
        self.save()
        self.build_star_menu()
        self.build_history_menu()


class ResultsController(object):
    def __init__(self, owner, results_tab, results_tab_layout, results_label, results_table, preview_limit, update_callback):
        self.owner = owner
        self.results_tab = results_tab
        self.results_tab_layout = results_tab_layout
        self.results_label = results_label
        self.results_table = results_table
        self.preview_limit = preview_limit
        self.update_callback = update_callback
        self.results_header_widget = None
        self.results_start_spin = None
        self.results_end_spin = None
        self.results_total_label = None
        self.results_update_button = None

    def setup(self):
        header_layout = self.results_tab_layout
        results_label_index = header_layout.indexOf(self.results_label)
        if results_label_index < 0:
            return

        header_layout.removeWidget(self.results_label)
        self.results_label.hide()

        self.results_header_widget = QtWidgets.QWidget(self.results_tab)
        results_header_layout = QtWidgets.QHBoxLayout(self.results_header_widget)
        results_header_layout.setContentsMargins(0, 0, 0, 0)
        results_header_layout.setSpacing(6)
        results_header_layout.addWidget(QtWidgets.QLabel('Results (', self.results_header_widget))

        self.results_start_spin = QtWidgets.QSpinBox(self.results_header_widget)
        self.results_start_spin.setRange(0, 1000000000)
        self.results_start_spin.setValue(0)
        self.results_start_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.results_start_spin.setMinimumWidth(64)
        results_header_layout.addWidget(self.results_start_spin)

        results_header_layout.addWidget(QtWidgets.QLabel('-', self.results_header_widget))

        self.results_end_spin = QtWidgets.QSpinBox(self.results_header_widget)
        self.results_end_spin.setRange(0, 1000000000)
        self.results_end_spin.setValue(self.preview_limit)
        self.results_end_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.results_end_spin.setMinimumWidth(64)
        results_header_layout.addWidget(self.results_end_spin)

        self.results_total_label = QtWidgets.QLabel('/ 0)', self.results_header_widget)
        results_header_layout.addWidget(self.results_total_label)

        self.results_update_button = QtWidgets.QPushButton('Update', self.results_header_widget)
        self.results_update_button.clicked.connect(self.update_callback)
        results_header_layout.addWidget(self.results_update_button)
        results_header_layout.addStretch()

        header_layout.insertWidget(results_label_index, self.results_header_widget)

    def preview_range(self):
        start_row = self.results_start_spin.value()
        end_row = self.results_end_spin.value()
        if end_row < start_row:
            start_row, end_row = end_row, start_row
            self.results_start_spin.setValue(start_row)
            self.results_end_spin.setValue(end_row)
        return start_row, end_row

    def set_label(self, total_count):
        start_row, end_row = self.preview_range()
        actual_start = min(start_row, total_count)
        actual_end = min(end_row, total_count)
        if actual_end < actual_start:
            actual_end = actual_start
        self.results_total_label.setText('/ {})'.format(total_count))
        self.results_start_spin.setValue(actual_start)
        self.results_end_spin.setValue(actual_end if total_count else end_row)

    def populate_preview(self, column_info, rows, total_count):
        self.results_table.clear()
        self.results_table.setColumnCount(len(column_info))
        self.results_table.setHorizontalHeaderLabels([column['name'] for column in column_info])
        self.results_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.results_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem('' if value is None else str(value)),
                )
        self.results_table.resizeColumnsToContents()
        self.set_label(total_count)
