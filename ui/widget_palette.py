"""Draggable widget palette list."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem


class WidgetPalette(QListWidget):
    """Draggable list of available widget types in one alphabetical list."""

    def __init__(self, widget_specs: dict):
        super().__init__()
        self.widget_specs = widget_specs
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        items = sorted(
            ((wtype, spec['display']) for wtype, spec in self.widget_specs.items()),
            key=lambda x: x[1].lower(),
        )

        for wtype, display in items:
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, wtype)
            item.setForeground(QColor('#c8c8c8'))
            self.addItem(item)

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None or not item.data(Qt.UserRole):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData('application/x-pyflame-widget', item.data(Qt.UserRole).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
