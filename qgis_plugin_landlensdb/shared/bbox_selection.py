"""QGIS's rectangle drawing tool with explicit cancellation."""

from qgis.PyQt import QtCore
from qgis.gui import QgsMapToolExtent


class BboxSelectionTool(QgsMapToolExtent):
    cancelled = QtCore.pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            event.accept()
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def canvasPressEvent(self, event):
        if event.button() == QtCore.Qt.RightButton:
            self.cancelled.emit()
        elif event.button() == QtCore.Qt.LeftButton:
            super().canvasPressEvent(event)

    def canvasReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            super().canvasReleaseEvent(event)
