"""Code generation service for PyFlame UI Builder."""

from __future__ import annotations

import datetime
import os

from models.ui_models import PlacedWidget, ScriptWindow, WindowConfig
from services.utils import to_snake


class CodeGenerator:
    """Generate Flame script source from project config and widget models."""

    # Injected dependencies from app module to avoid behavior drift during refactor.
    TEMPLATE_DIR = ''
    LICENSE_DATA = {}
    WIDGET_SPECS = {}
    HOOK_TO_TYPE = {}
    HOOK_SCOPE = {}
    SCOPE_DEFS = {}
    ENUM_PROP_MAP = {}

    # Widget type → comment section label
    _SECTION_LABELS = {
        'PyFlameLabel': 'Labels',
        'PyFlameEntry': 'Entries',
        'PyFlameEntryBrowser': 'Entries',
        'PyFlameButton': 'Buttons',
        'PyFlamePushButton': 'Buttons',
        'PyFlameMenu': 'Menus',
        'PyFlameColorMenu': 'Menus',
        'PyFlameTokenMenu': 'Menus',
        'PyFlameSlider': 'Sliders',
        'PyFlameListWidget': 'List Widgets',
        'PyFlameTreeWidget': 'Tree Widgets',
        'PyFlameTable': 'Tables',
        'PyFlameTextEdit': 'Text Edits',
        'PyFlameTextBrowser': 'Text Browsers',
        'PyFlameProgressBarWidget': 'Progress Bars',
        'PyFlameHorizontalLine': 'Lines',
        'PyFlameVerticalLine': 'Lines',
    }

    @classmethod
    def configure(
        cls,
        *,
        template_dir: str,
        license_data: dict,
        widget_specs: dict,
        hook_to_type: dict,
        hook_scope: dict,
        scope_defs: dict,
        enum_prop_map: dict,
    ) -> None:
        """Inject runtime configuration from the app layer.

        Keeping this data injected (instead of imported globally) prevents
        circular imports and makes service-level testing easier.
        """
        cls.TEMPLATE_DIR = template_dir
        cls.LICENSE_DATA = license_data
        cls.WIDGET_SPECS = widget_specs
        cls.HOOK_TO_TYPE = hook_to_type
        cls.HOOK_SCOPE = hook_scope
        cls.SCOPE_DEFS = scope_defs
        cls.ENUM_PROP_MAP = enum_prop_map

    @classmethod
    def generate(
        cls,
        config: WindowConfig,
        widgets: list[PlacedWidget],
        tab_order: list[str] | None = None,
        windows: list[ScriptWindow] | None = None,
    ) -> str:
        """Render a complete exportable Flame script from current UI state.

        Parameters:
        - `config`: top-level script metadata and defaults.
        - `widgets`: active-window widgets (legacy arg; kept for compatibility).
        - `tab_order`: optional ordered entry variable names for first window.
        - `windows`: optional multi-window model list (preferred).
        """
        today = datetime.date.today().strftime('%m.%d.%y')
        year = str(datetime.date.today().year)
        snake = to_snake(config.script_name)
        classname = ''.join(w.title() for w in config.script_name.split())
        lic = cls.LICENSE_DATA.get(config.license_type, cls.LICENSE_DATA['GPL-3.0'])

        # Read template
        tmpl_path = os.path.join(cls.TEMPLATE_DIR, 'script_template.py')
        with open(tmpl_path, 'r') as _f:
            tmpl = _f.read()

        if lic['header']:
            lic_header = '\n'.join(lic['header']) + '\n\n'
        else:
            lic_header = '\n'

        resolved_windows = windows or [
            ScriptWindow(
                function_name='main_window',
                grid_columns=config.grid_columns,
                grid_rows=config.grid_rows,
                widgets=widgets,
            )
        ]

        flame_menus = '\n'.join(cls._menu_hook(config, classname))

        window_methods_block = '\n\n'.join(
            cls._build_window_method(
                w.function_name,
                w.widgets,
                w.grid_columns,
                w.grid_rows,
                getattr(w, 'window_title', None),
                getattr(w, 'parent_window', None),
                getattr(w, 'window_margins', 15),
                tab_order if i == 0 else None,
            )
            for i, w in enumerate(resolved_windows)
        )

        subs = {
            '<<<SCRIPT_NAME>>>': config.script_name,
            '<<<WRITTEN_BY>>>': config.written_by,
            '<<<YEAR>>>': year,
            '<<<LICENSE_HEADER>>>': lic_header,
            '<<<SCRIPT_VERSION>>>': config.script_version,
            '<<<FLAME_VERSION>>>': config.flame_version,
            '<<<DATE>>>': today,
            '<<<LICENSE_DOCSTRING>>>': lic['docstring'],
            '<<<SCRIPT_TYPE>>>': cls._script_type_label(config.hook_types),
            '<<<MENU_PATH>>>': cls._menu_path(config),
            '<<<SNAKE_NAME>>>': snake,
            '<<<CLASS_NAME>>>': classname,
            '<<<GRID_COLUMNS>>>': str(config.grid_columns),
            '<<<GRID_ROWS>>>': str(config.grid_rows),
            '<<<FLAME_MENUS>>>': flame_menus,
        }
        for marker, value in subs.items():
            tmpl = tmpl.replace(marker, value)

        # Replace template startup call and method block with generated methods.
        # This keeps exported scripts deterministic and easy to diff.
        startup_method = cls._method_name(resolved_windows[0].function_name or 'main_window')
        tmpl = tmpl.replace('        # Open main window\n        self.main_window()', f'        # Open main window\n        self.{startup_method}()')

        methods_start = tmpl.find('    def main_window(self) -> None:')
        menus_marker = '# ==============================================================================\n# [Flame Menus]'
        methods_end = tmpl.find(menus_marker)
        if methods_start != -1 and methods_end != -1 and methods_start < methods_end:
            tmpl = tmpl[:methods_start] + window_methods_block + '\n\n' + tmpl[methods_end:]

        return tmpl

    @classmethod
    def _build_widget_declarations(cls, widgets: list[PlacedWidget]) -> str:
        """Generate widget constructor blocks grouped by widget family."""
        if not widgets:
            return ''
        type_order = list(cls.WIDGET_SPECS.keys())
        grouped: dict[str, list[PlacedWidget]] = {}
        for w in widgets:
            grouped.setdefault(w.widget_type, []).append(w)
        sorted_types = sorted(grouped.keys(), key=lambda t: type_order.index(t) if t in type_order else 99)
        lines = []
        used_sections: set[str] = set()
        for wtype in sorted_types:
            section = cls._SECTION_LABELS.get(wtype, 'Widgets')
            if section not in used_sections:
                lines.append(f'        # {section}')
                used_sections.add(section)
            for w in grouped[wtype]:
                var = w.var_name or f'{wtype.replace("PyFlame", "").lower()}_1'
                lines.append(f'        self.{var} = {wtype}(')
                kwargs = cls._widget_kwargs(wtype, w.properties)
                for k, v in kwargs.items():
                    lines.append(f'            {k}={v},')
                if wtype == 'PyFlameButton' and 'connect' not in kwargs:
                    callback_name = f'on_{var}_click'
                    lines.append(f'            # connect={callback_name},  # TODO: Uncomment and implement callback')
                if wtype == 'PyFlameTokenMenu' and 'token_dest' not in kwargs:
                    lines.append("            # token_dest=self.entry_1,  # TODO: Connect token_dest to an Entry widget")
                lines.append('            )')
            lines.append('')
        return '\n'.join(lines) + '\n'

    @staticmethod
    def _method_name(window_name: str) -> str:
        base = (window_name or 'main_window').strip()
        return base if base.startswith('create_') else f'create_{base}'

    @staticmethod
    def _window_attr_name(window_name: str) -> str:
        return (window_name or 'main_window').strip()

    @classmethod
    def _build_window_method(
        cls,
        function_name: str,
        widgets: list[PlacedWidget],
        grid_columns: int,
        grid_rows: int,
        window_title: str | None,
        parent_window: str | None,
        window_margins: int | list[int],
        tab_order: list[str] | None = None,
    ) -> str:
        """Build one `create_*` method source block for a single script window."""
        window_name = (function_name or 'main_window').strip()
        fn = cls._method_name(window_name)
        window_attr = cls._window_attr_name(window_name)
        widget_decl = cls._build_widget_declarations(widgets)

        if tab_order:
            tab_lines = [
                '        # Set Entry Tab-key Order',
                f'        self.{window_attr}.tab_order = [',
            ]
            for var in tab_order:
                tab_lines.append(f'            self.{var},')
            tab_lines += ['            ]', '']
            tab_block = '\n'.join(tab_lines) + '\n'
        else:
            tab_block = ''

        layout_lines = []
        for w in sorted(widgets, key=lambda x: (x.row, x.col)):
            var = w.var_name or 'widget'
            if w.row_span > 1 or w.col_span > 1:
                layout_lines.append(
                    f'        self.{window_attr}.grid_layout.addWidget('
                    f'self.{var}, {w.row}, {w.col}, {w.row_span}, {w.col_span})'
                )
            else:
                layout_lines.append(
                    f'        self.{window_attr}.grid_layout.addWidget('
                    f'self.{var}, {w.row}, {w.col})'
                )
        layout_block = '\n'.join(layout_lines) + '\n' if layout_lines else ''

        entry_widgets = [w for w in widgets if w.widget_type in ('PyFlameEntry', 'PyFlameEntryBrowser')]
        set_focus = ''
        first_focusable = None
        for w in entry_widgets:
            read_only = bool((w.properties or {}).get('read_only', False))
            if not read_only:
                first_focusable = w
                break
        if first_focusable:
            first_var = first_focusable.var_name or 'entry'
            set_focus = f'        self.{first_var}.set_focus()\n\n'

        if isinstance(window_margins, (list, tuple)):
            _m = [max(0, int(x)) for x in list(window_margins)[:4]]
            if len(_m) == 1:
                margins_repr = str(_m[0])
            elif len(_m) == 4:
                margins_repr = f'[{_m[0]}, {_m[1]}, {_m[2]}, {_m[3]}]'
            else:
                margins_repr = '15'
        else:
            try:
                margins_repr = str(max(0, int(window_margins)))
            except Exception:
                margins_repr = '15'

        title_expr = repr(str(window_title)) if window_title else "f'{SCRIPT_NAME} <small>{SCRIPT_VERSION}'"
        parent_expr = f'self.{parent_window}' if parent_window else 'None'

        return (
            f"    def {fn}(self) -> None:\n"
            f"        \"\"\"\n"
            f"        {fn}\n"
            f"        {'=' * len(fn)}\n\n"
            f"        Generated window for script.\n"
            f"        \"\"\"\n\n"
            f"        def do_something() -> None:\n"
            f"            self.{window_attr}.close()\n"
            f"            print('Do something...')\n\n"
            f"        def close_window() -> None:\n"
            f"            self.{window_attr}.close()\n\n"
            f"        # ------------------------------------------------------------------------------\n"
            f"        # [Start Window Build]\n"
            f"        # ------------------------------------------------------------------------------\n\n"
            f"        self.{window_attr} = PyFlameWindow(\n"
            f"            title={title_expr},\n"
            f"            parent={parent_expr},\n"
            f"            return_pressed=do_something,\n"
            f"            escape_pressed=close_window,\n"
            f"            grid_layout_columns={int(max(1, grid_columns))},\n"
            f"            grid_layout_rows={int(max(1, grid_rows))},\n"
            f"            window_margins={margins_repr},\n"
            f"            )\n\n"
            f"{widget_decl}{tab_block}"
            f"        # ------------------------------------------------------------------------------\n"
            f"        # [Widget Layout]\n"
            f"        # ------------------------------------------------------------------------------\n\n"
            f"{layout_block}\n"
            f"{set_focus}"
            f"        # ------------------------------------------------------------------------------\n"
            f"        # [End Window Build]\n"
            f"        # ------------------------------------------------------------------------------"
        )

    @staticmethod
    def _script_type_label(hook_types: list) -> str:
        types = [CodeGenerator.HOOK_TO_TYPE.get(h, h) for h in hook_types]
        return ', '.join(types) if types else 'Batch'

    @staticmethod
    def _menu_path(config: WindowConfig) -> str:
        name = config.script_name
        paths = []
        for hook in config.hook_types:
            if 'main_menu' in hook:
                paths.append(f'Flame Main Menu -> Logik -> {name}')
            elif 'batch' in hook:
                paths.append(f'Flame Batch -> Right-click -> {name}')
            elif 'media_panel' in hook:
                paths.append(f'Flame Media Panel -> Right-click -> {name}')
            elif 'media_hub' in hook:
                paths.append(f'Flame Media Hub -> Right-click -> {name}')
            elif 'timeline' in hook:
                paths.append(f'Flame Timeline -> Right-click -> {name}')
        return ('\n    '.join(paths)) if paths else name

    @staticmethod
    def _scope_stubs(hook_types: list) -> list:
        lines = []
        emitted = set()
        for hook in hook_types:
            scope_fn = CodeGenerator.HOOK_SCOPE.get(hook)
            if scope_fn is None or scope_fn in emitted:
                continue
            lines += CodeGenerator.SCOPE_DEFS[scope_fn]
            lines.append('')
            emitted.add(scope_fn)
        return lines

    @staticmethod
    def _menu_hook(config: WindowConfig, classname: str) -> list:
        name = config.script_name
        min_version = config.flame_version
        lines = []
        for hook in config.hook_types:
            if 'main_menu' in hook:
                lines += [
                    f'def {hook}():',
                    '',
                    '    return [',
                    '        {',
                    "            'name': 'Logik',",
                    "            'hierarchy': [],",
                    "            'actions': []",
                    '        },',
                    '        {',
                    f"            'name': '{name}',",
                    "            'hierarchy': ['Logik'],",
                    "            'order': 2,",
                    "            'actions': [",
                    '               {',
                    f"                    'name': '{name}',",
                    f"                    'execute': {classname},",
                    f"                    'minimumVersion': '{min_version}'",
                    '               }',
                    '           ]',
                    '        }',
                    '    ]',
                    '',
                ]
            else:
                action = [
                    f"                    'name': '{name}',",
                    f"                    'execute': {classname},",
                ]
                action.append(f"                    'minimumVersion': '{min_version}'")
                lines += [
                    f'def {hook}():',
                    '',
                    '    return [',
                    '        {',
                    f"            'name': '{name}',",
                    "            'actions': [",
                    '                {',
                ] + action + [
                    '                }',
                    '            ]',
                    '        }',
                    '    ]',
                    '',
                ]
        return lines

    @staticmethod
    def _widget_kwargs(widget_type: str, props: dict) -> dict:
        """Normalize runtime widget properties into stable Python kwargs strings."""
        specs = CodeGenerator.WIDGET_SPECS.get(widget_type, {})
        prop_defs = {p.name: p for p in specs.get('props', [])}
        result = {}
        for key, val in props.items():
            if key not in prop_defs:
                continue
            pdef = prop_defs[key]
            if pdef.kind == 'connect':
                if val:
                    result[key] = str(val)
            elif pdef.kind == 'token_dest':
                if val:
                    result[key] = f'self.{val}'
            elif pdef.kind == 'enum':
                if widget_type == 'PyFlameColorMenu' and key == 'color':
                    result[key] = repr(str(val) if val is not None else 'No Color')
                else:
                    enum_class = CodeGenerator.ENUM_PROP_MAP.get(key, '')
                    result[key] = f'{enum_class}.{val}' if enum_class else repr(val)
            elif pdef.kind == 'bool':
                result[key] = 'True' if val else 'False'
            elif pdef.kind == 'int':
                try:
                    result[key] = str(int(val))
                except (TypeError, ValueError):
                    result[key] = str(pdef.default)
            elif pdef.kind == 'list':
                if isinstance(val, list):
                    result[key] = repr(val)
                elif isinstance(val, str):
                    items = [x.strip() for x in val.splitlines() if x.strip()]
                    result[key] = repr(items)
                else:
                    result[key] = '[]'
            else:
                result[key] = repr(str(val) if val is not None else '')
        return result
