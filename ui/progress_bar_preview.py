"""Simple visual preview for progress bar widget placeholders."""

from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QRect


class ProgressBarPreview(QWidget):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        pad = 5
        inner_w = max(1, w - (pad * 2))
        inner_h_space = max(1, h - (pad * 2))
        bar_h = max(1, (inner_h_space // 2) - 4)
        bar_y = (h - bar_h) // 2

        p.fillRect(QRect(pad, bar_y, inner_w, bar_h), QColor('#2f7fbf'))
        p.end()
