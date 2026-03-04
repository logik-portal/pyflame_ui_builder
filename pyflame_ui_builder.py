#!/usr/bin/env python3
# PyFlame UI Builder
# Copyright (c) 2026 Michael Vaglienty
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# License:       GNU General Public License v3.0 (GPL-3.0)
#                https://www.gnu.org/licenses/gpl-3.0.en.html

# ==============================================================================
# Flame Mock — injected before pyflame_lib loads (it imports flame at module level)
# ==============================================================================

import sys
import types

_flame_mock = types.ModuleType('flame')
_flame_mock.projects = types.SimpleNamespace(
    current_project=types.SimpleNamespace(name='MockProject')
)
for _cls in ['PyBatch', 'PyClip', 'PyFolder', 'PyLibrary', 'PySequence',
             'PySegment', 'PyTrack', 'PyTimeline', 'PyDesktop', 'PyNode']:
    setattr(_flame_mock, _cls, type(_cls, (), {}))
# pyflame_lib expects flame.messages.show_in_console when reporting warnings.
_flame_mock.messages = types.SimpleNamespace(show_in_console=lambda *args, **kwargs: None)
sys.modules['flame'] = _flame_mock

# ==============================================================================
# Standard Imports
# ==============================================================================

import os
import re
import ast
import html
import copy
import json
import queue
import shutil
import datetime
import subprocess
import importlib.util
import threading
import textwrap
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from app.config import (
    APP_NAME,
    APP_VERSION,
    APP_AUTHOR,
    APP_LICENSE,
    APP_URL,
    APP_DESCRIPTION,
)
from app.logging_setup import get_bootstrap_logger, init_logging
from models.ui_models import PropDef, PlacedWidget, ScriptWindow, WindowConfig
from services.code_generator import CodeGenerator
from services.project_serializer import ProjectSerializer
from services.script_analysis import (
    analyze_create_windows,
    detect_classes,
)
from services.utils import to_snake
from services.workflow import (
    build_imported_windows,
    summarize_import_result,
    suggest_script_name_from_path,
)
from services.export_workflow import prepare_export_tree, decide_export_code
from ui.canvas_widget import CanvasWidget
from ui.help_dialog import HelpDialog
from ui.pannable_scroll_area import PannableScrollArea
from ui.progress_bar_preview import ProgressBarPreview
from ui.properties_panel import PropertiesPanel
from ui.widget_container import TabOrderDialog, WidgetContainer
from ui.widget_palette import WidgetPalette
from ui.window_config_bar import WindowConfigBar

# ==============================================================================
# Platform Guard
# ==============================================================================

if sys.platform != 'darwin':
    print(
        'PyFlame UI Builder is currently macOS-only.\n'
        'Detected platform: ' + sys.platform + '\n'
        'Please run this tool on macOS.',
        file=sys.stderr,
    )
    sys.exit(1)

# ==============================================================================
# PySide6 Imports
# ==============================================================================

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QSplitter, QFrame, QDialog,
    QPlainTextEdit, QPushButton, QFileDialog, QMessageBox, QTextEdit,
    QInputDialog, QTabBar, QMenu, QTextBrowser,
)
from PySide6.QtCore import Qt, QRect, QSettings, QTimer, QEvent, Signal, QSize, QPoint, QThread
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QKeySequence, QAction, QCursor, QPainter, QPolygon,
    QTextCursor, QTextFormat, QTextDocument, QSyntaxHighlighter, QTextCharFormat, QTextBlock,
)

from ui.code_editor import SpacesTabPlainTextEdit, PythonSyntaxHighlighter


# ==============================================================================
# QApplication must exist before pyflame_lib loads (it calls screenGeometry() at
# module level via _load_font() → pyflame.gui_resize() → pyflame.window_resolution())
# ==============================================================================

# Bootstrap logger so early module-load events are visible in terminal.
_bootstrap_logger = get_bootstrap_logger()

_early_app = QApplication.instance() or QApplication(sys.argv)
_early_app.setApplicationName(APP_NAME)
_early_app.setApplicationDisplayName(APP_NAME)
_early_app.setStyle('Fusion')

# PySide6 compat: pyflame_lib calls QScreen.screenGeometry() which was a
# QDesktopWidget method in Qt5. In PySide6 the equivalent is QScreen.geometry().
from PySide6.QtGui import QScreen as _QScreen
if not hasattr(_QScreen, 'screenGeometry'):
    _QScreen.screenGeometry = _QScreen.geometry

# ==============================================================================
# Load pyflame_lib from canonical location
# ==============================================================================

PYFLAME_LIB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'assets', 'script_template', 'lib', 'pyflame_lib.py',
)

_PYFLAME_EXPORTS = [
    'PyFlameLabel', 'PyFlameEntry', 'PyFlameEntryBrowser',
    'PyFlameButton', 'PyFlamePushButton', 'PyFlameMenu',
    'PyFlameColorMenu', 'PyFlameTokenMenu', 'PyFlameSlider',
    'PyFlameListWidget', 'PyFlameTreeWidget', 'PyFlameTextEdit',
    'PyFlameTextBrowser', 'PyFlameProgressBarWidget',
    'PyFlameHorizontalLine', 'PyFlameVerticalLine',
    'Style', 'Align', 'Color', 'TextType', 'TextStyle', 'BrowserType',
    'pyflame',
]

_pyflame_loaded = False
try:
    _spec = importlib.util.spec_from_file_location('pyflame_lib', PYFLAME_LIB_PATH)
    _pyflame_mod = importlib.util.module_from_spec(_spec)
    sys.modules['pyflame_lib'] = _pyflame_mod
    _spec.loader.exec_module(_pyflame_mod)
    for _n in _PYFLAME_EXPORTS:
        if hasattr(_pyflame_mod, _n):
            globals()[_n] = getattr(_pyflame_mod, _n)

    # In builder preview mode, pyflame widgets can create helper dialogs
    # (e.g. entry calculator) with a Qt parent that is not a PyFlameWindow.
    # That strict type check is valid in Flame, but too strict for this host app.
    try:
        _orig_raise_type_error = _pyflame_mod.pyflame.raise_type_error

        def _builder_safe_raise_type_error(*args, **kwargs):
            cls_name = args[0] if len(args) > 0 else kwargs.get('class_name')
            arg_name = args[1] if len(args) > 1 else kwargs.get('arg_name')
            if cls_name == 'PyFlameWindow' and arg_name == 'parent':
                _bootstrap_logger.debug(
                    'Suppressed PyFlameWindow parent type error in builder preview context.'
                )
                return
            return _orig_raise_type_error(*args, **kwargs)

        _pyflame_mod.pyflame.raise_type_error = _builder_safe_raise_type_error
    except Exception:
        _bootstrap_logger.debug('Could not install builder-safe pyflame type-check shim.')

    _pyflame_loaded = True
    _bootstrap_logger.info('pyflame_lib loaded successfully.')
except Exception as _e:
    _bootstrap_logger.warning('Could not load pyflame_lib: %s', _e)
    _bootstrap_logger.exception('pyflame_lib import traceback')

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'script_template')
CHANGELOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CHANGELOG.md')

# Local preview API toggle for builder runtime (can still be overridden by env vars below).
PREVIEW_API_ENABLED = False

# ==============================================================================
# License Data
# ==============================================================================
# Each entry: 'header' = comment lines inserted after the copyright line,
#             'docstring' = text for the "License:" field in the module docstring.

LICENSE_DATA = {
    'None': {
        'header': [],
        'docstring': 'Proprietary',
    },
    'GPL-3.0': {
        'header': [
            '#',
            '# This program is free software: you can redistribute it and/or modify',
            '# it under the terms of the GNU General Public License as published by',
            '# the Free Software Foundation, either version 3 of the License, or',
            '# (at your option) any later version.',
            '#',
            '# This program is distributed in the hope that it will be useful,',
            '# but WITHOUT ANY WARRANTY; without even the implied warranty of',
            '# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the',
            '# GNU General Public License for more details.',
            '#',
            '# You should have received a copy of the GNU General Public License',
            '# along with this program. If not, see <https://www.gnu.org/licenses/>.',
            '#',
            '# License:       GNU General Public License v3.0 (GPL-3.0)',
            '#                https://www.gnu.org/licenses/gpl-3.0.en.html',
        ],
        'docstring': 'GNU General Public License v3.0 (GPL-3.0) - see LICENSE file for details',
    },
    'LGPL-3.0': {
        'header': [
            '#',
            '# This program is free software: you can redistribute it and/or modify',
            '# it under the terms of the GNU Lesser General Public License as',
            '# published by the Free Software Foundation, either version 3 of the',
            '# License, or (at your option) any later version.',
            '#',
            '# This program is distributed in the hope that it will be useful,',
            '# but WITHOUT ANY WARRANTY; without even the implied warranty of',
            '# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the',
            '# GNU Lesser General Public License for more details.',
            '#',
            '# You should have received a copy of the GNU Lesser General Public',
            '# License along with this program. If not, see <https://www.gnu.org/licenses/>.',
            '#',
            '# License:       GNU Lesser General Public License v3.0 (LGPL-3.0)',
            '#                https://www.gnu.org/licenses/lgpl-3.0.en.html',
        ],
        'docstring': 'GNU Lesser General Public License v3.0 (LGPL-3.0) - see LICENSE file for details',
    },
    'MIT': {
        'header': [
            '#',
            '# Permission is hereby granted, free of charge, to any person obtaining a copy',
            '# of this software and associated documentation files (the "Software"), to deal',
            '# in the Software without restriction, including without limitation the rights',
            '# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell',
            '# copies of the Software, and to permit persons to whom the Software is',
            '# furnished to do so, subject to the following conditions:',
            '#',
            '# The above copyright notice and this permission notice shall be included in all',
            '# copies or substantial portions of the Software.',
            '#',
            '# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR',
            '# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,',
            '# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE',
            '# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER',
            '# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,',
            '# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE',
            '# SOFTWARE.',
            '#',
            '# License:       MIT License',
            '#                https://opensource.org/licenses/MIT',
        ],
        'docstring': 'MIT License - see LICENSE file for details',
    },
    'Apache-2.0': {
        'header': [
            '#',
            '# Licensed under the Apache License, Version 2.0 (the "License");',
            '# you may not use this file except in compliance with the License.',
            '# You may obtain a copy of the License at',
            '#',
            '#     https://www.apache.org/licenses/LICENSE-2.0',
            '#',
            '# Unless required by applicable law or agreed to in writing, software',
            '# distributed under the License is distributed on an "AS IS" BASIS,',
            '# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.',
            '# See the License for the specific language governing permissions and',
            '# limitations under the License.',
            '#',
            '# License:       Apache License 2.0',
            '#                https://www.apache.org/licenses/LICENSE-2.0',
        ],
        'docstring': 'Apache License 2.0 - see LICENSE file for details',
    },
    'BSD-2-Clause': {
        'header': [
            '#',
            '# Redistribution and use in source and binary forms, with or without',
            '# modification, are permitted provided that the following conditions are met:',
            '#',
            '# 1. Redistributions of source code must retain the above copyright notice,',
            '#    this list of conditions and the following disclaimer.',
            '# 2. Redistributions in binary form must reproduce the above copyright notice,',
            '#    this list of conditions and the following disclaimer in the documentation',
            '#    and/or other materials provided with the distribution.',
            '#',
            '# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"',
            '# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE',
            '# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE',
            '# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE',
            '# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL',
            '# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR',
            '# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER',
            '# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,',
            '# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE',
            '# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.',
            '#',
            '# License:       BSD 2-Clause License',
            '#                https://opensource.org/licenses/BSD-2-Clause',
        ],
        'docstring': 'BSD 2-Clause License - see LICENSE file for details',
    },
    'BSD-3-Clause': {
        'header': [
            '#',
            '# Redistribution and use in source and binary forms, with or without',
            '# modification, are permitted provided that the following conditions are met:',
            '#',
            '# 1. Redistributions of source code must retain the above copyright notice,',
            '#    this list of conditions and the following disclaimer.',
            '# 2. Redistributions in binary form must reproduce the above copyright notice,',
            '#    this list of conditions and the following disclaimer in the documentation',
            '#    and/or other materials provided with the distribution.',
            '# 3. Neither the name of the copyright holder nor the names of its contributors',
            '#    may be used to endorse or promote products derived from this software',
            '#    without specific prior written permission.',
            '#',
            '# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"',
            '# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE',
            '# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE',
            '# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE',
            '# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL',
            '# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR',
            '# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER',
            '# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,',
            '# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE',
            '# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.',
            '#',
            '# License:       BSD 3-Clause License',
            '#                https://opensource.org/licenses/BSD-3-Clause',
        ],
        'docstring': 'BSD 3-Clause License - see LICENSE file for details',
    },
}


# ==============================================================================
# Hook Metadata
# ==============================================================================

# Short display label for each hook (used in the config bar checkable list)
HOOK_DISPLAY = {
    'get_batch_custom_ui_actions':       'Batch',
    'get_main_menu_custom_ui_actions':   'Main Menu',
    'get_media_panel_custom_ui_actions': 'Media Panel',
    'get_media_hub_custom_ui_actions':   'Media Hub',
    'get_timeline_custom_ui_actions':    'Timeline',
}

# Human-readable script type derived from a hook name
HOOK_TO_TYPE = {
    'get_batch_custom_ui_actions':       'Batch',
    'get_main_menu_custom_ui_actions':   'Main Menu',
    'get_media_panel_custom_ui_actions': 'Media Panel',
    'get_media_hub_custom_ui_actions':   'Media Hub',
    'get_timeline_custom_ui_actions':    'Timeline',
}

# Scope function name per hook (None = no scope needed for that hook)
HOOK_SCOPE = {
    'get_batch_custom_ui_actions':       'scope_batch',
    'get_main_menu_custom_ui_actions':   None,
    'get_media_panel_custom_ui_actions': 'scope_clip',
    'get_media_hub_custom_ui_actions':   'scope_media_hub',
    'get_timeline_custom_ui_actions':    'scope_segment',
}

# Scope function body lines (keyed by scope function name)
SCOPE_DEFS = {
    'scope_batch': [
        'def scope_batch(selection):',
        '    for item in selection:',
        '        if isinstance(item, flame.PyBatch):',
        '            return True',
        '    return False',
    ],
    'scope_clip': [
        'def scope_clip(selection):',
        '    for item in selection:',
        '        if isinstance(item, flame.PyClip):',
        '            return True',
        '    return False',
    ],
    'scope_media_hub': [
        'def scope_media_hub(selection):',
        '    return True',
    ],
    'scope_segment': [
        'def scope_segment(selection):',
        '    for item in selection:',
        '        if isinstance(item, flame.PySegment):',
        '            return True',
        '    return False',
    ],
}

# ==============================================================================
# Widget Specifications
# ==============================================================================

WIDGET_SPECS = {
    'PyFlameLabel': {
        'display': 'Label',
        'category': 'Layout',
        'fixed_axes': {'h'},
        'props': [
            PropDef('text', 'str', 'Label', []),
            PropDef('style', 'enum', 'NORMAL',
                    ['NORMAL', 'UNDERLINE', 'BORDER', 'BACKGROUND', 'BACKGROUND_THIN']),
            PropDef('align', 'enum', 'LEFT', ['LEFT', 'RIGHT', 'CENTER']),
        ],
    },
    'PyFlameEntry': {
        'display': 'Entry',
        'category': 'Input',
        'fixed_axes': {'h'},
        'props': [
            PropDef('text', 'str', '', []),
            PropDef('placeholder_text', 'str', '', []),
            PropDef('read_only', 'bool', False, []),
            PropDef('text_changed', 'connect', None, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlameEntryBrowser': {
        'display': 'Entry Browser',
        'category': 'Input',
        'fixed_axes': {'h'},
        'props': [
            PropDef('path', 'str', '', []),
            PropDef('placeholder_text', 'str', '', []),
            PropDef('browser_type', 'enum', 'FILE', ['FILE', 'DIRECTORY']),
            PropDef('browser_title', 'str', 'Select File', []),
            PropDef('connect', 'connect', None, []),
        ],
    },
    'PyFlameButton': {
        'display': 'Button',
        'category': 'Buttons',
        'fixed_axes': {'h', 'w'},
        'props': [
            PropDef('text', 'str', 'Button', []),
            PropDef('color', 'enum', 'GRAY',
                    ['GRAY', 'BLUE', 'RED']),
            PropDef('connect', 'connect', None, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlamePushButton': {
        'display': 'Push Button',
        'category': 'Buttons',
        'fixed_axes': {'h', 'w'},
        'props': [
            PropDef('text', 'str', 'Push Button', []),
            PropDef('checked', 'bool', False, []),
            PropDef('connect', 'connect', None, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlameMenu': {
        'display': 'Menu',
        'category': 'Buttons',
        'fixed_axes': {'h'},
        'props': [
            PropDef('text', 'str', 'Option 1', []),
            PropDef('menu_options', 'list', ['Option 1', 'Option 2', 'Option 3'], []),
            PropDef('align', 'enum', 'LEFT', ['LEFT', 'RIGHT', 'CENTER']),
            PropDef('menu_indicator', 'bool', False, []),
            PropDef('connect', 'connect', None, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlameColorMenu': {
        'display': 'Color Menu',
        'category': 'Buttons',
        'fixed_axes': {'h', 'w'},
        'props': [
            PropDef('color', 'enum', 'No Color', [
                'No Color', 'Red', 'Green', 'Bright Green', 'Blue', 'Light Blue',
                'Purple', 'Orange', 'Gold', 'Yellow', 'Grey', 'Black'
            ]),
            PropDef('menu_indicator', 'bool', False, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlameTokenMenu': {
        'display': 'Token Menu',
        'category': 'Buttons',
        'fixed_axes': {'h', 'w'},
        'props': [
            PropDef('text', 'str', 'Add Token', []),
            PropDef('token_dest', 'token_dest', None, []),
            PropDef('tooltip', 'str', '', []),
        ],
    },
    'PyFlameSlider': {
        'display': 'Slider',
        'category': 'Input',
        'fixed_axes': {'h', 'w'},
        'props': [
            PropDef('min_value', 'int', 0, []),
            PropDef('max_value', 'int', 100, []),
            PropDef('start_value', 'int', 0, []),
            PropDef('connect', 'connect', None, []),
        ],
    },
    'PyFlameListWidget': {
        'display': 'List Widget',
        'category': 'Collections',
        'fixed_axes': set(),
        'props': [
            PropDef('items', 'list', [], []),
            PropDef('alternating_row_colors', 'bool', True, []),
            PropDef('multi_selection', 'bool', True, []),
        ],
    },
    'PyFlameTreeWidget': {
        'display': 'Tree Widget',
        'category': 'Collections',
        'fixed_axes': set(),
        'props': [
            PropDef('column_names', 'list', ['Column 1'], []),
            PropDef('alternating_row_colors', 'bool', True, []),
            PropDef('connect', 'connect', None, []),
            PropDef('update_connect', 'connect', None, []),
        ],
    },
    'PyFlameTable': {
        'display': 'Table',
        'category': 'Collections',
        'fixed_axes': set(),
        'props': [
            PropDef('csv_file_path', 'str', '', []),
            PropDef('alternating_row_colors', 'bool', True, []),
            PropDef('enabled', 'bool', True, []),
            PropDef('tooltip', 'str', '', []),
            PropDef('tooltip_delay', 'int', 3, []),
            PropDef('tooltip_duration', 'int', 5, []),
        ],
    },
    'PyFlameTextEdit': {
        'display': 'Text Edit',
        'category': 'Input',
        'fixed_axes': set(),
        'props': [
            PropDef('text', 'str', '', []),
            PropDef('text_type', 'enum', 'PLAIN', ['PLAIN', 'MARKDOWN', 'HTML']),
            PropDef('text_style', 'enum', 'EDITABLE',
                    ['EDITABLE', 'READ_ONLY', 'UNSELECTABLE']),
        ],
    },
    'PyFlameTextBrowser': {
        'display': 'Text Browser',
        'category': 'Collections',
        'fixed_axes': set(),
        'props': [
            PropDef('text', 'str', '', []),
            PropDef('text_type', 'enum', 'PLAIN', ['PLAIN', 'MARKDOWN', 'HTML']),
            PropDef('open_external_links', 'bool', True, []),
        ],
    },
    'PyFlameProgressBarWidget': {
        'display': 'Progress Bar',
        'category': 'Layout',
        'fixed_axes': set(),
        'props': [
            PropDef('total_tasks', 'int', 100, []),
            PropDef('processing_task', 'int', 0, []),
        ],
    },
    'PyFlameHorizontalLine': {
        'display': 'Horizontal Line',
        'category': 'Layout',
        'fixed_axes': {'h'},
        'props': [
            PropDef('color', 'enum', 'GRAY',
                    ['BLACK', 'WHITE', 'GRAY', 'BRIGHT_GRAY', 'BLUE', 'RED']),
        ],
    },
    'PyFlameVerticalLine': {
        'display': 'Vertical Line',
        'category': 'Layout',
        'fixed_axes': {'w'},
        'props': [
            PropDef('color', 'enum', 'GRAY',
                    ['BLACK', 'WHITE', 'GRAY', 'BRIGHT_GRAY', 'BLUE', 'RED']),
        ],
    },
}

# ==============================================================================
# Canvas Chrome Constants
# ==============================================================================

CHROME_TITLE_H = 48
CHROME_MSG_H = 24
CHROME_SIDE_W = 2
CELL_GAP = 4
HANDLE_SIZE = 8

# Enum → code name mapping used by both widget instantiation and code generation
ENUM_PROP_MAP = {
    'style': 'Style',
    'align': 'Align',
    'color': 'Color',
    'bar_color': 'Color',
    'browser_type': 'BrowserType',
    'text_type': 'TextType',
    'text_style': 'TextStyle',
}

CodeGenerator.configure(
    template_dir=TEMPLATE_DIR,
    license_data=LICENSE_DATA,
    widget_specs=WIDGET_SPECS,
    hook_to_type=HOOK_TO_TYPE,
    hook_scope=HOOK_SCOPE,
    scope_defs=SCOPE_DEFS,
    enum_prop_map=ENUM_PROP_MAP,
)


# ==============================================================================
# Helper Functions
# ==============================================================================

def _handle_rects(widget_rect):
    """Return dict of handle_id → QRect for 8 resize handles."""
    x, y = widget_rect.x(), widget_rect.y()
    w, h = widget_rect.width(), widget_rect.height()
    hs = HANDLE_SIZE
    cx = x + w // 2 - hs // 2
    cy = y + h // 2 - hs // 2
    return {
        'nw': QRect(x,          y,          hs, hs),
        'n':  QRect(cx,         y,          hs, hs),
        'ne': QRect(x + w - hs, y,          hs, hs),
        'e':  QRect(x + w - hs, cy,         hs, hs),
        'se': QRect(x + w - hs, y + h - hs, hs, hs),
        's':  QRect(cx,         y + h - hs, hs, hs),
        'sw': QRect(x,          y + h - hs, hs, hs),
        'w':  QRect(x,          cy,         hs, hs),
    }


def _parse_template_callbacks() -> list[str]:
    """Return inner function names defined inside main_window in script_template.py."""
    tmpl_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'assets', 'script_template', 'script_template.py'
    )
    try:
        with open(tmpl_path, 'r') as f:
            content = f.read()
        # 8-space-indented defs are nested inside main_window
        return re.findall(r'^        def (\w+)\(', content, re.MULTILINE)
    except Exception:
        return []


def _allowed_handle_ids(widget_type: str) -> set:
    """Return the set of resize handle IDs that are valid for this widget type.

    Handles that resize a fixed axis are excluded:
      fixed 'h' → removes n, s, nw, ne, sw, se
      fixed 'w' → removes e, w, nw, ne, sw, se
    """
    fixed   = WIDGET_SPECS.get(widget_type, {}).get('fixed_axes', set())
    blocked = set()
    if 'h' in fixed:
        blocked |= {'n', 's', 'nw', 'ne', 'sw', 'se'}
    if 'w' in fixed:
        blocked |= {'e', 'w', 'nw', 'ne', 'sw', 'se'}
    return {'n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'} - blocked


def _str_to_enum(prop_name, val):
    """Convert a string like 'BLUE' to the appropriate enum instance."""
    enum_class_name = ENUM_PROP_MAP.get(prop_name)
    if not enum_class_name:
        return val
    enum_cls = globals().get(enum_class_name)
    if not enum_cls:
        return val
    try:
        return enum_cls[val]
    except (KeyError, TypeError):
        try:
            return list(enum_cls)[0]
        except Exception:
            return val


def _props_to_kwargs(widget_type, props):
    """Convert props dict (string values) to proper Python types for widget instantiation."""
    specs = WIDGET_SPECS.get(widget_type, {})
    prop_defs = {p.name: p for p in specs.get('props', [])}
    kwargs = {}
    for key, val in props.items():
        if key not in prop_defs:
            continue
        pdef = prop_defs[key]
        if pdef.kind == 'connect':
            # Never pass connect props to the live preview widget
            continue
        if pdef.kind == 'token_dest':
            # token_dest expects a widget object (self.entry_x) in generated code;
            # skip for live preview instantiation.
            continue
        elif pdef.kind == 'enum':
            # PyFlameColorMenu expects color as a string name (e.g. 'No Color').
            if widget_type == 'PyFlameColorMenu' and key == 'color':
                kwargs[key] = str(val) if val is not None else 'No Color'
            else:
                kwargs[key] = _str_to_enum(key, val)
        elif pdef.kind == 'bool':
            kwargs[key] = bool(val)
        elif pdef.kind == 'int':
            try:
                kwargs[key] = int(val)
            except (TypeError, ValueError):
                kwargs[key] = pdef.default
        elif pdef.kind == 'list':
            if isinstance(val, list):
                kwargs[key] = val
            elif isinstance(val, str):
                kwargs[key] = [x.strip() for x in val.splitlines() if x.strip()]
            else:
                kwargs[key] = []
        else:
            kwargs[key] = str(val) if val is not None else ''
    return kwargs


def _make_fallback_widget(widget_type):
    """Return a plain QLabel as fallback when a PyFlame widget can't be created."""
    lbl = QLabel(f'[{widget_type}]')
    lbl.setStyleSheet(
        'color: #c8c8c8; background: #3a3a3a; padding: 4px; border: 1px dashed #666;'
    )
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


WidgetContainer.configure(
    props_to_kwargs=_props_to_kwargs,
    make_fallback_widget=_make_fallback_widget,
    widget_class_getter=lambda name: globals().get(name),
    pyflame_loaded=_pyflame_loaded,
    progress_preview_cls=ProgressBarPreview,
    allowed_handle_ids=_allowed_handle_ids,
    handle_rects=_handle_rects,
    chrome_title_h=CHROME_TITLE_H,
    chrome_side_w=CHROME_SIDE_W,
)


# ==============================================================================
# Dark Stylesheet
# ==============================================================================

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background: #1e1e1e;
    color: #c8c8c8;
    font-size: 11px;
}
QListWidget {
    background: #252525;
    border: 1px solid #3a3a3a;
    color: #c8c8c8;
    outline: none;
}
QListWidget::item:selected {
    background: #2c3e50;
    color: #e0e0e0;
}
QListWidget::item:hover {
    background: #2a2a2a;
}
QLineEdit, QSpinBox, QPlainTextEdit {
    background: #2d2d2d;
    border: 1px solid #3a3a3a;
    color: #c8c8c8;
    padding: 2px 4px;
    selection-background-color: #006eaf;
}
QComboBox {
    background: #2d2d2d;
    border: 1px solid #3a3a3a;
    color: #c8c8c8;
    padding: 2px 4px;
}
QComboBox::drop-down { border: none; background: #3a3a3a; width: 16px; }
QComboBox QAbstractItemView {
    background: #2d2d2d;
    border: 1px solid #3a3a3a;
    selection-background-color: #3a3a3a;
    color: #c8c8c8;
}
QPushButton {
    background: #3a3a3a;
    border: none;
    color: #c8c8c8;
    padding: 4px 10px;
    border-radius: 2px;
}
QPushButton:hover  { background: #4a4a4a; }
QPushButton:pressed { background: #2a2a2a; }
QScrollArea  { border: none; }
QScrollBar:vertical {
    background: #1e1e1e;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3a3a3a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #2d2d2d; }
QMenuBar {
    background: #252525;
    color: #c8c8c8;
    border-bottom: 1px solid #3a3a3a;
}
QMenuBar::item:selected { background: #3a3a3a; }
QMenu {
    background: #252525;
    color: #c8c8c8;
    border: 1px solid #3a3a3a;
}
QMenu::item:selected { background: #3a3a3a; }
QGroupBox {
    color: #888;
    border: 1px solid #3a3a3a;
    border-radius: 3px;
    margin-top: 8px;
    font-size: 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QCheckBox { color: #c8c8c8; spacing: 6px; }
QCheckBox::indicator {
    width: 14px;
    height: 14px;
}
QCheckBox::indicator:unchecked {
    image: url("__CHECKBOX_UNCHECKED__");
}
QCheckBox::indicator:checked {
    image: url("__CHECKBOX_CHECKED__");
}
QLabel { color: #c8c8c8; }

"""


def _app_stylesheet() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    unchecked = os.path.join(base, 'assets', 'ui', 'checkbox_unchecked.svg').replace('\\', '/')
    checked = os.path.join(base, 'assets', 'ui', 'checkbox_checked.svg').replace('\\', '/')
    return (DARK_STYLESHEET
            .replace('__CHECKBOX_UNCHECKED__', unchecked)
            .replace('__CHECKBOX_CHECKED__', checked))


def _patch_messagebox_no_icons() -> None:
    """Force static QMessageBox helpers to use NoIcon (no !/? glyphs)."""

    def _show(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        msg = QMessageBox(parent)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.NoIcon)
        msg.setStandardButtons(buttons)
        if defaultButton not in (None, QMessageBox.NoButton):
            msg.setDefaultButton(defaultButton)
        return msg.exec()

    QMessageBox.information = staticmethod(
        lambda parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton:
        _show(parent, title, text, buttons, defaultButton)
    )
    QMessageBox.warning = staticmethod(
        lambda parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton:
        _show(parent, title, text, buttons, defaultButton)
    )
    QMessageBox.critical = staticmethod(
        lambda parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton:
        _show(parent, title, text, buttons, defaultButton)
    )
    QMessageBox.question = staticmethod(
        lambda parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.NoButton:
        _show(parent, title, text, buttons, defaultButton)
    )


# ==============================================================================
# PyFlameBuilder — Main Window
# ==============================================================================

class PyFlameBuilder(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self.config = WindowConfig()
        self.windows: list[ScriptWindow] = [
            ScriptWindow(function_name='main_window', grid_columns=self.config.grid_columns, grid_rows=self.config.grid_rows, widgets=[])
        ]
        self.active_window_index = 0
        self._dirty = False
        self._save_path: str | None = None

        self._preview_auto = True
        self._preview_visible = True
        self._preview_center_on_change = True
        self._last_preview_code = ''
        self._raw_import_code: str | None = None
        self._preview_user_edited = False
        self._suppress_preview_text_signal = False
        self._api_preview_highlight_active = False
        self._active_work_panel = None
        self._active_aux_panel = None
        self._last_find_text = ''
        self._last_replace_text = ''
        self._find_match_case = False
        self._find_whole_word = False
        self._find_regex = False
        self._replace_in_selection = False
        self._recent_searches: list[str] = []
        self._grid_was_on_before_preview = False
        self._main_split_sizes_before_preview_hide: list[int] | None = None
        self._preview_timer = QTimer(self)
        self._code_to_ui_sync_timer = QTimer(self)
        self._code_to_ui_sync_timer.setSingleShot(True)
        self._code_to_ui_sync_timer.setInterval(220)
        self._code_to_ui_sync_timer.timeout.connect(self._sync_canvas_from_preview_code_best_effort)
        self._generated_code_snapshot = ''
        self._bookmark_lines: set[int] = set()
        self._cursor_history: list[int] = []
        self._cursor_history_index = -1
        self._cursor_history_nav = False

        self._history_limit = 10
        self._history: list[dict] = []
        self._history_index = -1
        self._restoring_history = False

        self._api_queue: queue.Queue = queue.Queue()
        self._api_server = None
        self._api_thread = None
        self._api_timer = QTimer(self)
        self._api_timer.setInterval(80)
        self._api_timer.timeout.connect(self._process_api_requests)
        self._api_timer.start()

        try:
            self._flame_available: bool = importlib.util.find_spec('flame') is not None
        except ValueError:
            # flame is in sys.modules with __spec__ = None (Flame's custom loader)
            self._flame_available = 'flame' in sys.modules

        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.setStyleSheet(_app_stylesheet())
        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._restore_window_layout_settings()
        # Global click handling for deselection outside canvas.
        QApplication.instance().installEventFilter(self)
        # Ensure startup shows window properties when no widget is selected.
        self._show_active_window_properties()
        self._update_title()
        self._record_history_state()
        self._update_undo_redo_actions()
        self._start_preview_api_if_enabled()
        QTimer.singleShot(0, self._show_whats_new_if_needed)

    # ── UI construction ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_hover_hints_from_pyflame_lib(path: str) -> dict[str, str]:
        """Build symbol->hint map from class/function docstrings in pyflame_lib.py.

        VS Code-like intent:
        - Prefer full-symbol hover text with a signature/header line.
        - For classes, fall back to __init__ docstring when class docstring is missing.
        """
        hints: dict[str, str] = {}
        try:
            # Read full file (no truncation) so AST parse remains valid.
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
            if not code:
                return hints
            tree = ast.parse(code)
        except Exception:
            return hints

        def _doc_body(doc: str) -> str:
            raw_lines = (doc or '').splitlines()
            # Keep paragraph spacing but trim outer blank lines for a cleaner popup.
            while raw_lines and not raw_lines[0].strip():
                raw_lines.pop(0)
            while raw_lines and not raw_lines[-1].strip():
                raw_lines.pop()
            return '\n'.join(raw_lines).strip()

        def _func_sig(fn_node: ast.AST, name: str) -> str:
            try:
                if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return f'{name}(...)'
                args = []
                for a in fn_node.args.args:
                    if a.arg == 'self':
                        continue
                    args.append(a.arg)
                if fn_node.args.vararg:
                    args.append('*' + fn_node.args.vararg.arg)
                for a in fn_node.args.kwonlyargs:
                    args.append(a.arg)
                if fn_node.args.kwarg:
                    args.append('**' + fn_node.args.kwarg.arg)
                return f"{name}({', '.join(args)})"
            except Exception:
                return f'{name}(...)'

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                doc = ast.get_docstring(node) or ''
                if not doc.strip():
                    continue
                body = _doc_body(doc)
                sig = _func_sig(node, name)
                hints[name] = f"{sig}\n{body}" if body else sig
                continue

            if isinstance(node, ast.ClassDef):
                name = node.name
                class_doc = ast.get_docstring(node) or ''
                init_node = next((n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == '__init__'), None)
                init_doc = ast.get_docstring(init_node) if init_node is not None else ''
                doc = class_doc or init_doc or ''
                if not doc.strip():
                    continue
                body = _doc_body(doc)
                sig = _func_sig(init_node, name) if init_node is not None else f'{name}(...)'
                hints[name] = f"{sig}\n{body}" if body else sig

        return hints

    def _build_ui(self):
        self.config_bar = WindowConfigBar(
            self.config,
            hook_display=HOOK_DISPLAY,
            license_types=list(LICENSE_DATA.keys()),
        )

        # Canvas in a scroll area
        self.canvas = CanvasWidget(
            self.config,
            widget_specs=WIDGET_SPECS,
            widget_container_cls=WidgetContainer,
            chrome_title_h=CHROME_TITLE_H,
            chrome_msg_h=CHROME_MSG_H,
            chrome_side_w=CHROME_SIDE_W,
            cell_gap=CELL_GAP,
        )
        self.canvas_scroll = PannableScrollArea()
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas_scroll.setWidgetResizable(False)
        self.canvas_scroll.setAlignment(Qt.AlignCenter)
        self.canvas_scroll.setStyleSheet('QScrollArea { background: #171717; }')

        self.window_tabs = QTabBar()
        self.window_tabs.setMovable(False)
        self.window_tabs.setTabsClosable(True)
        # Selected tab highlight for clearer active-window context.
        self.window_tabs.setStyleSheet(
            """
            QTabBar::tab {
                background: #262626;
                color: #bdbdbd;
                border: 1px solid #3f3f3f;
                padding: 4px 10px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #343434;
                color: #d0d0d0;
                border: 1px solid #4a4a4a;
            }
            QTabBar::tab:hover {
                background: #2e2e2e;
            }
            """
        )
        self.window_tabs.tabCloseRequested.connect(self.action_remove_window_tab)
        self.window_tabs.tabBarDoubleClicked.connect(self._on_window_tab_double_clicked)
        self.window_tabs.currentChanged.connect(self._on_window_tab_changed)
        self.window_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.window_tabs.customContextMenuRequested.connect(self._show_window_tab_menu)

        self.window_add_btn = QPushButton('+')
        self.window_add_btn.setFixedSize(24, 22)
        self.window_add_btn.setToolTip('Add Window')
        self.window_add_btn.clicked.connect(self.action_add_window_tab)

        self.window_remove_btn = QPushButton('−')
        self.window_remove_btn.setFixedSize(24, 22)
        self.window_remove_btn.setToolTip('Remove Current Window')
        self.window_remove_btn.clicked.connect(lambda: self.action_remove_window_tab(self.active_window_index))

        self.window_tab_row = QWidget()
        tab_row_layout = QHBoxLayout(self.window_tab_row)
        tab_row_layout.setContentsMargins(0, 0, 0, 0)
        tab_row_layout.setSpacing(4)
        tab_row_layout.addWidget(self.window_tabs, 1)
        tab_row_layout.addWidget(self.window_add_btn)
        tab_row_layout.addWidget(self.window_remove_btn)

        self._rebuild_window_tabs()

        # Palette
        self.palette = WidgetPalette(widget_specs=WIDGET_SPECS)
        self.palette_panel = QWidget()
        self.palette_panel.setObjectName('WidgetPalettePanelFrame')
        palette_layout = QVBoxLayout(self.palette_panel)
        palette_layout.setContentsMargins(4, 4, 4, 4)
        palette_layout.setSpacing(4)
        palette_title = QLabel('Widgets')
        palette_title.setStyleSheet('color: #888; font-size: 11px; padding: 4px 4px 2px;')
        palette_layout.addWidget(palette_title)
        palette_layout.addWidget(self.palette)

        # Properties
        self.props = PropertiesPanel(
            widget_specs=WIDGET_SPECS,
            parse_template_callbacks=_parse_template_callbacks,
            widget_factory=WidgetContainer,
        )
        self.props_frame = QFrame()
        self.props_frame.setObjectName('PropertiesPanelFrame')
        self.props_frame.setFrameShape(QFrame.NoFrame)
        _pf_layout = QVBoxLayout(self.props_frame)
        _pf_layout.setContentsMargins(0, 0, 0, 0)
        _pf_layout.setSpacing(0)
        _pf_layout.addWidget(self.props)

        # Right pane: palette (top) + properties (bottom)
        self.right_split = QSplitter(Qt.Vertical)
        self.right_split.addWidget(self.palette_panel)
        self.right_split.addWidget(self.props_frame)
        self.right_split.setStretchFactor(0, 1)
        self.right_split.setStretchFactor(1, 3)
        # Tune default vertical split: reduce Properties height ~20% from prior default.
        self.right_split.setSizes([344, 496])

        # Live preview panel (left)
        self.preview_panel = QWidget()
        self.preview_panel.setObjectName('CodePreviewPanelFrame')
        pv = QVBoxLayout(self.preview_panel)
        pv.setContentsMargins(6, 6, 6, 6)
        pv.setSpacing(6)

        preview_title = QLabel('Code Editor')
        preview_title.setStyleSheet('color: #888; font-size: 11px; padding: 2px 2px 0px;')
        pv.addWidget(preview_title)

        preview_controls = QHBoxLayout()
        self.preview_auto_check = QCheckBox('Auto Update Code')
        self.preview_auto_check.setChecked(True)
        self.preview_auto_check.toggled.connect(self._set_preview_auto)
        self.preview_export_btn = QPushButton('Export')
        self.preview_export_btn.clicked.connect(self._generate_script)
        self.preview_close_btn = QPushButton('✕')
        self.preview_close_btn.setFixedWidth(28)
        self.preview_close_btn.clicked.connect(lambda: self._set_preview_visible(False))
        preview_controls.addWidget(self.preview_auto_check)
        preview_controls.addStretch()
        preview_controls.addWidget(self.preview_export_btn)
        preview_controls.addWidget(self.preview_close_btn)
        pv.addLayout(preview_controls)

        self.find_bar = QWidget()
        self.find_bar.setObjectName('CodeFindBar')
        self.find_bar.setStyleSheet(
            '#CodeFindBar { background: #232323; border: 1px solid #3a3a3a; border-radius: 3px; }'
            '#CodeFindBar QLabel { color: #9a9a9a; }'
        )
        fb = QVBoxLayout(self.find_bar)
        fb.setContentsMargins(8, 6, 8, 6)
        fb.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        find_lbl = QLabel('Find')
        repl_lbl = QLabel('Replace')

        self.find_input = QComboBox()
        self.find_input.setEditable(True)
        self.find_input.setMinimumWidth(260)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText('Replacement text')
        self.replace_input.setMinimumWidth(260)

        self.find_bar_match_case = QCheckBox('Match Case')
        self.find_bar_whole_word = QCheckBox('Whole Word')
        self.find_bar_regex = QCheckBox('Regex')
        self.find_bar_sel_only = QCheckBox('In Selection')
        self.find_bar_match_case.setToolTip('Case-sensitive search')
        self.find_bar_whole_word.setToolTip('Match whole words only')
        self.find_bar_regex.setToolTip('Use regular expression pattern')
        self.find_bar_sel_only.setToolTip('Apply replace operations to current selection only')

        self.find_prev_btn = QPushButton('Prev')
        self.find_next_btn = QPushButton('Next')
        self.find_rep_btn = QPushButton('Replace')
        self.find_rep_all_btn = QPushButton('Replace All')

        self.find_close_btn = QPushButton('✕')
        self.find_close_btn.setFixedWidth(28)
        self.find_close_btn.setToolTip('Close find bar')

        row1.addWidget(find_lbl)
        row1.addWidget(self.find_input, 1)
        row1.addWidget(self.find_prev_btn)
        row1.addWidget(self.find_next_btn)
        row1.addWidget(self.find_close_btn)

        row2.addWidget(repl_lbl)
        row2.addWidget(self.replace_input, 1)
        row2.addWidget(self.find_rep_btn)
        row2.addWidget(self.find_rep_all_btn)
        row2.addWidget(self.find_bar_match_case)
        row2.addWidget(self.find_bar_whole_word)
        row2.addWidget(self.find_bar_regex)
        row2.addWidget(self.find_bar_sel_only)

        fb.addLayout(row1)
        fb.addLayout(row2)

        self.find_bar.setVisible(False)
        pv.addWidget(self.find_bar)

        self.preview_text = SpacesTabPlainTextEdit()
        self.preview_text.setReadOnly(False)
        self.preview_text.setPlaceholderText('Generated code appears here. You can edit manually.')
        hover_hints = {
            'PyFlameWindow': 'PyFlameWindow(...)\nMain application window container.\nCommon args: title, parent, grid_layout_columns, grid_layout_rows, window_margins.',
            'Color': 'Color enum\nUsed by color-capable widgets (buttons/lines/etc).',
            'Align': 'Align enum\nText alignment options: LEFT, CENTER, RIGHT.',
            'Style': 'Style enum\nVisual style variants used by selected widgets.',
            'TextType': 'TextType enum\nText format: PLAIN / MARKDOWN / HTML.',
            'TextStyle': 'TextStyle enum\nText behavior: EDITABLE / READ_ONLY / UNSELECTABLE.',
            'BrowserType': 'BrowserType enum\nEntry browser mode: FILE or DIRECTORY.',
        }
        # Enrich hints from pyflame_lib docstrings when available.
        hover_hints.update(self._extract_hover_hints_from_pyflame_lib(PYFLAME_LIB_PATH))

        for wt, spec in WIDGET_SPECS.items():
            display = spec.get('display', wt)
            hover_hints.setdefault(wt, f'{wt}(...)\nWidget: {display}')
        self.preview_text.set_hover_hints(hover_hints)
        self.preview_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_text.setStyleSheet(self._preview_style())
        pv.addWidget(self.preview_text)

        self.preview_status_label = QLabel('Ln 1, Col 1 | Sel 0 | generated')
        self.preview_status_label.setStyleSheet('color: #888; font-size: 10px; padding: 2px 2px 0px;')
        pv.addWidget(self.preview_status_label)

        # Center pane: canvas area + local bottom zoom controls
        self.center_pane = QWidget()
        center_layout = QVBoxLayout(self.center_pane)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        ui_title = QLabel('UI Preview')
        ui_title.setStyleSheet('color: #888; font-size: 11px; padding: 4px 4px 2px;')
        center_layout.addWidget(ui_title)
        center_layout.addWidget(self.window_tab_row)
        center_layout.addWidget(self.canvas_scroll)

        self.zoom_bar = QWidget()
        zoom_layout = QHBoxLayout(self.zoom_bar)
        zoom_layout.setContentsMargins(8, 4, 8, 4)
        zoom_layout.setSpacing(6)
        self.grid_toggle_btn = QPushButton('Grid: Off')
        self.grid_toggle_btn.setFixedHeight(22)
        self.grid_toggle_btn.clicked.connect(self.action_toggle_grid_visibility)
        zoom_layout.addWidget(self.grid_toggle_btn)

        self.preview_mode_btn = QPushButton('Preview: Off')
        self.preview_mode_btn.setFixedHeight(22)
        self.preview_mode_btn.clicked.connect(self.action_toggle_preview_mode)
        zoom_layout.addWidget(self.preview_mode_btn)

        zoom_layout.addStretch()

        zoom_label = QLabel('Zoom:')
        zoom_label.setStyleSheet('color: #888; font-size: 10px;')
        zoom_layout.addWidget(zoom_label)

        self.zoom_out_btn = QPushButton('−')
        self.zoom_out_btn.setFixedWidth(28)
        self.zoom_out_btn.setFixedHeight(22)
        self.zoom_out_btn.clicked.connect(self.action_zoom_out)
        zoom_layout.addWidget(self.zoom_out_btn)

        self.zoom_reset_btn = QPushButton('100%')
        self.zoom_reset_btn.setFixedHeight(22)
        self.zoom_reset_btn.clicked.connect(self.action_zoom_reset)
        zoom_layout.addWidget(self.zoom_reset_btn)

        self.zoom_fit_btn = QPushButton('Fit')
        self.zoom_fit_btn.setFixedHeight(22)
        self.zoom_fit_btn.clicked.connect(self.action_zoom_fit)
        zoom_layout.addWidget(self.zoom_fit_btn)

        self.zoom_in_btn = QPushButton('+')
        self.zoom_in_btn.setFixedWidth(28)
        self.zoom_in_btn.setFixedHeight(22)
        self.zoom_in_btn.clicked.connect(self.action_zoom_in)
        zoom_layout.addWidget(self.zoom_in_btn)


        center_layout.addWidget(self._separator())
        center_layout.addWidget(self.zoom_bar)

        # Main horizontal splitter  (preview | canvas | properties)
        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.addWidget(self.preview_panel)
        self.main_split.addWidget(self.center_pane)
        self.main_split.addWidget(self.right_split)
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setStretchFactor(2, 0)
        self.main_split.setCollapsible(2, False)
        self.main_split.splitterMoved.connect(self._clamp_right_panel)
        self.main_split.setSizes([420, 900, 320])
        main_split = self.main_split

        # Central layout
        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self.config_bar)
        vbox.addWidget(self._separator())
        vbox.addWidget(main_split)

        self.setCentralWidget(central)
        self._set_active_panel(None)
        self._update_mode_toggle_button_styles()

    def _separator(self):
        f = QFrame()
        # Use a plain 1px block instead of QFrame.HLine so Qt palette doesn't
        # draw a bright bevel line on some platforms/themes.
        f.setFrameShape(QFrame.NoFrame)
        f.setFixedHeight(1)
        f.setStyleSheet('background-color: #3f3f3f; border: none;')
        return f

    def _build_menu(self):
        """Build top-level menus and action wiring."""
        mb = self.menuBar()
        mb.setNativeMenuBar(False)

        # File menu: project lifecycle + import/export script flows.
        fm = mb.addMenu('File')

        new_a = QAction('New', self)
        new_a.setShortcut(QKeySequence.New)
        new_a.triggered.connect(self._new)
        fm.addAction(new_a)

        load_a = QAction('Load Project...', self)
        load_a.setShortcut(QKeySequence.Open)
        load_a.triggered.connect(self._open)
        fm.addAction(load_a)

        self._recent_menu = fm.addMenu('Load Recent Project')
        self._rebuild_recent_menu()

        fm.addSeparator()

        save_a = QAction('Save Project', self)
        save_a.setShortcut(QKeySequence.Save)
        save_a.triggered.connect(self._save)
        fm.addAction(save_a)

        saveas_a = QAction('Save Project As...', self)
        saveas_a.setShortcut(QKeySequence('Ctrl+Shift+S'))
        saveas_a.triggered.connect(self._save_as)
        fm.addAction(saveas_a)

        fm.addSeparator()

        generate_a = QAction('Export Script...', self)
        generate_a.setShortcut(QKeySequence('Ctrl+Shift+G'))
        generate_a.triggered.connect(self._generate_script)
        fm.addAction(generate_a)

        export_ui_only_a = QAction('Export UI Code Only...', self)
        export_ui_only_a.triggered.connect(self._export_ui_code_only)
        fm.addAction(export_ui_only_a)

        fm.addSeparator()

        exit_a = QAction('Exit', self)
        exit_a.setShortcut(QKeySequence.Quit)
        exit_a.triggered.connect(self.close)
        fm.addAction(exit_a)

        # Edit menu: undo/redo, window tabs, and code-edit helpers.
        self.edit_menu = mb.addMenu('Edit')
        self.undo_action = QAction('Undo', self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.action_undo)

        self.redo_action = QAction('Redo', self)
        self.redo_action.setShortcut(QKeySequence('Ctrl+Shift+Z'))
        self.redo_action.triggered.connect(self.action_redo)

        self.comment_selection_action = QAction('Comment Selection', self)
        self.comment_selection_action.triggered.connect(self.action_comment_selection)

        self.uncomment_selection_action = QAction('Uncomment Selection', self)
        self.uncomment_selection_action.triggered.connect(self.action_uncomment_selection)

        self.toggle_comment_selection_action = QAction('Toggle Comment Selection', self)
        self.toggle_comment_selection_action.setShortcut(QKeySequence('Ctrl+/'))
        self.toggle_comment_selection_action.triggered.connect(self.action_toggle_comment_selection)

        self.find_action = QAction('Find...', self)
        self.find_action.setShortcut(QKeySequence('Ctrl+F'))
        self.find_action.triggered.connect(self.action_find)

        self.find_next_action = QAction('Find Next', self)
        self.find_next_action.setShortcut(QKeySequence('F3'))
        self.find_next_action.triggered.connect(self.action_find_next)

        self.find_prev_action = QAction('Find Previous', self)
        self.find_prev_action.setShortcut(QKeySequence('Shift+F3'))
        self.find_prev_action.triggered.connect(self.action_find_previous)

        self.replace_action = QAction('Replace...', self)
        self.replace_action.setShortcut(QKeySequence('Ctrl+H'))
        self.replace_action.triggered.connect(self.action_replace)

        self.goto_line_action = QAction('Go to Line...', self)
        self.goto_line_action.setShortcut(QKeySequence('Ctrl+L'))
        self.goto_line_action.triggered.connect(self.action_go_to_line)

        self.find_match_case_action = QAction('Match Case', self)
        self.find_match_case_action.setCheckable(True)
        self.find_match_case_action.setChecked(self._find_match_case)
        self.find_match_case_action.toggled.connect(self._set_find_match_case)

        self.find_whole_word_action = QAction('Whole Word', self)
        self.find_whole_word_action.setCheckable(True)
        self.find_whole_word_action.setChecked(self._find_whole_word)
        self.find_whole_word_action.toggled.connect(self._set_find_whole_word)

        self.find_regex_action = QAction('Regex Mode', self)
        self.find_regex_action.setCheckable(True)
        self.find_regex_action.setChecked(self._find_regex)
        self.find_regex_action.toggled.connect(self._set_find_regex)

        self.replace_in_selection_action = QAction('Replace in Selection', self)
        self.replace_in_selection_action.setCheckable(True)
        self.replace_in_selection_action.setChecked(self._replace_in_selection)
        self.replace_in_selection_action.toggled.connect(self._set_replace_in_selection)

        self.inline_find_action = QAction('Inline Find Bar', self)
        self.inline_find_action.setShortcut(QKeySequence('Ctrl+Shift+F'))
        self.inline_find_action.triggered.connect(self.action_toggle_inline_find_bar)

        self.duplicate_line_action = QAction('Duplicate Line / Selection', self)
        self.duplicate_line_action.setShortcut(QKeySequence('Ctrl+D'))
        self.duplicate_line_action.triggered.connect(self.action_duplicate_selection_or_line)

        self.move_line_up_action = QAction('Move Line / Selection Up', self)
        self.move_line_up_action.setShortcut(QKeySequence('Alt+Up'))
        self.move_line_up_action.triggered.connect(lambda: self.action_move_selection_or_line(-1))

        self.move_line_down_action = QAction('Move Line / Selection Down', self)
        self.move_line_down_action.setShortcut(QKeySequence('Alt+Down'))
        self.move_line_down_action.triggered.connect(lambda: self.action_move_selection_or_line(1))

        self.trim_whitespace_action = QAction('Trim Trailing Whitespace', self)
        self.trim_whitespace_action.triggered.connect(self.action_trim_trailing_whitespace)

        self.normalize_tabs_action = QAction('Normalize Tabs to Spaces', self)
        self.normalize_tabs_action.triggered.connect(self.action_normalize_tabs_to_spaces)

        self.toggle_bookmark_action = QAction('Toggle Bookmark', self)
        self.toggle_bookmark_action.setShortcut(QKeySequence('F2'))
        self.toggle_bookmark_action.triggered.connect(self.action_toggle_bookmark)

        self.next_bookmark_action = QAction('Next Bookmark', self)
        self.next_bookmark_action.setShortcut(QKeySequence('Ctrl+F2'))
        self.next_bookmark_action.triggered.connect(self.action_next_bookmark)

        self.prev_bookmark_action = QAction('Previous Bookmark', self)
        self.prev_bookmark_action.setShortcut(QKeySequence('Ctrl+Shift+F2'))
        self.prev_bookmark_action.triggered.connect(self.action_prev_bookmark)

        self.cursor_back_action = QAction('Cursor Back', self)
        self.cursor_back_action.setShortcut(QKeySequence('Alt+Left'))
        self.cursor_back_action.triggered.connect(lambda: self.action_cursor_history(-1))

        self.cursor_forward_action = QAction('Cursor Forward', self)
        self.cursor_forward_action.setShortcut(QKeySequence('Alt+Right'))
        self.cursor_forward_action.triggered.connect(lambda: self.action_cursor_history(1))

        self.open_symbol_action = QAction('Open Symbol...', self)
        self.open_symbol_action.setShortcut(QKeySequence('Ctrl+Shift+O'))
        self.open_symbol_action.triggered.connect(self.action_open_symbol)

        self.fold_current_action = QAction('Fold/Unfold Current Block', self)
        self.fold_current_action.setShortcut(QKeySequence('Ctrl+Shift+['))
        self.fold_current_action.triggered.connect(self.action_toggle_fold_current)

        self.unfold_all_action = QAction('Unfold All Blocks', self)
        self.unfold_all_action.setShortcut(QKeySequence('Ctrl+Shift+]'))
        self.unfold_all_action.triggered.connect(self.action_unfold_all)

        self.lint_check_action = QAction('Lint Check', self)
        self.lint_check_action.triggered.connect(self.action_lint_check)

        self.snapshot_compare_action = QAction('Compare Generated vs Editor...', self)
        self.snapshot_compare_action.triggered.connect(self.action_snapshot_compare)

        self.add_window_action = QAction('Add Window...', self)
        self.add_window_action.setShortcut(QKeySequence('Ctrl+T'))
        self.add_window_action.triggered.connect(self.action_add_window_tab)

        self.rename_window_action = QAction('Rename Current Window...', self)
        self.rename_window_action.triggered.connect(lambda: self.action_rename_window_tab(self.active_window_index))

        self.remove_window_action = QAction('Remove Current Window...', self)
        self.remove_window_action.triggered.connect(lambda: self.action_remove_window_tab(self.active_window_index))

        self._refresh_edit_menu()
        self.edit_menu.aboutToShow.connect(self._refresh_edit_menu)

        # View menu: preview visibility + inspection actions.
        vm = mb.addMenu('View')
        preview_a = QAction('Preview Code...', self)
        preview_a.setShortcut(QKeySequence('Ctrl+G'))
        preview_a.triggered.connect(self._generate_code)
        vm.addAction(preview_a)

        self.toggle_preview_action = QAction('Show Code Editor', self)
        self.toggle_preview_action.setCheckable(True)
        self.toggle_preview_action.setChecked(True)
        self.toggle_preview_action.toggled.connect(self._set_preview_visible)
        vm.addAction(self.toggle_preview_action)

        vm.addSeparator()
        reset_layout_action = QAction('Reset Layout to Default', self)
        reset_layout_action.triggered.connect(self.action_reset_layout)
        vm.addAction(reset_layout_action)

        # Help menu: docs, what's-new, and app metadata.
        hm = mb.addMenu('Help')

        whats_new_menu = hm.addMenu("What's New")
        versions = self._list_whats_new_versions()
        if versions:
            for ver in versions:
                act = QAction(ver, self)
                act.triggered.connect(lambda checked=False, v=ver: self.action_open_whats_new(v))
                whats_new_menu.addAction(act)
        else:
            none_act = QAction('No entries', self)
            none_act.setEnabled(False)
            whats_new_menu.addAction(none_act)

        hm.addSeparator()

        getting_started_action = QAction('Getting Started', self)
        getting_started_action.triggered.connect(lambda: self.action_open_help('getting-started.md'))
        hm.addAction(getting_started_action)

        shortcuts_action = QAction('Keyboard Shortcuts', self)
        shortcuts_action.triggered.connect(lambda: self.action_open_help('keyboard-shortcuts.md'))
        hm.addAction(shortcuts_action)

        hm.addSeparator()
        about_action = QAction('About PyFlame UI Builder', self)
        about_action.triggered.connect(self.action_about)
        hm.addAction(about_action)


    def _connect_signals(self):
        """Connect Qt signals to state-mutating handlers."""
        self.config_bar.config_changed.connect(self._on_config_changed)
        self.canvas.widget_selected.connect(self._on_widget_selected)
        self.canvas.widget_moved.connect(self._on_widget_moved)
        self.canvas.grid_changed.connect(self._on_grid_changed)
        self.canvas.content_changed.connect(self._on_canvas_content_changed)
        self.props.properties_changed.connect(self._on_properties_changed)
        self.props.panel_interacted.connect(lambda: self._set_active_panel('props'))
        self.preview_text.textChanged.connect(self._on_preview_text_changed)
        self.preview_text.cursorPositionChanged.connect(self._update_editor_status)
        self.preview_text.protectedEditAttempted.connect(self._on_protected_edit_attempted)
        self.preview_text.duplicateRequested.connect(self.action_duplicate_selection_or_line)
        self.preview_text.moveUpRequested.connect(lambda: self.action_move_selection_or_line(-1))
        self.preview_text.moveDownRequested.connect(lambda: self.action_move_selection_or_line(1))
        self.preview_text.bookmarkToggleRequested.connect(self.action_toggle_bookmark)
        self.preview_text.bookmarkNextRequested.connect(self.action_next_bookmark)
        self.preview_text.bookmarkPrevRequested.connect(self.action_prev_bookmark)
        self.preview_text.foldToggleRequested.connect(self.action_toggle_fold_current)
        self.palette.currentItemChanged.connect(self._on_palette_item_selected)
        self.palette.itemClicked.connect(lambda _item: self._on_palette_item_selected(self.palette.currentItem(), None))
        self.palette.itemSelectionChanged.connect(lambda: self._on_palette_item_selected(self.palette.currentItem(), None))
        self.find_next_btn.clicked.connect(self.action_find_next)
        self.find_prev_btn.clicked.connect(self.action_find_previous)
        self.find_rep_btn.clicked.connect(lambda: self.action_replace(one_only=True))
        self.find_rep_all_btn.clicked.connect(lambda: self.action_replace(one_only=False))
        self.find_close_btn.clicked.connect(lambda: self.find_bar.setVisible(False))
        self.find_bar_match_case.toggled.connect(self._set_find_match_case)
        self.find_bar_whole_word.toggled.connect(self._set_find_whole_word)
        self.find_bar_regex.toggled.connect(self._set_find_regex)
        self.find_bar_sel_only.toggled.connect(self._set_replace_in_selection)
        self._preview_highlighter = PythonSyntaxHighlighter(self.preview_text.document())
        self._refresh_preview()
        self._update_editor_status()
        self._apply_preview_lockdown()

    # ── local preview API (expandable) ───────────────────────────────────────

    def _start_preview_api_if_enabled(self):
        # Local code toggle + env override.
        # - Default follows PREVIEW_API_ENABLED.
        # - Set PYFLAME_UI_API=1/on/true/yes to force-enable.
        # - Set PYFLAME_UI_API=0/off/false/no to force-disable.
        enabled = bool(PREVIEW_API_ENABLED)
        enabled_env = os.getenv('PYFLAME_UI_API', '').strip().lower()
        if enabled_env in {'1', 'true', 'yes', 'on'}:
            enabled = True
        elif enabled_env in {'0', 'false', 'no', 'off'}:
            enabled = False
        if not enabled:
            return

        host = os.getenv('PYFLAME_UI_API_HOST', '127.0.0.1').strip() or '127.0.0.1'
        try:
            port = int(os.getenv('PYFLAME_UI_API_PORT', '18791'))
        except Exception:
            port = 18791

        app = self

        class _ApiHandler(BaseHTTPRequestHandler):
            def _send_json(self, status_code: int, payload: dict):
                body = json.dumps(payload).encode('utf-8')
                self.send_response(status_code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ('/health', '/api/health'):
                    self._send_json(200, {'ok': True})
                    return
                if self.path in ('/preview', '/api/preview'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('get_preview', None, event, box))
                    if not event.wait(timeout=2.0):
                        self._send_json(504, {'ok': False, 'error': 'preview request timed out'})
                        return
                    self._send_json(200, {'ok': True, **box})
                    return
                if self.path in ('/state', '/api/state'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('get_state', None, event, box))
                    if not event.wait(timeout=2.0):
                        self._send_json(504, {'ok': False, 'error': 'state request timed out'})
                        return
                    self._send_json(200, {'ok': True, **box})
                    return
                self._send_json(404, {'ok': False, 'error': 'not found'})

            def do_POST(self):
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    raw = self.rfile.read(length) if length > 0 else b'{}'
                    payload = json.loads(raw.decode('utf-8') or '{}')
                except Exception as e:
                    self._send_json(400, {'ok': False, 'error': f'invalid json: {e}'})
                    return

                if self.path in ('/preview', '/api/preview'):
                    code = payload.get('code')
                    if not isinstance(code, str):
                        self._send_json(400, {'ok': False, 'error': 'code must be a string'})
                        return
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('set_preview', {'code': code}, event, box))
                elif self.path in ('/new', '/api/new'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('new_project', payload or {}, event, box))
                elif self.path in ('/import', '/api/import'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('import_script', payload or {}, event, box))
                elif self.path in ('/export', '/api/export'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('export_script', payload or {}, event, box))
                elif self.path in ('/widget/add', '/api/widget/add'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('widget_add', payload or {}, event, box))
                elif self.path in ('/widget/move', '/api/widget/move'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('widget_move', payload or {}, event, box))
                elif self.path in ('/widget/props', '/api/widget/props'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('widget_props', payload or {}, event, box))
                elif self.path in ('/window/props', '/api/window/props'):
                    event = threading.Event()
                    box: dict = {}
                    app._api_queue.put(('window_props', payload or {}, event, box))
                else:
                    self._send_json(404, {'ok': False, 'error': 'not found'})
                    return

                if not event.wait(timeout=10.0):
                    self._send_json(504, {'ok': False, 'error': 'api request timed out'})
                    return
                ok = bool(box.get('ok', True) and not box.get('error'))
                self._send_json(200 if ok else 400, {'ok': ok, **box})

            def log_message(self, fmt, *args):
                return

        try:
            self._api_server = ThreadingHTTPServer((host, port), _ApiHandler)
        except Exception as e:
            _bootstrap_logger.warning('Preview API failed to start on %s:%s (%s)', host, port, e)
            return

        self._api_thread = threading.Thread(target=self._api_server.serve_forever, daemon=True)
        self._api_thread.start()
        _bootstrap_logger.info('Preview API listening on http://%s:%s', host, port)

    def _process_api_requests(self):
        """Handle queued API actions on the Qt thread.

        API HTTP handlers enqueue requests from background threads; this method
        performs UI mutations safely on the main thread.
        """
        while True:
            try:
                action, payload, event, box = self._api_queue.get_nowait()
            except queue.Empty:
                break

            try:
                if action == 'get_preview':
                    box.update(
                        {
                            'code': self.preview_text.toPlainText(),
                            'dirty': bool(self._dirty),
                            'source': 'imported' if self._raw_import_code is not None else 'generated',
                        }
                    )
                elif action == 'get_state':
                    self._persist_active_window()
                    box.update(
                        {
                            'active_window_index': self.active_window_index,
                            'windows': [
                                {
                                    'function_name': w.function_name,
                                    'grid_columns': w.grid_columns,
                                    'grid_rows': w.grid_rows,
                                    'window_title': getattr(w, 'window_title', None),
                                    'parent_window': getattr(w, 'parent_window', None),
                                    'window_margins': getattr(w, 'window_margins', 15),
                                    'widgets': [
                                        {
                                            'widget_type': x.widget_type,
                                            'var_name': x.var_name,
                                            'row': x.row,
                                            'col': x.col,
                                            'row_span': x.row_span,
                                            'col_span': x.col_span,
                                            'properties': x.properties,
                                            'code_error': bool(getattr(x, '_code_error', False)),
                                        }
                                        for x in w.widgets
                                    ],
                                }
                                for w in self.windows
                            ],
                        }
                    )
                elif action == 'set_preview':
                    code = str((payload or {}).get('code', ''))
                    ok_protected, msg_protected = self._api_validate_protected_update(code)
                    if not ok_protected:
                        box.update({'ok': False, 'message': msg_protected})
                    else:
                        self._set_active_panel('preview')
                        self._raw_import_code = code
                        self._set_preview_text_programmatic(code)
                        self._center_and_highlight_preview_api_write()
                        self._preview_user_edited = True
                        self._last_preview_code = code
                        # Keep UI preview in sync for API code edits as well.
                        self._sync_canvas_from_preview_code_best_effort()
                        self._dirty_mark()
                        box.update({'updated': True, 'length': len(code)})
                elif action == 'new_project':
                    self._new_project_no_prompt()
                    box.update({'ok': True})
                elif action == 'import_script':
                    path = str((payload or {}).get('path', ''))
                    ok, msg = self._import_script_from_path(path, interactive=False)
                    box.update({'ok': ok, 'message': msg})
                elif action == 'export_script':
                    output_dir = str((payload or {}).get('output_dir', ''))
                    overwrite = bool((payload or {}).get('overwrite', True))
                    ok, msg = self._export_script_to_dir(output_dir, overwrite=overwrite, interactive=False, reveal=False)
                    box.update({'ok': ok, 'message': msg})
                elif action == 'widget_add':
                    ok, msg = self._api_widget_add(payload or {})
                    box.update({'ok': ok, 'message': msg})
                elif action == 'widget_move':
                    ok, msg = self._api_widget_move(payload or {})
                    box.update({'ok': ok, 'message': msg})
                elif action == 'widget_props':
                    self._set_active_panel('props')
                    ok, msg = self._api_widget_props(payload or {})
                    box.update({'ok': ok, 'message': msg})
                elif action == 'window_props':
                    self._set_active_panel('props')
                    ok, msg = self._api_window_props(payload or {})
                    box.update({'ok': ok, 'message': msg})
                else:
                    box.update({'error': f'unknown action: {action}'})
            except Exception as e:
                box.update({'error': str(e)})
            finally:
                event.set()

    def _api_find_container(self, var_name: str):
        vn = (var_name or '').strip()
        for c in self.canvas.containers:
            if (c.model.var_name or '').strip() == vn:
                return c
        return None

    def _api_apply_dirty_refresh(self):
        self._raw_import_code = None
        self._dirty_mark()
        self._schedule_preview_update(center_on_change=False)
        self._record_history_state()

    def _api_validate_protected_update(self, new_code: str) -> tuple[bool, str]:
        """Reject API code edits that modify protected Window Build blocks.

        Protected regions are editor-owned UI/layout structure. Widget/layout changes
        must go through widget/window API endpoints instead of raw code writes.
        """
        try:
            ranges = self.preview_text._protected_ranges()
        except Exception:
            ranges = []
        if not ranges:
            return True, ''

        old_code = self.preview_text.toPlainText()
        for start, end in ranges:
            if start < 0 or end < start:
                continue
            if end > len(old_code) or end > len(new_code):
                return False, 'API code edit rejected: protected Window Build blocks are read-only; use /api/widget/* or /api/window/props.'
            if old_code[start:end] != new_code[start:end]:
                return False, 'API code edit rejected: protected Window Build blocks are read-only; use /api/widget/* or /api/window/props.'
        return True, ''

    def _api_widget_add(self, payload: dict) -> tuple[bool, str]:
        widget_type = str(payload.get('widget_type', '')).strip()
        if not widget_type:
            return False, 'widget_type is required'

        window_index = payload.get('window_index', None)
        if window_index is not None:
            try:
                idx = max(0, min(int(window_index), len(self.windows) - 1))
            except Exception:
                return False, 'invalid window_index'
            self.active_window_index = idx
            self._sync_canvas_from_active_window()

        try:
            row = int(payload.get('row', 0))
            col = int(payload.get('col', 0))
        except Exception:
            return False, 'row/col must be integers'

        before = len(self.canvas.containers)
        self.canvas._add_widget(widget_type, row, col)
        if len(self.canvas.containers) <= before:
            return False, 'failed to add widget (type/overlap/position)'

        c = self.canvas.containers[-1]
        if payload.get('var_name'):
            c.model.var_name = str(payload.get('var_name'))
            try:
                c.replace_inner_widget(WidgetContainer.make_widget(c.model.widget_type, c.model.properties))
            except Exception:
                pass
        self._persist_active_window()
        self._api_apply_dirty_refresh()
        return True, c.model.var_name or 'widget added'

    def _api_widget_move(self, payload: dict) -> tuple[bool, str]:
        c = self._api_find_container(str(payload.get('var_name', '')))
        if c is None:
            return False, 'widget not found by var_name'

        m = c.model
        try:
            row = int(payload.get('row', m.row))
            col = int(payload.get('col', m.col))
            row_span = int(payload.get('row_span', m.row_span))
            col_span = int(payload.get('col_span', m.col_span))
        except Exception:
            return False, 'row/col/row_span/col_span must be integers'

        row_span = max(1, row_span)
        col_span = max(1, col_span)
        row = max(0, min(row, self.config.grid_rows - row_span))
        col = max(0, min(col, self.config.grid_columns - col_span))

        if self.canvas._has_overlap(row, col, row_span, col_span, ignore_container=c):
            return False, 'target position overlaps another widget'

        m.row, m.col, m.row_span, m.col_span = row, col, row_span, col_span
        c.setGeometry(self.canvas.cell_rect(row, col, row_span, col_span))
        self.canvas.widget_moved.emit(c)
        self._persist_active_window()
        self._api_apply_dirty_refresh()
        return True, 'widget moved'

    def _api_widget_props(self, payload: dict) -> tuple[bool, str]:
        c = self._api_find_container(str(payload.get('var_name', '')))
        if c is None:
            return False, 'widget not found by var_name'

        props = payload.get('properties', {})
        if not isinstance(props, dict):
            return False, 'properties must be an object'

        c.model.properties.update(props)
        if 'new_var_name' in payload:
            c.model.var_name = str(payload.get('new_var_name') or c.model.var_name)

        try:
            c.replace_inner_widget(WidgetContainer.make_widget(c.model.widget_type, c.model.properties))
        except Exception as e:
            return False, f'failed to rebuild widget: {e}'

        self._persist_active_window()
        self._api_apply_dirty_refresh()
        return True, 'widget properties updated'

    def _api_window_props(self, payload: dict) -> tuple[bool, str]:
        window_index = payload.get('window_index', self.active_window_index)
        try:
            idx = max(0, min(int(window_index), len(self.windows) - 1))
        except Exception:
            return False, 'invalid window_index'

        self.active_window_index = idx
        w = self.windows[idx]

        if 'title' in payload:
            w.window_title = (str(payload.get('title') or '').strip() or None)

        if 'name' in payload:
            old_name = w.function_name
            name = re.sub(r'[^a-zA-Z0-9_]+', '_', str(payload.get('name') or '').strip()).strip('_') or w.function_name
            if name and name[0].isdigit():
                name = f'window_{name}'
            w.function_name = name
            if old_name != name:
                for ww in self.windows:
                    if getattr(ww, 'parent_window', None) == old_name:
                        ww.parent_window = name

        if 'parent_window' in payload:
            p = payload.get('parent_window')
            if p in (None, '', 'None'):
                w.parent_window = None
            else:
                p = str(p)
                w.parent_window = p if p != w.function_name else None

        try:
            new_cols = int(payload.get('cols', w.grid_columns))
            new_rows = int(payload.get('rows', w.grid_rows))
            new_margins = self._parse_window_margins_value(payload.get('window_margins', getattr(w, 'window_margins', 15)))
        except Exception:
            return False, 'cols/rows must be integers and window_margins must be 1 or 4 integers'
        new_cols = max(1, new_cols)
        new_rows = max(1, new_rows)

        # Remove widgets outside new bounds.
        w.widgets = [x for x in w.widgets if x.row < new_rows and x.col < new_cols]
        for x in w.widgets:
            x.row = max(0, min(x.row, new_rows - 1))
            x.col = max(0, min(x.col, new_cols - 1))
            x.row_span = max(1, min(x.row_span, new_rows - x.row))
            x.col_span = max(1, min(x.col_span, new_cols - x.col))

        w.grid_columns = new_cols
        w.grid_rows = new_rows
        w.window_margins = new_margins
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()
        self._persist_active_window()
        self._api_apply_dirty_refresh()
        return True, 'window properties updated'

    def _current_window(self) -> ScriptWindow:
        if not self.windows:
            self.windows = [ScriptWindow(function_name='main_window', grid_columns=4, grid_rows=3, widgets=[])]
            self.active_window_index = 0
        self.active_window_index = max(0, min(self.active_window_index, len(self.windows) - 1))
        return self.windows[self.active_window_index]

    def _sync_canvas_from_active_window(self):
        """Load active window model into canvas UI."""
        w = self._current_window()
        self.config.grid_columns = max(1, int(getattr(w, 'grid_columns', 4) or 4))
        self.config.grid_rows = max(1, int(getattr(w, 'grid_rows', 3) or 3))
        self.canvas.update_config(self.config)
        self.canvas.set_window_margins(getattr(w, 'window_margins', 15))
        self.canvas.set_window_title_override(getattr(w, 'window_title', None))

        # Clear previous tab widgets from canvas (avoid stale UI when switching tabs).
        for c in list(getattr(self.canvas, 'containers', [])):
            try:
                c.deleteLater()
            except Exception:
                pass
        self.canvas.containers = []
        self.canvas.selected_container = None

        for model in w.widgets:
            try:
                widget = WidgetContainer.make_widget(model.widget_type, model.properties)
                container = WidgetContainer(widget, model, self.canvas)
                container.setGeometry(self.canvas.cell_rect(model.row, model.col, model.row_span, model.col_span))
                container.set_preview_mode(self.canvas.preview_mode)
                container.show()
                self.canvas.containers.append(container)
            except Exception as e:
                print(f'Error restoring widget in tab switch: {e}')

        self.canvas.update()
        self.config_bar.load_config(self.config)
        self._show_active_window_properties()
        self._refresh_preview()

    def _current_models(self) -> list[PlacedWidget]:
        if not hasattr(self, 'canvas'):
            return []
        return [c.model for c in getattr(self.canvas, 'containers', [])]

    def _persist_active_window(self):
        if not self.windows:
            return
        w = self._current_window()
        w.grid_columns = max(1, self.config.grid_columns)
        w.grid_rows = max(1, self.config.grid_rows)
        w.widgets = self._current_models()

    def _rebuild_window_tabs(self):
        if not hasattr(self, 'window_tabs'):
            return
        self.window_tabs.blockSignals(True)
        while self.window_tabs.count() > 0:
            self.window_tabs.removeTab(0)
        for i, w in enumerate(self.windows):
            label = (w.function_name or f'window_{i+1}').replace('_', ' ')
            self.window_tabs.addTab(label)
        if self.windows:
            self.window_tabs.setCurrentIndex(max(0, min(self.active_window_index, len(self.windows)-1)))
            self.window_tabs.setTabsClosable(len(self.windows) > 1)
        can_remove = len(self.windows) > 1
        if hasattr(self, 'window_remove_btn'):
            self.window_remove_btn.setEnabled(can_remove)
        self.window_tabs.blockSignals(False)

    def _default_new_window_name(self) -> str:
        count = sum(1 for w in self.windows if (w.function_name or '').startswith('main_window'))
        return f'main_window_{count + 1}'

    def action_add_window_tab(self):
        default_name = self._default_new_window_name()
        name, ok = QInputDialog.getText(self, 'Add Window', 'Window function name:', text=default_name)
        if not ok:
            return
        fn = re.sub(r'[^a-zA-Z0-9_]+', '_', (name or '').strip()).strip('_') or default_name
        if fn[0].isdigit():
            fn = f'window_{fn}'
        existing = {w.function_name for w in self.windows}
        base = fn
        suffix = 2
        while fn in existing:
            fn = f'{base}_{suffix}'
            suffix += 1
        self._persist_active_window()
        self.windows.append(ScriptWindow(function_name=fn, window_title='New Window', grid_columns=4, grid_rows=3, widgets=[]))
        self.active_window_index = len(self.windows) - 1
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()
        self._dirty_mark()

    def action_remove_window_tab(self, index: int | None = None):
        if len(self.windows) <= 1:
            msg = QMessageBox(self)
            msg.setWindowTitle('Cannot Remove Window')
            msg.setText('At least one window is required. Add another window before removing this one.')
            msg.setIcon(QMessageBox.NoIcon)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            return
        idx = self.active_window_index if index is None else int(index)
        if idx < 0 or idx >= len(self.windows):
            return

        # Safety confirmation: removing a tab deletes that window from exported script.
        label = self.windows[idx].function_name or f'window_{idx+1}'
        msg = QMessageBox(self)
        msg.setWindowTitle('Delete Window?')
        msg.setText(
            f'You are about to delete window "{label}" from this script.\n\n'
            'Do you want to proceed?'
        )
        msg.setIcon(QMessageBox.NoIcon)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        if msg.exec() != QMessageBox.Yes:
            return

        self._persist_active_window()
        self.windows.pop(idx)
        self.active_window_index = max(0, min(idx, len(self.windows) - 1))
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()
        self._dirty_mark()

    def _rename_window_references_in_preview(self, old_name: str, new_name: str):
        if not hasattr(self, 'preview_text'):
            return
        code = self.preview_text.toPlainText()
        if not code.strip() or old_name == new_name:
            return

        old_method = f'create_{old_name}'
        new_method = f'create_{new_name}'

        # Rename method calls/defs and object references conservatively.
        code = re.sub(rf'\b{re.escape(old_method)}\b', new_method, code)
        code = re.sub(rf'\bself\.{re.escape(old_name)}\b', f'self.{new_name}', code)

        self.preview_text.setPlainText(code)

    def action_rename_window_tab(self, index: int | None = None):
        if not self.windows:
            return
        idx = self.active_window_index if index is None else int(index)
        if idx < 0 or idx >= len(self.windows):
            return
        current = self.windows[idx].function_name or f'window_{idx+1}'
        name, ok = QInputDialog.getText(self, 'Rename Window', 'Window function name:', text=current)
        if not ok:
            return
        fn = re.sub(r'[^a-zA-Z0-9_]+', '_', (name or '').strip()).strip('_') or current
        if fn[0].isdigit():
            fn = f'window_{fn}'
        existing = {w.function_name for i, w in enumerate(self.windows) if i != idx}
        base = fn
        suffix = 2
        while fn in existing:
            fn = f'{base}_{suffix}'
            suffix += 1

        old_name = self.windows[idx].function_name
        self.windows[idx].function_name = fn
        if old_name and fn and old_name != fn:
            self._rename_window_references_in_preview(old_name, fn)

        self._rebuild_window_tabs()
        self._dirty_mark()

    def _on_window_tab_changed(self, index: int):
        if index < 0 or index >= len(self.windows):
            return
        if index == self.active_window_index:
            return
        self._persist_active_window()
        self.active_window_index = index
        self._sync_canvas_from_active_window()

    def _on_window_tab_double_clicked(self, index: int):
        if index < 0:
            return
        self.action_rename_window_tab(index)

    def _show_window_tab_menu(self, pos):
        menu = QMenu(self)
        menu.addAction('Add Window', self.action_add_window_tab)
        menu.addAction('Rename Window', lambda: self.action_rename_window_tab(self.window_tabs.tabAt(pos)))
        rm = menu.addAction('Remove Window', lambda: self.action_remove_window_tab(self.window_tabs.tabAt(pos)))
        rm.setEnabled(len(self.windows) > 1)
        menu.exec(self.window_tabs.mapToGlobal(pos))

    # ── signal handlers ───────────────────────────────────────────────────────

    # Lock right sidebar width (Widgets + Properties) to avoid unnecessary horizontal stretching.
    _RIGHT_MIN = 320
    _RIGHT_MAX = 320

    def _clamp_right_panel(self):
        sizes = self.main_split.sizes()
        if len(sizes) < 3:
            return
        right = max(self._RIGHT_MIN, min(self._RIGHT_MAX, sizes[2]))
        if right != sizes[2]:
            total = sum(sizes)
            preview_w = sizes[0]
            center = max(300, total - preview_w - right)
            self.main_split.setSizes([preview_w, center, right])

    def _on_grid_changed(self, config):
        self._raw_import_code = None
        self.config = config
        self._persist_active_window()
        self.config_bar.load_config(config)
        self._dirty = True
        self._update_title()
        self._schedule_preview_update()
        self._record_history_state()

    def _on_config_changed(self, config):
        self._raw_import_code = None
        self.canvas.update_config(config)
        self._persist_active_window()
        self._dirty = True
        self._update_title()
        self._schedule_preview_update()
        self._record_history_state()

    @staticmethod
    def _parse_window_margins_value(raw) -> int | list[int]:
        """Accept one int or four comma-separated ints for window margins."""
        if isinstance(raw, (list, tuple)):
            vals = [int(x) for x in raw]
            if len(vals) == 1:
                return max(0, vals[0])
            if len(vals) == 4:
                return [max(0, v) for v in vals]
            raise ValueError('window_margins must have 1 or 4 values')

        s = str(raw).strip()
        if not s:
            return 15
        if ',' in s:
            parts = [p.strip() for p in s.split(',') if p.strip()]
            vals = [int(p) for p in parts]
            if len(vals) == 1:
                return max(0, vals[0])
            if len(vals) == 4:
                return [max(0, v) for v in vals]
            raise ValueError('window_margins must be one value or four values (l,t,r,b)')
        return max(0, int(s))

    def _show_active_window_properties(self):
        w = self._current_window()

        def _apply_window_grid(cols: int, rows: int, window_margins):
            new_cols = max(1, int(cols))
            new_rows = max(1, int(rows))
            try:
                new_margins = self._parse_window_margins_value(window_margins)
            except Exception:
                self._show_active_window_properties()
                return
            cur_cols = int(self.config.grid_columns)
            cur_rows = int(self.config.grid_rows)

            # If shrinking grid would remove occupied rows/cols, warn first.
            if new_rows < cur_rows or new_cols < cur_cols:
                affected = [
                    c for c in self.canvas.containers
                    if c.model.row >= new_rows or c.model.col >= new_cols
                ]
                if affected:
                    msg = QMessageBox(self)
                    msg.setWindowTitle('Grid Shrink Will Delete Widgets')
                    msg.setText(
                        f'Reducing window size will delete {len(affected)} widget(s) '\
                        'from removed rows/columns.\n\nContinue?'
                    )
                    msg.setIcon(QMessageBox.NoIcon)
                    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
                    msg.setDefaultButton(QMessageBox.Cancel)
                    if msg.exec() != QMessageBox.Yes:
                        # Repaint current values in properties panel.
                        self._show_active_window_properties()
                        return

            # Apply shrink via delete helpers so widgets in removed rows/cols are removed.
            if new_rows < cur_rows:
                for r in range(cur_rows - 1, new_rows - 1, -1):
                    self.canvas._delete_row(r, confirm=False)
            if new_cols < cur_cols:
                for c in range(cur_cols - 1, new_cols - 1, -1):
                    self.canvas._delete_col(c, confirm=False)

            # Apply growth directly.
            self.config.grid_columns = max(1, new_cols)
            self.config.grid_rows = max(1, new_rows)
            w.grid_columns = self.config.grid_columns
            w.grid_rows = self.config.grid_rows
            w.window_margins = new_margins
            self.canvas.update_config(self.config)
            self.canvas.set_window_margins(new_margins)
            self.config_bar.load_config(self.config)
            self._raw_import_code = None
            self._dirty_mark()
            self._schedule_preview_update(center_on_change=False)
            self._record_history_state()

        def _apply_window_title(new_title: str):
            idx = self.active_window_index
            self.windows[idx].window_title = (new_title or '').strip() or None
            self.canvas.set_window_title_override(self.windows[idx].window_title)
            self._dirty_mark()
            self._schedule_preview_update(center_on_change=False)
            self._record_history_state()

        def _apply_window_name(new_name: str):
            idx = self.active_window_index
            old_name = self.windows[idx].function_name
            fn = re.sub(r'[^a-zA-Z0-9_]+', '_', (new_name or '').strip()).strip('_') or old_name or f'window_{idx+1}'
            if fn and fn[0].isdigit():
                fn = f'window_{fn}'
            existing = {w.function_name for i, w in enumerate(self.windows) if i != idx}
            base = fn
            suffix = 2
            while fn in existing:
                fn = f'{base}_{suffix}'
                suffix += 1
            self.windows[idx].function_name = fn
            if old_name and fn and old_name != fn:
                # Update parent links referencing old name.
                for ww in self.windows:
                    if getattr(ww, 'parent_window', None) == old_name:
                        ww.parent_window = fn
                self._rename_window_references_in_preview(old_name, fn)
            self._rebuild_window_tabs()
            # Reflect final normalized/uniquified name back into the field.
            self._show_active_window_properties()
            self._dirty_mark()
            self._record_history_state()

        def _apply_window_parent(parent_name: str | None):
            idx = self.active_window_index
            cur = self.windows[idx]
            cur.parent_window = parent_name if parent_name and parent_name != cur.function_name else None
            self._normalize_window_parent_refs()
            self._dirty_mark()
            self._schedule_preview_update(center_on_change=False)
            self._record_history_state()

        if self.active_window_index > 0 and not getattr(w, 'window_title', None):
            w.window_title = 'New Window'

        parent_opts = [ww.function_name for i, ww in enumerate(self.windows) if i != self.active_window_index]
        self.props.show_window_properties(
            w.function_name,
            getattr(w, 'window_title', None),
            w.grid_columns,
            w.grid_rows,
            getattr(w, 'window_margins', 15),
            _apply_window_grid,
            _apply_window_name,
            on_title_changed=_apply_window_title,
            parent_window=getattr(w, 'parent_window', None),
            parent_options=parent_opts,
            on_parent_changed=_apply_window_parent,
            show_parent=(self.active_window_index > 0),
        )

    def _on_widget_selected(self, container):
        if container is None:
            self._show_active_window_properties()
        else:
            self.props.show_properties(container)

    def _on_palette_item_selected(self, current, _previous):
        """Selecting a widget type in Widgets panel should show a matching widget's properties."""
        if current is None:
            return
        try:
            widget_type = current.data(Qt.UserRole)
        except Exception:
            widget_type = None
        if not widget_type:
            return

        containers = list(getattr(self.canvas, 'containers', []) or [])

        # Prefer currently selected matching widget if one is already selected.
        selected = getattr(self.canvas, 'selected_container', None)
        if selected is not None and getattr(getattr(selected, 'model', None), 'widget_type', None) == widget_type:
            self.props.show_properties(selected)
            return

        # Otherwise pick the first matching widget on active canvas.
        match = next((c for c in containers if getattr(getattr(c, 'model', None), 'widget_type', None) == widget_type), None)
        if match is not None:
            self.canvas.select_widget(match)
            self.props.show_properties(match)
            return

        # No placed widget of this type yet: show default property schema preview.
        spec = WIDGET_SPECS.get(widget_type, {})
        defaults = {}
        for p in spec.get('props', []):
            if isinstance(p, PropDef):
                defaults[p.name] = copy.deepcopy(p.default)

        class _PalettePreviewContainer:
            def __init__(self, model):
                self.model = model
                # properties_panel may read container.canvas for token_dest options.
                self.canvas = None

            def replace_inner_widget(self, _new_widget):
                # Palette preview row is schema-only; no canvas widget to rebuild.
                return

        preview_model = PlacedWidget(
            widget_type=widget_type,
            row=0,
            col=0,
            row_span=1,
            col_span=1,
            properties=defaults,
            var_name=to_snake(spec.get('display', widget_type)).replace('-', '_') or 'widget',
        )
        self.props.show_properties(_PalettePreviewContainer(preview_model))

    def _on_widget_moved(self, container):
        self._raw_import_code = None
        # Refresh properties panel so grid position fields update
        if container is not None:
            self.props.show_properties(container)
        self._persist_active_window()
        self._dirty_mark()
        self._schedule_preview_update(center_on_change=False)
        self._record_history_state()

    def _on_canvas_content_changed(self):
        self._raw_import_code = None
        self._persist_active_window()
        if getattr(self.canvas, 'selected_container', None) is None:
            self._show_active_window_properties()
        self._dirty_mark()
        self._schedule_preview_update(center_on_change=True)
        self._record_history_state()

    def _on_properties_changed(self):
        self._raw_import_code = None
        self._persist_active_window()
        self._dirty_mark()
        self._schedule_preview_update()
        self._record_history_state()

    # ── title / dirty state ───────────────────────────────────────────────────

    def _update_title(self):
        name = self.config.script_name or 'Untitled'
        app_title = f'PyFlame UI Builder v{APP_VERSION}'
        if self._save_path:
            base = f'{app_title} - {name} ({self._save_path})'
        else:
            base = f'{app_title} - {name}'
        self.setWindowTitle(f'{base} *' if self._dirty else base)

    def _dirty_mark(self):
        self._dirty = True
        self._update_title()

    def _clean_mark(self):
        self._dirty = False
        self._update_title()

    # ── live preview ──────────────────────────────────────────────────────────

    def _set_preview_auto(self, enabled: bool):
        self._preview_auto = bool(enabled)
        if enabled:
            self._schedule_preview_update()

    def _set_preview_visible(self, visible: bool):
        visible = bool(visible)
        if visible == self._preview_visible:
            return

        if not visible:
            # Preserve current splitter layout before hiding code panel.
            try:
                self._main_split_sizes_before_preview_hide = list(self.main_split.sizes())
            except Exception:
                self._main_split_sizes_before_preview_hide = None

        self._preview_visible = visible
        self.preview_panel.setVisible(self._preview_visible)

        if self._preview_visible:
            # Re-open Code Editor at a sane default width.
            cur = self.main_split.sizes()
            right = cur[2] if len(cur) >= 3 else 320
            remaining = max(700, sum(cur[:2]) if len(cur) >= 3 else 1320)
            default_preview = 420
            default_center = max(320, remaining - default_preview)
            self.main_split.setSizes([default_preview, default_center, right])
            self._refresh_preview()
        else:
            cur = self.main_split.sizes()
            right = cur[2] if len(cur) >= 3 else 320
            center = sum(cur[:2]) if len(cur) >= 3 else 1320
            self.main_split.setSizes([0, center, right])

        if hasattr(self, 'toggle_preview_action'):
            self.toggle_preview_action.blockSignals(True)
            self.toggle_preview_action.setChecked(self._preview_visible)
            self.toggle_preview_action.blockSignals(False)

    def action_zoom_in(self):
        self.canvas.zoom_in()

    def action_zoom_out(self):
        self.canvas.zoom_out()

    def action_zoom_reset(self):
        self.canvas.zoom_reset()

    def action_zoom_fit(self):
        vp = self.canvas_scroll.viewport().size()
        base_w = CHROME_SIDE_W + self.config.grid_columns * self.config.column_width
        base_h = CHROME_TITLE_H + self.config.grid_rows * self.config.row_height + CHROME_MSG_H
        if base_w <= 0 or base_h <= 0:
            return
        fit_w = max(0.5, (vp.width() - 24) / base_w)
        fit_h = max(0.5, (vp.height() - 24) / base_h)
        self.canvas.set_zoom(min(2.0, fit_w, fit_h))

    def action_reset_layout(self):
        """Reset splitters/panels/layout to app defaults and persist them."""
        try:
            self.showNormal()
        except Exception:
            pass
        self.resize(1400, 800)
        self.main_split.setSizes([420, 900, 320])
        if hasattr(self, 'right_split'):
            self.right_split.setSizes([344, 496])
        self._set_preview_visible(True)
        self._set_active_panel(None)
        self._save_window_layout_settings()

    def _update_mode_toggle_button_styles(self):
        blue = 'rgb(0, 110, 175)'
        off_bg = '#2d2d2d'
        off_border = '#3a3a3a'
        on_style = f'background: {blue}; border: 1px solid {blue}; color: #ffffff; padding: 0 8px;'
        off_style = f'background: {off_bg}; border: 1px solid {off_border}; color: #c8c8c8; padding: 0 8px;'

        self.grid_toggle_btn.setStyleSheet(on_style if self.canvas.grid_visible else off_style)
        self.preview_mode_btn.setStyleSheet(on_style if self.canvas.preview_mode else off_style)

        # Keep UI-area highlight state in sync with preview mode behavior.
        self._set_aux_panel_highlight(self._active_aux_panel)

    def action_toggle_grid_visibility(self):
        if self.canvas.preview_mode:
            return
        self.canvas.grid_visible = not self.canvas.grid_visible
        self.grid_toggle_btn.setText('Grid: On' if self.canvas.grid_visible else 'Grid: Off')
        self._update_mode_toggle_button_styles()
        self.canvas.update()

    def _apply_preview_lockdown(self):
        """When Preview is ON, lock non-UI-preview editing surfaces."""
        locked = bool(self.canvas.preview_mode)
        # Keep the actual UI preview canvas + Preview button usable.
        self.preview_panel.setEnabled(not locked)
        self.palette_panel.setEnabled(not locked)
        self.props_frame.setEnabled(not locked)
        self.window_tab_row.setEnabled(not locked)
        self.config_bar.setEnabled(not locked)
        self.grid_toggle_btn.setEnabled(not locked)

        # Window/tab editing actions should be locked in preview mode.
        for act_name in (
            'add_window_action', 'rename_window_action', 'remove_window_action',
            'undo_action', 'redo_action',
        ):
            act = getattr(self, act_name, None)
            if act is not None:
                act.setEnabled(not locked)

    def action_toggle_preview_mode(self):
        turning_on = not self.canvas.preview_mode
        self.canvas.set_preview_mode(turning_on)
        self.preview_mode_btn.setText('Preview: On' if self.canvas.preview_mode else 'Preview: Off')

        # Grid behavior in preview mode:
        # - entering preview: temporarily force grid off (remember prior state)
        # - leaving preview: restore prior grid-on state
        if turning_on:
            self._grid_was_on_before_preview = bool(self.canvas.grid_visible)
            if self.canvas.grid_visible:
                self.canvas.grid_visible = False
                self.grid_toggle_btn.setText('Grid: Off')
                self.canvas.update()
        else:
            if self._grid_was_on_before_preview:
                self.canvas.grid_visible = True
                self.grid_toggle_btn.setText('Grid: On')
                self.canvas.update()
            self._grid_was_on_before_preview = False

        self._apply_preview_lockdown()
        if self.canvas.preview_mode:
            self._show_active_window_properties()
        self._update_mode_toggle_button_styles()

    def action_open_help(self, initial_file: str | None = None):
        help_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'help')
        dlg = HelpDialog(help_dir=help_dir, stylesheet=_app_stylesheet(), parent=self, initial_file=initial_file)
        dlg.exec()

    def action_about(self):
        msg = QMessageBox(self)
        msg.setWindowTitle(f'About {APP_NAME}')
        msg.setIcon(QMessageBox.NoIcon)
        msg.setText(
            f'{APP_NAME}\n\n'
            f'Version: {APP_VERSION}\n'
            f'Author: {APP_AUTHOR}\n'
            f'License: {APP_LICENSE}\n\n'
            f'{APP_DESCRIPTION}\n\n'
            f'{APP_URL}'
        )
        msg.exec()

    def _schedule_preview_update(self, center_on_change: bool = True):
        if not self._preview_auto:
            return
        self._preview_center_on_change = center_on_change
        self._preview_timer.start(180)

    def _preview_style(self, framed: bool = False) -> str:
        border = '2px solid #5aa9ff' if framed else '1px solid #3a3a3a'
        return (
            f'background: #282c34; color: #abb2bf; border: {border};'
            ' font-family: "Courier New", monospace; font-size: 12px;'
            ' selection-background-color: #3e4451; selection-color: #e6e6e6;'
        )

    def _flash_preview_frame(self):
        self.preview_text.setStyleSheet(self._preview_style(framed=True))
        QTimer.singleShot(700, lambda: self.preview_text.setStyleSheet(self._preview_style()))

    def _on_preview_text_changed(self):
        if not self._suppress_preview_text_signal:
            self._preview_user_edited = True
            if self._api_preview_highlight_active:
                self.preview_text.setExtraSelections([])
                self._api_preview_highlight_active = False
            # Best-effort live reflection from code editor -> UI preview.
            self._code_to_ui_sync_timer.start()
        self._update_editor_status()

    def _set_preview_text_programmatic(self, code: str):
        self._suppress_preview_text_signal = True
        try:
            self.preview_text.setPlainText(code)
        finally:
            self._suppress_preview_text_signal = False

    def _sync_canvas_from_preview_code_best_effort(self):
        """Best-effort code->UI sync from Code Editor assignments.

        - Applies parsed kwargs for matching `self.<var> = <WidgetType>(...)` assignments.
        - If a widget assignment/args are invalid for live preview rebuild, show
          `[<WidgetType> CODE ERROR]` in that widget slot until code is fixed.
        """
        def _attr_to_str(node):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                return '.'.join(reversed(parts))
            return None

        def _value_to_prop(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, (ast.List, ast.Tuple)):
                return [
                    _value_to_prop(x)
                    for x in node.elts
                ]
            if isinstance(node, ast.Attribute):
                v = _attr_to_str(node)
                # Enum-like values (Color.BLUE -> 'BLUE')
                if v and '.' in v:
                    return v.split('.')[-1]
                return v
            if isinstance(node, ast.Name):
                if node.id in {'True', 'False'}:
                    return node.id == 'True'
                if node.id == 'None':
                    return None
                raise ValueError('unsupported expression')
            raise ValueError('unsupported expression')

        def _set_error_outline(container, enabled: bool):
            try:
                if enabled:
                    container.setStyleSheet('background: transparent; border: 1px solid #a83a3a;')
                else:
                    container.setStyleSheet('background: transparent; border: none;')
            except Exception:
                pass

        def _show_code_error_placeholder(container):
            try:
                wt = getattr(getattr(container, 'model', None), 'widget_type', 'Widget')
                err = QLabel(f'⚠  {wt}\nCODE ERROR')
                err.setAlignment(Qt.AlignCenter)
                err.setStyleSheet('background:#3a1f1f; color:#ff8a8a; border:1px solid #6b2f2f;')
                container.replace_inner_widget(err)
                mdl = getattr(container, 'model', None)
                if mdl is not None:
                    setattr(mdl, '_code_error', True)
                # Only show red outline when Properties is currently focused on this widget.
                _set_error_outline(container, getattr(self.props, 'container', None) is container)
            except Exception:
                pass

        code = self.preview_text.toPlainText()
        syntax_error_vars: set[str] = set()
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None
            # Targeted fallback: inspect each `self.<var> = ...` call block
            # independently so errors map to the correct widget while typing.
            lines = code.splitlines()
            assign_start_re = re.compile(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*=")
            i = 0
            while i < len(lines):
                line = lines[i]
                m = assign_start_re.search(line)
                if not m:
                    i += 1
                    continue
                var = m.group(1)

                # Collect likely constructor block until parentheses balance.
                # Supports both styles:
                #   self.label_01 = PyFlameLabel(...)
                #   self.label_01 =\n                #       PyFlameLabel(...)
                block_lines = []
                depth = 0
                found_open = False
                j = i
                max_lookahead = min(len(lines), i + 40)
                while j < max_lookahead:
                    ln = lines[j]
                    block_lines.append(ln)
                    for ch in ln:
                        if ch == '(':
                            depth += 1
                            found_open = True
                        elif ch == ')':
                            depth -= 1
                    if found_open and depth <= 0:
                        break
                    j += 1

                block = '\n'.join(block_lines)
                # Ignore non-widget assignments during syntax fallback.
                if 'PyFlame' not in block:
                    i = max(i + 1, j + 1)
                    continue
                if block.strip():
                    try:
                        ast.parse(textwrap.dedent(block))
                    except Exception:
                        syntax_error_vars.add(var)

                i = max(i + 1, j + 1)

        if tree is None:
            updated = False
            if syntax_error_vars:
                for c in list(getattr(self.canvas, 'containers', []) or []):
                    mdl = getattr(c, 'model', None)
                    if mdl is None:
                        continue
                    var = (getattr(mdl, 'var_name', '') or '').strip()
                    if var in syntax_error_vars:
                        _show_code_error_placeholder(c)
                        updated = True
            if updated:
                self.canvas.update()
                self._persist_active_window()
                selected = getattr(self.canvas, 'selected_container', None)
                if selected is not None:
                    self.props.show_properties(selected)
                else:
                    self._show_active_window_properties()
            return

        # Clear stale code-error placeholders when widget code is valid again.
        for c in list(getattr(self.canvas, 'containers', []) or []):
            mdl = getattr(c, 'model', None)
            if mdl is not None and getattr(mdl, '_code_error', False):
                setattr(mdl, '_code_error', False)
                try:
                    c.replace_inner_widget(WidgetContainer.make_widget(mdl.widget_type, mdl.properties))
                    _set_error_outline(c, False)
                except Exception:
                    _show_code_error_placeholder(c)

        def _to_int(node, default=None):
            try:
                v = _value_to_prop(node)
                return int(v)
            except Exception:
                return default

        assigns: dict[str, tuple[str, dict, bool]] = {}
        # var -> (widget_type, parsed_props, has_parse_error)
        placements: dict[str, tuple[int, int, int, int]] = {}
        # var -> (row, col, row_span, col_span)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if not (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == 'self'):
                    continue
                var_name = tgt.attr
                call = node.value
                if not isinstance(call, ast.Call):
                    continue
                if isinstance(call.func, ast.Name):
                    widget_type = call.func.id
                elif isinstance(call.func, ast.Attribute):
                    widget_type = call.func.attr
                else:
                    continue
                if not widget_type.startswith('PyFlame'):
                    continue

                props = {}
                has_error = False
                for kw in call.keywords:
                    if kw.arg is None:
                        continue
                    try:
                        props[kw.arg] = _value_to_prop(kw.value)
                    except Exception:
                        has_error = True
                assigns[var_name] = (widget_type, props, has_error)
                continue

            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == 'addWidget'):
                continue
            args = list(getattr(call, 'args', []) or [])
            if len(args) < 3:
                continue
            warg = args[0]
            if not (isinstance(warg, ast.Attribute) and isinstance(warg.value, ast.Name) and warg.value.id == 'self'):
                continue
            var_name = warg.attr
            row = _to_int(args[1], None)
            col = _to_int(args[2], None)
            if row is None or col is None:
                continue
            row_span = _to_int(args[3], 1) if len(args) > 3 else 1
            col_span = _to_int(args[4], 1) if len(args) > 4 else 1
            if row_span is None:
                row_span = 1
            if col_span is None:
                col_span = 1
            placements[var_name] = (max(0, row), max(0, col), max(1, row_span), max(1, col_span))

        updated = False

        # Remove widgets only when the code is clearly using self.<var> widget style
        # for current canvas vars; avoid destructive false positives with local vars.
        existing_vars = [
            (getattr(getattr(c, 'model', None), 'var_name', '') or '').strip()
            for c in list(getattr(self.canvas, 'containers', []) or [])
        ]
        self_style_detected = any(v and (f'self.{v}' in code) for v in existing_vars)
        if assigns and self_style_detected:
            for c in list(getattr(self.canvas, 'containers', []) or []):
                mdl = getattr(c, 'model', None)
                if mdl is None:
                    continue
                var = (getattr(mdl, 'var_name', '') or '').strip()
                if not var:
                    continue
                if var in assigns and var in placements:
                    continue
                if var in placements:
                    # addWidget line still present but assignment is broken/unrecognised —
                    # keep the slot visible as a placeholder rather than silently removing.
                    _show_code_error_placeholder(c)
                    updated = True
                    continue
                try:
                    if getattr(self.canvas, 'selected_container', None) is c:
                        self.canvas.select_widget(None)
                    self.canvas.containers.remove(c)
                except Exception:
                    pass
                try:
                    c.deleteLater()
                except Exception:
                    pass
                updated = True

        existing_by_var = {}
        for c in list(getattr(self.canvas, 'containers', []) or []):
            mdl = getattr(c, 'model', None)
            if mdl is None:
                continue
            var = (getattr(mdl, 'var_name', '') or '').strip()
            if var:
                existing_by_var[var] = c

        for var, c in list(existing_by_var.items()):
            if var not in assigns:
                continue
            mdl = getattr(c, 'model', None)
            if mdl is None:
                continue
            widget_type, props, has_error = assigns[var]

            if has_error:
                _show_code_error_placeholder(c)
                updated = True
                continue

            # Apply parsed properties and attempt live rebuild.
            new_props = dict(getattr(mdl, 'properties', {}) or {})
            new_props.update(props)
            mdl.properties = new_props
            if widget_type != getattr(mdl, 'widget_type', None):
                mdl.widget_type = widget_type

            if var in placements:
                row, col, row_span, col_span = placements[var]
                max_rows = max(1, int(getattr(self.config, 'grid_rows', 1) or 1))
                max_cols = max(1, int(getattr(self.config, 'grid_columns', 1) or 1))
                row = max(0, min(row, max_rows - 1))
                col = max(0, min(col, max_cols - 1))
                row_span = max(1, min(row_span, max_rows - row))
                col_span = max(1, min(col_span, max_cols - col))

                # Prevent API/code sync from stacking widgets on top of others.
                if not self.canvas._has_overlap(row, col, row_span, col_span, ignore_container=c):
                    mdl.row = row
                    mdl.col = col
                    mdl.row_span = row_span
                    mdl.col_span = col_span
                    try:
                        c.setGeometry(self.canvas.cell_rect(mdl.row, mdl.col, mdl.row_span, mdl.col_span))
                    except Exception:
                        pass

            try:
                new_widget = WidgetContainer.make_widget(mdl.widget_type, mdl.properties)
                # Widget factory may silently fall back on invalid args; convert that
                # path into an explicit CODE ERROR placeholder for clarity.
                c.replace_inner_widget(new_widget)
                setattr(mdl, '_code_error', False)
                _set_error_outline(c, False)
            except Exception:
                _show_code_error_placeholder(c)
            updated = True

        # Add newly introduced self.<var> widgets from code that don't exist on canvas yet.
        for var, (widget_type, props, has_error) in assigns.items():
            if var in existing_by_var:
                continue
            if var not in placements:
                continue

            row, col, row_span, col_span = placements[var]
            max_rows = max(1, int(getattr(self.config, 'grid_rows', 1) or 1))
            max_cols = max(1, int(getattr(self.config, 'grid_columns', 1) or 1))
            row = max(0, min(row, max_rows - 1))
            col = max(0, min(col, max_cols - 1))
            row_span = max(1, min(row_span, max_rows - row))
            col_span = max(1, min(col_span, max_cols - col))
            # Never create overlapping widgets through API/code sync.
            if self.canvas._has_overlap(row, col, row_span, col_span):
                continue

            model = PlacedWidget(
                widget_type=widget_type,
                row=row,
                col=col,
                row_span=row_span,
                col_span=col_span,
                properties=dict(props or {}),
                var_name=var,
            )
            try:
                widget = WidgetContainer.make_widget(model.widget_type, model.properties)
                container = WidgetContainer(widget, model, self.canvas)
                container.setGeometry(self.canvas.cell_rect(model.row, model.col, model.row_span, model.col_span))
                if hasattr(container, 'set_preview_mode'):
                    container.set_preview_mode(getattr(self.canvas, 'preview_mode', False))
                container.show()
                self.canvas.containers.append(container)
                if has_error:
                    _show_code_error_placeholder(container)
                updated = True
            except Exception:
                # If build fails, still show explicit code error placeholder.
                try:
                    fallback = QLabel(f'⚠  {widget_type}\nCODE ERROR')
                    fallback.setAlignment(Qt.AlignCenter)
                    fallback.setStyleSheet('background:#3a1f1f; color:#ff8a8a; border:1px solid #6b2f2f;')
                    container = WidgetContainer(fallback, model, self.canvas)
                    container.setGeometry(self.canvas.cell_rect(model.row, model.col, model.row_span, model.col_span))
                    container.show()
                    self.canvas.containers.append(container)
                    setattr(model, '_code_error', True)
                    updated = True
                except Exception:
                    pass

        if updated:
            self.canvas.update()
            self._persist_active_window()
            selected = getattr(self.canvas, 'selected_container', None)
            if selected is not None:
                self.props.show_properties(selected)
            else:
                # If selected widget was removed from code, fall back to window props.
                self._show_active_window_properties()

    def _center_and_highlight_preview_api_write(self):
        """Center API-written preview text and highlight it in PyFlame blue."""
        text = self.preview_text.toPlainText()
        if not text:
            self.preview_text.setExtraSelections([])
            self._api_preview_highlight_active = False
            return

        lines = text.count('\n') + 1
        mid_line = max(1, lines // 2)
        cursor = self.preview_text.textCursor()
        cursor.movePosition(QTextCursor.Start)
        for _ in range(mid_line - 1):
            if not cursor.movePosition(QTextCursor.Down):
                break
        self.preview_text.setTextCursor(cursor)
        self.preview_text.centerCursor()

        # Highlight whole inserted text block with translucent PyFlame blue.
        full = self.preview_text.textCursor()
        full.select(QTextCursor.Document)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = full
        sel.format.setBackground(QColor(0, 110, 175, 70))
        self.preview_text.setExtraSelections([sel])
        self._api_preview_highlight_active = True

    def _set_work_panel_highlight(self, panel: str | None):
        """Highlight active work panel (preview/properties) with 1px PyFlame blue border.

        Use object-name scoped selectors so only panel frames are outlined (not
        child widgets/controls inside those panels).
        """
        self._active_work_panel = panel
        blue_border = '1px solid rgb(0, 110, 175)'
        off_border = '1px solid transparent'
        self.preview_panel.setStyleSheet(
            f'#CodePreviewPanelFrame {{ border: {blue_border if panel == "preview" else off_border}; padding: 0px; }}'
        )
        self.props_frame.setStyleSheet(
            f'#PropertiesPanelFrame {{ border: {blue_border if panel == "props" else off_border}; padding: 0px; }}'
        )

    def _set_aux_panel_highlight(self, panel: str | None):
        """Highlight widget palette or UI canvas area with panel/mode-aware borders."""
        self._active_aux_panel = panel
        blue_border = '1px solid rgb(0, 110, 175)'
        off_border = '1px solid transparent'
        preview_border = '1px solid rgb(0, 180, 170)'
        self.palette_panel.setStyleSheet(
            f'#WidgetPalettePanelFrame {{ border: {blue_border if panel == "widgets" else off_border}; padding: 0px; }}'
        )
        if panel == 'ui':
            border = preview_border if self.canvas.preview_mode else blue_border
            self.canvas_scroll.setStyleSheet(f'QScrollArea {{ border: {border}; }}')
        else:
            self.canvas_scroll.setStyleSheet('QScrollArea { border: none; }')

    def _set_active_panel(self, panel: str | None):
        """Enforce single-active blue outline across all major panels."""
        if panel == 'preview':
            self._set_work_panel_highlight('preview')
            self._set_aux_panel_highlight(None)
        elif panel == 'props':
            self._set_work_panel_highlight('props')
            self._set_aux_panel_highlight(None)
        elif panel == 'widgets':
            self._set_work_panel_highlight(None)
            self._set_aux_panel_highlight('widgets')
        elif panel == 'ui':
            self._set_work_panel_highlight(None)
            self._set_aux_panel_highlight('ui')
        else:
            self._set_work_panel_highlight(None)
            self._set_aux_panel_highlight(None)

    @staticmethod
    def _is_descendant_widget(widget, ancestor) -> bool:
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget() if hasattr(w, 'parentWidget') else None
        return False

    def _is_ui_area_widget(self, widget) -> bool:
        """Treat canvas + tab/zoom controls as one UI interaction area."""
        if widget is None:
            return False
        return (
            self._is_descendant_widget(widget, self.canvas_scroll)
            or self._is_descendant_widget(widget, self.window_tab_row)
            or self._is_descendant_widget(widget, self.zoom_bar)
            or self._is_descendant_widget(widget, self.center_pane)
        )

    def eventFilter(self, obj, event):
        # Selection policy:
        # - Deselect only when clicking in the Flame preview region itself
        #   (empty canvas or its surrounding scroll viewport area).
        # - Never deselect from clicks in other UI panels (properties, code preview, menus).
        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            try:
                hovered = QApplication.widgetAt(QCursor.pos())
                in_props = (
                    self._is_descendant_widget(obj, self.props)
                    or self._is_descendant_widget(obj, self.props_frame)
                    or self._is_descendant_widget(hovered, self.props)
                    or self._is_descendant_widget(hovered, self.props_frame)
                    or bool(getattr(self.props, 'underMouse', lambda: False)())
                    or bool(getattr(self.props_frame, 'underMouse', lambda: False)())
                )
                in_preview = (
                    self._is_descendant_widget(obj, self.preview_panel)
                    or self._is_descendant_widget(hovered, self.preview_panel)
                    or bool(getattr(self.preview_panel, 'underMouse', lambda: False)())
                )
                in_widgets = self._is_descendant_widget(obj, self.palette_panel) or self._is_descendant_widget(hovered, self.palette_panel)
                in_ui = self._is_ui_area_widget(obj) or self._is_ui_area_widget(hovered)

                if in_props:
                    self._set_active_panel('props')
                elif in_preview:
                    self._set_active_panel('preview')
                elif in_widgets:
                    self._set_active_panel('widgets')
                elif in_ui:
                    self._set_active_panel('ui')

                if event.type() == QEvent.MouseButtonPress and getattr(self.canvas, 'selected_container', None) is not None:
                    in_canvas_scroll = self._is_descendant_widget(obj, self.canvas_scroll) or self._is_descendant_widget(hovered, self.canvas_scroll)
                    in_canvas = self._is_descendant_widget(obj, self.canvas) or self._is_descendant_widget(hovered, self.canvas)
                    if in_canvas_scroll and not in_canvas:
                        self.canvas.select_widget(None)
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def _first_changed_line(self, old: str, new: str) -> int:
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        max_common = min(len(old_lines), len(new_lines))
        for idx in range(max_common):
            if old_lines[idx] != new_lines[idx]:
                return idx
        return max_common

    def _scroll_preview_to_line(self, line_index: int):
        doc = self.preview_text.document()
        block = doc.findBlockByLineNumber(max(0, line_index))
        if not block.isValid():
            return
        cursor = self.preview_text.textCursor()
        cursor.setPosition(block.position())
        self.preview_text.setTextCursor(cursor)
        self.preview_text.centerCursor()

    def _flash_preview_line(self, line_index: int):
        doc = self.preview_text.document()
        block = doc.findBlockByLineNumber(max(0, line_index))
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        cursor.select(QTextCursor.LineUnderCursor)

        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format.setBackground(QColor('#2a5f9e'))
        sel.format.setForeground(QColor('#ffffff'))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)

        self.preview_text.setExtraSelections([sel])
        QTimer.singleShot(900, lambda: self.preview_text.setExtraSelections([]))

    @staticmethod
    def _protected_window_build_ranges(text: str):
        ranges = []
        for m in re.finditer(
            r"#\s*-{10,}.*?\[Start Window Build\].*?\[End Window Build\].*?#\s*-{10,}",
            text,
            re.DOTALL,
        ):
            ranges.append((m.start(), m.end()))
        return ranges

    @staticmethod
    def _merge_generated_protected_sections(current_text: str, generated_text: str) -> str | None:
        """Keep user-editable code, replace only protected Window Build blocks from generated code.

        Returns merged text when both versions contain matching protected block counts,
        otherwise None to signal fallback behavior.
        """
        def _ranges(text: str):
            return PyFlameBuilder._protected_window_build_ranges(text)

        cur = _ranges(current_text)
        gen = _ranges(generated_text)
        if not cur or not gen or len(cur) != len(gen):
            return None

        out = []
        cursor = 0
        for (cs, ce), (gs, ge) in zip(cur, gen):
            out.append(current_text[cursor:cs])
            out.append(generated_text[gs:ge])
            cursor = ce
        out.append(current_text[cursor:])
        return ''.join(out)

    def _refresh_preview(self):
        self._persist_active_window()
        if self._raw_import_code is not None:
            code = self._raw_import_code
        else:
            models = [c.model for c in self.canvas.containers]
            try:
                code = CodeGenerator.generate(self.config, models, tab_order=None, windows=self.windows)
            except Exception as e:
                code = f'# Preview generation error\n# {e}'

            current_text = self.preview_text.toPlainText() if hasattr(self, 'preview_text') else ''
            if self._preview_auto and self._preview_user_edited and current_text and current_text != self._generated_code_snapshot:
                merged = self._merge_generated_protected_sections(current_text, code)
                if merged is not None:
                    # User logic edits stay intact; only builder-owned UI blocks update.
                    code = merged
                else:
                    msg = QMessageBox(self)
                    msg.setWindowTitle('Manual Edits Detected')
                    msg.setText('Auto Update Code wants to regenerate, but manual edits would be overwritten.')
                    keep_btn = msg.addButton('Keep My Edits', QMessageBox.AcceptRole)
                    overwrite_btn = msg.addButton('Overwrite with Generated', QMessageBox.DestructiveRole)
                    pause_btn = msg.addButton('Disable Auto Update', QMessageBox.RejectRole)
                    msg.exec()
                    clicked = msg.clickedButton()
                    if clicked is keep_btn:
                        self._generated_code_snapshot = code
                        self._update_editor_status()
                        return
                    if clicked is pause_btn:
                        self.preview_auto_check.setChecked(False)
                        self._generated_code_snapshot = code
                        self._update_editor_status()
                        return

        changed = code != self._last_preview_code
        changed_line = self._first_changed_line(self._last_preview_code, code)
        added_code = changed and len(code) > len(self._last_preview_code)

        vbar = self.preview_text.verticalScrollBar()
        hbar = self.preview_text.horizontalScrollBar()
        prev_v = vbar.value()
        prev_h = hbar.value()

        if self._api_preview_highlight_active:
            self.preview_text.setExtraSelections([])
            self._api_preview_highlight_active = False
        self._set_preview_text_programmatic(code)
        if self._raw_import_code is None:
            self._preview_user_edited = False
        if changed and self._preview_center_on_change:
            self._scroll_preview_to_line(changed_line)
            self._flash_preview_line(changed_line)
        elif changed:
            # Some Qt repaints override immediate scrollbar restoration; do both.
            vbar.setValue(prev_v)
            hbar.setValue(prev_h)
            QTimer.singleShot(0, lambda: self.preview_text.verticalScrollBar().setValue(prev_v))
            QTimer.singleShot(0, lambda: self.preview_text.horizontalScrollBar().setValue(prev_h))

        self._last_preview_code = code
        self._generated_code_snapshot = code
        self._preview_center_on_change = True

        if added_code:
            self._flash_preview_frame()
        self._update_editor_status()

    # ── undo / redo history ──────────────────────────────────────────────────

    def _snapshot_state(self) -> dict:
        cfg = {
            'script_name': self.config.script_name,
            'written_by': self.config.written_by,
            'script_version': self.config.script_version,
            'flame_version': self.config.flame_version,
            'hook_types': list(self.config.hook_types),
            'license_type': self.config.license_type,
            'grid_columns': self.config.grid_columns,
            'grid_rows': self.config.grid_rows,
            'column_width': self.config.column_width,
            'row_height': self.config.row_height,
        }
        widgets = []
        for c in self.canvas.containers:
            m = c.model
            widgets.append({
                'widget_type': m.widget_type,
                'row': m.row,
                'col': m.col,
                'row_span': m.row_span,
                'col_span': m.col_span,
                'properties': copy.deepcopy(m.properties),
                'var_name': m.var_name,
            })
        return {'config': cfg, 'widgets': widgets}

    def _apply_snapshot_state(self, state: dict):
        self._restoring_history = True
        try:
            cfg = state.get('config', {})
            config = WindowConfig(
                script_name=cfg.get('script_name', 'My Script'),
                written_by=cfg.get('written_by', 'Your Name'),
                script_version=cfg.get('script_version', 'v1.0.0'),
                flame_version=cfg.get('flame_version', '2025.1'),
                hook_types=cfg.get('hook_types', ['get_batch_custom_ui_actions']),
                license_type=cfg.get('license_type', 'None'),
                grid_columns=cfg.get('grid_columns', 4),
                grid_rows=cfg.get('grid_rows', 3),
                column_width=cfg.get('column_width', 150),
                row_height=cfg.get('row_height', 28),
            )

            for c in list(self.canvas.containers):
                c.deleteLater()
            self.canvas.containers.clear()
            self.canvas.selected_container = None

            self.config = config
            self.config_bar.load_config(config)
            self.canvas.update_config(config)

            for wd in state.get('widgets', []):
                try:
                    model = PlacedWidget(
                        widget_type=wd.get('widget_type', ''),
                        row=wd.get('row', 0),
                        col=wd.get('col', 0),
                        row_span=wd.get('row_span', 1),
                        col_span=wd.get('col_span', 1),
                        properties=copy.deepcopy(wd.get('properties', {})),
                        var_name=wd.get('var_name', ''),
                    )
                    widget = WidgetContainer.make_widget(model.widget_type, model.properties)
                    container = WidgetContainer(widget, model, self.canvas)
                    container.setGeometry(self.canvas.cell_rect(model.row, model.col, model.row_span, model.col_span))
                    container.set_preview_mode(self.canvas.preview_mode)
                    container.show()
                    self.canvas.containers.append(container)
                except Exception as e:
                    print(f'Error restoring widget: {e}')

            self._show_active_window_properties()
            self._refresh_preview()
            self._dirty_mark()
        finally:
            self._restoring_history = False

    def _record_history_state(self):
        if self._restoring_history:
            return
        snapshot = self._snapshot_state()
        if self._history_index >= 0 and snapshot == self._history[self._history_index]:
            return
        if self._history_index < len(self._history) - 1:
            self._history = self._history[:self._history_index + 1]
        self._history.append(snapshot)
        if len(self._history) > self._history_limit:
            self._history.pop(0)
        self._history_index = len(self._history) - 1
        self._update_undo_redo_actions()

    def _refresh_edit_menu(self):
        if not hasattr(self, 'edit_menu'):
            return
        self.edit_menu.clear()
        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addAction(self.redo_action)
        self._strip_macos_edit_menu_extras()

    def _strip_macos_edit_menu_extras(self):
        """Best-effort removal of macOS auto-injected Edit submenu items
        (Writing Tools, Dictation, etc.) so only Undo/Redo remain."""
        try:
            if sys.platform != 'darwin':
                return
            from AppKit import NSApp

            main_menu = NSApp.mainMenu()
            if main_menu is None:
                return

            # Find the native Edit menu by title
            edit_submenu = None
            for i in range(main_menu.numberOfItems()):
                item = main_menu.itemAtIndex_(i)
                if item and str(item.title()) == 'Edit':
                    edit_submenu = item.submenu()
                    break

            if edit_submenu is None:
                return

            keep_titles = {'Undo', 'Redo'}
            # Remove all non-Undo/Redo items (including separators)
            for idx in range(edit_submenu.numberOfItems() - 1, -1, -1):
                mi = edit_submenu.itemAtIndex_(idx)
                if mi is None:
                    continue
                title = str(mi.title() or '')
                if title not in keep_titles:
                    edit_submenu.removeItemAtIndex_(idx)
        except Exception:
            pass

    def _update_undo_redo_actions(self):
        can_undo = self._history_index > 0
        can_redo = self._history_index >= 0 and self._history_index < len(self._history) - 1
        if hasattr(self, 'undo_action'):
            self.undo_action.setEnabled(can_undo)
        if hasattr(self, 'redo_action'):
            self.redo_action.setEnabled(can_redo)

    def action_undo(self):
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._apply_snapshot_state(self._history[self._history_index])
        self._update_undo_redo_actions()

    def action_redo(self):
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._apply_snapshot_state(self._history[self._history_index])
        self._update_undo_redo_actions()

    def _transform_preview_selection(self, mode: str):
        if not hasattr(self, 'preview_text'):
            return

        cursor = self.preview_text.textCursor()
        if cursor is None:
            return

        sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
        sel_end = max(cursor.selectionStart(), cursor.selectionEnd())

        if sel_start == sel_end:
            cursor.movePosition(QTextCursor.StartOfLine)
            cursor.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(sel_start)
            cursor.movePosition(QTextCursor.StartOfLine)
            line_start = cursor.position()

            end_cursor = self.preview_text.textCursor()
            end_cursor.setPosition(sel_end)
            if end_cursor.atBlockStart() and sel_end > sel_start:
                end_cursor.movePosition(QTextCursor.PreviousBlock)
            end_cursor.movePosition(QTextCursor.EndOfBlock)
            line_end = end_cursor.position()

            cursor.setPosition(line_start)
            cursor.setPosition(line_end, QTextCursor.KeepAnchor)

        selected = cursor.selectedText()
        if not selected:
            return

        lines = selected.split('\u2029')

        if mode == 'comment':
            out_lines = [f'# {line}' if line.strip() else line for line in lines]
        elif mode == 'uncomment':
            out_lines = [re.sub(r'^\s*#\s?', '', line, count=1) if line.strip() else line for line in lines]
        else:  # toggle
            non_empty = [ln for ln in lines if ln.strip()]
            all_commented = bool(non_empty) and all(re.match(r'^\s*#', ln) for ln in non_empty)
            if all_commented:
                out_lines = [re.sub(r'^\s*#\s?', '', line, count=1) if line.strip() else line for line in lines]
            else:
                out_lines = [f'# {line}' if line.strip() else line for line in lines]

        cursor.beginEditBlock()
        cursor.insertText('\n'.join(out_lines))
        cursor.endEditBlock()
        self._dirty_mark()

    def action_comment_selection(self):
        self._transform_preview_selection('comment')

    def action_uncomment_selection(self):
        self._transform_preview_selection('uncomment')

    def action_toggle_comment_selection(self):
        self._transform_preview_selection('toggle')

    def _set_find_match_case(self, enabled: bool):
        self._find_match_case = bool(enabled)
        if hasattr(self, 'find_match_case_action'):
            self.find_match_case_action.setChecked(self._find_match_case)
        if hasattr(self, 'find_bar_match_case'):
            self.find_bar_match_case.setChecked(self._find_match_case)

    def _set_find_whole_word(self, enabled: bool):
        self._find_whole_word = bool(enabled)
        if hasattr(self, 'find_whole_word_action'):
            self.find_whole_word_action.setChecked(self._find_whole_word)
        if hasattr(self, 'find_bar_whole_word'):
            self.find_bar_whole_word.setChecked(self._find_whole_word)

    def _set_find_regex(self, enabled: bool):
        self._find_regex = bool(enabled)
        if hasattr(self, 'find_regex_action'):
            self.find_regex_action.setChecked(self._find_regex)
        if hasattr(self, 'find_bar_regex'):
            self.find_bar_regex.setChecked(self._find_regex)

    def _set_replace_in_selection(self, enabled: bool):
        self._replace_in_selection = bool(enabled)
        if hasattr(self, 'replace_in_selection_action'):
            self.replace_in_selection_action.setChecked(self._replace_in_selection)
        if hasattr(self, 'find_bar_sel_only'):
            self.find_bar_sel_only.setChecked(self._replace_in_selection)

    def _remember_search(self, text: str):
        text = (text or '').strip()
        if not text:
            return
        if text in self._recent_searches:
            self._recent_searches.remove(text)
        self._recent_searches.insert(0, text)
        self._recent_searches = self._recent_searches[:10]
        if hasattr(self, 'find_input'):
            self.find_input.clear()
            self.find_input.addItems(self._recent_searches)
            self.find_input.setCurrentText(text)

    def _find_regex_or_plain(self, text: str, *, backward: bool = False) -> bool:
        if not text:
            return False
        if not self._find_regex:
            flags = QTextDocument.FindFlags()
            if backward:
                flags |= QTextDocument.FindBackward
            if self._find_match_case:
                flags |= QTextDocument.FindCaseSensitively
            if self._find_whole_word:
                flags |= QTextDocument.FindWholeWords
            found = self.preview_text.find(text, flags)
            if not found:
                cursor = self.preview_text.textCursor()
                cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
                self.preview_text.setTextCursor(cursor)
                found = self.preview_text.find(text, flags)
            return bool(found)

        try:
            pattern = re.compile(text, 0 if self._find_match_case else re.IGNORECASE)
        except re.error as e:
            QMessageBox.warning(self, 'Regex Error', f'Invalid regular expression:\n{e}')
            return False

        full = self.preview_text.toPlainText()
        cursor = self.preview_text.textCursor()
        pos = cursor.selectionStart() if backward else cursor.selectionEnd()
        matches = list(pattern.finditer(full))
        if not matches:
            return False
        picked = None
        if backward:
            for m in reversed(matches):
                if m.start() < pos:
                    picked = m
                    break
            picked = picked or matches[-1]
        else:
            for m in matches:
                if m.start() > pos:
                    picked = m
                    break
            picked = picked or matches[0]

        c = self.preview_text.textCursor()
        c.setPosition(picked.start())
        c.setPosition(picked.end(), QTextCursor.KeepAnchor)
        self.preview_text.setTextCursor(c)
        return True

    def action_toggle_inline_find_bar(self):
        self.find_bar.setVisible(not self.find_bar.isVisible())
        if self.find_bar.isVisible():
            self.find_input.setFocus()
            self.find_input.lineEdit().selectAll()

    def action_find(self):
        # Use inline find bar as the single Find UI so all find controls
        # (match case/whole word/regex/in-selection/replace buttons) are always available.
        if not self.find_bar.isVisible():
            self.find_bar.setVisible(True)
            seed = self._selected_text_or_current_line().strip() or self._last_find_text
            if seed:
                self.find_input.setCurrentText(seed)
            self.find_input.setFocus()
            self.find_input.lineEdit().selectAll()
            return

        text = self.find_input.currentText().strip()
        if text:
            self._last_find_text = text
            self._remember_search(text)
            if not self._find_regex_or_plain(text, backward=False):
                QMessageBox.information(self, 'Find', f'No matches found for: {text}')

    def action_find_next(self):
        if self.find_bar.isVisible() and self.find_input.currentText().strip():
            self._last_find_text = self.find_input.currentText().strip()
        if not self._last_find_text:
            self.action_find()
            return
        if not self._find_regex_or_plain(self._last_find_text, backward=False):
            QMessageBox.information(self, 'Find Next', f'No matches found for: {self._last_find_text}')

    def action_find_previous(self):
        if self.find_bar.isVisible() and self.find_input.currentText().strip():
            self._last_find_text = self.find_input.currentText().strip()
        if not self._last_find_text:
            self.action_find()
            return
        if not self._find_regex_or_plain(self._last_find_text, backward=True):
            QMessageBox.information(self, 'Find Previous', f'No matches found for: {self._last_find_text}')

    def action_replace(self, one_only: bool | None = None):
        if self.find_bar.isVisible():
            find_text = self.find_input.currentText().strip()
            replace_text = self.replace_input.text()
            if not find_text:
                return
            self._last_find_text = find_text
            self._last_replace_text = replace_text
            self._remember_search(find_text)
            replace_all = not bool(one_only)
        else:
            # Keep replace workflow in the inline find bar so all related controls
            # are visible in one place instead of split dialog prompts.
            self.find_bar.setVisible(True)
            seed = self._selected_text_or_current_line().strip() or self._last_find_text
            if seed and not self.find_input.currentText().strip():
                self.find_input.setCurrentText(seed)
            if self._last_replace_text and not self.replace_input.text():
                self.replace_input.setText(self._last_replace_text)
            self.find_input.setFocus()
            self.find_input.lineEdit().selectAll()
            return

        code = self.preview_text.toPlainText()
        scope_start = 0
        scope_end = len(code)
        sel_cursor = self.preview_text.textCursor()
        if self._replace_in_selection and sel_cursor.hasSelection():
            scope_start = min(sel_cursor.selectionStart(), sel_cursor.selectionEnd())
            scope_end = max(sel_cursor.selectionStart(), sel_cursor.selectionEnd())

        segment = code[scope_start:scope_end]
        if self._find_regex:
            try:
                pattern = re.compile(find_text, 0 if self._find_match_case else re.IGNORECASE)
            except re.error as e:
                QMessageBox.warning(self, 'Regex Error', f'Invalid regular expression:\n{e}')
                return
        else:
            pattern = re.compile((rf'\\b{re.escape(find_text)}\\b' if self._find_whole_word else re.escape(find_text)), 0 if self._find_match_case else re.IGNORECASE)

        if replace_all:
            new_segment, count = pattern.subn(replace_text, segment)
            if count <= 0:
                QMessageBox.information(self, 'Replace', f'No matches found for: {find_text}')
                return
            new_code = code[:scope_start] + new_segment + code[scope_end:]
            self._set_preview_text_programmatic(new_code)
            self._dirty_mark()
            QMessageBox.information(self, 'Replace', f'Replaced {count} occurrence(s).')
            return

        m = pattern.search(segment)
        if not m:
            QMessageBox.information(self, 'Replace', f'No matches found for: {find_text}')
            return
        abs_start, abs_end = scope_start + m.start(), scope_start + m.end()
        c = self.preview_text.textCursor()
        c.setPosition(abs_start)
        c.setPosition(abs_end, QTextCursor.KeepAnchor)
        c.insertText(replace_text)
        self._dirty_mark()

    def action_duplicate_selection_or_line(self):
        cursor = self.preview_text.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace('\u2029', '\n')
            cursor.insertText(text)
        else:
            cursor.select(QTextCursor.LineUnderCursor)
            line = cursor.selectedText().replace('\u2029', '\n')
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText('\n' + line)
        self._dirty_mark()

    def action_move_selection_or_line(self, direction: int):
        if direction not in (-1, 1):
            return
        cursor = self.preview_text.textCursor()
        doc = self.preview_text.document()
        sel_start = min(cursor.selectionStart(), cursor.selectionEnd())
        sel_end = max(cursor.selectionStart(), cursor.selectionEnd())
        work = QTextCursor(doc)
        work.setPosition(sel_start)
        work.movePosition(QTextCursor.StartOfBlock)
        block_start = work.blockNumber()
        work.setPosition(sel_end)
        if work.atBlockStart() and sel_end > sel_start:
            work.movePosition(QTextCursor.PreviousBlock)
        block_end = work.blockNumber()
        lines = self.preview_text.toPlainText().split('\n')
        if block_start < 0 or block_end >= len(lines):
            return
        if direction < 0 and block_start == 0:
            return
        if direction > 0 and block_end >= len(lines) - 1:
            return
        chunk = lines[block_start:block_end + 1]
        del lines[block_start:block_end + 1]
        insert_at = block_start - 1 if direction < 0 else block_start + 1
        for i, ln in enumerate(chunk):
            lines.insert(insert_at + i, ln)
        self._set_preview_text_programmatic('\n'.join(lines))
        new_line = insert_at
        b = self.preview_text.document().findBlockByLineNumber(new_line)
        if b.isValid():
            c = self.preview_text.textCursor()
            c.setPosition(b.position())
            self.preview_text.setTextCursor(c)
        self._dirty_mark()

    def _current_source_mode(self) -> str:
        if self._raw_import_code is not None:
            return 'imported'
        if self._preview_user_edited:
            return 'edited'
        return 'generated'

    def _on_protected_edit_attempted(self):
        """Flash a read-only warning in the editor status bar for 2.5 s."""
        if not hasattr(self, 'preview_status_label'):
            return
        self.preview_status_label.setText(
            'Window build region is read-only — use the canvas to edit widgets'
        )
        self.preview_status_label.setStyleSheet(
            'color: #ff8a8a; font-size: 10px; padding: 2px 2px 0px;'
        )
        if not hasattr(self, '_protected_warning_timer'):
            from PySide6.QtCore import QTimer
            self._protected_warning_timer = QTimer(self)
            self._protected_warning_timer.setSingleShot(True)
            self._protected_warning_timer.timeout.connect(self._clear_protected_warning)
        self._protected_warning_timer.start(2500)

    def _clear_protected_warning(self):
        self.preview_status_label.setStyleSheet(
            'color: #888; font-size: 10px; padding: 2px 2px 0px;'
        )
        self._update_editor_status()

    def _update_editor_status(self):
        if not hasattr(self, 'preview_text'):
            return
        c = self.preview_text.textCursor()
        line = c.blockNumber() + 1
        col = c.columnNumber() + 1
        sel_len = abs(c.selectionEnd() - c.selectionStart())
        source = self._current_source_mode()
        dirty = ' *dirty*' if self.preview_text.toPlainText() != self._generated_code_snapshot else ''
        self.preview_status_label.setText(f'Ln {line}, Col {col} | Sel {sel_len} | {source}{dirty}')
        if not self._cursor_history_nav:
            pos = c.position()
            if not self._cursor_history or self._cursor_history[-1] != pos:
                self._cursor_history.append(pos)
                self._cursor_history = self._cursor_history[-200:]
                self._cursor_history_index = len(self._cursor_history) - 1

    def action_trim_trailing_whitespace(self):
        code = self.preview_text.toPlainText()
        cleaned = '\n'.join(line.rstrip() for line in code.split('\n'))
        if cleaned != code:
            self._set_preview_text_programmatic(cleaned)
            self._dirty_mark()

    def action_normalize_tabs_to_spaces(self):
        code = self.preview_text.toPlainText()
        cleaned = code.replace('\t', '    ')
        if cleaned != code:
            self._set_preview_text_programmatic(cleaned)
            self._dirty_mark()

    def action_toggle_bookmark(self):
        line = self.preview_text.textCursor().blockNumber()
        if line in self._bookmark_lines:
            self._bookmark_lines.remove(line)
        else:
            self._bookmark_lines.add(line)
        self._flash_preview_line(line)

    def _goto_bookmark(self, forward: bool):
        if not self._bookmark_lines:
            return
        current = self.preview_text.textCursor().blockNumber()
        lines = sorted(self._bookmark_lines)
        if forward:
            target = next((ln for ln in lines if ln > current), lines[0])
        else:
            target = next((ln for ln in reversed(lines) if ln < current), lines[-1])
        block = self.preview_text.document().findBlockByLineNumber(target)
        if block.isValid():
            c = self.preview_text.textCursor()
            c.setPosition(block.position())
            self.preview_text.setTextCursor(c)
            self.preview_text.centerCursor()

    def action_next_bookmark(self):
        self._goto_bookmark(True)

    def action_prev_bookmark(self):
        self._goto_bookmark(False)

    def action_cursor_history(self, step: int):
        if not self._cursor_history:
            return
        idx = max(0, min(len(self._cursor_history) - 1, self._cursor_history_index + step))
        if idx == self._cursor_history_index:
            return
        self._cursor_history_index = idx
        self._cursor_history_nav = True
        try:
            c = self.preview_text.textCursor()
            c.setPosition(self._cursor_history[idx])
            self.preview_text.setTextCursor(c)
            self.preview_text.centerCursor()
        finally:
            self._cursor_history_nav = False

    def action_open_symbol(self):
        code = self.preview_text.toPlainText()
        symbols = re.findall(r'^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)', code, re.MULTILINE)
        names = [f'{kind} {name}' for kind, name in symbols]
        if not names:
            QMessageBox.information(self, 'Open Symbol', 'No def/class symbols found.')
            return
        picked, ok = QInputDialog.getItem(self, 'Open Symbol', 'Symbol:', names, editable=False)
        if not ok or not picked:
            return
        sym = picked.split(' ', 1)[1]
        m = re.search(rf'^\s*(def|class)\s+{re.escape(sym)}\b', code, re.MULTILINE)
        if not m:
            return
        block = self.preview_text.document().findBlock(m.start())
        c = self.preview_text.textCursor()
        c.setPosition(block.position())
        self.preview_text.setTextCursor(c)
        self.preview_text.centerCursor()

    @staticmethod
    def _line_indent_width(line: str) -> int:
        return len(line) - len(line.lstrip(' '))

    def _fold_range_from_block(self, block: QTextBlock):
        if not block.isValid():
            return None
        text = block.text()
        if not re.match(r'^\s*(def|class)\s+[A-Za-z_][A-Za-z0-9_]*', text):
            return None
        base_indent = self._line_indent_width(text)
        start = block.next()
        if not start.isValid():
            return None
        end = None
        b = start
        while b.isValid():
            t = b.text()
            if t.strip() == '':
                b = b.next()
                continue
            indent = self._line_indent_width(t)
            if indent <= base_indent:
                break
            end = b
            b = b.next()
        if end is None or end.blockNumber() < start.blockNumber():
            return None
        return start, end

    def action_toggle_fold_current(self, line_no: int | None = None):
        if isinstance(line_no, int) and line_no > 0:
            block = self.preview_text.document().findBlockByLineNumber(line_no - 1)
        else:
            block = self.preview_text.textCursor().block()
        rng = self._fold_range_from_block(block)
        if rng is None:
            return
        start, end = rng
        hide = start.isVisible()
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            b.setVisible(not hide)
            b.setLineCount(1 if not hide else 0)
            b = b.next()
        self.preview_text.document().markContentsDirty(start.position(), end.position() - start.position() + end.length())
        self.preview_text.viewport().update()

    def action_unfold_all(self):
        b = self.preview_text.document().firstBlock()
        while b.isValid():
            b.setVisible(True)
            b.setLineCount(1)
            b = b.next()
        self.preview_text.document().markContentsDirty(0, self.preview_text.document().characterCount())
        self.preview_text.viewport().update()

    def action_lint_check(self):
        import ast
        code = self.preview_text.toPlainText()
        try:
            ast.parse(code)
            QMessageBox.information(self, 'Lint Check', 'Syntax check passed.')
        except SyntaxError as e:
            QMessageBox.warning(self, 'Lint Check', f'Syntax error at line {e.lineno}, column {e.offset}:\n{e.msg}')

    def action_snapshot_compare(self):
        current = self.preview_text.toPlainText()
        generated = self._generated_code_snapshot or ''
        if current == generated:
            QMessageBox.information(self, 'Snapshot Compare', 'No differences between generated and editor content.')
            return
        import difflib
        diff = ''.join(difflib.unified_diff(generated.splitlines(True), current.splitlines(True), fromfile='generated', tofile='editor'))
        dlg = QDialog(self)
        dlg.setWindowTitle('Snapshot Compare')
        dlg.resize(900, 600)
        layout = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(diff[:20000] or '(Diff too large or unavailable)')
        layout.addWidget(txt)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def action_go_to_line(self):
        text = self.preview_text.toPlainText()
        line_count = max(1, text.count('\n') + 1)
        line_no, ok = QInputDialog.getInt(
            self,
            'Go to Line',
            f'Line number (1-{line_count}):',
            value=1,
            min=1,
            max=line_count,
            step=1,
        )
        if not ok:
            return

        block = self.preview_text.document().findBlockByLineNumber(line_no - 1)
        if not block.isValid():
            return
        cursor = self.preview_text.textCursor()
        cursor.setPosition(block.position())
        self.preview_text.setTextCursor(cursor)
        self.preview_text.centerCursor()
        self._set_active_panel('preview')

    # ── File menu actions ─────────────────────────────────────────────────────

    # ── recent files ──────────────────────────────────────────────────────────

    _MAX_RECENT = 5

    def _settings(self):
        return QSettings('PyFlameUIBuilder', 'PyFlameUIBuilder')

    @staticmethod
    def _parse_saved_sizes(raw) -> list[int]:
        """Normalize QSettings splitter sizes across Qt/Python variants."""
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            out = []
            for x in raw:
                try:
                    out.append(int(x))
                except Exception:
                    pass
            return [v for v in out if v >= 0]
        if isinstance(raw, str):
            parts = re.findall(r'-?\d+', raw)
            return [int(p) for p in parts] if parts else []
        return []

    def _restore_window_layout_settings(self):
        s = self._settings()
        try:
            g = s.value('window/geometry')
            if g:
                self.restoreGeometry(g)
        except Exception:
            pass
        try:
            st = s.value('window/state')
            if st:
                self.restoreState(st)
        except Exception:
            pass

        # Apply splitter/layout settings after Qt finishes initial layout.
        def _apply_late_layout():
            try:
                sizes = self._parse_saved_sizes(s.value('window/main_split_sizes', defaultValue=None))
                if len(sizes) >= 3:
                    # Keep current 3-pane layout: preview | canvas | properties.
                    self.main_split.setSizes(sizes[-3:])
            except Exception:
                pass
            try:
                rsizes = self._parse_saved_sizes(s.value('window/right_split_sizes', defaultValue=None))
                if len(rsizes) >= 2 and hasattr(self, 'right_split'):
                    self.right_split.setSizes(rsizes[:2])
            except Exception:
                pass
            try:
                preview_visible = s.value('ui/preview_visible', defaultValue=True, type=bool)
                self._set_preview_visible(bool(preview_visible))
            except Exception:
                pass
            try:
                active_panel = s.value('ui/active_panel', defaultValue='', type=str) or None
                if active_panel in {'preview', 'props', 'widgets', 'ui'}:
                    self._set_active_panel(active_panel)
            except Exception:
                pass

        QTimer.singleShot(0, _apply_late_layout)

    def _save_window_layout_settings(self):
        s = self._settings()
        try:
            s.setValue('window/geometry', self.saveGeometry())
            s.setValue('window/state', self.saveState())
            s.setValue('window/main_split_sizes', self.main_split.sizes())
            if hasattr(self, 'right_split'):
                s.setValue('window/right_split_sizes', self.right_split.sizes())
            s.setValue('ui/preview_visible', bool(self._preview_visible))
            s.setValue('ui/active_panel', self._active_work_panel or self._active_aux_panel or '')
            s.sync()
        except Exception:
            pass


    def _read_whats_new_points(self, version: str | None = None) -> list[str]:
        target = (version or APP_VERSION).strip()
        if not os.path.exists(CHANGELOG_PATH):
            return []

        points: list[str] = []
        in_target = False
        try:
            with open(CHANGELOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                for raw in f:
                    line = raw.strip()
                    m = re.match(r'^##\s+\[(.+?)\]', line)
                    if m:
                        if in_target:
                            break
                        in_target = (m.group(1).strip() == target)
                        continue
                    if in_target and line.startswith('- '):
                        points.append(line[2:].strip())
        except Exception:
            return []
        return [p for p in points if p]

    def _list_whats_new_versions(self) -> list[str]:
        if not os.path.exists(CHANGELOG_PATH):
            return []

        versions: list[str] = []
        try:
            with open(CHANGELOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                for raw in f:
                    line = raw.strip()
                    m = re.match(r'^##\s+\[(.+?)\]', line)
                    if m:
                        versions.append(m.group(1).strip())
        except Exception:
            return []

        return versions

    def action_open_whats_new(self, version: str):
        points = self._read_whats_new_points(version)
        if points:
            bullets = '\n'.join(f'• {p}' for p in points)
        else:
            bullets = '• No details listed for this version yet.'
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.NoIcon)
        msg.setWindowTitle(f"What's New — {version}")
        msg.setText(f"{APP_NAME}\nVersion {version}\n\nWhat's New:\n{bullets}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    def _show_whats_new_if_needed(self):
        s = self._settings()
        seen = s.value('whatsNewSeenVersion', defaultValue='', type=str) or ''
        if seen == APP_VERSION:
            return

        points = self._read_whats_new_points(APP_VERSION)
        if points:
            bullets = '\n'.join(f'• {p}' for p in points)
        else:
            bullets = '• Improvements and fixes in this release.'

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.NoIcon)
        msg.setWindowTitle(f"What's New — {APP_NAME}")
        msg.setText(f"{APP_NAME}\nVersion {APP_VERSION}\n\nWhat's New:\n{bullets}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()
        s.setValue('whatsNewSeenVersion', APP_VERSION)

    def _recent_files(self) -> list[str]:
        s = self._settings()
        return s.value('recentFiles', defaultValue=[], type=list) or []

    def _add_recent_file(self, path: str):
        files = self._recent_files()
        if path in files:
            files.remove(path)
        files.insert(0, path)
        files = files[:self._MAX_RECENT]
        self._settings().setValue('recentFiles', files)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        files = self._recent_files()
        if files:
            for path in files:
                action = QAction(path, self)
                action.triggered.connect(lambda checked, p=path: self._open_recent(p))
                self._recent_menu.addAction(action)
            self._recent_menu.addSeparator()
            clear_a = QAction('Clear Recent Files', self)
            clear_a.triggered.connect(self._clear_recent)
            self._recent_menu.addAction(clear_a)
        else:
            none_a = QAction('No Recent Files', self)
            none_a.setEnabled(False)
            self._recent_menu.addAction(none_a)

    def _clear_recent(self):
        self._settings().setValue('recentFiles', [])
        self._rebuild_recent_menu()

    def _open_recent(self, path: str):
        if not self._check_unsaved():
            return
        if not os.path.exists(path):
            msg = QMessageBox(self)
            msg.setWindowTitle('File Not Found')
            msg.setText(f'File not found:\n{path}')
            msg.setIcon(QMessageBox.NoIcon)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            files = self._recent_files()
            if path in files:
                files.remove(path)
                self._settings().setValue('recentFiles', files)
                self._rebuild_recent_menu()
            return
        self._load_project(path)

    # ── File menu actions ─────────────────────────────────────────────────────

    def _check_unsaved(self) -> bool:
        if not self._dirty:
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle('Unsaved Changes')
        msg.setText('You have unsaved changes. Continue?')
        msg.setIcon(QMessageBox.NoIcon)
        msg.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        reply = msg.exec()
        if reply == QMessageBox.Save:
            return self._save()
        return reply == QMessageBox.Discard

    def _new_project_no_prompt(self):
        self._raw_import_code = None
        self._preview_user_edited = False
        for c in list(self.canvas.containers):
            c.deleteLater()
        self.canvas.containers.clear()
        self.canvas.selected_container = None
        self.config = WindowConfig()
        self.windows = [ScriptWindow(function_name='main_window', grid_columns=self.config.grid_columns, grid_rows=self.config.grid_rows, widgets=[])]
        self.active_window_index = 0
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()
        self._show_active_window_properties()
        self._save_path = None
        self._clean_mark()
        self._refresh_preview()
        self._history = []
        self._history_index = -1
        self._record_history_state()
        self._update_undo_redo_actions()

    def _new(self):
        if not self._check_unsaved():
            return
        self._new_project_no_prompt()

    def _open(self):
        if not self._check_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Project', '',
            'PyFlame Builder (*.pfb);;All Files (*)',
        )
        if not path:
            return
        self._load_project(path)

    def _normalize_imported_properties(self, widget_type: str, props: dict) -> dict:
        specs = WIDGET_SPECS.get(widget_type, {})
        prop_defs = {p.name: p for p in specs.get('props', [])}
        out = dict(props or {})
        for key, pdef in prop_defs.items():
            if key not in out:
                continue
            val = out[key]
            if pdef.kind == 'enum' and isinstance(val, str):
                # Accept dotted enum forms like Color.RED or direct RED.
                enum_token = val.split('.')[-1]
                if enum_token in (pdef.options or []):
                    out[key] = enum_token
            elif pdef.kind == 'bool' and not isinstance(val, bool):
                if isinstance(val, str):
                    out[key] = val.strip().lower() in ('1', 'true', 'yes', 'on')
                else:
                    out[key] = bool(val)
            elif pdef.kind == 'int' and not isinstance(val, int):
                try:
                    out[key] = int(val)
                except Exception:
                    out[key] = pdef.default
            elif pdef.kind == 'list' and isinstance(val, tuple):
                out[key] = list(val)
        return out

    def _import_script_from_path(self, path: str, interactive: bool = True) -> tuple[bool, str]:
        """Import script windows into current project state.

        This method intentionally delegates conversion details to workflow/services
        so UI code only coordinates prompts + state assignment.
        """
        if not path:
            return False, 'No path provided'

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
        except Exception as e:
            if interactive:
                QMessageBox.critical(self, 'Import Error', f'Failed to read script:\n{e}')
            return False, f'Failed to read script: {e}'

        class_names = detect_classes(code)
        if not class_names:
            if interactive:
                QMessageBox.information(self, 'Import Script', 'No classes found in script. Nothing to import yet.')
            return False, 'No classes found'

        target_class = class_names[0]
        if interactive and len(class_names) > 1:
            target_class, ok = QInputDialog.getItem(
                self,
                'Select Class to Import',
                'Multiple classes found. Import window methods from:',
                class_names,
                0,
                False,
            )
            if not ok:
                return False, 'Class selection cancelled'

        windows_meta = analyze_create_windows(code, target_class)
        if not windows_meta:
            windows_meta = analyze_create_windows(code, None)
        if not windows_meta:
            msg = (
                f'No window-build methods found in class "{target_class}".\n\n'
                'Importer looks for [Start Window Build]/[End Window Build] markers (or create_*/main_window methods).'
            )
            if interactive:
                QMessageBox.information(self, 'Import Script', msg)
            return False, msg

        imported_windows, skipped_items = build_imported_windows(
            windows_meta,
            widget_specs=WIDGET_SPECS,
            normalize_properties=self._normalize_imported_properties,
        )

        self.config.script_name = suggest_script_name_from_path(path)
        self._preview_user_edited = False
        self.windows = imported_windows
        self.active_window_index = 0
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()
        self._raw_import_code = code
        self._refresh_preview()
        self._dirty_mark()

        text = summarize_import_result(imported_windows, skipped_items, target_class)
        if interactive:
            msg = QMessageBox(self)
            msg.setWindowTitle('Import Complete')
            msg.setText(text + '\n\nBeta note: complex/custom widget logic may be skipped in this phase.')
            msg.setIcon(QMessageBox.NoIcon)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
        return True, text

    def action_import_existing_script(self):
        if not self._check_unsaved():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            'Import Script',
            '',
            'Python Script (*.py);;All Files (*)',
        )
        if not path:
            return
        self._import_script_from_path(path, interactive=True)

    def _load_project(self, path: str):
        self._raw_import_code = None
        self._preview_user_edited = False
        try:
            config, windows, active_window = ProjectSerializer.load(path)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to load project:\n{e}')
            return

        for c in list(self.canvas.containers):
            c.deleteLater()
        self.canvas.containers.clear()
        self.canvas.selected_container = None

        self.config = config
        self.windows = windows or [ScriptWindow(function_name='main_window', grid_columns=config.grid_columns, grid_rows=config.grid_rows, widgets=[])]
        self.active_window_index = max(0, min(active_window, len(self.windows)-1))
        self._rebuild_window_tabs()
        self._sync_canvas_from_active_window()

        self._show_active_window_properties()
        self._save_path = path
        self._add_recent_file(path)
        self._clean_mark()
        self._refresh_preview()
        self._history = []
        self._history_index = -1
        self._record_history_state()
        self._update_undo_redo_actions()

    def _save(self) -> bool:
        if self._save_path is None:
            return self._save_as()
        try:
            self._persist_active_window()
            ProjectSerializer.save(self._save_path, self.config, self.windows, active_window=self.active_window_index)
            self._add_recent_file(self._save_path)
            self._clean_mark()
            return True
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to save:\n{e}')
            return False

    def _save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Project', '',
            'PyFlame Builder (*.pfb);;All Files (*)',
        )
        if not path:
            return False
        if not path.endswith('.pfb'):
            path += '.pfb'
        self._save_path = path
        return self._save()

    # ── code generation ───────────────────────────────────────────────────────

    def _prompt_tab_order(self, models: list) -> 'list[str] | None':
        """Show tab-order dialog if there are 2+ entry widgets; return ordered
        var list or None if skipped / not applicable."""
        entries = [m for m in models
                   if m.widget_type in ('PyFlameEntry', 'PyFlameEntryBrowser')]
        if len(entries) < 2:
            return None
        dlg = TabOrderDialog(entries, parent=self)
        if dlg.exec() == QDialog.Accepted:
            return dlg.ordered_vars()
        return None

    def _generate_code(self):
        self._persist_active_window()
        current_models = [c.model for c in self.canvas.containers]
        tab_order = self._prompt_tab_order(current_models)
        code = CodeGenerator.generate(self.config, current_models, tab_order=tab_order, windows=self.windows)

        dlg = QDialog(self)
        dlg.setWindowTitle('Generated Code')
        dlg.resize(860, 640)
        dlg.setStyleSheet(_app_stylesheet())

        layout = QVBoxLayout(dlg)

        te = QPlainTextEdit()
        te.setReadOnly(True)
        te.setPlainText(code)
        te.setStyleSheet(
            'background: #1a1a1a; color: #c8c8c8;'
            ' font-family: "Courier New", monospace; font-size: 12px;'
        )
        layout.addWidget(te)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton('Copy to Clipboard')
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(code),
            copy_btn.setText('Copied!'),
        ))
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dlg.exec()

    # ── script generation ─────────────────────────────────────────────────────

    def _export_script_to_dir(self, output_dir: str, *, overwrite: bool, interactive: bool, reveal: bool) -> tuple[bool, str]:
        """Export current builder state to a Flame-ready script folder."""
        # Interactive mode is allowed to prompt before overwrite.
        effective_overwrite = overwrite

        # Warn (but allow) duplicate window names because they can produce
        # ambiguous generated method names and unexpected behavior.
        names = [(w.function_name or '').strip() for w in self.windows]
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        if interactive and dupes:
            msg = QMessageBox(self)
            msg.setWindowTitle('Duplicate Window Names Detected')
            msg.setText(
                'Two or more windows share the same name. This may cause problems in exported scripts.\n\n'
                f'Duplicates: {", ".join(dupes)}\n\n'
                'Do you want to continue exporting?'
            )
            msg.setIcon(QMessageBox.NoIcon)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Cancel)
            if msg.exec() != QMessageBox.Yes:
                return False, 'Export cancelled'
        if interactive and not overwrite:
            snake = to_snake(self.config.script_name)
            script_dir = os.path.join(output_dir, snake)
            if os.path.exists(script_dir):
                msg = QMessageBox(self)
                msg.setWindowTitle('Folder Exists')
                msg.setText(f'A folder named "{snake}" already exists at:\n{output_dir}\n\nOverwrite it?')
                msg.setIcon(QMessageBox.NoIcon)
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
                if msg.exec() != QMessageBox.Yes:
                    return False, 'Export cancelled'
                effective_overwrite = True

        try:
            ok, dir_or_err, snake = prepare_export_tree(
                TEMPLATE_DIR,
                output_dir,
                self.config.script_name,
                overwrite=effective_overwrite,
            )
            if not ok:
                return False, dir_or_err
            script_dir = dir_or_err

            self._persist_active_window()
            current_models = [c.model for c in self.canvas.containers]
            tab_order = self._prompt_tab_order(current_models) if interactive else None
            generated_code = CodeGenerator.generate(self.config, current_models, tab_order=tab_order, windows=self.windows)
            edited_code = self.preview_text.toPlainText()

            def _select_target_class(class_names: list[str]) -> str | None:
                if not interactive:
                    return class_names[0] if class_names else None
                selected, ok = QInputDialog.getItem(
                    self,
                    'Select Target Class',
                    'Multiple classes found. Insert generated windows into:',
                    class_names,
                    0,
                    False,
                )
                if not ok:
                    return None
                return selected

            ok_code, code_or_err, _mode = decide_export_code(
                generated_code=generated_code,
                edited_code=edited_code,
                preview_user_edited=self._preview_user_edited,
                raw_import_code=self._raw_import_code,
                windows=self.windows,
                class_selector=_select_target_class,
            )
            if not ok_code:
                return False, code_or_err

            with open(os.path.join(script_dir, f'{snake}.py'), 'w') as f:
                f.write(code_or_err)

            if self.config.license_type != 'None':
                self._write_license_file(script_dir, self.config.license_type)

        except Exception as e:
            return False, f'Failed to export script: {e}'

        if reveal:
            self._reveal_in_finder(script_dir)
        return True, script_dir

    def _collect_export_preflight_warnings(self) -> list[str]:
        warnings: list[str] = []
        names = [w.function_name for w in self.windows if (w.function_name or '').strip()]
        dups = sorted({n for n in names if names.count(n) > 1})
        if dups:
            warnings.append(f'Duplicate window function names: {", ".join(dups)}')
        known = {w.function_name for w in self.windows}
        unresolved = sorted({w.parent_window for w in self.windows if getattr(w, 'parent_window', None) and w.parent_window not in known})
        if unresolved:
            warnings.append(f'Unresolved parent window references: {", ".join(unresolved)}')
        if self._preview_user_edited and self.preview_text.toPlainText() != self._generated_code_snapshot:
            warnings.append('Manual edits diverge from generated code; export will prefer editor content.')
        return warnings

    def _show_export_preflight(self) -> bool:
        warnings = self._collect_export_preflight_warnings()
        if not warnings:
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle('Export Preflight')
        msg.setIcon(QMessageBox.Warning)
        msg.setText('Please review preflight warnings before export:')
        msg.setInformativeText('\n'.join(f'• {w}' for w in warnings))
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        return msg.exec() == QMessageBox.Ok

    def _export_ui_code_only(self):
        text = self.preview_text.toPlainText() if hasattr(self, 'preview_text') else ''
        ranges = self._protected_window_build_ranges(text)
        if not ranges:
            QMessageBox.information(self, 'Export UI Code Only', 'No protected UI Window Build sections found.')
            return

        blocks = [text[s:e].rstrip() for s, e in ranges]
        payload = '\n\n'.join(blocks).rstrip() + '\n'

        default_name = f"{to_snake(getattr(self.config, 'script_name', 'script') or 'script')}_ui_code.py"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export UI Code Only',
            default_name,
            'Python Script (*.py);;All Files (*)',
        )
        if not out_path:
            return

        try:
            with open(out_path, 'w', encoding='utf-8') as fh:
                fh.write(payload)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to export UI code:\n{e}')
            return

        QMessageBox.information(self, 'Export UI Code Only', f'UI code exported successfully:\n{out_path}')

    def _generate_script(self):
        if not self._show_export_preflight():
            return
        output_dir = QFileDialog.getExistingDirectory(
            self, 'Select Output Directory', '',
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not output_dir:
            return

        ok, result = self._export_script_to_dir(output_dir, overwrite=False, interactive=True, reveal=True)
        if not ok:
            if result != 'Export cancelled':
                QMessageBox.critical(self, 'Error', result)
            return

        msg = QMessageBox(self)
        msg.setWindowTitle('Script Exported')
        msg.setText(f'Script exported successfully:\n{result}\n\n(Revealed in Finder)')
        msg.setIcon(QMessageBox.NoIcon)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()

    @staticmethod
    def _reveal_in_finder(path: str):
        try:
            if sys.platform == 'darwin':
                subprocess.run(['open', path], check=False)
            elif sys.platform.startswith('linux'):
                subprocess.run(['xdg-open', path], check=False)
        except Exception:
            pass

    @staticmethod
    def _write_license_file(script_dir: str, license_type: str):
        """Write a LICENSE file to the script root for the chosen license."""
        year = datetime.date.today().year

        # For GPL-3.0 we can copy the full text already bundled in the template
        gpl_src = os.path.join(TEMPLATE_DIR, 'lib', 'LICENSE')
        if license_type == 'GPL-3.0' and os.path.exists(gpl_src):
            shutil.copy2(gpl_src, os.path.join(script_dir, 'LICENSE'))
            return

        urls = {
            'LGPL-3.0':    'https://www.gnu.org/licenses/lgpl-3.0.en.html',
            'MIT':         'https://opensource.org/licenses/MIT',
            'Apache-2.0':  'https://www.apache.org/licenses/LICENSE-2.0',
            'BSD-2-Clause':'https://opensource.org/licenses/BSD-2-Clause',
            'BSD-3-Clause':'https://opensource.org/licenses/BSD-3-Clause',
        }

        mit_text = f"""\
MIT License

Copyright (c) {year}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

        bsd2_text = f"""\
BSD 2-Clause License

Copyright (c) {year}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

        bsd3_text = f"""\
BSD 3-Clause License

Copyright (c) {year}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

        full_texts = {
            'MIT':          mit_text,
            'BSD-2-Clause': bsd2_text,
            'BSD-3-Clause': bsd3_text,
        }

        if license_type in full_texts:
            text = full_texts[license_type]
        else:
            url  = urls.get(license_type, '')
            text = (
                f'SPDX-License-Identifier: {license_type}\n\n'
                f'Copyright (c) {year}\n\n'
                f'See {url} for the full license text.\n'
            )

        with open(os.path.join(script_dir, 'LICENSE'), 'w') as f:
            f.write(text)

    # ── window events ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._check_unsaved():
            self._save_window_layout_settings()
            try:
                QApplication.instance().removeEventFilter(self)
            except Exception:
                pass
            try:
                if self._api_server is not None:
                    self._api_server.shutdown()
                    self._api_server.server_close()
            except Exception:
                pass
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            event.accept()
            return
        if event.key() == Qt.Key_Delete:
            self.canvas.remove_selected()
            return
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self.canvas.keyPressEvent(event)
            return
        else:
            super().keyPressEvent(event)


# ==============================================================================
# Entry Point
# ==============================================================================

def _set_macos_app_name(name: str):
    """Patch process/bundle names so macOS menu bar shows custom app name."""
    try:
        from Foundation import NSBundle, NSProcessInfo
        NSProcessInfo.processInfo().setProcessName_(name)
        info = NSBundle.mainBundle().infoDictionary()
        info['CFBundleName'] = name
        info['CFBundleDisplayName'] = name
    except Exception:
        pass


def _load_fonts() -> str | None:
    """Load bundled fonts and return preferred family when available."""
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts')
    loaded_families: list[str] = []
    for fname in ('Montserrat-Regular.ttf', 'Montserrat-Light.ttf', 'Montserrat-Thin.ttf'):
        font_id = QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
        if font_id != -1:
            loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id) or [])

    preferred = next((f for f in loaded_families if isinstance(f, str) and f.strip()), None)
    return preferred


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logger = init_logging(base_dir)
    logger.info('Starting %s v%s', APP_NAME, APP_VERSION)

    def _log_unhandled(exc_type, exc, tb):
        logger.exception('Unhandled exception', exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _unraisable_hook(unraisable):
        # Suppress noisy Qt shutdown warnings from pyflame_lib tooltip timers.
        try:
            msg = str(unraisable.exc_value) if unraisable.exc_value else ''
            obj = str(unraisable.object) if unraisable.object else ''
            if (
                isinstance(unraisable.exc_value, RuntimeError)
                and 'Internal C++ object (PySide6.QtCore.QTimer) already deleted' in msg
                and 'PyFlameToolTip.__del__' in obj
            ):
                logger.debug('Suppressed known PyFlameToolTip shutdown timer warning')
                return
        except Exception:
            pass
        sys.__unraisablehook__(unraisable)

    sys.excepthook = _log_unhandled
    sys.unraisablehook = _unraisable_hook

    app = QApplication.instance() or QApplication(sys.argv)
    _patch_messagebox_no_icons()
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    _set_macos_app_name(APP_NAME)
    preferred_font = _load_fonts()
    if preferred_font:
        app.setFont(QFont(preferred_font, 10))
    window = PyFlameBuilder()
    window.show()
    rc = app.exec()
    logger.info('Shutting down %s with exit code %s', APP_NAME, rc)
    sys.exit(rc)


if __name__ == '__main__':
    main()
