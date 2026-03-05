"""Shared app dialogs for consistent message/confirmation UX."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


class AppMessageDialog(QDialog):
    """Small, styled modal dialog with explicit button outcomes."""

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        text: str,
        informative_text: str | None = None,
    ):
        super().__init__(parent, Qt.Dialog)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(420)
        self._result_key: str | None = None

        self.setStyleSheet(
            """
            QDialog {
                background: #2b2b2b;
                border: 1px solid #555;
            }
            QLabel {
                color: #c8c8c8;
                font-size: 12px;
                background: transparent;
            }
            QPushButton {
                background: #3a3a3a;
                color: #c8c8c8;
                border: none;
                padding: 6px 16px;
                font-size: 11px;
                min-width: 72px;
            }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:pressed { background: #2a2a2a; }
            QPushButton#primary_btn {
                background: #006eaf;
                color: #fff;
            }
            QPushButton#primary_btn:hover { background: #0080c8; }
            QPushButton#primary_btn:pressed { background: #005a8e; }
            QPushButton#danger_btn {
                background: #8b2f2f;
                color: #fff;
            }
            QPushButton#danger_btn:hover { background: #a43838; }
            QPushButton#danger_btn:pressed { background: #742727; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)

        main_label = QLabel(text)
        main_label.setWordWrap(True)
        layout.addWidget(main_label)

        if informative_text:
            info_label = QLabel(informative_text)
            info_label.setWordWrap(True)
            layout.addWidget(info_label)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        self._button_row.addStretch()
        layout.addLayout(self._button_row)

    def add_action(
        self,
        key: str,
        label: str,
        *,
        primary: bool = False,
        danger: bool = False,
        default: bool = False,
        escape: bool = False,
    ) -> QPushButton:
        btn = QPushButton(label)
        if danger:
            btn.setObjectName('danger_btn')
        elif primary:
            btn.setObjectName('primary_btn')
        btn.clicked.connect(lambda: self._finish(key))
        self._button_row.addWidget(btn)
        if default:
            btn.setDefault(True)
            btn.setAutoDefault(True)
        if escape:
            self._escape_key = key
        return btn

    def _finish(self, key: str):
        self._result_key = key
        self.accept()

    def reject(self):
        # Treat close/escape as explicit cancel when available.
        if hasattr(self, '_escape_key'):
            self._result_key = getattr(self, '_escape_key')
        super().reject()

    def run(self) -> str | None:
        self.exec()
        return self._result_key

    @staticmethod
    def info(parent, title: str, text: str, *, informative_text: str | None = None) -> bool:
        dlg = AppMessageDialog(parent, title=title, text=text, informative_text=informative_text)
        dlg.add_action('ok', 'OK', primary=True, default=True, escape=True)
        return dlg.run() == 'ok'

    @staticmethod
    def confirm(
        parent,
        title: str,
        text: str,
        *,
        informative_text: str | None = None,
        confirm_label: str = 'Yes',
        cancel_label: str = 'Cancel',
        danger: bool = False,
    ) -> bool:
        dlg = AppMessageDialog(parent, title=title, text=text, informative_text=informative_text)
        dlg.add_action('cancel', cancel_label, default=True, escape=True)
        dlg.add_action('confirm', confirm_label, primary=not danger, danger=danger)
        return dlg.run() == 'confirm'

    @staticmethod
    def save_discard_cancel(parent, title: str, text: str) -> str:
        dlg = AppMessageDialog(parent, title=title, text=text)
        dlg.add_action('cancel', 'Cancel', default=True, escape=True)
        dlg.add_action('discard', 'Discard', danger=True)
        dlg.add_action('save', 'Save', primary=True)
        return dlg.run() or 'cancel'


class AppTextInputDialog(QDialog):
    """Styled text input dialog for consistent add/rename flows."""

    def __init__(self, parent=None, *, title: str, label: str, text: str = ''):
        super().__init__(parent, Qt.Dialog)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(420)
        self._accepted = False

        self.setStyleSheet(
            """
            QDialog {
                background: #2b2b2b;
                border: 1px solid #555;
            }
            QLabel {
                color: #c8c8c8;
                font-size: 12px;
                background: transparent;
            }
            QLineEdit {
                background: #1e1e1e;
                color: #dcdcdc;
                border: 1px solid #3f3f3f;
                padding: 5px 8px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #5aa9ff;
            }
            QPushButton {
                background: #3a3a3a;
                color: #c8c8c8;
                border: none;
                padding: 6px 16px;
                font-size: 11px;
                min-width: 72px;
            }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:pressed { background: #2a2a2a; }
            QPushButton#primary_btn {
                background: #006eaf;
                color: #fff;
            }
            QPushButton#primary_btn:hover { background: #0080c8; }
            QPushButton#primary_btn:pressed { background: #005a8e; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)

        lbl = QLabel(label)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.input = QLineEdit(text)
        self.input.selectAll()
        layout.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)

        ok_btn = QPushButton('OK')
        ok_btn.setObjectName('primary_btn')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        row.addWidget(ok_btn)

        layout.addLayout(row)

    def _accept(self):
        self._accepted = True
        self.accept()

    @staticmethod
    def get_text(parent, *, title: str, label: str, text: str = '') -> tuple[str, bool]:
        dlg = AppTextInputDialog(parent, title=title, label=label, text=text)
        dlg.exec()
        return dlg.input.text(), dlg._accepted
