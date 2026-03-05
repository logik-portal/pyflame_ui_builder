"""Canvas design surface widget."""

from __future__ import annotations

import copy
import re

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from models.ui_models import PlacedWidget, WindowConfig
from ui.dialogs import AppMessageDialog


class CanvasWidget(QWidget):
    """The design surface. Children (WidgetContainers) are placed absolutely."""

    widget_moved = Signal(object)   # emits WidgetContainer
    widget_selected = Signal(object)   # emits WidgetContainer or None
    grid_changed = Signal(object)   # emits updated WindowConfig
    content_changed = Signal()         # add/remove widgets

    _MENU_STYLE = (
        'QMenu { background: #2d2d2d; color: #c8c8c8;'
        '        border: 1px solid #555; padding: 2px; }'
        'QMenu::item { padding: 4px 20px 4px 12px; }'
        'QMenu::item:selected { background: #0078d7; color: white; }'
        'QMenu::item:disabled { color: #555; }'
        'QMenu::separator { height: 1px; background: #444; margin: 3px 6px; }'
    )

    def __init__(
        self,
        config: WindowConfig,
        widget_specs: dict,
        widget_container_cls,
        chrome_title_h: int,
        chrome_msg_h: int,
        chrome_side_w: int,
        cell_gap: int,
    ):
        super().__init__()
        self.config = config
        self.widget_specs = widget_specs
        self.widget_container_cls = widget_container_cls
        self.chrome_title_h = chrome_title_h
        self.chrome_msg_h = chrome_msg_h
        self.chrome_side_w = chrome_side_w
        self.cell_gap = cell_gap

        self.zoom_factor = 1.0
        self.grid_visible = False
        self.preview_mode = False
        self.window_title_override = None
        # Per-window margins: [left, top, right, bottom]
        self.window_margins = [15, 15, 15, 15]
        self.containers = []
        self.selected_container = None
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        sz = self.canvas_size()
        self.setMinimumSize(sz)
        self.resize(sz)

    def canvas_size(self):
        ml, mt, mr, mb = self.window_margins
        base_w = self.chrome_side_w + ml + self.config.grid_columns * self.config.column_width + mr
        base_h = self.chrome_title_h + mt + self.config.grid_rows * self.config.row_height + mb + self.chrome_msg_h
        return QSize(int(base_w * self.zoom_factor), int(base_h * self.zoom_factor))

    def sizeHint(self):
        return self.canvas_size()

    def grid_origin(self):
        ml, mt, _mr, _mb = self.window_margins
        return QPoint(int((self.chrome_side_w + ml) * self.zoom_factor), int((self.chrome_title_h + mt) * self.zoom_factor))

    def cell_rect(self, row, col, rowspan=1, colspan=1):
        ml, mt, _mr, _mb = self.window_margins
        ox = int((self.chrome_side_w + ml) * self.zoom_factor)
        oy = int((self.chrome_title_h + mt) * self.zoom_factor)
        cw = int(self.config.column_width * self.zoom_factor)
        rh = int(self.config.row_height * self.zoom_factor)
        gap = max(1, int(self.cell_gap * self.zoom_factor))
        x = ox + col * cw + gap // 2
        y = oy + row * rh + gap // 2
        w = max(1, colspan * cw - gap)
        h = max(1, rowspan * rh - gap)
        return QRect(x, y, w, h)

    def _pos_to_cell(self, pos):
        ml, mt, _mr, _mb = self.window_margins
        ox = int((self.chrome_side_w + ml) * self.zoom_factor)
        oy = int((self.chrome_title_h + mt) * self.zoom_factor)
        cw = max(1, int(self.config.column_width * self.zoom_factor))
        rh = max(1, int(self.config.row_height * self.zoom_factor))
        col = max(0, min((pos.x() - ox) // cw, self.config.grid_columns - 1))
        row = max(0, min((pos.y() - oy) // rh, self.config.grid_rows - 1))
        return int(row), int(col)

    @staticmethod
    def _cells_overlap(r1, c1, rs1, cs1, r2, c2, rs2, cs2) -> bool:
        return not (r1 + rs1 <= r2 or r2 + rs2 <= r1 or c1 + cs1 <= c2 or c2 + cs2 <= c1)

    def _has_overlap(self, row, col, row_span, col_span, ignore_container=None) -> bool:
        for c in self.containers:
            if c is ignore_container:
                continue
            m = c.model
            if self._cells_overlap(row, col, row_span, col_span, m.row, m.col, m.row_span, m.col_span):
                return True
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        cs = self.canvas_size()
        p.fillRect(self.rect(), QColor('#232323'))

        side_w = int(self.chrome_side_w * self.zoom_factor)
        title_h = int(self.chrome_title_h * self.zoom_factor)
        msg_h = int(self.chrome_msg_h * self.zoom_factor)
        p.fillRect(0, 0, side_w, cs.height(), QColor(0, 110, 175))

        title_rect = QRect(side_w, 0, cs.width() - side_w, title_h)
        p.fillRect(title_rect, QColor('#222222'))
        p.setPen(QColor('#b0b0b0'))
        p.setFont(QFont('Montserrat', 22, QFont.Light))

        if self.window_title_override:
            # For non-root windows, show explicit window title exactly as configured.
            name_text = str(self.window_title_override)
            version_text = ''
        else:
            name_text = self.config.script_name
            version_text = (self.config.script_version or '').strip()
            if version_text and not version_text.lower().startswith('v'):
                version_text = f'v{version_text}'

        text_rect = title_rect.adjusted(16, 0, -8, 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, name_text)

        if version_text:
            name_width = p.fontMetrics().horizontalAdvance(name_text)
            p.setFont(QFont('Montserrat', 16, QFont.Light))
            version_x = text_rect.x() + name_width + 10
            version_rect = QRect(version_x, text_rect.y() + 2, text_rect.width(), text_rect.height())
            p.drawText(version_rect, Qt.AlignVCenter | Qt.AlignLeft, version_text)

        _ml, mt, _mr, mb = self.window_margins
        msg_y = title_h + int((mt + self.config.grid_rows * self.config.row_height + mb) * self.zoom_factor)
        p.fillRect(QRect(side_w, msg_y, cs.width() - side_w, msg_h), QColor('#222222'))

        content_h = msg_y - title_h
        if content_h > 0:
            p.fillRect(QRect(side_w, title_h, cs.width() - side_w, content_h), QColor('#2b2b2b'))

        if self.grid_visible:
            for row in range(self.config.grid_rows):
                for col in range(self.config.grid_columns):
                    r = self.cell_rect(row, col)
                    p.fillRect(r, QColor('#2d2d2d'))
                    p.setPen(QPen(QColor('#3a3a3a'), 1))
                    p.drawRect(r.adjusted(0, 0, -1, -1))

        p.end()

    def dragEnterEvent(self, event):
        if self.preview_mode:
            event.ignore()
            return
        if event.mimeData().hasFormat('application/x-pyflame-widget'):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self.preview_mode:
            event.ignore()
            return
        if event.mimeData().hasFormat('application/x-pyflame-widget'):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.preview_mode:
            event.ignore()
            return
        widget_type = event.mimeData().data('application/x-pyflame-widget').data().decode()
        row, col = self._pos_to_cell(event.position().toPoint())
        self._add_widget(widget_type, row, col)
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            if self.preview_mode:
                event.ignore()
                return
            row, col = self._pos_to_cell(event.position().toPoint())
            self._show_grid_menu(event.globalPosition().toPoint(), row, col)
        else:
            self.select_widget(None)

    def select_widget(self, container):
        if self.selected_container is container:
            return
        if self.selected_container is not None:
            self.selected_container.set_selected(False)
        self.selected_container = container
        if container is not None:
            container.set_selected(True)
        self.setFocus()
        self.widget_selected.emit(container)

    def _add_widget(self, widget_type, row, col):
        if self.preview_mode:
            return
        specs = self.widget_specs.get(widget_type)
        if not specs:
            return
        if self._has_overlap(row, col, 1, 1):
            return
        default_props = {p.name: p.default for p in specs['props']}
        model = PlacedWidget(widget_type=widget_type, row=row, col=col, properties=default_props)
        model.var_name = self._auto_var_name(widget_type)
        try:
            widget = self.widget_container_cls.make_widget(widget_type, default_props)
        except Exception as e:
            print(f'Error creating widget: {e}')
            return
        container = self.widget_container_cls(widget, model, self)
        container.setGeometry(self.cell_rect(row, col))
        if hasattr(container, 'set_preview_mode'):
            container.set_preview_mode(self.preview_mode)
        container.show()
        self.containers.append(container)
        self.select_widget(container)
        self.content_changed.emit()

    def _auto_var_name(self, widget_type):
        raw = widget_type.replace('PyFlame', '')
        short = re.sub(r'(?<!^)(?=[A-Z])', '_', raw).lower()
        count = sum(1 for c in self.containers if c.model.widget_type == widget_type) + 1
        return f'{short}_{count}'

    def remove_selected(self):
        if self.preview_mode:
            return
        if not self.selected_container:
            return
        c = self.selected_container
        self.selected_container = None
        self.containers.remove(c)
        c.deleteLater()
        self.widget_selected.emit(None)
        self.content_changed.emit()

    def duplicate_selected(self):
        if self.preview_mode:
            return
        if not self.selected_container:
            return
        src = self.selected_container
        sm = src.model
        candidate_positions = [(sm.row, sm.col + 1), (sm.row + 1, sm.col), (sm.row + 1, sm.col + 1), (sm.row, sm.col - 1), (sm.row - 1, sm.col)]
        for r in range(self.config.grid_rows):
            for c in range(self.config.grid_columns):
                candidate_positions.append((r, c))

        target = None
        for row, col in candidate_positions:
            if row < 0 or col < 0:
                continue
            if row + sm.row_span > self.config.grid_rows:
                continue
            if col + sm.col_span > self.config.grid_columns:
                continue
            if self._has_overlap(row, col, sm.row_span, sm.col_span):
                continue
            target = (row, col)
            break
        if target is None:
            return

        new_props = copy.deepcopy(sm.properties)
        model = PlacedWidget(widget_type=sm.widget_type, row=target[0], col=target[1], row_span=sm.row_span, col_span=sm.col_span, properties=new_props)
        model.var_name = self._auto_var_name(sm.widget_type)

        try:
            widget = self.widget_container_cls.make_widget(sm.widget_type, new_props)
        except Exception as e:
            print(f'Error duplicating widget: {e}')
            return

        container = self.widget_container_cls(widget, model, self)
        container.setGeometry(self.cell_rect(model.row, model.col, model.row_span, model.col_span))
        if hasattr(container, 'set_preview_mode'):
            container.set_preview_mode(self.preview_mode)
        container.show()
        self.containers.append(container)
        self.select_widget(container)
        self.content_changed.emit()

    def nudge_selected(self, d_row: int, d_col: int):
        if self.preview_mode:
            return
        if not self.selected_container:
            return
        c = self.selected_container
        m = c.model
        new_row = m.row + d_row
        new_col = m.col + d_col
        if new_row < 0 or new_col < 0:
            return
        if new_row + m.row_span > self.config.grid_rows:
            return
        if new_col + m.col_span > self.config.grid_columns:
            return
        if self._has_overlap(new_row, new_col, m.row_span, m.col_span, ignore_container=c):
            return
        m.row = new_row
        m.col = new_col
        c.setGeometry(self.cell_rect(m.row, m.col, m.row_span, m.col_span))
        self.widget_moved.emit(c)

    def _show_grid_menu(self, global_pos, row, col):
        menu = QMenu(self)
        menu.setStyleSheet(self._MENU_STYLE)

        mw = self.window()
        if hasattr(mw, 'action_undo') and hasattr(mw, 'action_redo'):
            menu.addAction('Undo', mw.action_undo)
            menu.addAction('Redo', mw.action_redo)
            menu.addSeparator()

        menu.addAction('Add Row Above', lambda: self._insert_row(row, above=True))
        menu.addAction('Add Row Below', lambda: self._insert_row(row, above=False))
        del_row = menu.addAction('Delete Row', lambda: self._delete_row(row))
        del_row.setEnabled(self.config.grid_rows > 1)
        menu.addSeparator()
        menu.addAction('Add Column Left', lambda: self._insert_col(col, left=True))
        menu.addAction('Add Column Right', lambda: self._insert_col(col, left=False))
        del_col = menu.addAction('Delete Column', lambda: self._delete_col(col))
        del_col.setEnabled(self.config.grid_columns > 1)
        menu.exec(global_pos)

    def _insert_row(self, at_row, above):
        insert_at = at_row if above else at_row + 1
        for c in self.containers:
            if c.model.row >= insert_at:
                c.model.row += 1
        self.config.grid_rows += 1
        self.update_config(self.config)
        self.grid_changed.emit(self.config)

    def _insert_col(self, at_col, left):
        insert_at = at_col if left else at_col + 1
        for c in self.containers:
            if c.model.col >= insert_at:
                c.model.col += 1
        self.config.grid_columns += 1
        self.update_config(self.config)
        self.grid_changed.emit(self.config)

    def _delete_row(self, del_row, *, confirm: bool = True):
        if self.config.grid_rows <= 1:
            return

        affected = [c for c in self.containers if c.model.row == del_row]
        if confirm and affected:
            ok = AppMessageDialog.confirm(
                self.window(),
                'Delete Row?',
                f'Row {del_row + 1} contains {len(affected)} widget(s).',
                informative_text='Delete the row and its widgets?',
                confirm_label='Delete',
                danger=True,
            )
            if not ok:
                return

        for c in list(self.containers):
            if c.model.row == del_row:
                if c is self.selected_container:
                    self.selected_container = None
                self.containers.remove(c)
                c.deleteLater()
            elif c.model.row > del_row:
                c.model.row -= 1
        self.config.grid_rows -= 1
        self.update_config(self.config)
        self.widget_selected.emit(None)
        self.grid_changed.emit(self.config)

    def _delete_col(self, del_col, *, confirm: bool = True):
        if self.config.grid_columns <= 1:
            return

        affected = [c for c in self.containers if c.model.col == del_col]
        if confirm and affected:
            ok = AppMessageDialog.confirm(
                self.window(),
                'Delete Column?',
                f'Column {del_col + 1} contains {len(affected)} widget(s).',
                informative_text='Delete the column and its widgets?',
                confirm_label='Delete',
                danger=True,
            )
            if not ok:
                return

        for c in list(self.containers):
            if c.model.col == del_col:
                if c is self.selected_container:
                    self.selected_container = None
                self.containers.remove(c)
                c.deleteLater()
            elif c.model.col > del_col:
                c.model.col -= 1
        self.config.grid_columns -= 1
        self.update_config(self.config)
        self.widget_selected.emit(None)
        self.grid_changed.emit(self.config)

    def update_config(self, config: WindowConfig):
        self.config = config
        sz = self.canvas_size()
        self.setMinimumSize(sz)
        self.resize(sz)
        self.update()
        for c in self.containers:
            m = c.model
            m.col = min(m.col, config.grid_columns - 1)
            m.row = min(m.row, config.grid_rows - 1)
            m.col_span = min(m.col_span, config.grid_columns - m.col)
            m.row_span = min(m.row_span, config.grid_rows - m.row)
            fixed = self.widget_specs.get(m.widget_type, {}).get('fixed_axes', set())
            if {'h', 'w'} <= set(fixed):
                m.row_span = 1
                m.col_span = 1
            c.setGeometry(self.cell_rect(m.row, m.col, m.row_span, m.col_span))

    def set_window_title_override(self, title: str | None):
        self.window_title_override = title if title else None
        self.update()

    def set_window_margins(self, margins):
        vals = margins
        if isinstance(vals, int):
            vals = [vals, vals, vals, vals]
        elif isinstance(vals, (list, tuple)):
            vals = [int(x) for x in vals]
            if len(vals) == 1:
                vals = [vals[0], vals[0], vals[0], vals[0]]
            elif len(vals) != 4:
                vals = [15, 15, 15, 15]
        else:
            vals = [15, 15, 15, 15]
        self.window_margins = [max(0, int(v)) for v in vals[:4]]
        sz = self.canvas_size()
        self.setMinimumSize(sz)
        self.resize(sz)
        self.update()

    def set_preview_mode(self, enabled: bool):
        """Enable interactive widget preview and disable edit interactions."""
        self.preview_mode = bool(enabled)
        if self.preview_mode:
            self.select_widget(None)
        for c in self.containers:
            if hasattr(c, 'set_preview_mode'):
                c.set_preview_mode(self.preview_mode)

    def set_zoom(self, zoom: float):
        self.zoom_factor = max(0.5, min(2.0, float(zoom)))
        self.update_config(self.config)

    def zoom_in(self):
        self.set_zoom(self.zoom_factor + 0.1)

    def zoom_out(self):
        self.set_zoom(self.zoom_factor - 0.1)

    def zoom_reset(self):
        self.set_zoom(1.0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.remove_selected()
        elif event.key() == Qt.Key_Escape:
            self.select_widget(None)
        elif event.key() == Qt.Key_Left:
            self.nudge_selected(0, -1)
        elif event.key() == Qt.Key_Right:
            self.nudge_selected(0, 1)
        elif event.key() == Qt.Key_Up:
            self.nudge_selected(-1, 0)
        elif event.key() == Qt.Key_Down:
            self.nudge_selected(1, 0)
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
