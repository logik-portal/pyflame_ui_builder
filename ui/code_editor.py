"""Code editor components: syntax highlighter, gutter, and editor widget."""

import os
import re
import html

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QTextEdit, QTextBrowser, QWidget, QPlainTextEdit,
)
from PySide6.QtCore import Qt, QRect, QSize, QPoint, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QPainter, QPolygon,
    QTextCursor, QSyntaxHighlighter, QTextCharFormat,
)


class _HoverDocPopup(QFrame):
    """VS Code-like scrollable hover doc popup."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip)
        self.setObjectName('HoverDocPopup')
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            '#HoverDocPopup { background: #252526; border: 1px solid #3c3c3c; border-radius: 4px; }'
            '#HoverDocPopup QLabel { color: #9cdcfe; font-weight: 700; font-size: 13px; padding: 0 0 2px 0; }'
            '#HoverDocPopup QTextBrowser { background: #1e1e1e; color: #d4d4d4; border: 1px solid #333; font-size: 12px; }'
            '#HoverDocPopup .inline-code { background: #2d2d2d; color: #d19a66; padding: 1px 3px; border-radius: 3px; font-weight: 700; }'
            '#HoverDocPopup h3 { color: #dcdcaa; margin: 8px 0 4px 0; font-size: 26px; font-weight: 700; text-decoration: underline; }'
            '#HoverDocPopup h4 { color: #c5c5c5; margin: 6px 0 3px 0; font-size: 23px; font-weight: 700; text-decoration: underline; }'
            '#HoverDocPopup .section { color: #4fc1ff; font-weight: 700; margin-top: 8px; font-size: 16px; }'
            '#HoverDocPopup .bullet { color: #ce9178; }'
            '#HoverDocPopup p { margin: 2px 0; font-size: 12px; }'
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.title = QLabel('')
        self.body = QTextBrowser()
        self._font_family = None
        self.body.setReadOnly(True)
        self.body.setOpenExternalLinks(False)
        self.body.setOpenLinks(False)
        self.body.setLineWrapMode(QTextEdit.WidgetWidth)
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body.setMinimumSize(380, 120)
        self.body.setMaximumSize(680, 360)
        lay.addWidget(self.title)
        lay.addWidget(self.body)

        # Optional custom hover-doc font (resolved relative to this script).
        hover_font_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            '..', 'assets', 'fonts', 'Montserrat-Light.ttf',
        )
        try:
            fid = QFontDatabase.addApplicationFont(hover_font_path)
            if fid != -1:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    fam = fams[0]
                    if isinstance(fam, str) and fam.strip() and not fam.strip().startswith('<PySide6.'):
                        self._font_family = fam
                        f_body = QFont(fam, 12)
                        f_title = QFont(fam, 13)
                        self.body.setFont(f_body)
                        self.body.document().setDefaultFont(f_body)
                        self.title.setFont(f_title)
                        self.title.setStyleSheet(
                            f"color: #9cdcfe; font-weight: 700; font-size: 13px; font-family: '{fam}'; padding: 0 0 2px 0;"
                        )
        except Exception:
            pass

    @staticmethod
    def _doc_to_markdown(text: str) -> str:
        """Convert Google/reST-ish doc text to a markdown-like intermediate."""
        lines = (text or '').splitlines()
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            stripped = line.strip()
            nxt_stripped = nxt.strip()

            if stripped and nxt_stripped and set(nxt_stripped) <= {'='}:
                out.append(f'# {stripped}')
                i += 2
                continue
            if stripped and nxt_stripped and set(nxt_stripped) <= {'-'}:
                out.append(f'## {stripped}')
                i += 2
                continue

            # Normalize inline code markers to markdown single-backtick style.
            line = re.sub(r'``([^`]+)``', r'`\1`', line)
            out.append(line)
            i += 1
        return '\n'.join(out)

    @staticmethod
    def _markdownish_to_html(md: str) -> str:
        out: list[str] = []
        for line in (md or '').splitlines():
            stripped = line.strip()
            if not stripped:
                out.append('<p>&nbsp;</p>')
                continue
            if stripped.startswith('# '):
                out.append(f"<h3>{html.escape(stripped[2:].strip())}</h3>")
                continue
            if stripped.startswith('## '):
                out.append(f"<h4><u>{html.escape(stripped[3:].strip())}</u></h4>")
                continue

            if re.match(r'^(Args|Arguments|Parameters|Returns|Raises|Examples?|Notes?):\s*$', stripped):
                out.append(f"<p class='section'>{html.escape(stripped)}</p>")
                continue

            m_bullet = re.match(r'^\s*[-*]\s+(.*)$', line)
            if m_bullet:
                btxt = html.escape(m_bullet.group(1))
                btxt = re.sub(r'`([^`]+)`', r"<span class='inline-code'><b>\1</b></span>", btxt)
                out.append(f"<p><span class='bullet'>•</span> {btxt}</p>")
                continue

            m_param = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*\([^)]*\))?)\s*:\s*(.*)$', line)
            if m_param and len(m_param.group(1)) <= 48:
                pname = html.escape(m_param.group(1))
                pdesc = html.escape(m_param.group(2))
                pdesc = re.sub(r'`([^`]+)`', r"<span class='inline-code'><b>\1</b></span>", pdesc)
                out.append(f"<p><code>{pname}</code>: {pdesc}</p>")
                continue

            esc = html.escape(line)
            esc = re.sub(r'`([^`]+)`', r"<span class='inline-code'><b>\1</b></span>", esc)
            out.append(f'<p>{esc}</p>')

        return ''.join(out)

    def set_hint(self, symbol: str, text: str):
        self.title.setText(symbol)
        md = self._doc_to_markdown(text)
        body_html = self._markdownish_to_html(md)
        fam = self._font_family or self.body.font().family() or 'Sans Serif'
        full_html = (
            '<html><head><style>'
            f"body {{ font-family: '{fam}'; font-size: 12px; }}"
            '</style></head><body>'
            f'{body_html}'
            '</body></html>'
        )
        self.body.setHtml(full_html)
        self.body.verticalScrollBar().setValue(0)


class _CodeEditorGutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.gutter_paint_event(event)

    def mousePressEvent(self, event):
        self.editor.gutter_mouse_press(event)
        super().mousePressEvent(event)


class SpacesTabPlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit with editor-friendly Python behaviors."""

    duplicateRequested = Signal()
    moveUpRequested = Signal()
    moveDownRequested = Signal()
    bookmarkToggleRequested = Signal()
    bookmarkNextRequested = Signal()
    bookmarkPrevRequested = Signal()
    foldToggleRequested = Signal(int)
    protectedEditAttempted = Signal()

    _PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hover_hints: dict[str, str] = {}
        self._last_hover_word = ''
        self._hover_enabled = False  # Disabled to reduce editor clutter.
        self._hover_popup = _HoverDocPopup(self)
        self._hover_popup.hide()
        self._gutter = _CodeEditorGutter(self)
        self.blockCountChanged.connect(self._on_gutter_block_count_changed)
        self.updateRequest.connect(self._on_gutter_update_request)
        self.cursorPositionChanged.connect(self._on_gutter_cursor_changed)
        self._on_gutter_block_count_changed(0)

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance('9') * digits + 16

    def _on_gutter_block_count_changed(self, _new_count: int):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_gutter_update_request(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._on_gutter_block_count_changed(0)

    def _on_gutter_cursor_changed(self):
        self._gutter.update()

    # ------------------------------------------------------------------
    # Protected-region helpers
    # ------------------------------------------------------------------

    _SEP_RE = re.compile(r'^\s*#\s*-{20,}')

    def _protected_ranges(self) -> list:
        """Return [(start_pos, end_pos), ...] for every [Start/End Window Build] block.

        The range spans from the separator line immediately before
        [Start Window Build] to the separator line immediately after
        [End Window Build], inclusive of their trailing newlines.
        """
        text = self.toPlainText()
        if not text:
            return []
        lines = text.split('\n')
        line_starts: list[int] = []
        pos = 0
        for ln in lines:
            line_starts.append(pos)
            pos += len(ln) + 1  # +1 for '\n'

        ranges = []
        i = 0
        while i < len(lines):
            if '[Start Window Build]' in lines[i]:
                start_line = i - 1 if i > 0 and self._SEP_RE.match(lines[i - 1]) else i
                j = i + 1
                while j < len(lines):
                    if '[End Window Build]' in lines[j]:
                        end_line = j + 1 if j + 1 < len(lines) and self._SEP_RE.match(lines[j + 1]) else j
                        char_start = line_starts[start_line]
                        char_end = line_starts[end_line] + len(lines[end_line])
                        if end_line < len(lines) - 1:
                            char_end += 1  # include the trailing '\n'
                        ranges.append((char_start, char_end))
                        i = end_line + 1
                        break
                    j += 1
                else:
                    i += 1
                continue
            i += 1
        return ranges

    def _cursor_in_protected(self, cursor, for_backspace: bool = False) -> bool:
        """Return True if the cursor or its selection overlaps a protected range."""
        ranges = self._protected_ranges()
        if not ranges:
            return False
        if cursor.hasSelection():
            sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
            sel_end = max(cursor.selectionStart(), cursor.selectionEnd())
            return any(sel_start < pend and sel_end > pstart for pstart, pend in ranges)
        pos = cursor.position()
        check = pos - 1 if for_backspace and pos > 0 else pos
        return any(pstart <= check <= pend for pstart, pend in ranges)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    @staticmethod
    def _is_foldable_text(line: str) -> bool:
        return bool(re.match(r'^\s*(def|class)\s+[A-Za-z_][A-Za-z0-9_]*', line))

    def gutter_paint_event(self, event):
        p = QPainter(self._gutter)
        p.fillRect(event.rect(), QColor('#232323'))

        protected = self._protected_ranges()

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        current_line = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                ln = block_number + 1
                bstart = block.position()
                bend = bstart + block.length()
                in_protected = any(bstart < pend and bend > pstart for pstart, pend in protected)
                if in_protected:
                    p.fillRect(0, top, self._gutter.width(), self.fontMetrics().height(), QColor('#1e1616'))
                color = QColor('#9aa0a6') if block_number != current_line else QColor('#d7dae0')
                if in_protected:
                    color = QColor('#5a3838') if block_number != current_line else QColor('#8a5858')
                p.setPen(color)
                p.drawText(2, top, self._gutter.width() - 16, self.fontMetrics().height(), Qt.AlignRight, str(ln))

                text = block.text()
                if self._is_foldable_text(text):
                    next_block = block.next()
                    folded = next_block.isValid() and not next_block.isVisible()
                    p.setPen(QColor('#7f8c8d'))
                    p.setBrush(QColor('#7f8c8d'))
                    cx = self._gutter.width() - 10
                    cy = top + self.fontMetrics().height() // 2
                    if folded:
                        tri = QPolygon([QPoint(cx - 2, cy - 4), QPoint(cx - 2, cy + 4), QPoint(cx + 3, cy)])
                    else:
                        tri = QPolygon([QPoint(cx - 4, cy - 2), QPoint(cx + 4, cy - 2), QPoint(cx, cy + 3)])
                    p.drawPolygon(tri)

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def gutter_mouse_press(self, event):
        if event.button() != Qt.LeftButton:
            return
        y = event.position().y() if hasattr(event, 'position') else event.y()
        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid():
            if block.isVisible() and top <= y <= bottom:
                if self._is_foldable_text(block.text()):
                    self.foldToggleRequested.emit(block.blockNumber() + 1)
                return
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())

    def set_hover_hints(self, hints: dict[str, str]):
        if not self._hover_enabled:
            self._hover_hints = {}
            self._hover_popup.hide()
            self._last_hover_word = ''
            return
        self._hover_hints = dict(hints or {})

    def _word_under_pos(self, pos) -> str:
        c = self.cursorForPosition(pos)
        c.select(QTextCursor.WordUnderCursor)
        return (c.selectedText() or '').strip()

    def mouseMoveEvent(self, event):
        if not self._hover_enabled:
            if self._last_hover_word:
                self._hover_popup.hide()
                self._last_hover_word = ''
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        gpos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        word = self._word_under_pos(pos)
        hint = self._hover_hints.get(word)
        if hint:
            if word != self._last_hover_word:
                title, body = (hint.split('\n', 1) + [''])[:2]
                self._hover_popup.set_hint(word, body or title)
                self._hover_popup.adjustSize()
                self._hover_popup.move(gpos + QPoint(16, 18))
                self._hover_popup.show()
                self._last_hover_word = word
        else:
            if self._last_hover_word:
                self._hover_popup.hide()
                self._last_hover_word = ''
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._last_hover_word:
            self._hover_popup.hide()
            self._last_hover_word = ''
        super().leaveEvent(event)

    def wheelEvent(self, event):
        # When hover docs are open, mouse wheel should scroll the popup body
        # similar to editor hovers in VS Code.
        if self._hover_popup.isVisible():
            sb = self._hover_popup.body.verticalScrollBar()
            step = sb.singleStep() or 20
            delta = event.angleDelta().y()
            if delta != 0:
                sb.setValue(sb.value() - (step if delta > 0 else -step))
                event.accept()
                return
        super().wheelEvent(event)

    def _selected_line_range(self, cursor: QTextCursor) -> tuple[int, int]:
        sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
        sel_end = max(cursor.selectionStart(), cursor.selectionEnd())
        work = QTextCursor(self.document())
        work.setPosition(sel_start)
        work.movePosition(QTextCursor.StartOfBlock)
        line_start = work.position()

        work.setPosition(sel_end)
        if work.atBlockStart() and sel_end > sel_start:
            work.movePosition(QTextCursor.PreviousBlock)
        work.movePosition(QTextCursor.EndOfBlock)
        line_end = work.position()
        return line_start, line_end

    def _indent_selection(self, outdent: bool = False):
        cursor = self.textCursor()
        start, end = self._selected_line_range(cursor)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        lines = cursor.selectedText().split('\u2029')
        if not lines:
            return
        if outdent:
            out = [ln[4:] if ln.startswith('    ') else (ln[1:] if ln.startswith(' ') else ln) for ln in lines]
        else:
            out = [f'    {ln}' if ln else '    ' for ln in lines]
        cursor.beginEditBlock()
        cursor.insertText('\n'.join(out))
        cursor.endEditBlock()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Protected-region guard: block any operation that would modify a locked zone.
        _MODIFYING_KEYS = {Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab}
        _would_modify = (
            key in _MODIFYING_KEYS
            or (bool(event.text()) and not (mods & (Qt.ControlModifier | Qt.MetaModifier)))
            or (key == Qt.Key_X and bool(mods & Qt.ControlModifier))   # cut
            or (key == Qt.Key_V and bool(mods & Qt.ControlModifier))   # paste
            or (key == Qt.Key_D and bool(mods & Qt.ControlModifier))   # duplicate line
            or (key in (Qt.Key_Up, Qt.Key_Down) and bool(mods & Qt.AltModifier))  # move line
        )
        if _would_modify:
            _for_bs = key == Qt.Key_Backspace and not self.textCursor().hasSelection()
            if self._cursor_in_protected(self.textCursor(), for_backspace=_for_bs):
                self.protectedEditAttempted.emit()
                return

        if key == Qt.Key_D and mods == Qt.ControlModifier:
            self.duplicateRequested.emit()
            return
        if key == Qt.Key_Up and mods == Qt.AltModifier:
            self.moveUpRequested.emit()
            return
        if key == Qt.Key_Down and mods == Qt.AltModifier:
            self.moveDownRequested.emit()
            return

        if key == Qt.Key_Tab:
            self._indent_selection(outdent=bool(mods & Qt.ShiftModifier))
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            block_text = cursor.block().text()
            leading = re.match(r'^\s*', block_text).group(0)
            if block_text.rstrip().endswith(':'):
                leading += '    '
            super().keyPressEvent(event)
            self.insertPlainText(leading)
            return

        if key == Qt.Key_Backspace:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                pos = cursor.position()
                txt = self.toPlainText()
                if 0 < pos < len(txt):
                    left = txt[pos - 1]
                    right = txt[pos]
                    if self._PAIRS.get(left) == right:
                        cursor.beginEditBlock()
                        cursor.deletePreviousChar()
                        cursor.deleteChar()
                        cursor.endEditBlock()
                        return
            super().keyPressEvent(event)
            return

        pair = self._PAIRS.get(event.text())
        if pair and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            cursor = self.textCursor()
            if cursor.hasSelection():
                selected = cursor.selectedText().replace('\u2029', '\n')
                cursor.insertText(event.text() + selected + pair)
            else:
                cursor.insertText(event.text() + pair)
                cursor.movePosition(QTextCursor.Left)
                self.setTextCursor(cursor)
            return

        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        """Block paste operations that land inside a protected region."""
        if self._cursor_in_protected(self.textCursor()):
            self.protectedEditAttempted.emit()
            return
        super().insertFromMimeData(source)

    def contextMenuEvent(self, event):
        """Strip Cut/Paste/Delete from the right-click menu over protected regions."""
        menu = self.createStandardContextMenu()
        if self._cursor_in_protected(self.textCursor()):
            _BLOCKED = {'cut', 'paste', 'delete'}
            for action in list(menu.actions()):
                label = action.text().replace('&', '').split('\t')[0].strip().lower()
                if label in _BLOCKED:
                    menu.removeAction(action)
        gpos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
        menu.exec(gpos)


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Lightweight Python highlighter using VS Code Atom One Dark colors."""

    def __init__(self, parent):
        super().__init__(parent)
        self.rules: list[tuple[re.Pattern, QTextCharFormat]] = []

        # Atom One Dark palette
        # fg: #abb2bf, keyword: #c678dd, string: #98c379, comment: #5c6370,
        # function/type: #61afef, number: #d19a66, decorator: #e5c07b,
        # builtins/constants: #56b6c2

        kw = QTextCharFormat()
        kw.setForeground(QColor('#c678dd'))
        kw.setFontItalic(True)
        keywords = [
            'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 'finally',
            'return', 'import', 'from', 'as', 'pass', 'break', 'continue', 'with', 'lambda',
            'in', 'is', 'not', 'and', 'or', 'None', 'True', 'False', 'yield', 'raise', 'global', 'nonlocal',
            'async', 'await', 'match', 'case',
        ]
        self.rules.extend((re.compile(rf'\b{k}\b'), kw) for k in keywords)

        num = QTextCharFormat()
        num.setForeground(QColor('#d19a66'))
        self.rules.append((re.compile(r'\b\d+(?:\.\d+)?\b'), num))

        cmt = QTextCharFormat()
        cmt.setForeground(QColor('#5c6370'))
        cmt.setFontItalic(True)

        s = QTextCharFormat()
        s.setForeground(QColor('#98c379'))
        self.string_format = s

        fn = QTextCharFormat()
        fn.setForeground(QColor('#61afef'))
        fn.setFontItalic(True)
        self.rules.append((re.compile(r'\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\b'), fn))
        self.rules.append((re.compile(r'\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b'), fn))

        dec = QTextCharFormat()
        dec.setForeground(QColor('#e5c07b'))
        self.rules.append((re.compile(r'@\w+'), dec))

        builtin = QTextCharFormat()
        builtin.setForeground(QColor('#56b6c2'))
        builtins = [
            'print', 'len', 'range', 'str', 'int', 'float', 'dict', 'list', 'set', 'tuple',
            'min', 'max', 'sum', 'any', 'all', 'enumerate', 'zip', 'open',
        ]
        self.rules.extend((re.compile(rf'\b{b}\b'), builtin) for b in builtins)

        # Visual cue for self. prefix as in many One Dark Python themes.
        self_attr = QTextCharFormat()
        self_attr.setForeground(QColor('#e06c75'))
        self.rules.append((re.compile(r'\bself\b'), self_attr))

        # Keep comments/strings last so they override inner tokens (e.g. numbers in strings).
        self.rules.append((re.compile(r'#.*$'), cmt))
        self.rules.append((re.compile(r"'(?:[^'\\]|\\.)*'"), s))
        self.rules.append((re.compile(r'"(?:[^"\\]|\\.)*"'), s))

    def highlightBlock(self, text: str):
        # Multiline docstrings (triple quotes) should use the same green as strings.
        self.setCurrentBlockState(0)
        doc_ranges: list[tuple[int, int]] = []

        start_idx = 0
        if self.previousBlockState() in (1, 2):
            delim = "'''" if self.previousBlockState() == 1 else '"""'
            end = text.find(delim)
            if end == -1:
                doc_ranges.append((0, len(text)))
                self.setCurrentBlockState(1 if delim == "'''" else 2)
            else:
                doc_ranges.append((0, end + 3))
                start_idx = end + 3

        i = start_idx
        while i < len(text):
            s1 = text.find("'''", i)
            s2 = text.find('"""', i)
            starts = [(s1, "'''", 1), (s2, '"""', 2)]
            starts = [(p, d, st) for (p, d, st) in starts if p != -1]
            if not starts:
                break
            pos, delim, state = min(starts, key=lambda x: x[0])
            end = text.find(delim, pos + 3)
            if end == -1:
                doc_ranges.append((pos, len(text) - pos))
                self.setCurrentBlockState(state)
                break
            doc_ranges.append((pos, (end + 3) - pos))
            i = end + 3

        for pattern, fmt in self.rules:
            for m in pattern.finditer(text):
                # Prefer first capture group span when pattern highlights symbol names.
                if m.lastindex:
                    s, e = m.span(1)
                    self.setFormat(s, e - s, fmt)
                else:
                    self.setFormat(m.start(), m.end() - m.start(), fmt)

        # Apply docstring format last so inner tokens never override it.
        for s, n in doc_ranges:
            if n > 0:
                self.setFormat(s, n, self.string_format)
