"""Properties panel for selected widget editing."""

from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QLabel,
)


class DragSpinBox(QSpinBox):
    """QSpinBox with horizontal click-drag scrubbing behavior.

    Dragging from anywhere in the field (including the embedded line edit area)
    changes the value.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignCenter)
        self._drag_active = False
        self._drag_start_global = QPoint()
        self._drag_start_value = 0
        self.setMouseTracking(True)
        self.lineEdit().installEventFilter(self)

    def _begin_drag(self, global_pos: QPoint):
        self._drag_active = True
        self._drag_start_global = global_pos
        self._drag_start_value = self.value()

    def _update_drag(self, global_pos: QPoint):
        delta_x = global_pos.x() - self._drag_start_global.x()
        step_delta = int(delta_x / 6)
        self.setValue(self._drag_start_value + step_delta * self.singleStep())

    def eventFilter(self, obj, event):
        if obj is self.lineEdit():
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                self._begin_drag(event.globalPosition().toPoint())
                event.accept()
                return True
            if event.type() == event.Type.MouseMove and self._drag_active:
                self._update_drag(event.globalPosition().toPoint())
                event.accept()
                return True
            if event.type() == event.Type.MouseButtonRelease and self._drag_active:
                self._drag_active = False
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            self._update_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        super().mouseReleaseEvent(event)


class PropertiesPanel(QWidget):
    """Dynamically-built form showing selected widget or active window properties."""

    properties_changed = Signal()
    panel_interacted = Signal()

    def __init__(self, widget_specs: dict, parse_template_callbacks: Callable[[], list[str]], widget_factory: Any):
        super().__init__()
        self.container = None
        self._window_props_mode = False
        self._window_title = ''
        self._window_name = 'main_window'
        self._window_parent = None
        self._window_parent_options = []
        self._window_show_parent = True
        self._window_cols = 4
        self._window_rows = 3
        self._window_margins = 15
        self._window_margins_split = False
        self._window_props_changed = None
        self._window_name_changed = None
        self._window_title_changed = None
        self._window_parent_changed = None
        self._building = False
        self.widget_specs = widget_specs
        self.parse_template_callbacks = parse_template_callbacks
        self.widget_factory = widget_factory

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.title_label = QLabel('Widget Properties')
        self.title_label.setStyleSheet('color: #888; font-size: 11px; padding: 4px 4px 2px;')
        layout.addWidget(self.title_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameStyle(QFrame.NoFrame)
        layout.addWidget(self.scroll)

        self.inner = QWidget()
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(4, 4, 4, 4)
        self.inner_layout.setSpacing(6)
        self.inner_layout.addStretch()
        self.scroll.setWidget(self.inner)

    def show_properties(self, container):
        self._window_props_mode = False
        self.container = container
        self._rebuild()

    def mousePressEvent(self, event):
        self.panel_interacted.emit()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.panel_interacted.emit()
        super().focusInEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (event.Type.MouseButtonPress, event.Type.FocusIn):
            self.panel_interacted.emit()
        return super().eventFilter(obj, event)

    def show_window_properties(
        self,
        window_name: str,
        window_title: str | None,
        cols: int,
        rows: int,
        window_margins,
        on_changed,
        on_name_changed=None,
        on_title_changed=None,
        parent_window=None,
        parent_options=None,
        on_parent_changed=None,
        show_parent: bool = True,
    ):
        self.container = None
        self._window_props_mode = True
        self._window_name = window_name or 'main_window'
        self._window_title = '' if window_title is None else str(window_title)
        self._window_cols = int(cols)
        self._window_rows = int(rows)
        self._window_parent = parent_window
        self._window_parent_options = list(parent_options or [])
        if isinstance(window_margins, (list, tuple)):
            vals = [int(x) for x in list(window_margins)[:4]]
            if len(vals) == 4:
                self._window_margins = vals
                self._window_margins_split = True
            elif len(vals) == 1:
                self._window_margins = int(vals[0])
                self._window_margins_split = False
            else:
                self._window_margins = 15
                self._window_margins_split = False
        else:
            self._window_margins = int(window_margins)
            self._window_margins_split = False
        self._window_props_changed = on_changed
        self._window_name_changed = on_name_changed
        self._window_title_changed = on_title_changed
        self._window_parent_changed = on_parent_changed
        self._window_show_parent = bool(show_parent)
        self._rebuild()

    def clear(self):
        self.container = None
        self._window_props_mode = False
        self._rebuild()

    def _rebuild(self):
        self._building = True
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._window_props_mode:
            self.title_label.setText(f'Window Properties ({self._window_name})')
            window_rows = []
            if self._window_show_parent:
                window_rows.append(('Title', 'str', self._window_title, []))
            window_rows.append(('Function Name', 'str', self._window_name, []))
            self._add_group('Window', window_rows, is_window=True)
            if self._window_show_parent:
                self._add_window_parent_group()
            self._add_group('Flame Window', [
                ('Cols', 'int', self._window_cols, []),
                ('Rows', 'int', self._window_rows, []),
            ], is_window=True)
            self._add_window_margins_group()
            self.inner_layout.addStretch()
            self._building = False
            return

        if self.container is None:
            self.title_label.setText('Widget Properties')
            self.inner_layout.addStretch()
            self._building = False
            return

        model = self.container.model
        specs = self.widget_specs.get(model.widget_type, {})
        self.title_label.setText(f'{specs.get("display", model.widget_type)} Properties')

        self._add_group('Variable', [('var_name', 'str', model.var_name, [])])

        if specs.get('props'):
            rows = [(p.name, p.kind, model.properties.get(p.name, p.default), p.options) for p in specs['props']]
            self._add_group('Properties', rows, is_props=True)

        grid_rows = [('row', 'int', model.row, []), ('col', 'int', model.col, [])]
        fixed = self.widget_specs.get(model.widget_type, {}).get('fixed_axes', set())
        if not ({'h', 'w'} <= set(fixed)):
            grid_rows += [('rowspan', 'int', model.row_span, []), ('colspan', 'int', model.col_span, [])]
        self._add_group('Grid Position', grid_rows, is_grid=True)

        self.inner_layout.addStretch()
        self._building = False

    def _add_group(self, title, rows, is_props=False, is_grid=False, is_window=False):
        grp = QGroupBox(title)
        grp.setStyleSheet(self._group_style())
        form = QFormLayout(grp)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)
        form.setLabelAlignment(Qt.AlignRight)

        for row in rows:
            name, kind, val, opts = row
            w = self._make_input(name, kind, val, opts, is_props=is_props, is_grid=is_grid, is_window=is_window)
            form.addRow(f'{name}:', w)

        self.inner_layout.addWidget(grp)

    def _make_input(self, name, kind, val, opts, is_props=False, is_grid=False, is_window=False):
        s = self._input_style()
        if kind == 'str':
            w = QLineEdit(str(val) if val is not None else '')
            w.setStyleSheet(s)
            if is_window:
                w.textChanged.connect(lambda t, n=name: self._on_window_prop(n, t))
            elif name == 'var_name':
                w.textChanged.connect(lambda t: self._on_var_changed(t))
            else:
                w.textChanged.connect(lambda t, n=name: self._on_prop(n, t))
            w.installEventFilter(self)
            return w
        elif kind == 'enum':
            w = QComboBox()
            w.setStyleSheet(s)
            w.addItems(opts)
            if str(val) in opts:
                w.setCurrentText(str(val))
            w.currentTextChanged.connect(lambda t, n=name: self._on_prop(n, t))
            w.installEventFilter(self)
            return w
        elif kind == 'bool':
            w = QCheckBox()
            w.setChecked(bool(val))
            w.stateChanged.connect(lambda st, n=name: self._on_prop(n, bool(st)))
            w.installEventFilter(self)
            return w
        elif kind == 'int':
            w = DragSpinBox()
            w.setStyleSheet(s)
            w.setFixedWidth(90)
            w.setRange(-999999, 999999)
            try:
                w.setValue(int(val))
            except (TypeError, ValueError):
                w.setValue(0)
            if is_window:
                w.valueChanged.connect(lambda v, n=name: self._on_window_prop(n, v))
            elif is_grid:
                w.valueChanged.connect(lambda v, n=name: self._on_grid(n, v))
            else:
                w.valueChanged.connect(lambda v, n=name: self._on_prop(n, v))
            w.installEventFilter(self)
            return w
        elif kind == 'connect':
            callbacks = ['(none)'] + self.parse_template_callbacks()
            w = QComboBox()
            w.setStyleSheet(s)
            w.addItems(callbacks)
            current = val if val else '(none)'
            if current in callbacks:
                w.setCurrentText(current)
            w.currentTextChanged.connect(lambda t, n=name: self._on_prop(n, None if t == '(none)' else t))
            w.installEventFilter(self)
            return w
        elif kind == 'token_dest':
            w = QComboBox()
            w.setStyleSheet(s)
            entry_vars = []
            if self.container and self.container.canvas:
                for c in self.container.canvas.containers:
                    wt = c.model.widget_type
                    if wt in ('PyFlameEntry', 'PyFlameEntryBrowser'):
                        vn = (c.model.var_name or '').strip()
                        if vn:
                            entry_vars.append(vn)
            options = ['None'] + sorted(set(entry_vars)) if entry_vars else ['None']
            w.addItems(options)
            current = val if val else 'None'
            if current in options:
                w.setCurrentText(current)
            w.currentTextChanged.connect(lambda t, n=name: self._on_prop(n, None if t == 'None' else t))
            w.installEventFilter(self)
            return w
        elif kind == 'list':
            w = QPlainTextEdit()
            w.setStyleSheet(s)
            w.setMaximumHeight(72)
            if isinstance(val, list):
                w.setPlainText('\n'.join(str(x) for x in val))
            else:
                w.setPlainText(str(val) if val else '')
            w.textChanged.connect(lambda n=name, widget=w: self._on_prop(n, [x.strip() for x in widget.toPlainText().splitlines() if x.strip()]))
            w.installEventFilter(self)
            return w
        else:
            w = QLineEdit(str(val) if val else '')
            w.setStyleSheet(s)
            w.textChanged.connect(lambda t, n=name: self._on_prop(n, t))
            w.installEventFilter(self)
            return w

    def _on_prop(self, name, value):
        if self._building or not self.container:
            return
        model = self.container.model
        model.properties[name] = value

        if model.widget_type == 'PyFlameSlider':
            props = model.properties
            try:
                min_v = int(props.get('min_value', 0))
            except (TypeError, ValueError):
                min_v = 0
            try:
                max_v = int(props.get('max_value', 100))
            except (TypeError, ValueError):
                max_v = 100
            try:
                start_v = int(props.get('start_value', 0))
            except (TypeError, ValueError):
                start_v = 0
            if max_v <= min_v:
                max_v = min_v + 1
            if start_v < min_v:
                start_v = min_v
            if start_v > max_v:
                start_v = max_v
            props['min_value'] = min_v
            props['max_value'] = max_v
            props['start_value'] = start_v

        self._recreate_widget()
        self.properties_changed.emit()

    def _on_grid(self, attr, value):
        if self._building or not self.container:
            return
        m = self.container.model
        canvas = self.container.canvas
        cfg = canvas.config
        prev = (m.row, m.col, m.row_span, m.col_span)
        if attr == 'row':
            m.row = value
        elif attr == 'col':
            m.col = value
        elif attr == 'rowspan':
            m.row_span = value
        elif attr == 'colspan':
            m.col_span = value

        m.row_span = max(1, min(m.row_span, cfg.grid_rows))
        m.col_span = max(1, min(m.col_span, cfg.grid_columns))
        m.row = max(0, min(m.row, cfg.grid_rows - m.row_span))
        m.col = max(0, min(m.col, cfg.grid_columns - m.col_span))

        if canvas._has_overlap(m.row, m.col, m.row_span, m.col_span, ignore_container=self.container):
            m.row, m.col, m.row_span, m.col_span = prev

        r = self.container.canvas.cell_rect(m.row, m.col, m.row_span, m.col_span)
        self.container.setGeometry(r)
        self.show_properties(self.container)
        self.properties_changed.emit()

    def _emit_window_props_changed(self):
        if callable(self._window_props_changed):
            self._window_props_changed(self._window_cols, self._window_rows, self._window_margins)
        self.properties_changed.emit()

    def _on_window_margins_mode_changed(self, checked: bool):
        if self._building:
            return
        self._window_margins_split = bool(checked)
        if self._window_margins_split:
            if isinstance(self._window_margins, int):
                v = max(0, int(self._window_margins))
                self._window_margins = [v, v, v, v]
            elif isinstance(self._window_margins, list) and len(self._window_margins) == 1:
                v = max(0, int(self._window_margins[0]))
                self._window_margins = [v, v, v, v]
            elif not isinstance(self._window_margins, list) or len(self._window_margins) != 4:
                self._window_margins = [15, 15, 15, 15]
        else:
            if isinstance(self._window_margins, list) and self._window_margins:
                self._window_margins = max(0, int(self._window_margins[0]))
            else:
                self._window_margins = 15
        self._rebuild()
        self._emit_window_props_changed()

    def _on_window_margin_single_changed(self, value: int):
        if self._building:
            return
        self._window_margins = max(0, int(value))
        self._emit_window_props_changed()

    def _on_window_margin_part_changed(self, index: int, value: int):
        if self._building:
            return
        if not isinstance(self._window_margins, list) or len(self._window_margins) != 4:
            self._window_margins = [15, 15, 15, 15]
        self._window_margins[index] = max(0, int(value))
        self._emit_window_props_changed()

    def _on_window_parent_changed_local(self, text: str):
        if self._building:
            return
        self._window_parent = None if text == 'None' else text
        if callable(self._window_parent_changed):
            self._window_parent_changed(self._window_parent)
        self.properties_changed.emit()

    def _add_window_parent_group(self):
        group = QGroupBox('Window Parent')
        group.setStyleSheet(self._group_style())
        lay = QVBoxLayout(group)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        combo = QComboBox()
        combo.setStyleSheet(self._input_style())
        opts = ['None'] + [o for o in self._window_parent_options if o]
        combo.addItems(opts)
        current = self._window_parent or 'None'
        idx = combo.findText(current)
        combo.setCurrentIndex(max(0, idx))
        combo.currentTextChanged.connect(self._on_window_parent_changed_local)
        combo.installEventFilter(self)
        lay.addWidget(combo)

        self.inner_layout.addWidget(group)

    def _add_window_margins_group(self):
        group = QGroupBox('Window Margins')
        group.setStyleSheet(self._group_style())
        lay = QVBoxLayout(group)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        mode = QCheckBox('Use 4-value margins (L/T/R/B)')
        mode.setChecked(bool(self._window_margins_split))
        mode.stateChanged.connect(lambda _s: self._on_window_margins_mode_changed(mode.isChecked()))
        mode.installEventFilter(self)
        lay.addWidget(mode)

        row = QHBoxLayout()
        row.setSpacing(6)
        s = self._input_style()

        if self._window_margins_split:
            vals = self._window_margins if isinstance(self._window_margins, list) and len(self._window_margins) == 4 else [15, 15, 15, 15]
            labels = ['L', 'T', 'R', 'B']
            for i, lbl in enumerate(labels):
                row.addWidget(QLabel(lbl))
                sp = DragSpinBox()
                sp.setStyleSheet(s)
                sp.setFixedWidth(56)
                sp.setRange(0, 999999)
                sp.setValue(int(vals[i]))
                sp.valueChanged.connect(lambda v, idx=i: self._on_window_margin_part_changed(idx, v))
                sp.installEventFilter(self)
                row.addWidget(sp)
        else:
            row.addWidget(QLabel('All'))
            v = int(self._window_margins) if not isinstance(self._window_margins, list) else int(self._window_margins[0])
            sp = DragSpinBox()
            sp.setStyleSheet(s)
            sp.setFixedWidth(90)
            sp.setRange(0, 999999)
            sp.setValue(max(0, v))
            sp.valueChanged.connect(self._on_window_margin_single_changed)
            sp.installEventFilter(self)
            row.addWidget(sp)

        row.addStretch()
        lay.addLayout(row)
        self.inner_layout.addWidget(group)

    @staticmethod
    def _sanitize_identifier(raw: str, fallback: str = 'item') -> str:
        s = (raw or '').replace(' ', '_')
        s = re.sub(r'[^a-zA-Z0-9_]+', '_', s)
        s = re.sub(r'_+', '_', s).strip('_')
        s = s or fallback
        if s and s[0].isdigit():
            s = f'_{s}'
        return s

    def _on_window_prop(self, name, value):
        if self._building:
            return
        if name == 'Title':
            self._window_title = str(value)
            if callable(self._window_title_changed):
                self._window_title_changed(self._window_title)
        elif name == 'Function Name':
            self._window_name = self._sanitize_identifier(str(value), fallback='main_window')
            sender = self.sender()
            if isinstance(sender, QLineEdit) and sender.text() != self._window_name:
                sender.blockSignals(True)
                sender.setText(self._window_name)
                sender.blockSignals(False)
            self.title_label.setText(f'Window Properties ({self._window_name})')
            if callable(self._window_name_changed):
                self._window_name_changed(self._window_name)
        elif name == 'Cols':
            self._window_cols = int(value)
        elif name == 'Rows':
            self._window_rows = int(value)
        if name in ('Cols', 'Rows'):
            self._emit_window_props_changed()
        else:
            self.properties_changed.emit()

    def _on_var_changed(self, text):
        if self._building or not self.container:
            return
        cleaned = self._sanitize_identifier(str(text), fallback='widget')
        sender = self.sender()
        if isinstance(sender, QLineEdit) and sender.text() != cleaned:
            sender.blockSignals(True)
            sender.setText(cleaned)
            sender.blockSignals(False)
        self.container.model.var_name = cleaned
        # Refresh fallback labels that display var_name.
        self._recreate_widget()
        self.properties_changed.emit()

    def _recreate_widget(self):
        if not self.container:
            return
        m = self.container.model
        try:
            new_w = self.widget_factory.make_widget(m.widget_type, m.properties)
            self.container.replace_inner_widget(new_w)
        except Exception as e:
            print(f'Error recreating widget: {e}')

    def _group_style(self):
        return (
            'QGroupBox { color: #888; border: 1px solid #3a3a3a; border-radius: 3px;'
            ' margin-top: 8px; font-size: 10px; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }'
        )

    def _input_style(self):
        return 'background: #2d2d2d; border: 1px solid #3a3a3a; color: #c8c8c8; padding: 2px;'
