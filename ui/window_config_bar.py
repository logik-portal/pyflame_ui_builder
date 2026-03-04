"""Top configuration bar widget for script/window metadata."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRegularExpression, Signal
from PySide6.QtGui import QAction, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models.ui_models import WindowConfig


class WindowConfigBar(QWidget):
    """Top config bar for script-level metadata (window grid controls moved to Properties panel)."""

    config_changed = Signal(object)   # emits WindowConfig

    def __init__(self, config: WindowConfig, hook_display: dict[str, str], license_types: list[str]):
        super().__init__()
        self.config = config
        self._updating = False
        self._hook_display = hook_display
        self._license_types = license_types

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 3, 8, 3)
        vbox.setSpacing(2)

        es = ('background: #2d2d2d; border: 1px solid #3a3a3a;'
              ' color: #c8c8c8; padding: 1px 4px;')
        ls = 'color: #888; font-size: 10px;'

        def lbl(t):
            w = QLabel(t)
            w.setStyleSheet(ls)
            return w

        # ── Row 1: Script metadata ────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        row1.addWidget(lbl('Script Name:'))
        self.script_name = QLineEdit(config.script_name)
        self.script_name.setStyleSheet(es)
        self.script_name.setFixedWidth(140)
        self.script_name.setFixedHeight(22)
        self.script_name.textChanged.connect(self._on_change)
        row1.addWidget(self.script_name)

        row1.addWidget(lbl('Written By:'))
        self.written_by = QLineEdit(config.written_by)
        self.written_by.setStyleSheet(es)
        self.written_by.setFixedWidth(140)
        self.written_by.setFixedHeight(22)
        self.written_by.textChanged.connect(self._on_change)
        row1.addWidget(self.written_by)

        row1.addWidget(lbl('Script Version:'))
        self.version = QLineEdit(config.script_version)
        self.version.setStyleSheet(es)
        self.version.setMaximumWidth(80)
        self.version.setFixedHeight(22)
        self.version.textChanged.connect(self._on_change)
        row1.addWidget(self.version)

        row1.addWidget(lbl('Flame Version:'))
        self.flame_version = QLineEdit(config.flame_version)
        self.flame_version.setStyleSheet(es)
        self.flame_version.setFixedWidth(95)
        self.flame_version.setFixedHeight(22)
        self.flame_version.setToolTip('Use digits and dots only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1')
        self._flame_validator = QRegularExpressionValidator(QRegularExpression(r'^\d+(?:\.\d+){0,2}$'))
        self.flame_version.setValidator(self._flame_validator)
        self.flame_version.textChanged.connect(self._on_change)
        row1.addWidget(self.flame_version)

        row1.addWidget(lbl('Hooks:'))

        self._hook_button = QPushButton()
        self._hook_button.setStyleSheet(
            es + ' text-align: left; padding: 1px 8px; min-width: 160px;'
        )
        self._hook_button.setFixedHeight(22)
        self._hook_button.clicked.connect(self._show_hooks_menu)

        hook_menu_style = (
            'QMenu { background: #2d2d2d; color: #c8c8c8;'
            '        border: 1px solid #555; padding: 2px; }'
            'QMenu::item { padding: 4px 20px 4px 8px; }'
            'QMenu::item:selected { background: #0078d7; color: white; }'
            'QMenu::indicator { width: 13px; height: 13px; }'
        )
        self._hooks_menu = QMenu(self)
        self._hooks_menu.setStyleSheet(hook_menu_style)

        self._hook_actions: dict[str, QAction] = {}
        for hook, label in self._hook_display.items():
            action = QAction(label, self._hooks_menu)
            action.setCheckable(True)
            action.setChecked(hook in config.hook_types)
            action.triggered.connect(self._on_hook_toggled)
            self._hooks_menu.addAction(action)
            self._hook_actions[hook] = action

        self._update_hook_button()
        row1.addWidget(self._hook_button)

        row1.addWidget(lbl('License:'))
        self.license_type = QComboBox()
        self.license_type.addItems(self._license_types)
        self.license_type.setCurrentText(config.license_type)
        self.license_type.setStyleSheet(es)
        self.license_type.setMinimumWidth(110)
        self.license_type.setFixedHeight(22)
        self.license_type.currentTextChanged.connect(self._on_change)
        row1.addWidget(self.license_type)

        row1.addStretch()
        vbox.addLayout(row1)
        vbox.addSpacing(8)

    def _show_hooks_menu(self):
        pos = self._hook_button.mapToGlobal(QPoint(0, self._hook_button.height()))
        self._hooks_menu.exec(pos)

    def _update_hook_button(self):
        selected = [self._hook_display[h] for h, a in self._hook_actions.items() if a.isChecked()]
        self._hook_button.setText(', '.join(selected) if selected else 'None')

    def _on_hook_toggled(self):
        self._update_hook_button()
        self._on_change()

    @staticmethod
    def _is_flame_version_supported(version_text: str) -> bool:
        if not version_text:
            return False
        parts = version_text.split('.')
        if any((not p.isdigit()) for p in parts):
            return False
        nums = [int(p) for p in parts][:3]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums) >= (2025, 1, 0)

    def _set_flame_version_error(self, is_error: bool):
        base = 'background: #2d2d2d; border: 1px solid #3a3a3a; color: #c8c8c8; padding: 1px 4px;'
        err = 'background: #3a1f1f; border: 1px solid #b94a48; color: #ffd7d7; padding: 1px 4px;'
        self.flame_version.setStyleSheet(err if is_error else base)
        if is_error:
            self.flame_version.setToolTip('Invalid Flame Version. Use numeric version only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1.')
        else:
            self.flame_version.setToolTip('Use digits and dots only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1')

    def _on_change(self):
        if self._updating:
            return

        flame_version_text = self.flame_version.text().strip()
        flame_ok = self._is_flame_version_supported(flame_version_text)
        self._set_flame_version_error(not flame_ok)

        if not flame_ok:
            return

        self.config.script_name = self.script_name.text()
        self.config.written_by = self.written_by.text()
        self.config.script_version = self.version.text()
        self.config.flame_version = flame_version_text
        self.config.hook_types = [h for h, a in self._hook_actions.items() if a.isChecked()]
        self.config.license_type = self.license_type.currentText()
        self.config_changed.emit(self.config)

    def load_config(self, config: WindowConfig):
        self._updating = True
        self.config = config
        self.script_name.setText(config.script_name)
        self.written_by.setText(config.written_by)
        self.version.setText(config.script_version)
        self.flame_version.setText(config.flame_version)
        self._set_flame_version_error(not self._is_flame_version_supported(config.flame_version))
        for hook, action in self._hook_actions.items():
            action.setChecked(hook in config.hook_types)
        self._update_hook_button()
        self.license_type.setCurrentText(config.license_type)
        self._updating = False
