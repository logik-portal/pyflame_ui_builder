"""Core UI/project data models."""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field

PropDef = namedtuple('PropDef', ['name', 'kind', 'default', 'options'])


@dataclass
class PlacedWidget:
    widget_type: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    properties: dict = field(default_factory=dict)
    var_name: str = ''


@dataclass
class WindowConfig:
    script_name: str = 'My Script'
    written_by: str = 'Your Name'
    script_version: str = 'v1.0.0'
    flame_version: str = '2025.1'
    hook_types: list = field(default_factory=lambda: ['get_batch_custom_ui_actions'])
    license_type: str = 'None'
    grid_columns: int = 4
    grid_rows: int = 3
    column_width: int = 150
    row_height: int = 28


@dataclass
class ScriptWindow:
    function_name: str = 'main_window'
    # Optional explicit PyFlameWindow title. None means use SCRIPT_NAME.
    window_title: str | None = None
    grid_columns: int = 4
    grid_rows: int = 3
    # Optional parent window by function_name. None means top-level window.
    parent_window: str | None = None
    # Accept either a single int or 4-value margins [left, top, right, bottom].
    window_margins: int | list[int] = 15
    widgets: list[PlacedWidget] = field(default_factory=list)
