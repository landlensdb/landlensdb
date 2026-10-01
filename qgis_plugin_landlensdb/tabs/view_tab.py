from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.core import QgsMapLayerType, QgsProject

from ..landlensdb.geoclasses.geoimageframe import GeoImageFrame
from shapely.wkb import loads as load_wkb

from ..shared.connection_utils import (
    connection_kwargs,
    load_connection_settings,
    psycopg2,
    sql,
)
from ..shared.image_sources import (
    metadata_field_paths,
    metadata_value,
    resolve_image_path,
)


class ImageCanvas(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super(ImageCanvas, self).__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._fit_scale = 1.0
        self._current_scale = 1.0
        self.setScene(self._scene)
        self.setRenderHints(
            QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing
        )
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QtGui.QColor("#111111"))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setMinimumSize(0, 220)

    def set_pixmap(self, pixmap):
        self._pixmap_item.setPixmap(pixmap)
        self.setSceneRect(QtCore.QRectF(pixmap.rect()))
        if not pixmap.isNull():
            self._fit_to_view()

    def clear(self):
        self.resetTransform()
        self._fit_scale = 1.0
        self._current_scale = 1.0
        self._pixmap_item.setPixmap(QtGui.QPixmap())
        self.setSceneRect(QtCore.QRectF())

    def wheelEvent(self, event):
        event.accept()
        if self._pixmap_item.pixmap().isNull():
            return
        step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        target_scale = self._current_scale * step
        target_scale = max(self._fit_scale, target_scale)
        if abs(target_scale - self._current_scale) < 1e-9:
            return
        scale_factor = target_scale / self._current_scale
        self.scale(scale_factor, scale_factor)
        self._current_scale = target_scale

    def resizeEvent(self, event):
        super(ImageCanvas, self).resizeEvent(event)
        if self._pixmap_item.pixmap().isNull():
            return
        if self._current_scale <= self._fit_scale + 1e-9:
            self._fit_to_view()

    def _fit_to_view(self):
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return
        viewport_size = self.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        width_scale = float(viewport_size.width()) / float(pixmap.width())
        height_scale = float(viewport_size.height()) / float(pixmap.height())
        self._fit_scale = min(1.0, width_scale, height_scale)
        self.resetTransform()
        self.scale(self._fit_scale, self._fit_scale)
        self._current_scale = self._fit_scale


class ImageScrollArea(QtWidgets.QScrollArea):
    """Keep scrollbar navigation while ignoring wheel gestures on the outer area."""

    def wheelEvent(self, event):
        event.accept()


class ImageTile(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super(ImageTile, self).__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.status_label = QtWidgets.QLabel(self)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.status_label, 1)
        self.selection_checkbox = QtWidgets.QCheckBox(self)
        self.selection_checkbox.setToolTip("Select this image to add to the map")
        header.addWidget(self.selection_checkbox, 0, QtCore.Qt.AlignTop)
        layout.addLayout(header)

        self.canvas = ImageCanvas(self)
        layout.addWidget(self.canvas, 1)

    def set_content(self, pixmap, status):
        self.status_label.setText(status)
        if pixmap is None or pixmap.isNull():
            self.canvas.clear()
        else:
            self.canvas.set_pixmap(pixmap)


class LayerSelectionComboBox(QtWidgets.QComboBox):
    popupAboutToShow = QtCore.pyqtSignal()

    def showPopup(self):
        self.popupAboutToShow.emit()
        super(LayerSelectionComboBox, self).showPopup()


class ViewTab(QtWidgets.QWidget):
    ACTIVE_LAYER_VALUE = "__active_layer__"
    addImagesRequested = QtCore.pyqtSignal(str, list, bool, bool)

    def __init__(self, iface, parent=None):
        super(ViewTab, self).__init__(parent)
        self.iface = iface
        self.connection_values = load_connection_settings()
        self._host_tab_widget = None
        self._active = False
        self._iface_connected = False
        self._selected_layer_id = self.ACTIVE_LAYER_VALUE
        self._watched_layer = None
        self._watch_connected = False
        self._current_geoimageframe = None
        self._source_query = ""
        self._checked_image_urls = set()
        self._last_grid_rows = 0
        self._last_grid_columns = 0
        self._organize_path = None
        self._navigation_cache = None
        self._source_mode = "preview"
        self._source_metadata_path = ()

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(10)

        header_row = QtWidgets.QHBoxLayout()
        outer_layout.addLayout(header_row)

        header_row.addWidget(QtWidgets.QLabel("Source:", self))
        self.source_button = QtWidgets.QPushButton("Preview", self)
        self.source_menu = QtWidgets.QMenu(self)
        self.source_menu.aboutToShow.connect(self._rebuild_source_menu)
        self._rebuild_source_menu()
        self.source_button.setMenu(self.source_menu)
        header_row.addWidget(self.source_button)

        self.add_button = QtWidgets.QPushButton("Add", self)
        add_menu = QtWidgets.QMenu(self.add_button)
        self._add_actions = []
        for label, thumbnail, geometry in (
            ("Add Both", True, True),
            ("Add Geometry", False, True),
            ("Add Thumbnail", True, False),
        ):
            action = add_menu.addAction(label)
            self._add_actions.append(action)
            action.triggered.connect(
                lambda _checked=False, t=thumbnail, g=geometry: self._add_checked_images(
                    t, g
                )
            )
        add_menu.addSeparator()
        self.select_all_action = add_menu.addAction("Select all")
        self.select_all_action.triggered.connect(self._select_all_images)
        self.add_button.setMenu(add_menu)
        self._update_selection_actions()
        header_row.addWidget(self.add_button)

        header_row.addWidget(QtWidgets.QLabel("Update from selection:", self))
        self.update_from_selection_toggle = QtWidgets.QCheckBox(self)
        self.update_from_selection_toggle.setChecked(True)
        self.update_from_selection_toggle.toggled.connect(
            self._handle_update_toggle_changed
        )
        header_row.addWidget(self.update_from_selection_toggle)

        header_row.addWidget(QtWidgets.QLabel("Select layer:", self))
        self.layer_selector = LayerSelectionComboBox(self)
        self.layer_selector.setMinimumWidth(220)
        self.layer_selector.popupAboutToShow.connect(self._refresh_layer_selector)
        self.layer_selector.currentIndexChanged.connect(
            self._handle_layer_selector_changed
        )
        header_row.addWidget(self.layer_selector)

        header_row.addWidget(QtWidgets.QLabel("Navigate:", self))
        self.bulk_previous_button = QtWidgets.QToolButton(self)
        self.bulk_previous_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_MediaSeekBackward)
        )
        self.bulk_previous_button.setAutoRaise(True)
        self.bulk_previous_button.clicked.connect(
            lambda: self._navigate_selection(-1, bulk=True)
        )
        header_row.addWidget(self.bulk_previous_button)

        self.previous_button = QtWidgets.QToolButton(self)
        self.previous_button.setArrowType(QtCore.Qt.LeftArrow)
        self.previous_button.setAutoRaise(True)
        self.previous_button.clicked.connect(
            lambda: self._navigate_selection(-1, bulk=False)
        )
        header_row.addWidget(self.previous_button)

        self.organize_button = QtWidgets.QPushButton("Select Organize Field", self)
        self.organize_menu = QtWidgets.QMenu(self.organize_button)
        self.organize_button.clicked.connect(self._open_organize_menu)
        header_row.addWidget(self.organize_button)

        self.next_button = QtWidgets.QToolButton(self)
        self.next_button.setArrowType(QtCore.Qt.RightArrow)
        self.next_button.setAutoRaise(True)
        self.next_button.clicked.connect(
            lambda: self._navigate_selection(1, bulk=False)
        )
        header_row.addWidget(self.next_button)

        self.bulk_next_button = QtWidgets.QToolButton(self)
        self.bulk_next_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_MediaSeekForward)
        )
        self.bulk_next_button.setAutoRaise(True)
        self.bulk_next_button.clicked.connect(
            lambda: self._navigate_selection(1, bulk=True)
        )
        header_row.addWidget(self.bulk_next_button)

        header_row.addWidget(QtWidgets.QLabel("North up:", self))
        self.north_up_toggle = QtWidgets.QCheckBox(self)
        self.north_up_toggle.toggled.connect(self._render_geoimageframe)
        header_row.addWidget(self.north_up_toggle)

        header_row.addStretch(1)
        self.status_label = QtWidgets.QLabel("", self)
        self.status_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        header_row.addWidget(self.status_label)

        self.scroll_area = ImageScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer_layout.addWidget(self.scroll_area, 1)

        self.grid_host = QtWidgets.QWidget(self.scroll_area)
        self.grid_layout = QtWidgets.QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(0)
        self.scroll_area.setWidget(self.grid_host)

        self._refresh_layer_selector()
        self._update_navigation_buttons()

    def set_host_tab_widget(self, tab_widget):
        self._host_tab_widget = tab_widget

    def set_active(self, active):
        self._active = bool(active)
        if self._active:
            self._connect_iface_signals()
            self._watch_active_layer()
            if self._sync_enabled():
                self._load_selected_features()
        else:
            self._disconnect_watched_layer()
            self._disconnect_iface_signals()

    def reload_connection_settings(self, values=None):
        self.connection_values = values or load_connection_settings()
        if self._sync_enabled():
            self._load_selected_features()

    def set_geoimageframe(self, geoimageframe, *, source_query=""):
        if source_query != self._source_query:
            self._checked_image_urls.clear()
        self._source_query = source_query
        self._current_geoimageframe = geoimageframe
        self._render_geoimageframe()

    def _set_image_checked(self, image_url, checked):
        if checked:
            self._checked_image_urls.add(image_url)
        else:
            self._checked_image_urls.discard(image_url)
        self._update_selection_actions()

    def _update_selection_actions(self):
        for action in self._add_actions:
            action.setEnabled(bool(self._checked_image_urls))
        self.select_all_action.setEnabled(
            self._current_geoimageframe is not None
            and len(self._current_geoimageframe) > 0
        )

    def _select_all_images(self):
        for index in range(self.grid_layout.count()):
            checkbox = self.grid_layout.itemAt(index).widget().selection_checkbox
            if checkbox.isEnabled():
                checkbox.setChecked(True)

    def _add_checked_images(self, add_thumbnail, add_geometry):
        if not self._checked_image_urls or self._current_geoimageframe is None:
            return
        if not self._source_query:
            self.status_label.setText(
                "Choose images from a Landlensdb query layer to add them."
            )
            return
        image_urls = list(
            dict.fromkeys(
                str(url)
                for url in self._current_geoimageframe["image_url"]
                if str(url) in self._checked_image_urls
            )
        )
        self.addImagesRequested.emit(
            self._source_query, image_urls, add_thumbnail, add_geometry
        )

    def _rebuild_source_menu(self):
        self.source_menu.clear()
        for mode, label in (("preview", "Preview"), ("image_url", "image_url")):
            action = self.source_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._source_mode == mode)
            action.triggered.connect(
                lambda _checked=False, mode=mode: self._set_source_mode(mode)
            )

        metadata_menu = self.source_menu.addMenu("Metadata")
        paths = set()
        frame = self._current_geoimageframe
        if frame is not None and "metadata" in frame.columns:
            for value in frame["metadata"]:
                paths.update(metadata_field_paths(value))
        menus = {(): metadata_menu}
        for path in sorted(paths, key=lambda parts: tuple(str(part) for part in parts)):
            for length in range(1, len(path)):
                prefix = path[:length]
                if prefix not in menus:
                    menus[prefix] = menus[prefix[:-1]].addMenu(str(prefix[-1]))
            action = menus[path[:-1]].addAction(str(path[-1]))
            action.setCheckable(True)
            action.setChecked(
                self._source_mode == "metadata" and self._source_metadata_path == path
            )
            action.triggered.connect(
                lambda _checked=False, path=path: self._set_source_mode(
                    "metadata", path
                )
            )
        if not paths:
            metadata_menu.addAction("No metadata fields").setEnabled(False)

    def _set_source_mode(self, mode, metadata_path=()):
        self._source_mode = mode
        self._source_metadata_path = tuple(metadata_path)
        label = (
            "metadata.{}".format(".".join(str(part) for part in metadata_path))
            if mode == "metadata"
            else "Preview" if mode == "preview" else "image_url"
        )
        # Deep field names stay visible in the tooltip without widening the toolbar.
        self.source_button.setText(
            self.source_button.fontMetrics().elidedText(
                label, QtCore.Qt.ElideMiddle, 220
            )
        )
        self.source_button.setToolTip(label)
        self._render_geoimageframe()

    def _handle_layer_selector_changed(self, _index):
        self._selected_layer_id = self.layer_selector.currentData()
        self._navigation_cache = None
        self._disconnect_watched_layer()
        if self._sync_enabled():
            self._watch_active_layer()
            QtCore.QTimer.singleShot(0, self._load_selected_features)

    def _handle_current_layer_changed(self, _layer):
        if not self._sync_enabled():
            self._disconnect_watched_layer()
            return
        if self._selected_layer_id != self.ACTIVE_LAYER_VALUE:
            return
        self._navigation_cache = None
        self._watch_active_layer()
        QtCore.QTimer.singleShot(0, self._load_selected_features)

    def _handle_update_toggle_changed(self, checked):
        if not checked:
            self._disconnect_watched_layer()
            self._disconnect_iface_signals()
            return
        self._connect_iface_signals()
        if self._sync_enabled():
            self._watch_active_layer()
            QtCore.QTimer.singleShot(0, self._load_selected_features)

    def _watch_active_layer(self):
        self._disconnect_watched_layer()
        layer = self._selected_vector_layer()
        self._watched_layer = layer
        if layer is not None:
            layer.selectionChanged.connect(self._handle_selection_changed)
            self._watch_connected = True

    def _disconnect_watched_layer(self):
        if self._watched_layer is not None and self._watch_connected:
            self._watched_layer.selectionChanged.disconnect(
                self._handle_selection_changed
            )
        self._watched_layer = None
        self._watch_connected = False

    def _connect_iface_signals(self):
        if self._iface_connected:
            return
        if self.iface is not None and hasattr(self.iface, "currentLayerChanged"):
            self.iface.currentLayerChanged.connect(self._handle_current_layer_changed)
            self._iface_connected = True

    def _disconnect_iface_signals(self):
        if not self._iface_connected:
            return
        if self.iface is not None and hasattr(self.iface, "currentLayerChanged"):
            self.iface.currentLayerChanged.disconnect(
                self._handle_current_layer_changed
            )
        self._iface_connected = False

    def _handle_selection_changed(
        self, _selected=None, _deselected=None, _clear_and_select=None
    ):
        if not self._sync_enabled():
            self._disconnect_watched_layer()
            return
        QtCore.QTimer.singleShot(0, self._load_selected_features)

    def _active_vector_layer(self):
        if self.iface is None:
            return None
        layer = self.iface.activeLayer()
        if layer is None:
            return None
        if layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _selected_vector_layer(self):
        if self._selected_layer_id == self.ACTIVE_LAYER_VALUE:
            return self._active_vector_layer()
        layer = QgsProject.instance().mapLayer(self._selected_layer_id)
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None
        return layer

    def _vector_layers(self):
        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if layer.type() == QgsMapLayerType.VectorLayer:
                layers.append(layer)
        return sorted(layers, key=lambda layer: layer.name().lower())

    def _refresh_layer_selector(self):
        selected_value = self.layer_selector.currentData()
        if selected_value is None:
            selected_value = self._selected_layer_id
        self.layer_selector.blockSignals(True)
        self.layer_selector.clear()
        self.layer_selector.addItem("Active Layer", self.ACTIVE_LAYER_VALUE)
        for layer in self._vector_layers():
            self.layer_selector.addItem(layer.name(), layer.id())
        index = self.layer_selector.findData(selected_value)
        if index < 0:
            index = self.layer_selector.findData(self.ACTIVE_LAYER_VALUE)
        self.layer_selector.setCurrentIndex(index)
        self.layer_selector.blockSignals(False)
        self._selected_layer_id = self.layer_selector.currentData()
        self._update_navigation_buttons()

    def _load_selected_features(self):
        if not self._sync_enabled():
            self._disconnect_watched_layer()
            return
        layer = self._watched_layer or self._selected_vector_layer()
        if layer is None:
            self.status_label.setText("No selected vector layer.")
            self.set_geoimageframe(None)
            return
        field_names = [field.name() for field in layer.fields()]
        if "image_url" not in field_names:
            self.status_label.setText(
                "The active layer does not have an image_url field."
            )
            self.set_geoimageframe(None)
            return
        selected_features = list(layer.selectedFeatures())
        image_urls = []
        for feature in selected_features:
            image_url = feature["image_url"]
            if image_url:
                image_urls.append(str(image_url))
        if not image_urls:
            self.status_label.setText(
                "Select features in layers added by Landlensdb to view them."
            )
            self.set_geoimageframe(None)
            self._update_navigation_buttons()
            return
        if layer.customProperty("landlensdb/query_text", "") and layer.customProperty(
            "landlensdb/geometry_column", ""
        ):
            geoimageframe = self._fetch_geoimageframe_for_image_urls(layer, image_urls)
        else:
            geoimageframe = self._geoimageframe_from_selected_features(
                selected_features
            )
        self.status_label.setText(
            "Loaded {} image{}".format(
                len(geoimageframe), "" if len(geoimageframe) == 1 else "s"
            )
        )
        self.set_geoimageframe(
            geoimageframe,
            source_query=layer.customProperty("landlensdb/query_text", ""),
        )
        self._update_navigation_buttons()

    def _fetch_geoimageframe_for_image_urls(self, layer, image_urls):
        if psycopg2 is None:
            self.status_label.setText(
                "psycopg2 is not available in this QGIS Python environment."
            )
            return self._empty_geoimageframe()

        query_text = layer.customProperty("landlensdb/query_text", "")
        geometry_column = layer.customProperty("landlensdb/geometry_column", "")
        if not query_text or not geometry_column:
            self.status_label.setText(
                "The active layer is missing Landlensdb query metadata."
            )
            return self._empty_geoimageframe()

        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        geometry_identifier = '"{}"'.format(geometry_column.replace('"', '""'))
        query = """
            SELECT
                q.image_url,
                q.name,
                q.metadata,
                ST_AsBinary(q.{geometry_column}) AS geometry_wkb,
                CASE
                    WHEN q.thumbnail IS NULL THEN NULL
                    ELSE ST_AsGDALRaster(q.thumbnail, 'PNG')
                END AS preview_png
            FROM ({query_text}) AS q
            WHERE q.image_url = ANY(%s)
            ORDER BY q.image_url
        """.format(
            geometry_column=geometry_identifier,
            query_text=query_text.replace("%", "%%"),
        )

        with psycopg2.connect(
            **connection_kwargs(self.connection_values)
        ) as connection:
            with connection.cursor() as cursor:
                if schema_name:
                    cursor.execute(
                        sql.SQL("SET search_path TO {}, public").format(
                            sql.Identifier(schema_name),
                        )
                    )
                cursor.execute(query, (image_urls,))
                rows = cursor.fetchall()

        records = []
        for image_url, name, metadata, geometry_wkb, preview_png in rows:
            records.append(
                {
                    "image_url": image_url,
                    "name": name or image_url,
                    "metadata": metadata or {},
                    "geometry": (
                        load_wkb(bytes(geometry_wkb))
                        if geometry_wkb is not None
                        else None
                    ),
                    "preview_png": (
                        bytes(preview_png) if preview_png is not None else None
                    ),
                }
            )
        if not records:
            return self._empty_geoimageframe()
        return GeoImageFrame(records)

    def _render_geoimageframe(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for column in range(self._last_grid_columns):
            self.grid_layout.setColumnStretch(column, 0)
        for row_index in range(self._last_grid_rows):
            self.grid_layout.setRowStretch(row_index, 0)

        geoimageframe = self._current_geoimageframe
        if geoimageframe is None or len(geoimageframe) == 0:
            self._checked_image_urls.clear()
            self._update_selection_actions()
            self._last_grid_rows = 1
            self._last_grid_columns = 1
            self.grid_layout.setColumnStretch(0, 1)
            self.grid_layout.setRowStretch(0, 1)
            return

        self._checked_image_urls.intersection_update(
            str(url) for url in geoimageframe["image_url"] if url
        )
        self._update_selection_actions()
        rows, columns = self._compute_grid_size(len(geoimageframe))
        for index, (_, row) in enumerate(geoimageframe.iterrows()):
            tile = ImageTile(self.grid_host)
            pixmap, status = self._build_tile_content(row)
            tile.set_content(pixmap, status)
            image_url = str(row.get("image_url") or "")
            tile.selection_checkbox.setAccessibleName("Select {}".format(image_url))
            tile.selection_checkbox.setEnabled(bool(image_url))
            tile.selection_checkbox.setChecked(image_url in self._checked_image_urls)
            tile.selection_checkbox.toggled.connect(
                lambda checked, url=image_url: self._set_image_checked(url, checked)
            )
            self.grid_layout.addWidget(tile, index // columns, index % columns)

        for column in range(columns):
            self.grid_layout.setColumnStretch(column, 1)
        for row_index in range(rows):
            self.grid_layout.setRowStretch(row_index, 1)
        self._last_grid_rows = rows
        self._last_grid_columns = columns

    def _open_organize_menu(self):
        self._rebuild_organize_menu()
        self.organize_menu.exec_(
            self.organize_button.mapToGlobal(self.organize_button.rect().bottomLeft())
        )

    def _rebuild_organize_menu(self):
        self.organize_menu.clear()
        self._populate_metadata_sections(
            self.organize_menu,
            lambda _section, path: self._set_organize_field(path),
        )

    def _populate_metadata_sections(self, menu, leaf_callback):
        schema = {}
        frame = self._current_geoimageframe
        if frame is not None and "metadata" in frame.columns:
            for value in frame["metadata"]:
                schema = self._merge_metadata_schema(schema, value or {})
        if not schema:
            action = menu.addAction("No metadata fields")
            action.setEnabled(False)
            return
        submenu = menu.addMenu("Metadata")
        self._populate_metadata_submenu(
            submenu,
            schema,
            [],
            "Metadata",
            leaf_callback,
        )

    def _merge_metadata_schema(self, current, value):
        merged = dict(current or {})
        if not isinstance(value, dict):
            return merged
        for key, item in value.items():
            if isinstance(item, dict):
                merged[key] = self._merge_metadata_schema(merged.get(key, {}), item)
            else:
                merged.setdefault(key, None)
        return merged

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

    def _populate_metadata_submenu(
        self, menu, metadata, path_parts, section_label, leaf_callback
    ):
        for key, value in metadata.items():
            current_path = path_parts + [key]
            if isinstance(value, dict):
                submenu = menu.addMenu(key)
                self._populate_metadata_submenu(
                    submenu, value, current_path, section_label, leaf_callback
                )
                continue
            action = menu.addAction(key)
            action.triggered.connect(
                lambda _checked=False, path=current_path, section=section_label: leaf_callback(
                    section,
                    path,
                )
            )

    def _set_organize_field(self, path_parts):
        self._organize_path = list(path_parts)
        self.organize_button.setText("Organize by: {}".format(".".join(path_parts)))
        self._rebuild_navigation_cache()
        self._update_navigation_buttons()

    def _metadata_sql_expression(self, path_parts):
        if not path_parts:
            return "metadata"
        sql_parts = ["metadata::jsonb"]
        for key in path_parts[:-1]:
            sql_parts.append("->'{}'".format(key.replace("'", "''")))
        sql_parts.append("->>'{}'".format(path_parts[-1].replace("'", "''")))
        return "".join(sql_parts)

    def _rebuild_navigation_cache(self):
        layer = self._selected_vector_layer()
        self._navigation_cache = None
        if layer is None or not self._organize_path:
            return
        query_text = layer.customProperty("landlensdb/query_text", "")
        if not query_text:
            return
        organize_sql = self._metadata_sql_expression(self._organize_path)
        schema_name = self.connection_values.get("schema", "public").strip() or "public"
        query = """
            SELECT q.image_url, {organize_sql}
            FROM ({query_text}) AS q
            WHERE q.image_url IS NOT NULL
            ORDER BY {organize_sql} NULLS LAST, q.image_url
        """.format(
            organize_sql=organize_sql,
            query_text=query_text.replace("%", "%%"),
        )
        with psycopg2.connect(
            **connection_kwargs(self.connection_values)
        ) as connection:
            with connection.cursor() as cursor:
                if schema_name:
                    cursor.execute(
                        sql.SQL("SET search_path TO {}, public").format(
                            sql.Identifier(schema_name),
                        )
                    )
                cursor.execute(query)
                rows = cursor.fetchall()
        feature_id_by_url = {}
        for feature in layer.getFeatures():
            image_url = feature["image_url"]
            if image_url:
                feature_id_by_url[str(image_url)] = feature.id()
        ordered_urls = []
        values_by_url = {}
        for image_url, organize_value in rows:
            if image_url in feature_id_by_url:
                ordered_urls.append(image_url)
                values_by_url[image_url] = organize_value
        self._navigation_cache = {
            "layer_id": layer.id(),
            "ordered_urls": ordered_urls,
            "index_by_url": {
                image_url: index for index, image_url in enumerate(ordered_urls)
            },
            "feature_id_by_url": feature_id_by_url,
            "values_by_url": values_by_url,
        }

    def _navigate_selection(self, direction, bulk):
        cache = self._navigation_cache
        layer = self._selected_vector_layer()
        if cache is None or layer is None or cache.get("layer_id") != layer.id():
            return
        selected_urls = []
        for feature in layer.selectedFeatures():
            image_url = feature["image_url"]
            if image_url:
                image_url = str(image_url)
                if image_url in cache["index_by_url"]:
                    selected_urls.append(image_url)
        if not selected_urls:
            return
        selected_indices = sorted(
            cache["index_by_url"][image_url] for image_url in selected_urls
        )
        step = len(selected_indices) if bulk else 1
        max_index = len(cache["ordered_urls"]) - 1
        target_indices = []
        for index in selected_indices:
            target_index = index + (direction * step)
            target_index = max(0, min(max_index, target_index))
            target_indices.append(target_index)
        target_urls = [cache["ordered_urls"][index] for index in target_indices]
        if not target_urls:
            return
        layer.selectByIds(
            [
                cache["feature_id_by_url"][image_url]
                for image_url in target_urls
                if image_url in cache["feature_id_by_url"]
            ]
        )

    def _update_navigation_buttons(self):
        enabled = bool(self._organize_path and self._navigation_cache)
        self.previous_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
        self.bulk_previous_button.setEnabled(enabled)
        self.bulk_next_button.setEnabled(enabled)

    def _build_tile_content(self, row):
        if self._source_mode == "preview":
            preview_png = row.get("preview_png")
            if not preview_png:
                return None, "No Image\nNo preview raster is available for this image."
            image = QtGui.QImage.fromData(preview_png)
            if image.isNull():
                return None, "No Image\nThe preview raster could not be decoded."
            return self._apply_north_up(QtGui.QPixmap.fromImage(image), row), "Preview"

        image_path = self._image_path_for_row(row)
        if not image_path:
            if self._source_mode == "metadata":
                return (
                    None,
                    "No Image\nNo image path in metadata.{} for this image.".format(
                        ".".join(str(part) for part in self._source_metadata_path)
                    ),
                )
            return None, "No Image\nNo image path is available for this image."
        image = QtGui.QImage(image_path)
        if image.isNull():
            return None, "No Image\nThe image path could not be loaded:\n{}".format(
                image_path
            )
        return self._apply_north_up(QtGui.QPixmap.fromImage(image), row), image_path

    def _apply_north_up(self, pixmap, row):
        if pixmap.isNull() or not self.north_up_toggle.isChecked():
            return pixmap
        angle = self._compass_angle_for_row(row)
        if angle is None:
            return pixmap
        transform = QtGui.QTransform()
        transform.rotate(-float(angle))
        return pixmap.transformed(transform, QtCore.Qt.SmoothTransformation)

    def _compass_angle_for_row(self, row):
        metadata = row.get("metadata") or {}
        sensor = metadata.get("sensor") or {}
        angle = sensor.get("compass_angle")
        if angle in (None, ""):
            return None
        return angle

    def _image_path_for_row(self, row):
        if self._source_mode == "metadata":
            value = metadata_value(row.get("metadata"), self._source_metadata_path)
            return resolve_image_path(value, row.get("image_url"))
        return row.get("image_url")

    def _compute_grid_size(self, image_count):
        if image_count <= 0:
            return 1, 1
        columns = min(4, image_count)
        rows = (image_count + columns - 1) // columns
        return rows, columns

    def _empty_geoimageframe(self):
        return GeoImageFrame(
            {
                "image_url": [],
                "name": [],
                "geometry": [],
                "metadata": [],
                "preview_png": [],
            }
        )

    def _geoimageframe_from_selected_features(self, features):
        records = []
        for feature in features:
            image_url = feature["image_url"]
            if not image_url:
                continue
            records.append(
                {
                    "image_url": str(image_url),
                    "name": str(feature["image_url"]),
                    "geometry": feature.geometry().asWkb(),
                    "metadata": {},
                    "preview_png": None,
                }
            )
        shapely_records = []
        for record in records:
            shapely_records.append(
                {
                    "image_url": record["image_url"],
                    "name": record["name"],
                    "geometry": load_wkb(bytes(record["geometry"])),
                    "metadata": record["metadata"],
                    "preview_png": record["preview_png"],
                }
            )
        if not shapely_records:
            return self._empty_geoimageframe()
        return GeoImageFrame(shapely_records)

    def hideEvent(self, event):
        self._disconnect_watched_layer()
        self._disconnect_iface_signals()
        super(ViewTab, self).hideEvent(event)

    def showEvent(self, event):
        super(ViewTab, self).showEvent(event)
        if self._sync_enabled():
            self._connect_iface_signals()
            self._watch_active_layer()
            QtCore.QTimer.singleShot(0, self._load_selected_features)

    def _sync_enabled(self):
        dialog = self.window()
        return (
            self.update_from_selection_toggle.isChecked()
            and self._active
            and self.isVisible()
            and dialog is not None
            and dialog.isVisible()
            and self._host_tab_widget is not None
            and self._host_tab_widget.currentWidget() is self
        )
