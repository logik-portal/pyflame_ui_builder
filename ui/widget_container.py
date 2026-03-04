"""Widget container, overlay, and tab-order dialog components."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMenu,
    QSizePolicy,
)


class TabOrderDialog(QDialog):
    """Ask the user whether to include tab_order and in what sequence."""

    def __init__(self, entries: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Tab Order')
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setStyleSheet(
            'QDialog { background: #2d2d2d; }'
            'QLabel  { color: #c8c8c8; }'
            'QListWidget { background: #1e1e1e; color: #c8c8c8;'
            '              border: 1px solid #555; outline: none; }'
            'QListWidget::item { padding: 4px 8px; }'
            'QListWidget::item:selected { background: #0078d7; }'
            'QPushButton { background: #3a3a3a; color: #c8c8c8; border: none;'
            '              padding: 4px 14px; border-radius: 2px; }'
            'QPushButton:hover { background: #4a4a4a; }'
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        info = QLabel(f'{len(entries)} entry widgets found.\nDrag items or use the arrows to set the tab order.')
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        for e in entries:
            self._list.addItem(e.var_name or 'entry')
        layout.addWidget(self._list)

        arrow_row = QHBoxLayout()
        up_btn = QPushButton('▲  Up')
        down_btn = QPushButton('▼  Down')
        up_btn.clicked.connect(self._move_up)
        down_btn.clicked.connect(self._move_down)
        arrow_row.addWidget(up_btn)
        arrow_row.addWidget(down_btn)
        arrow_row.addStretch()
        layout.addLayout(arrow_row)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton('Include Tab Order')
        ok_btn.setStyleSheet('background: #0078d7; color: white; padding: 4px 16px;')
        ok_btn.clicked.connect(self.accept)
        skip_btn = QPushButton('Skip')
        skip_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(skip_btn)
        layout.addLayout(btn_row)

    def _move_up(self):
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)

    def ordered_vars(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]


class MoveResizeDialog(QDialog):
    """Dialog for setting a widget's grid position and span."""

    def __init__(self, container, canvas, widget_specs: dict):
        super().__init__(canvas)
        self.container = container
        self.canvas = canvas
        m = container.model
        cfg = canvas.config

        self.setWindowTitle('Move / Resize')
        self.setModal(True)
        self.setStyleSheet(
            'QDialog { background: #2d2d2d; }'
            'QLabel  { color: #c8c8c8; }'
            'QSpinBox { background: #3a3a3a; border: 1px solid #555;'
            '           color: #c8c8c8; padding: 2px; }'
            'QPushButton { padding: 4px 16px; color: white; border: none; border-radius: 2px; }'
        )

        form = QFormLayout(self)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(8)

        self._row = QSpinBox(); self._row.setRange(0, cfg.grid_rows - 1); self._row.setValue(m.row)
        self._col = QSpinBox(); self._col.setRange(0, cfg.grid_columns - 1); self._col.setValue(m.col)
        self._rowspan = QSpinBox(); self._rowspan.setRange(1, cfg.grid_rows); self._rowspan.setValue(m.row_span)
        self._colspan = QSpinBox(); self._colspan.setRange(1, cfg.grid_columns); self._colspan.setValue(m.col_span)

        fixed = widget_specs.get(m.widget_type, {}).get('fixed_axes', set())
        if 'h' in fixed:
            self._rowspan.setValue(1)
            self._rowspan.setEnabled(False)
        if 'w' in fixed:
            self._colspan.setValue(1)
            self._colspan.setEnabled(False)

        form.addRow('Row:', self._row)
        form.addRow('Column:', self._col)
        if not ({'h', 'w'} <= set(fixed)):
            form.addRow('Row Span:', self._rowspan)
            form.addRow('Col Span:', self._colspan)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton('Apply')
        apply_btn.setStyleSheet('background: #0078d7;')
        apply_btn.clicked.connect(self._apply)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setStyleSheet('background: #555;')
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        form.addRow(btn_row)

    def _apply(self):
        m = self.container.model
        cfg = self.canvas.config
        row = min(self._row.value(), cfg.grid_rows - 1)
        col = min(self._col.value(), cfg.grid_columns - 1)
        row_span = min(self._rowspan.value(), cfg.grid_rows - row)
        col_span = min(self._colspan.value(), cfg.grid_columns - col)
        m.row, m.col = row, col
        m.row_span, m.col_span = row_span, col_span
        self.container.setGeometry(self.canvas.cell_rect(row, col, row_span, col_span))
        self.canvas.widget_moved.emit(self.container)
        self.accept()


class WidgetOverlay(QWidget):
    _CURSOR_MAP = {
        'nw': Qt.SizeFDiagCursor, 'se': Qt.SizeFDiagCursor,
        'ne': Qt.SizeBDiagCursor, 'sw': Qt.SizeBDiagCursor,
        'n': Qt.SizeVerCursor, 's': Qt.SizeVerCursor,
        'e': Qt.SizeHorCursor, 'w': Qt.SizeHorCursor,
    }

    def __init__(self, container):
        super().__init__(container)
        self.container = container
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._mode = None
        self._press_pos = None
        self._press_geom = None
        self._rclick_pos = None
        self._rclick_local = None
        self._drag_started = False

    def paintEvent(self, event):
        if not self.container.selected:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(QColor(0, 120, 215), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))

        allowed_fn = self.container.__class__._allowed_handle_ids
        rects_fn = self.container.__class__._handle_rects
        allowed = allowed_fn(self.container.model.widget_type) if callable(allowed_fn) else set()
        rects = rects_fn(self.rect()) if callable(rects_fn) else {}
        p.setPen(QPen(QColor(0, 100, 200), 1))
        p.setBrush(QBrush(QColor(255, 255, 255)))
        for hid, hr in rects.items():
            if hid in allowed:
                p.drawRect(hr)

        m = self.container.model
        coord_hint = f'R{m.row + 1} C{m.col + 1}'
        if m.row_span > 1 or m.col_span > 1:
            coord_hint += f' · {m.row_span}×{m.col_span}'
        p.setPen(QPen(QColor(0, 120, 215, 180), 1))
        p.setFont(QFont('Arial', 7))
        p.drawText(self.rect().adjusted(0, 0, -3, 0), Qt.AlignTop | Qt.AlignRight, coord_hint)
        p.end()

    def _hit_test(self, pos):
        allowed_fn = self.container.__class__._allowed_handle_ids
        rects_fn = self.container.__class__._handle_rects
        allowed = allowed_fn(self.container.model.widget_type) if callable(allowed_fn) else set()
        rects = rects_fn(self.rect()) if callable(rects_fn) else {}
        for hid, hr in rects.items():
            if hid in allowed and hr.contains(pos):
                return hid
        return None

    def mousePressEvent(self, event):
        if self.container.canvas.preview_mode:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._rclick_pos = event.globalPosition().toPoint()
            self._rclick_local = event.position().toPoint()
            self._drag_started = False
            self.container.canvas.select_widget(self.container)
            event.accept()
        elif event.button() == Qt.RightButton:
            self.container.canvas.select_widget(self.container)
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.container.canvas.preview_mode:
            event.ignore()
            return
        if event.buttons() & Qt.LeftButton:
            if self._rclick_pos is not None and not self._drag_started:
                moved = (event.globalPosition().toPoint() - self._rclick_pos).manhattanLength()
                if moved > 5:
                    self._start_drag(self._rclick_pos, self._rclick_local)
                    self._drag_started = True
            if self._mode is not None:
                self._do_move(event.globalPosition().toPoint())
            event.accept()
        else:
            handle = self._hit_test(event.position().toPoint())
            if handle:
                self.setCursor(self._CURSOR_MAP.get(handle, Qt.ArrowCursor))
            else:
                self.unsetCursor()

    def mouseReleaseEvent(self, event):
        if self.container.canvas.preview_mode:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            if self._drag_started and self._mode is not None:
                self._finish_drag()
            self._rclick_pos = None
            self._rclick_local = None
            self._drag_started = False
        event.accept()

    def _start_drag(self, global_pos, local_pos):
        handle = self._hit_test(local_pos)
        self._mode = handle if handle else 'move'
        self._press_pos = global_pos
        self._press_geom = self.container.geometry()
        self.container.canvas.select_widget(self.container)
        self.setCursor(Qt.SizeAllCursor if self._mode == 'move' else self._CURSOR_MAP.get(self._mode, Qt.SizeAllCursor))

    def _do_move(self, global_pos):
        delta = global_pos - self._press_pos
        if self._mode == 'move':
            self.container.move(self._press_geom.topLeft() + delta)
        else:
            self._apply_resize(delta, self._press_geom)

    def _finish_drag(self):
        self._snap_to_grid()
        self._mode = None
        self._press_pos = None
        self._press_geom = None
        self.unsetCursor()
        self.container.canvas.widget_moved.emit(self.container)

    def _show_context_menu(self, global_pos):
        m = self.container.model
        canvas = self.container.canvas

        menu = QMenu(self)
        menu.setStyleSheet(canvas._MENU_STYLE)
        mw = canvas.window()
        if hasattr(mw, 'undo_action') and hasattr(mw, 'redo_action'):
            menu.addAction(mw.undo_action)
            if mw.redo_action.isEnabled():
                menu.addAction(mw.redo_action)
            menu.addSeparator()

        duplicate_action = menu.addAction('Duplicate Widget')
        delete_action = menu.addAction('Delete Widget')
        menu.addSeparator()
        row_above_action = menu.addAction('Add Row Above')
        row_below_action = menu.addAction('Add Row Below')
        del_row_action = menu.addAction('Delete Row'); del_row_action.setEnabled(canvas.config.grid_rows > 1)
        menu.addSeparator()
        col_left_action = menu.addAction('Add Column Left')
        col_right_action = menu.addAction('Add Column Right')
        del_col_action = menu.addAction('Delete Column'); del_col_action.setEnabled(canvas.config.grid_columns > 1)

        action = menu.exec(global_pos)
        if action == row_above_action:
            canvas._insert_row(m.row, above=True)
        elif action == row_below_action:
            canvas._insert_row(m.row, above=False)
        elif action == del_row_action:
            canvas._delete_row(m.row)
        elif action == col_left_action:
            canvas._insert_col(m.col, left=True)
        elif action == col_right_action:
            canvas._insert_col(m.col, left=False)
        elif action == del_col_action:
            canvas._delete_col(m.col)
        elif action == duplicate_action:
            canvas.select_widget(self.container); canvas.duplicate_selected()
        elif action == delete_action:
            canvas.select_widget(self.container); canvas.remove_selected()

    def _apply_resize(self, delta, orig):
        canvas = self.container.canvas
        cfg = canvas.config
        z = canvas.zoom_factor
        min_w = max(1, int(cfg.column_width * z))
        min_h = max(1, int(cfg.row_height * z))
        dx, dy = delta.x(), delta.y()
        left, top, right, bottom = orig.left(), orig.top(), orig.right(), orig.bottom()

        if 'w' in self._mode: left = min(orig.left() + dx, right - min_w)
        if 'e' in self._mode: right = max(orig.right() + dx, left + min_w)
        if 'n' in self._mode: top = min(orig.top() + dy, bottom - min_h)
        if 's' in self._mode: bottom = max(orig.bottom() + dy, top + min_h)

        self.container.setGeometry(left, top, right - left, bottom - top)

    def _snap_to_grid(self):
        canvas = self.container.canvas
        cfg = canvas.config
        z = canvas.zoom_factor
        cw = max(1, int(cfg.column_width * z))
        rh = max(1, int(cfg.row_height * z))
        gap = max(1, int(getattr(canvas, 'cell_gap', 0) * z))
        origin = canvas.grid_origin()
        ox = int(origin.x())
        oy = int(origin.y())
        geom = self.container.geometry()

        prev_row = self.container.model.row
        prev_col = self.container.model.col
        prev_row_span = self.container.model.row_span
        prev_col_span = self.container.model.col_span

        # cell_rect places widgets at origin + gap//2 and sizes as span*cw - gap.
        # Invert that mapping here so snapping remains stable when margins/gap change.
        col = round((geom.x() - ox - gap // 2) / cw)
        row = round((geom.y() - oy - gap // 2) / rh)
        col_span = max(1, round((geom.width() + gap) / cw))
        row_span = max(1, round((geom.height() + gap) / rh))

        col = max(0, min(col, cfg.grid_columns - 1))
        row = max(0, min(row, cfg.grid_rows - 1))
        col_span = min(col_span, cfg.grid_columns - col)
        row_span = min(row_span, cfg.grid_rows - row)

        fixed = self.container.widget_specs.get(self.container.model.widget_type, {}).get('fixed_axes', set())
        if 'h' in fixed: row_span = 1
        if 'w' in fixed: col_span = 1

        if canvas._has_overlap(row, col, row_span, col_span, ignore_container=self.container):
            row, col, row_span, col_span = prev_row, prev_col, prev_row_span, prev_col_span

        model = self.container.model
        model.row, model.col = row, col
        model.row_span, model.col_span = row_span, col_span
        self.container.setGeometry(canvas.cell_rect(row, col, row_span, col_span))


class WidgetContainer(QFrame):
    """Wraps one real PyFlame widget on the canvas with a transparent overlay."""

    _props_to_kwargs: Callable[[str, dict], dict] | None = None
    _make_fallback_widget: Callable[[str], QWidget] | None = None
    _widget_class_getter: Callable[[str], Any] | None = None
    _pyflame_loaded: bool = False
    _progress_preview_cls: Any = None
    _allowed_handle_ids: Callable[[str], set[str]] | None = None
    _handle_rects: Callable[[Any], dict] | None = None
    _chrome_title_h: int = 48
    _chrome_side_w: int = 2

    @classmethod
    def configure(
        cls,
        *,
        props_to_kwargs: Callable[[str, dict], dict],
        make_fallback_widget: Callable[[str], QWidget],
        widget_class_getter: Callable[[str], Any],
        pyflame_loaded: bool,
        progress_preview_cls: Any,
        allowed_handle_ids: Callable[[str], set[str]],
        handle_rects: Callable[[Any], dict],
        chrome_title_h: int,
        chrome_side_w: int,
    ) -> None:
        cls._props_to_kwargs = props_to_kwargs
        cls._make_fallback_widget = make_fallback_widget
        cls._widget_class_getter = widget_class_getter
        cls._pyflame_loaded = pyflame_loaded
        cls._progress_preview_cls = progress_preview_cls
        cls._allowed_handle_ids = allowed_handle_ids
        cls._handle_rects = handle_rects
        cls._chrome_title_h = chrome_title_h
        cls._chrome_side_w = chrome_side_w

    def __init__(self, pyflame_widget, placed_model, canvas):
        super().__init__(canvas)
        self.model = placed_model
        self.canvas = canvas
        self.selected = False
        self.pyflame_widget = pyflame_widget
        self.widget_specs = getattr(canvas, 'widget_specs', {})
        self.chrome_title_h = self._chrome_title_h
        self.chrome_side_w = self._chrome_side_w

        self.setFrameStyle(QFrame.NoFrame)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet('background: transparent; border: none;')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(pyflame_widget)
        self._free_size_constraints(pyflame_widget)
        self._apply_fallback_display_name(pyflame_widget)

        self.overlay = WidgetOverlay(self)
        self.overlay.move(0, 0)
        self.overlay.raise_()
        self._install_filter(pyflame_widget)

    def _install_filter(self, widget):
        widget.installEventFilter(self.overlay)
        from PySide6.QtWidgets import QWidget as _QW
        for child in widget.findChildren(_QW):
            child.installEventFilter(self.overlay)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.resize(self.size())
        self.overlay.raise_()
        self.overlay.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.overlay.raise_()

    def set_selected(self, selected):
        self.selected = selected
        self.overlay.update()

    def set_preview_mode(self, enabled: bool):
        """Toggle interactive preview mode (disable edit overlay)."""
        self.overlay.setVisible(not enabled)

    @staticmethod
    def _free_size_constraints(widget):
        widget.setMinimumSize(0, 0)
        widget.setMaximumSize(16777215, 16777215)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def replace_inner_widget(self, new_widget):
        item = self._layout.takeAt(0)
        if item and item.widget():
            item.widget().deleteLater()
        self.pyflame_widget = new_widget
        self._layout.addWidget(new_widget)
        self._free_size_constraints(new_widget)
        self._apply_fallback_display_name(new_widget)
        self._install_filter(new_widget)
        self.overlay.raise_()

    def _apply_fallback_display_name(self, widget):
        """Show var_name for selected fallback labels instead of [PyFlameX]."""
        if not isinstance(widget, QLabel):
            return
        wt = getattr(self.model, 'widget_type', '')
        if wt not in {'PyFlameTable', 'PyFlameListWidget', 'PyFlameTextEdit', 'PyFlameTextBrowser', 'PyFlameProgressBarWidget'}:
            return
        txt = widget.text() or ''
        if not txt.startswith('['):
            return
        var_name = (getattr(self.model, 'var_name', '') or '').strip()
        if var_name:
            widget.setText(var_name)

    @classmethod
    def make_widget(cls, widget_type, props):
        if not cls._pyflame_loaded:
            return cls._make_fallback_widget(widget_type)
        wcls = cls._widget_class_getter(widget_type) if cls._widget_class_getter else None
        if wcls is None:
            return cls._make_fallback_widget(widget_type)
        kwargs = cls._props_to_kwargs(widget_type, props)
        try:
            w = wcls(**kwargs)
            if widget_type == 'PyFlameHorizontalLine':
                color_name = str((props or {}).get('color', 'GRAY') or 'GRAY').upper()
                # Use softer UI-preview tones to better match Flame-style line rendering.
                color_map = {
                    'BLACK': '#1f1f1f',
                    'WHITE': '#d8d8d8',
                    'GRAY': '#6f6f6f',
                    'BRIGHT_GRAY': '#a8a8a8',
                    'BLUE': '#4b7ea8',
                    'RED': '#a85a5a',
                }
                css_color = color_map.get(color_name, '#808080')
                host = QWidget(); host.setStyleSheet('background: transparent;')
                lay = QVBoxLayout(host); lay.setContentsMargins(0, 0, 0, 0); lay.addStretch(1)
                line = QFrame(); line.setFixedHeight(1); line.setStyleSheet(f'background: {css_color}; border: none;')
                lay.addWidget(line); lay.addStretch(1)
                return host
            if widget_type == 'PyFlameVerticalLine':
                color_name = str((props or {}).get('color', 'GRAY') or 'GRAY').upper()
                # Use softer UI-preview tones to better match Flame-style line rendering.
                color_map = {
                    'BLACK': '#1f1f1f',
                    'WHITE': '#d8d8d8',
                    'GRAY': '#6f6f6f',
                    'BRIGHT_GRAY': '#a8a8a8',
                    'BLUE': '#4b7ea8',
                    'RED': '#a85a5a',
                }
                css_color = color_map.get(color_name, '#808080')
                host = QWidget(); host.setStyleSheet('background: transparent;')
                lay = QHBoxLayout(host); lay.setContentsMargins(0, 0, 0, 0); lay.addStretch(1)
                line = QFrame(); line.setFixedWidth(1); line.setStyleSheet(f'background: {css_color}; border: none;')
                lay.addWidget(line); lay.addStretch(1)
                return host
            if widget_type == 'PyFlameProgressBarWidget':
                host = cls._progress_preview_cls(); host.setStyleSheet('background: transparent;')
                return host
            return w
        except Exception as e:
            print(f'Warning: {widget_type}({kwargs}) → {e}')
            return cls._make_fallback_widget(widget_type)
