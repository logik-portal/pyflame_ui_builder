"""Workflow orchestration helpers for import/export flows.

These helpers keep UI handlers thin by moving deterministic transformation logic
out of the main window class.
"""

from __future__ import annotations

import os
from typing import Callable

from models.ui_models import PlacedWidget, ScriptWindow


def build_imported_windows(
    windows_meta: list[dict],
    *,
    widget_specs: dict,
    normalize_properties: Callable[[str, dict], dict],
) -> tuple[list[ScriptWindow], list[tuple[str, str, str]]]:
    """Convert analyzer metadata into ScriptWindow models.

    Returns:
    - imported_windows: structured windows for the editor
    - skipped_items: tuples of (window_name, var_name, reason)
    """
    imported_windows: list[ScriptWindow] = []
    skipped_items: list[tuple[str, str, str]] = []

    for w in windows_meta:
        for sk in (w.get('skipped', []) or []):
            skipped_items.append(
                (
                    w.get('window_name', 'unknown'),
                    sk.get('var_name', '?'),
                    sk.get('reason', 'unknown'),
                )
            )

        imported_widgets: list[PlacedWidget] = []
        for wd in w.get('widgets', []) or []:
            wt = wd.get('widget_type', '')
            if wt not in widget_specs:
                skipped_items.append((w.get('window_name', 'unknown'), wd.get('var_name', '?'), f'unsupported widget type: {wt}'))
                continue

            normalized_props = normalize_properties(wt, wd.get('properties', {}) or {})
            imported_widgets.append(
                PlacedWidget(
                    widget_type=wt,
                    row=int(wd.get('row', 0) or 0),
                    col=int(wd.get('col', 0) or 0),
                    row_span=max(1, int(wd.get('row_span', 1) or 1)),
                    col_span=max(1, int(wd.get('col_span', 1) or 1)),
                    properties=normalized_props,
                    var_name=wd.get('var_name', '') or '',
                )
            )

        imported_windows.append(
            ScriptWindow(
                function_name=w.get('window_name', 'main_window') or 'main_window',
                window_title=w.get('window_title', None),
                grid_columns=int(w.get('grid_columns', 4) or 4),
                grid_rows=int(w.get('grid_rows', 3) or 3),
                parent_window=w.get('parent_window', None),
                window_margins=w.get('window_margins', 15),
                widgets=imported_widgets,
            )
        )

    return imported_windows, skipped_items


def summarize_import_result(imported_windows: list[ScriptWindow], skipped_items: list[tuple[str, str, str]], target_class: str) -> str:
    """Build user-facing import summary text."""
    imported_widget_total = sum(len(w.widgets) for w in imported_windows)
    skipped_total = len(skipped_items)

    details = ''
    if skipped_total:
        preview = '\n'.join(f'- {win}:{var} ({reason})' for win, var, reason in skipped_items[:8])
        more = '' if skipped_total <= 8 else f'\n...and {skipped_total - 8} more.'
        details = f'\n\nSkipped items:\n{preview}{more}'

    return (
        f'Imported {len(imported_windows)} window tabs from class "{target_class}".\n'
        f'Imported {imported_widget_total} widgets using deterministic patterns.\n'
        f'Skipped {skipped_total} items.{details}'
    )


def suggest_script_name_from_path(path: str) -> str:
    """Map script filename to default display script name."""
    return os.path.splitext(os.path.basename(path))[0].replace('_', ' ').title()
