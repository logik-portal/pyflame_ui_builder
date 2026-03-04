"""Help dialog for bundled markdown docs."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QPushButton, QSplitter, QTextBrowser, QVBoxLayout


class HelpDialog(QDialog):
    def __init__(self, help_dir: str, stylesheet: str, parent=None, initial_file: str | None = None):
        super().__init__(parent)
        self.setWindowTitle('Help')
        self.resize(900, 640)
        self.setStyleSheet(stylesheet)

        self.help_dir = help_dir
        self.help_files = {
            # Keep Getting Started sourced from repo root README.
            'Getting Started': os.path.join('..', '..', 'README.md'),
            'Keyboard Shortcuts': 'keyboard-shortcuts.md',
        }

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        self.nav = QListWidget()
        for title in self.help_files.keys():
            self.nav.addItem(title)
        self.nav.currentTextChanged.connect(self._load_topic)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setStyleSheet(
            'background: #1a1a1a; color: #c8c8c8; border: 1px solid #3a3a3a;'
            ' font-family: "Montserrat", "Arial"; font-size: 13px;'
        )

        splitter.addWidget(self.nav)
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 680])

        layout.addWidget(splitter)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        idx = 0
        if initial_file:
            files = list(self.help_files.values())
            if initial_file in files:
                idx = files.index(initial_file)
        self.nav.setCurrentRow(idx)

    @staticmethod
    def _sanitize_markdown_for_help(content: str) -> str:
        """Normalize README-style markdown for better QTextBrowser readability."""
        text = content or ''
        # Remove centered image wrapper blocks and inline images.
        text = re.sub(r'<p\s+align="center">.*?</p>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', text)
        # Convert HTML line breaks used in README badges/meta to plain newlines.
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        # Drop any remaining simple HTML tags that Qt markdown rendering may display awkwardly.
        text = re.sub(r'</?\w+[^>]*>', '', text)
        # Collapse excessive blank lines created by stripping.
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip() + '\n'

    def _load_topic(self, title: str):
        filename = self.help_files.get(title)
        if not filename:
            return
        path = os.path.join(self.help_dir, filename)
        if not os.path.exists(path):
            self.viewer.setPlainText(f'Help file missing:\n{path}')
            return
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Option 2: keep README as source of truth, but render a sanitized copy in Help UI.
        if title == 'Getting Started':
            content = self._sanitize_markdown_for_help(content)

        self.viewer.setMarkdown(content)
