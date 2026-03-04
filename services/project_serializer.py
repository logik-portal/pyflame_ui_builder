"""Project save/load serialization helpers.

This module is intentionally side-effect free apart from file I/O.
It owns conversion between in-memory UI models and `.pfb` JSON payloads.

Compatibility policy:
- New saves use schema_version=2 (multi-window format).
- Loads must continue to accept schema_version=1 (single-window legacy format).
- Missing fields must always fall back to safe defaults.
"""

from __future__ import annotations

import json

from models.ui_models import PlacedWidget, ScriptWindow, WindowConfig


class ProjectSerializer:
    """Serialize/deserialize PyFlame UI Builder project files."""

    @staticmethod
    def _widget_to_dict(w: PlacedWidget) -> dict:
        """Convert a widget model to a JSON-serializable dict."""
        return {
            'widget_type': w.widget_type,
            'row': w.row,
            'col': w.col,
            'row_span': w.row_span,
            'col_span': w.col_span,
            'properties': w.properties,
            'var_name': w.var_name,
        }

    @staticmethod
    def _widget_from_dict(wd: dict) -> PlacedWidget:
        """Create a widget model from a persisted dict with safe defaults."""
        return PlacedWidget(
            widget_type=wd.get('widget_type', ''),
            row=wd.get('row', 0),
            col=wd.get('col', 0),
            row_span=wd.get('row_span', 1),
            col_span=wd.get('col_span', 1),
            properties=wd.get('properties', {}),
            var_name=wd.get('var_name', ''),
        )

    @staticmethod
    def save(path: str, config: WindowConfig, windows: list[ScriptWindow], active_window: int = 0) -> None:
        """Persist current project state to `.pfb` JSON.

        Notes:
        - `active_window` is clamped to a valid index.
        - schema_version=2 stores explicit `windows` array.
        """
        active = max(0, min(int(active_window), max(0, len(windows) - 1))) if windows else 0
        data = {
            'schema_version': 2,
            'config': {
                'script_name': config.script_name,
                'written_by': config.written_by,
                'script_version': config.script_version,
                'flame_version': config.flame_version,
                'hook_types': config.hook_types,
                'license_type': config.license_type,
                'grid_columns': config.grid_columns,
                'grid_rows': config.grid_rows,
                'column_width': config.column_width,
                'row_height': config.row_height,
            },
            'windows': [
                {
                    'function_name': w.function_name,
                    'grid_columns': w.grid_columns,
                    'grid_rows': w.grid_rows,
                    'window_title': getattr(w, 'window_title', None),
                    'parent_window': getattr(w, 'parent_window', None),
                    'window_margins': getattr(w, 'window_margins', 15),
                    'widgets': [ProjectSerializer._widget_to_dict(x) for x in w.widgets],
                }
                for w in windows
            ],
            'active_window': active,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load(path: str) -> tuple[WindowConfig, list[ScriptWindow], int]:
        """Load project from `.pfb`, applying backward-compatible defaults."""
        with open(path) as f:
            data = json.load(f)
        cfg = data.get('config', {})

        # Backward compat: old files stored hook_type as a single string.
        raw_hooks = cfg.get('hook_types', cfg.get('hook_type', 'get_batch_custom_ui_actions'))
        if isinstance(raw_hooks, str):
            raw_hooks = [raw_hooks]

        config = WindowConfig(
            script_name=cfg.get('script_name', 'My Script'),
            written_by=cfg.get('written_by', 'Your Name'),
            script_version=cfg.get('script_version', 'v1.0.0'),
            flame_version=cfg.get('flame_version', '2025.1'),
            hook_types=raw_hooks,
            license_type=cfg.get('license_type', 'GPL-3.0'),
            grid_columns=cfg.get('grid_columns', 4),
            grid_rows=cfg.get('grid_rows', 3),
            column_width=cfg.get('column_width', 150),
            row_height=cfg.get('row_height', 28),
        )

        schema_version = int(data.get('schema_version', 1) or 1)
        windows: list[ScriptWindow] = []

        if schema_version >= 2 and isinstance(data.get('windows'), list):
            # Modern multi-window format.
            for wd in data.get('windows', []):
                if not isinstance(wd, dict):
                    continue
                name = wd.get('function_name', '').strip() or f'main_window_{len(windows)+1}'
                grid_columns = int(wd.get('grid_columns', cfg.get('grid_columns', 4) or 4))
                grid_rows = int(wd.get('grid_rows', cfg.get('grid_rows', 3) or 3))
                raw_margins = wd.get('window_margins', 15)
                if isinstance(raw_margins, list):
                    window_margins = [max(0, int(x)) for x in raw_margins[:4]]
                    if len(window_margins) == 1:
                        window_margins = window_margins[0]
                else:
                    try:
                        window_margins = max(0, int(raw_margins))
                    except Exception:
                        window_margins = 15

                widgets = [ProjectSerializer._widget_from_dict(x) for x in wd.get('widgets', []) if isinstance(x, dict)]
                windows.append(
                    ScriptWindow(
                        function_name=name,
                        window_title=wd.get('window_title', None),
                        grid_columns=max(1, grid_columns),
                        grid_rows=max(1, grid_rows),
                        parent_window=wd.get('parent_window', None),
                        window_margins=window_margins,
                        widgets=widgets,
                    )
                )
        else:
            # Legacy schema v1: single-window projects with top-level widgets.
            widgets = [ProjectSerializer._widget_from_dict(x) for x in data.get('widgets', []) if isinstance(x, dict)]
            windows = [
                ScriptWindow(
                    function_name='main_window',
                    grid_columns=max(1, int(cfg.get('grid_columns', 4) or 4)),
                    grid_rows=max(1, int(cfg.get('grid_rows', 3) or 3)),
                    widgets=widgets,
                )
            ]

        # Guarantee at least one usable window in memory.
        if not windows:
            windows = [
                ScriptWindow(
                    function_name='main_window',
                    grid_columns=max(1, int(cfg.get('grid_columns', 4) or 4)),
                    grid_rows=max(1, int(cfg.get('grid_rows', 3) or 3)),
                    widgets=[],
                )
            ]

        active_window = int(data.get('active_window', 0) or 0)
        active_window = max(0, min(active_window, len(windows) - 1))

        return config, windows, active_window
