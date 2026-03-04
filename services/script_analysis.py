"""AST helpers for analyzing and patching generated script classes."""

from __future__ import annotations

import ast
import re
from ast import literal_eval

START_WINDOW_BUILD_MARKER = '[Start Window Build]'


def _fallback_class_names(code: str) -> list[str]:
    return re.findall(r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b', code, flags=re.MULTILINE)


def _contains_window_build_markers(src: str) -> bool:
    # Start marker is the durable signal; end marker may fall outside AST end line.
    start = re.search(r'^\s*#\s*\[Start Window Build\]\s*$', src, flags=re.MULTILINE)
    return bool(start)


def _fallback_create_methods_by_class(code: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    class_blocks = re.finditer(
        r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b[^\n]*:\n(.*?)(?=^\s*class\s+[A-Za-z_]|\Z)',
        code,
        flags=re.MULTILINE | re.DOTALL,
    )
    for m in class_blocks:
        cls = m.group(1)
        body = m.group(2)
        method_blocks = re.finditer(
            r'^ {4}def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^\n]*\)\s*(?:->\s*[^:\n]+)?\s*:\n(.*?)(?=^ {4}def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|\Z)',
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
        methods: list[str] = []
        for mm in method_blocks:
            name = mm.group(1)
            mbody = mm.group(2)
            marker_match = _contains_window_build_markers(mbody) and not name.startswith('__')
            if name.startswith('create_') or name == 'main_window' or marker_match:
                methods.append(name)
        out[cls] = methods
    return out


def detect_classes(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
        return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    except Exception:
        return _fallback_class_names(code)


def extract_create_methods(code: str) -> tuple[str, str] | None:
    """Return (class_name, methods_source) for window-build methods in first class found."""
    try:
        tree = ast.parse(code)
    except Exception:
        return None
    lines = code.splitlines()
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            methods = []
            for m in n.body:
                if not isinstance(m, ast.FunctionDef):
                    continue
                method_src = '\n'.join(lines[m.lineno - 1:m.end_lineno])
                marker_match = _contains_window_build_markers(method_src) and not m.name.startswith('__')
                if m.name.startswith('create_') or m.name == 'main_window' or marker_match:
                    methods.append(method_src)
            return n.name, ('\n\n'.join(methods).strip() + '\n') if methods else ''
    return None


def list_create_methods_by_class(code: str) -> dict[str, list[str]]:
    """Return class -> window-build method names map."""
    try:
        tree = ast.parse(code)
        lines = code.splitlines()
        out: dict[str, list[str]] = {}
        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                names: list[str] = []
                for m in n.body:
                    if not isinstance(m, ast.FunctionDef):
                        continue
                    method_src = '\n'.join(lines[m.lineno - 1:m.end_lineno])
                    marker_match = _contains_window_build_markers(method_src) and not m.name.startswith('__')
                    if m.name.startswith('create_') or m.name == 'main_window' or marker_match:
                        names.append(m.name)
                out[n.name] = names
        return out
    except Exception:
        return _fallback_create_methods_by_class(code)


def _collect_simple_constants(module: ast.Module, class_node: ast.ClassDef | None = None) -> dict[str, object]:
    """Collect simple constant assignments from module/class scope."""
    constants: dict[str, object] = {}

    def _literal(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
            return -node.operand.value
        if isinstance(node, ast.List):
            vals = []
            for el in node.elts:
                lv = _literal(el)
                if lv is None:
                    return None
                vals.append(lv)
            return vals
        return None

    def _scan(nodes):
        for stmt in nodes:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                value = _literal(stmt.value)
                if value is None:
                    continue
                t = stmt.targets[0]
                if isinstance(t, ast.Name):
                    constants[t.id] = value
                elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == 'self':
                    constants[f'self.{t.attr}'] = value

    _scan(module.body)
    if class_node is not None:
        _scan(class_node.body)
    return constants


def _parse_window_method_block(method_name: str, mbody: str) -> dict:
    inferred_name = method_name[len('create_'):] if method_name.startswith('create_') else method_name
    window_name = inferred_name
    window_title = None
    parent_window = None
    grid_columns = 4
    grid_rows = 3
    window_margins = 15

    wmatch = re.search(r'self\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*PyFlameWindow\((.*?)\)', mbody, flags=re.DOTALL)
    if wmatch:
        window_name = wmatch.group(1)
        args = wmatch.group(2)
        gc = re.search(r'grid_layout_columns\s*=\s*(\d+)', args)
        gr = re.search(r'grid_layout_rows\s*=\s*(\d+)', args)
        wm = re.search(r'window_margins\s*=\s*(\d+)', args)
        pw = re.search(r'parent\s*=\s*self\.([A-Za-z_][A-Za-z0-9_]*)', args)
        tw = re.search(r"title\s*=\s*(['\"])(.*?)\1", args)
        if gc:
            grid_columns = int(gc.group(1))
        if gr:
            grid_rows = int(gr.group(1))
        if wm:
            window_margins = int(wm.group(1))
        if pw:
            parent_window = pw.group(1)
        if tw:
            window_title = tw.group(2)

    # Parse widget definitions and simple kwargs so imported widgets keep labels/text.
    widget_defs: dict[str, dict] = {}
    widget_assignments = re.finditer(
        r'self\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(PyFlame[A-Za-z0-9_]+)\((.*?)\)\s*(?=\n\s*self\.|\n\s*#|\n\s*$)',
        mbody,
        flags=re.DOTALL,
    )
    for wm in widget_assignments:
        var_name = wm.group(1)
        widget_type = wm.group(2)
        args_block = wm.group(3)
        props: dict = {}

        for km in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\n,#]+)', args_block):
            key = km.group(1)
            raw = km.group(2).strip()
            # Skip obvious callback refs in regex mode.
            if key in {'connect', 'return_pressed', 'escape_pressed'}:
                continue
            try:
                if raw.startswith(("'", '"', '[', '{', '(', '-', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    props[key] = literal_eval(raw)
                elif raw in {'True', 'False'}:
                    props[key] = (raw == 'True')
                else:
                    # Keep enum-like tokens (e.g. Color.GRAY) as-is for downstream normalization.
                    props[key] = raw
            except Exception:
                props[key] = raw

        widget_defs[var_name] = {
            'widget_type': widget_type,
            'properties': props,
        }

    widgets = []
    for pm in re.finditer(
        r'self\.[A-Za-z_][A-Za-z0-9_]*\.grid_layout\.addWidget\(\s*self\.([A-Za-z_][A-Za-z0-9_]*)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+)\s*,\s*(\d+))?',
        mbody,
    ):
        var_name = pm.group(1)
        row = int(pm.group(2))
        col = int(pm.group(3))
        row_span = int(pm.group(4) or 1)
        col_span = int(pm.group(5) or 1)

        spec = widget_defs.get(var_name, {})
        widget_type = spec.get('widget_type', 'PyFlameLabel')
        properties = spec.get('properties', {})
        widgets.append(
            {
                'widget_type': widget_type,
                'row': row,
                'col': col,
                'row_span': row_span,
                'col_span': col_span,
                'properties': properties,
                'var_name': var_name,
            }
        )

    return {
        'method_name': method_name,
        'window_name': window_name,
        'grid_columns': max(1, int(grid_columns)),
        'grid_rows': max(1, int(grid_rows)),
        'window_title': window_title,
        'parent_window': parent_window,
        'window_margins': max(0, int(window_margins)),
        'widgets': widgets,
        'skipped': [],
    }


def _analyze_create_windows_regex(code: str, class_name: str | None = None) -> list[dict]:
    out: list[dict] = []
    class_blocks = re.finditer(
        r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b[^\n]*:\n(.*?)(?=^\s*class\s+[A-Za-z_]|\Z)',
        code,
        flags=re.MULTILINE | re.DOTALL,
    )
    for cm in class_blocks:
        cls = cm.group(1)
        if class_name and cls != class_name:
            continue
        body = cm.group(2)
        method_blocks = re.finditer(
            r'^ {4}def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^\n]*\)\s*(?:->\s*[^:\n]+)?\s*:\n(.*?)(?=^ {4}def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|\Z)',
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
        for mm in method_blocks:
            method_name = mm.group(1)
            mbody = mm.group(2)
            marker_match = _contains_window_build_markers(mbody) and not method_name.startswith('__')
            if not (method_name.startswith('create_') or method_name == 'main_window' or marker_match):
                continue
            out.append(_parse_window_method_block(method_name, mbody))

    if class_name is None:
        top_level_defs = re.finditer(
            r'^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^\n]*\)\s*(?:->\s*[^:\n]+)?\s*:\n(.*?)(?=^def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|\Z)',
            code,
            flags=re.MULTILINE | re.DOTALL,
        )
        for dm in top_level_defs:
            method_name = dm.group(1)
            mbody = dm.group(2)
            if not (method_name.startswith('create_') or method_name == 'main_window' or _contains_window_build_markers(mbody)):
                continue
            out.append(_parse_window_method_block(method_name, mbody))

    return out


def analyze_create_windows(code: str, class_name: str | None = None) -> list[dict]:
    """Extract create_* window metadata from a class.

    Returns list of dicts:
      {method_name, window_name, grid_columns, grid_rows, widgets}

    widgets are best-effort extracted for deterministic patterns:
      self.<var> = PyFlameX(...)
      self.<window>.grid_layout.addWidget(self.<var>, row, col[, row_span, col_span])
    """
    try:
        tree = ast.parse(code)
    except Exception:
        return _analyze_create_windows_regex(code, class_name)

    target_class = None
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and (class_name is None or n.name == class_name):
            target_class = n
            break
    if target_class is None:
        return []

    constants = _collect_simple_constants(tree, target_class)

    def _simple_value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            vals = []
            for el in node.elts:
                sv = _simple_value(el)
                if sv is None:
                    return None
                vals.append(sv)
            return vals
        if isinstance(node, ast.Tuple):
            vals = []
            for el in node.elts:
                sv = _simple_value(el)
                if sv is None:
                    return None
                vals.append(sv)
            return vals
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.Attribute):
            # self.foo constant or enum-ish dotted path (e.g. Color.RED)
            if isinstance(node.value, ast.Name) and node.value.id == 'self':
                return constants.get(f'self.{node.attr}')
            base = _simple_value(node.value)
            if isinstance(base, str):
                return f'{base}.{node.attr}'
            if isinstance(node.value, ast.Name):
                return f'{node.value.id}.{node.attr}'
            return None
        return None

    def _const_int(node, default):
        sv = _simple_value(node)
        if isinstance(sv, int):
            return int(sv)
        return default

    out: list[dict] = []
    lines = code.splitlines()
    for m in target_class.body:
        if not isinstance(m, ast.FunctionDef):
            continue
        method_src = '\n'.join(lines[m.lineno - 1:m.end_lineno])
        marker_match = _contains_window_build_markers(method_src) and not m.name.startswith('__')
        if not (m.name.startswith('create_') or m.name == 'main_window' or marker_match):
            continue

        method_name = m.name
        inferred_name = method_name[len('create_'):] if method_name.startswith('create_') else method_name
        window_name = inferred_name
        window_title = None
        parent_window = None
        grid_columns = 4
        grid_rows = 3
        window_margins = 15

        # var_name -> {widget_type, properties}
        widget_defs: dict[str, dict] = {}
        placements: dict[str, tuple[int, int, int, int]] = {}
        skipped: list[dict] = []

        for stmt in m.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                call = stmt.value

                # Detect window assignment: self.<window> = PyFlameWindow(...)
                if isinstance(call.func, ast.Name) and call.func.id == 'PyFlameWindow':
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == 'self':
                            window_name = tgt.attr or inferred_name
                            break
                    for kw in call.keywords:
                        if kw.arg == 'grid_layout_columns':
                            grid_columns = _const_int(kw.value, grid_columns)
                        elif kw.arg == 'grid_layout_rows':
                            grid_rows = _const_int(kw.value, grid_rows)
                        elif kw.arg == 'window_margins':
                            window_margins = _const_int(kw.value, window_margins)
                        elif kw.arg == 'parent':
                            if isinstance(kw.value, ast.Attribute) and isinstance(kw.value.value, ast.Name) and kw.value.value.id == 'self':
                                parent_window = kw.value.attr
                        elif kw.arg == 'title':
                            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                window_title = kw.value.value
                    continue

                # Detect widget assignment: self.<var> = PyFlameX(...)
                if isinstance(call.func, ast.Name) and str(call.func.id).startswith('PyFlame'):
                    var_name = None
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == 'self':
                            var_name = tgt.attr
                            break
                    if var_name:
                        props: dict = {}
                        for kw in call.keywords:
                            if kw.arg is None:
                                continue
                            sv = _simple_value(kw.value)
                            if sv is not None:
                                props[kw.arg] = sv
                        widget_defs[var_name] = {
                            'widget_type': call.func.id,
                            'properties': props,
                        }
                    continue

            # Detect placement call: self.<window>.grid_layout.addWidget(self.<var>, r, c[, rs, cs])
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == 'addWidget':
                    owner = call.func.value
                    if (
                        isinstance(owner, ast.Attribute)
                        and owner.attr == 'grid_layout'
                        and isinstance(owner.value, ast.Attribute)
                        and isinstance(owner.value.value, ast.Name)
                        and owner.value.value.id == 'self'
                    ):
                        args = call.args
                        if len(args) >= 3:
                            arg0 = args[0]
                            if isinstance(arg0, ast.Attribute) and isinstance(arg0.value, ast.Name) and arg0.value.id == 'self':
                                var = arg0.attr
                                r_val = _simple_value(args[1])
                                c_val = _simple_value(args[2])
                                if not isinstance(r_val, int) or not isinstance(c_val, int):
                                    skipped.append({'var_name': var, 'reason': 'non-literal row/col in addWidget'})
                                    continue
                                rs_val = _simple_value(args[3]) if len(args) > 3 else 1
                                cs_val = _simple_value(args[4]) if len(args) > 4 else 1
                                rs = rs_val if isinstance(rs_val, int) else 1
                                cs = cs_val if isinstance(cs_val, int) else 1
                                placements[var] = (max(0, int(r_val)), max(0, int(c_val)), max(1, int(rs)), max(1, int(cs)))

        widgets = []
        for var_name, (r, c, rs, cs) in placements.items():
            spec = widget_defs.get(var_name)
            if not spec:
                skipped.append({'var_name': var_name, 'reason': 'layout found but widget definition missing'})
                continue
            widgets.append(
                {
                    'widget_type': spec['widget_type'],
                    'row': r,
                    'col': c,
                    'row_span': rs,
                    'col_span': cs,
                    'properties': spec.get('properties', {}),
                    'var_name': var_name,
                }
            )

        out.append(
            {
                'method_name': method_name,
                'window_name': window_name,
                'grid_columns': max(1, int(grid_columns)),
                'grid_rows': max(1, int(grid_rows)),
                'window_title': window_title,
                'parent_window': parent_window,
                'window_margins': max(0, int(window_margins)),
                'widgets': widgets,
                'skipped': skipped,
            }
        )

    if not out and class_name is None:
        return _analyze_create_windows_regex(code, None)

    return out


def upsert_create_methods_into_class(code: str, class_name: str, methods_source: str, startup_method: str) -> str:
    """Replace create_* methods in target class, append fresh methods, and point startup call at startup_method."""
    lines = code.splitlines()
    tree = ast.parse(code)

    target = None
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            target = n
            break
    if target is None:
        raise ValueError(f'Class not found: {class_name}')

    remove_spans = []
    for m in target.body:
        if isinstance(m, ast.FunctionDef) and (m.name.startswith('create_') or m.name == 'main_window'):
            remove_spans.append((m.lineno - 1, m.end_lineno))
    for start, end in sorted(remove_spans, reverse=True):
        del lines[start:end]

    code2 = '\n'.join(lines) + '\n'
    tree2 = ast.parse(code2)
    target2 = None
    for n in tree2.body:
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            target2 = n
            break
    if target2 is None:
        raise ValueError(f'Class not found after rewrite: {class_name}')

    insert_at = target2.end_lineno - 1
    method_lines = methods_source.rstrip('\n').splitlines()
    if method_lines:
        insertion = [''] + method_lines + ['']
        lines[insert_at:insert_at] = insertion

    out = '\n'.join(lines) + '\n'
    pattern = r'(self\.)create_[a-zA-Z0-9_]+(\(\))'
    out = re.sub(pattern, rf'\1{startup_method}\2', out, count=1)
    return out
