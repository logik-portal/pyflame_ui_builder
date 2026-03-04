"""Export workflow helpers for script generation.

This module keeps filesystem/export decision logic out of the UI class so it can
be tested independently.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable

from services.script_analysis import detect_classes, extract_create_methods, upsert_create_methods_into_class
from services.utils import to_snake


def prepare_export_tree(template_dir: str, output_dir: str, script_name: str, *, overwrite: bool) -> tuple[bool, str, str]:
    """Create export folder from template and normalize lib filenames.

    Returns: (ok, message_or_script_dir, snake_name)
    """
    if not os.path.isdir(template_dir):
        return False, f'Template folder not found: {template_dir}', ''
    if not output_dir:
        return False, 'No output directory provided', ''

    snake = to_snake(script_name)
    script_dir = os.path.join(output_dir, snake)

    if os.path.exists(script_dir):
        if not overwrite:
            return False, f'Folder exists: {script_dir}', snake
        shutil.rmtree(script_dir)

    shutil.copytree(template_dir, script_dir)

    # Remove builder-only template source file from generated output.
    generated_template_py = os.path.join(script_dir, 'script_template.py')
    if os.path.exists(generated_template_py):
        os.remove(generated_template_py)

    # Rename bundled lib module/stub to script-specific names.
    lib_src = os.path.join(script_dir, 'lib', 'pyflame_lib.py')
    lib_dst = os.path.join(script_dir, 'lib', f'pyflame_lib_{snake}.py')
    if os.path.exists(lib_src):
        os.rename(lib_src, lib_dst)

    lib_stub_src = os.path.join(script_dir, 'lib', 'pyflame_lib.pyi')
    lib_stub_dst = os.path.join(script_dir, 'lib', f'pyflame_lib_{snake}.pyi')
    if os.path.exists(lib_stub_src):
        os.rename(lib_stub_src, lib_stub_dst)

    return True, script_dir, snake


def decide_export_code(
    *,
    generated_code: str,
    edited_code: str,
    preview_user_edited: bool,
    raw_import_code: str | None,
    windows: list,
    class_selector: Callable[[list[str]], str | None] | None = None,
) -> tuple[bool, str, str]:
    """Pick final export code, optionally merging generated methods into edited code.

    Returns: (ok, code_or_error, detail)
    """
    code = generated_code
    use_edited_code = bool(edited_code.strip()) and bool(preview_user_edited)

    # Imported session safety: default to normalized generated code unless user
    # intentionally edited preview code.
    if raw_import_code is not None and not preview_user_edited:
        use_edited_code = False

    if not use_edited_code:
        return True, code, 'generated'

    edited = edited_code.strip()
    class_names = detect_classes(edited)
    if class_names:
        target_class = class_names[0]
        if len(class_names) > 1 and class_selector is not None:
            selected = class_selector(class_names)
            if not selected:
                return False, 'Export cancelled', 'cancelled'
            target_class = selected

        extracted = extract_create_methods(generated_code)
        methods_source = extracted[1] if extracted else ''
        startup_method = f"create_{windows[0].function_name}" if windows else 'create_main_window'
        if methods_source:
            merged = upsert_create_methods_into_class(edited + '\n', target_class, methods_source, startup_method)
            return True, merged, 'merged'
        return True, edited, 'edited-no-methods'

    return True, edited, 'edited-raw'
