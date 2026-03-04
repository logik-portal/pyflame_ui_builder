"""Scroll area with middle-mouse drag panning."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea


class PannableScrollArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self._panning = False
        self._pan_start = None
        self._h_start = 0
        self._v_start = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._h_start = self.horizontalScrollBar().value()
            self._v_start = self.verticalScrollBar().value()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(self._h_start - delta.x())
            self.verticalScrollBar().setValue(self._v_start - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
