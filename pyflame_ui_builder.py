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
sys.modules['flame'] = _flame_mock

# ==============================================================================
# Standard Imports
# ==============================================================================

import os
import re
import json
import copy
import shutil
import datetime
import logging
import subprocess
import importlib.util
import traceback
from logging.handlers import RotatingFileHandler
from collections import namedtuple
from dataclasses import dataclass, field

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
    QScrollArea, QListWidget, QListWidgetItem, QLabel, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QSplitter, QFrame, QDialog,
    QPlainTextEdit, QPushButton, QFileDialog, QMessageBox,
    QFormLayout, QGroupBox, QAbstractItemView, QSizePolicy, QMenu, QTextEdit,
    QTextBrowser,
)
from PySide6.QtCore import Qt, QPoint, QRect, QSize, QMimeData, Signal, QSettings, QTimer, QRegularExpression
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QDrag, QFont, QFontDatabase, QKeySequence, QAction,
    QTextCursor, QTextFormat, QRegularExpressionValidator,
)

# ==============================================================================
# QApplication must exist before pyflame_lib loads (it calls screenGeometry() at
# module level via _load_font() → pyflame.gui_resize() → pyflame.window_resolution())
# ==============================================================================

APP_NAME = 'PyFlame UI Builder'
APP_VERSION = '1.0.0'
APP_AUTHOR = 'Michael Vaglienty'
APP_LICENSE = 'GPL-3.0'
APP_URL = 'https://github.com/logik-portal/PyFlame-UI-Builder'
APP_DESCRIPTION = 'Visual UI builder for Autodesk Flame Python scripts.'

# Bootstrap logger so early module-load events are visible in terminal.
_bootstrap_logger = logging.getLogger('pyflame_builder')
_bootstrap_logger.setLevel(logging.INFO)
if not _bootstrap_logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    _bootstrap_logger.addHandler(_h)

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
    _pyflame_loaded = True
    _bootstrap_logger.info('pyflame_lib loaded successfully.')
except Exception as _e:
    _bootstrap_logger.warning('Could not load pyflame_lib: %s', _e)
    _bootstrap_logger.exception('pyflame_lib import traceback')

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'script_template')


def _to_snake(name: str) -> str:
    """Convert a script name to a safe lowercase_underscore identifier.
    Replaces any run of non-alphanumeric characters with a single underscore."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    return name or 'script'

# ==============================================================================
# Data Models
# ==============================================================================

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
    license_type: str = 'GPL-3.0'
    grid_columns: int = 4
    grid_rows: int = 3
    column_width: int = 150
    row_height: int = 28


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
                    ['GRAY', 'BLUE', 'RED', 'YELLOW', 'GREEN', 'TEAL']),
        ],
    },
    'PyFlameVerticalLine': {
        'display': 'Vertical Line',
        'category': 'Layout',
        'fixed_axes': {'w'},
        'props': [
            PropDef('color', 'enum', 'GRAY',
                    ['GRAY', 'BLUE', 'RED', 'YELLOW', 'GREEN', 'TEAL']),
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


# ==============================================================================
# TabOrderDialog
# ==============================================================================

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

        info = QLabel(
            f'{len(entries)} entry widgets found.\n'
            'Drag items or use the arrows to set the tab order.'
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setDefaultDropAction(Qt.MoveAction)
        for e in entries:
            self._list.addItem(e.var_name or 'entry')
        layout.addWidget(self._list)

        arrow_row = QHBoxLayout()
        up_btn   = QPushButton('▲  Up')
        down_btn = QPushButton('▼  Down')
        up_btn.clicked.connect(self._move_up)
        down_btn.clicked.connect(self._move_down)
        arrow_row.addWidget(up_btn)
        arrow_row.addWidget(down_btn)
        arrow_row.addStretch()
        layout.addLayout(arrow_row)

        btn_row = QHBoxLayout()
        ok_btn     = QPushButton('Include Tab Order')
        ok_btn.setStyleSheet('background: #0078d7; color: white; padding: 4px 16px;')
        ok_btn.clicked.connect(self.accept)
        skip_btn   = QPushButton('Skip')
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


# ==============================================================================
# MoveResizeDialog
# ==============================================================================

class MoveResizeDialog(QDialog):
    """Dialog for setting a widget's grid position and span."""

    def __init__(self, container, canvas):
        super().__init__(canvas)
        self.container = container
        self.canvas    = canvas
        m   = container.model
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

        self._row     = QSpinBox(); self._row.setRange(0, cfg.grid_rows - 1);     self._row.setValue(m.row)
        self._col     = QSpinBox(); self._col.setRange(0, cfg.grid_columns - 1);  self._col.setValue(m.col)
        self._rowspan = QSpinBox(); self._rowspan.setRange(1, cfg.grid_rows);      self._rowspan.setValue(m.row_span)
        self._colspan = QSpinBox(); self._colspan.setRange(1, cfg.grid_columns);   self._colspan.setValue(m.col_span)

        fixed = WIDGET_SPECS.get(m.widget_type, {}).get('fixed_axes', set())
        if 'h' in fixed:
            self._rowspan.setValue(1)
            self._rowspan.setEnabled(False)
        if 'w' in fixed:
            self._colspan.setValue(1)
            self._colspan.setEnabled(False)

        form.addRow('Row:',      self._row)
        form.addRow('Column:',   self._col)
        if not ({'h', 'w'} <= set(fixed)):
            form.addRow('Row Span:', self._rowspan)
            form.addRow('Col Span:', self._colspan)

        btn_row = QHBoxLayout()
        apply_btn  = QPushButton('Apply')
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
        m   = self.container.model
        cfg = self.canvas.config
        row      = min(self._row.value(),     cfg.grid_rows    - 1)
        col      = min(self._col.value(),     cfg.grid_columns - 1)
        row_span = min(self._rowspan.value(), cfg.grid_rows    - row)
        col_span = min(self._colspan.value(), cfg.grid_columns - col)
        m.row, m.col           = row, col
        m.row_span, m.col_span = row_span, col_span
        self.container.setGeometry(self.canvas.cell_rect(row, col, row_span, col_span))
        self.canvas.widget_moved.emit(self.container)
        self.accept()


# ==============================================================================
# WidgetOverlay
# ==============================================================================

class WidgetOverlay(QWidget):
    """
    Transparent overlay covering the entire WidgetContainer.

    Interaction model:
      • Left-click  → selects widget (properties panel) then forwards the click
                       to the real PyFlame widget so it stays fully interactive.
      • Right-drag  → moves the container freely; release snaps to grid.
      • Right-drag on a handle → resizes; release snaps to grid.
    """

    _CURSOR_MAP = {
        'nw': Qt.SizeFDiagCursor, 'se': Qt.SizeFDiagCursor,
        'ne': Qt.SizeBDiagCursor, 'sw': Qt.SizeBDiagCursor,
        'n':  Qt.SizeVerCursor,   's':  Qt.SizeVerCursor,
        'e':  Qt.SizeHorCursor,   'w':  Qt.SizeHorCursor,
    }

    def __init__(self, container):
        super().__init__(container)
        self.container  = container
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._mode         = None   # None | 'move' | handle_id
        self._press_pos    = None
        self._press_geom   = None
        self._rclick_pos   = None   # global pos of RMB press (before drag starts)
        self._rclick_local = None   # local pos of RMB press
        self._drag_started = False  # True once RMB drag threshold is crossed

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self.container.selected:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        # Blue dashed border
        p.setPen(QPen(QColor(0, 120, 215), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))

        # Resize handles — only draw handles valid for this widget type
        allowed = _allowed_handle_ids(self.container.model.widget_type)
        p.setPen(QPen(QColor(0, 100, 200), 1))
        p.setBrush(QBrush(QColor(255, 255, 255)))
        for hid, hr in _handle_rects(self.rect()).items():
            if hid in allowed:
                p.drawRect(hr)

        # Grid position hint in top-right corner
        m = self.container.model
        coord_hint = f'R{m.row + 1} C{m.col + 1}'
        if m.row_span > 1 or m.col_span > 1:
            coord_hint += f' · {m.row_span}×{m.col_span}'
        p.setPen(QPen(QColor(0, 120, 215, 180), 1))
        p.setFont(QFont('Arial', 7))
        p.drawText(self.rect().adjusted(0, 0, -3, 0),
                   Qt.AlignTop | Qt.AlignRight, coord_hint)
        p.end()

    # ── hit-testing ───────────────────────────────────────────────────────────

    def _hit_test(self, pos):
        allowed = _allowed_handle_ids(self.container.model.widget_type)
        for hid, hr in _handle_rects(self.rect()).items():
            if hid in allowed and hr.contains(pos):
                return hid
        return None

    # ── overlay mouse events (left-drag = move/resize, right-click = menu) ──

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Record position; defer drag start until mouse moves past threshold
            self._rclick_pos   = event.globalPosition().toPoint()
            self._rclick_local = event.position().toPoint()
            self._drag_started = False
            self.container.canvas.select_widget(self.container)
            event.accept()
        elif event.button() == Qt.RightButton:
            self.container.canvas.select_widget(self.container)
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
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
            # Update cursor: resize cursor over handles, arrow elsewhere
            handle = self._hit_test(event.position().toPoint())
            if handle:
                self.setCursor(self._CURSOR_MAP.get(handle, Qt.ArrowCursor))
            else:
                self.unsetCursor()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._drag_started and self._mode is not None:
                self._finish_drag()
            self._rclick_pos   = None
            self._rclick_local = None
            self._drag_started = False
        event.accept()

    # ── event filter (fallback: catches events when pyflame widget is on top) ─

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        t = event.type()

        if t == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                global_pos = obj.mapToGlobal(event.position().toPoint())
                local_pos  = self.mapFromGlobal(global_pos)
                self._rclick_pos   = global_pos
                self._rclick_local = local_pos
                self._drag_started = False
                self.container.canvas.select_widget(self.container)
                return True
            if event.button() == Qt.RightButton:
                self.container.canvas.select_widget(self.container)
                global_pos = obj.mapToGlobal(event.position().toPoint())
                self._show_context_menu(global_pos)
                return True

        if t == QEvent.MouseMove:
            if event.buttons() & Qt.LeftButton:
                if self._rclick_pos is not None and not self._drag_started:
                    global_pos = obj.mapToGlobal(event.position().toPoint())
                    moved = (global_pos - self._rclick_pos).manhattanLength()
                    if moved > 5:
                        self._start_drag(self._rclick_pos, self._rclick_local)
                        self._drag_started = True
                if self._mode is not None:
                    global_pos = obj.mapToGlobal(event.position().toPoint())
                    self._do_move(global_pos)
                    return True
            return False

        if t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._drag_started and self._mode is not None:
                self._finish_drag()
            self._rclick_pos   = None
            self._rclick_local = None
            self._drag_started = False
            return True

        return False

    # ── drag logic ────────────────────────────────────────────────────────────

    def _start_drag(self, global_pos, local_pos):
        handle = self._hit_test(local_pos)
        self._mode       = handle if handle else 'move'
        self._press_pos  = global_pos
        self._press_geom = self.container.geometry()
        self.container.canvas.select_widget(self.container)
        if self._mode == 'move':
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.setCursor(self._CURSOR_MAP.get(self._mode, Qt.SizeAllCursor))

    def _do_move(self, global_pos):
        delta = global_pos - self._press_pos
        if self._mode == 'move':
            self.container.move(self._press_geom.topLeft() + delta)
        else:
            self._apply_resize(delta, self._press_geom)

    def _finish_drag(self):
        self._snap_to_grid()
        self._mode       = None
        self._press_pos  = None
        self._press_geom = None
        self.unsetCursor()
        self.container.canvas.widget_moved.emit(self.container)

    # ── forward left-click to the real widget ─────────────────────────────────

    def _forward_event(self, event):
        """Send a cloned mouse event to the appropriate child of pyflame_widget."""
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QPointF
        widget     = self.container.pyflame_widget
        global_pos = event.globalPosition()
        local_pt   = widget.mapFromGlobal(global_pos.toPoint())
        target     = widget.childAt(local_pt) or widget
        target_pos = QPointF(target.mapFromGlobal(global_pos.toPoint()))
        QApplication.sendEvent(
            target,
            QMouseEvent(event.type(), target_pos, global_pos,
                        event.button(), event.buttons(), event.modifiers()),
        )

    # ── context menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, global_pos):
        m      = self.container.model
        canvas = self.container.canvas

        menu = QMenu(self)
        menu.setStyleSheet(canvas._MENU_STYLE)

        mw = canvas.window()
        if hasattr(mw, 'undo_action') and hasattr(mw, 'redo_action'):
            menu.addAction(mw.undo_action)
            # Only show Redo in context menu when redo is actually available.
            if mw.redo_action.isEnabled():
                menu.addAction(mw.redo_action)
            menu.addSeparator()

        duplicate_action   = menu.addAction('Duplicate Widget')
        delete_action      = menu.addAction('Delete Widget')
        menu.addSeparator()

        row_above_action   = menu.addAction('Add Row Above')
        row_below_action   = menu.addAction('Add Row Below')
        del_row_action     = menu.addAction('Delete Row')
        del_row_action.setEnabled(canvas.config.grid_rows > 1)
        menu.addSeparator()
        col_left_action    = menu.addAction('Add Column Left')
        col_right_action   = menu.addAction('Add Column Right')
        del_col_action     = menu.addAction('Delete Column')
        del_col_action.setEnabled(canvas.config.grid_columns > 1)

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
            canvas.select_widget(self.container)
            canvas.duplicate_selected()
        elif action == delete_action:
            self._delete_widget()

    def _delete_widget(self):
        canvas = self.container.canvas
        canvas.select_widget(self.container)
        canvas.remove_selected()

    def _open_move_resize_dialog(self):
        dlg = MoveResizeDialog(self.container, self.container.canvas)
        dlg.exec()

    # ── resize helper ─────────────────────────────────────────────────────────

    def _apply_resize(self, delta, orig):
        canvas = self.container.canvas
        cfg    = canvas.config
        z      = canvas.zoom_factor
        min_w  = max(1, int(cfg.column_width * z))
        min_h  = max(1, int(cfg.row_height * z))
        dx, dy = delta.x(), delta.y()
        left, top, right, bottom = orig.left(), orig.top(), orig.right(), orig.bottom()

        if 'w' in self._mode:
            left = min(orig.left() + dx, right - min_w)
        if 'e' in self._mode:
            right = max(orig.right() + dx, left + min_w)
        if 'n' in self._mode:
            top = min(orig.top() + dy, bottom - min_h)
        if 's' in self._mode:
            bottom = max(orig.bottom() + dy, top + min_h)

        self.container.setGeometry(left, top, right - left, bottom - top)

    # ── snap to grid ──────────────────────────────────────────────────────────

    def _snap_to_grid(self):
        canvas   = self.container.canvas
        cfg      = canvas.config
        z        = canvas.zoom_factor
        cw       = max(1, int(cfg.column_width * z))
        rh       = max(1, int(cfg.row_height * z))
        ox       = int(CHROME_SIDE_W * z)
        oy       = int(CHROME_TITLE_H * z)
        geom     = self.container.geometry()

        prev_row = self.container.model.row
        prev_col = self.container.model.col
        prev_row_span = self.container.model.row_span
        prev_col_span = self.container.model.col_span

        col      = round((geom.x() - ox) / cw)
        row      = round((geom.y() - oy) / rh)
        col_span = max(1, round(geom.width()  / cw))
        row_span = max(1, round(geom.height() / rh))

        col      = max(0, min(col,      cfg.grid_columns - 1))
        row      = max(0, min(row,      cfg.grid_rows    - 1))
        col_span = min(col_span, cfg.grid_columns - col)
        row_span = min(row_span, cfg.grid_rows    - row)

        # Lock span on fixed axes
        fixed = WIDGET_SPECS.get(self.container.model.widget_type, {}).get('fixed_axes', set())
        if 'h' in fixed:
            row_span = 1
        if 'w' in fixed:
            col_span = 1

        # Prevent overlap; if blocked, revert to previous grid placement.
        if canvas._has_overlap(row, col, row_span, col_span, ignore_container=self.container):
            row, col, row_span, col_span = prev_row, prev_col, prev_row_span, prev_col_span

        model = self.container.model
        model.row, model.col           = row, col
        model.row_span, model.col_span = row_span, col_span

        # Use canonical cell_rect so geometry is always consistent with
        # current grid gap/zoom rules.
        self.container.setGeometry(
            canvas.cell_rect(row, col, row_span, col_span)
        )


# ==============================================================================
# WidgetContainer
# ==============================================================================

class WidgetContainer(QFrame):
    """Wraps one real PyFlame widget on the canvas with a transparent overlay."""

    def __init__(self, pyflame_widget, placed_model, canvas):
        super().__init__(canvas)
        self.model = placed_model
        self.canvas = canvas
        self.selected = False
        self.pyflame_widget = pyflame_widget

        self.setFrameStyle(QFrame.NoFrame)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet('background: transparent; border: none;')
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(pyflame_widget)
        self._free_size_constraints(pyflame_widget)

        self.overlay = WidgetOverlay(self)
        self.overlay.move(0, 0)
        self.overlay.raise_()   # must be above pyflame_widget in Z-order

        # Belt-and-suspenders: if pyflame widget or any descendant ends up
        # above the overlay (some PyFlame widgets raise themselves), the event
        # filter on the overlay will still catch the click.
        self._install_filter(pyflame_widget)

    def _install_filter(self, widget):
        widget.installEventFilter(self.overlay)
        from PySide6.QtWidgets import QWidget as _QW
        for child in widget.findChildren(_QW):
            child.installEventFilter(self.overlay)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.resize(self.size())
        self.overlay.raise_()   # re-raise after Qt re-stacks layout children
        self.overlay.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.overlay.raise_()

    def set_selected(self, selected):
        self.selected = selected
        self.overlay.update()

    @staticmethod
    def _free_size_constraints(widget):
        """Remove fixed-size locks set by PyFlame widgets so the layout can
        expand them to fill the container."""
        widget.setMinimumSize(0, 0)
        widget.setMaximumSize(16777215, 16777215)   # QWIDGETSIZE_MAX
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def replace_inner_widget(self, new_widget):
        """Swap the inner PyFlame widget (called on property change)."""
        item = self._layout.takeAt(0)
        if item and item.widget():
            item.widget().deleteLater()
        self.pyflame_widget = new_widget
        self._layout.addWidget(new_widget)
        self._free_size_constraints(new_widget)
        # Reinstall event filter on the new widget and keep overlay on top
        self._install_filter(new_widget)
        self.overlay.raise_()

    # ── static factory ────────────────────────────────────────────────────────

    @staticmethod
    def make_widget(widget_type, props):
        """Instantiate the real PyFlame widget from type name + props dict."""
        if not _pyflame_loaded:
            return _make_fallback_widget(widget_type)
        cls = globals().get(widget_type)
        if cls is None:
            return _make_fallback_widget(widget_type)
        kwargs = _props_to_kwargs(widget_type, props)
        try:
            w = cls(**kwargs)
            if widget_type == 'PyFlameHorizontalLine':
                host = QWidget()
                host.setStyleSheet('background: transparent;')
                lay = QVBoxLayout(host)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addStretch(1)
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet('background: #4a4a4a; border: none;')
                lay.addWidget(line)
                lay.addStretch(1)
                return host
            if widget_type == 'PyFlameVerticalLine':
                host = QWidget()
                host.setStyleSheet('background: transparent;')
                lay = QHBoxLayout(host)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.addStretch(1)
                line = QFrame()
                line.setFixedWidth(1)
                line.setStyleSheet('background: #4a4a4a; border: none;')
                lay.addWidget(line)
                lay.addStretch(1)
                return host
            if widget_type == 'PyFlameProgressBarWidget':
                host = ProgressBarPreview()
                host.setStyleSheet('background: transparent;')
                return host
            return w
        except Exception as e:
            print(f'Warning: {widget_type}({kwargs}) → {e}')
            return _make_fallback_widget(widget_type)


# ==============================================================================
# CanvasWidget
# ==============================================================================

class CanvasWidget(QWidget):
    """The design surface. Children (WidgetContainers) are placed absolutely."""

    widget_moved    = Signal(object)   # emits WidgetContainer
    widget_selected = Signal(object)   # emits WidgetContainer or None
    grid_changed    = Signal(object)   # emits updated WindowConfig
    content_changed = Signal()         # add/remove widgets

    def __init__(self, config: WindowConfig):
        super().__init__()
        self.config = config
        self.zoom_factor = 1.0
        self.grid_visible = False
        self.containers: list[WidgetContainer] = []
        self.selected_container = None
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        sz = self.canvas_size()
        self.setMinimumSize(sz)
        self.resize(sz)

        # Zoom controls live in the main UI bottom bar (not inside canvas)

    # ── sizing ────────────────────────────────────────────────────────────────

    def canvas_size(self):
        base_w = CHROME_SIDE_W + self.config.grid_columns * self.config.column_width
        base_h = CHROME_TITLE_H + self.config.grid_rows * self.config.row_height + CHROME_MSG_H
        return QSize(int(base_w * self.zoom_factor), int(base_h * self.zoom_factor))

    def sizeHint(self):
        return self.canvas_size()

    def grid_origin(self):
        return QPoint(int(CHROME_SIDE_W * self.zoom_factor), int(CHROME_TITLE_H * self.zoom_factor))

    def cell_rect(self, row, col, rowspan=1, colspan=1):
        ox = int(CHROME_SIDE_W * self.zoom_factor)
        oy = int(CHROME_TITLE_H * self.zoom_factor)
        cw = int(self.config.column_width * self.zoom_factor)
        rh = int(self.config.row_height * self.zoom_factor)
        gap = max(1, int(CELL_GAP * self.zoom_factor))
        x = ox + col * cw + gap // 2
        y = oy + row * rh + gap // 2
        # Span from interior edge to interior edge across selected cells.
        # (Subtract one total gap, not one per cell, to avoid coming up short.)
        w = max(1, colspan * cw - gap)
        h = max(1, rowspan * rh - gap)
        return QRect(x, y, w, h)

    def _pos_to_cell(self, pos):
        ox = int(CHROME_SIDE_W * self.zoom_factor)
        oy = int(CHROME_TITLE_H * self.zoom_factor)
        cw = max(1, int(self.config.column_width * self.zoom_factor))
        rh = max(1, int(self.config.row_height * self.zoom_factor))
        col = max(0, min((pos.x() - ox) // cw, self.config.grid_columns - 1))
        row = max(0, min((pos.y() - oy) // rh, self.config.grid_rows - 1))
        return int(row), int(col)

    @staticmethod
    def _cells_overlap(r1, c1, rs1, cs1, r2, c2, rs2, cs2) -> bool:
        return not (
            r1 + rs1 <= r2 or r2 + rs2 <= r1 or
            c1 + cs1 <= c2 or c2 + cs2 <= c1
        )

    def _has_overlap(self, row, col, row_span, col_span, ignore_container=None) -> bool:
        for c in self.containers:
            if c is ignore_container:
                continue
            m = c.model
            if self._cells_overlap(row, col, row_span, col_span, m.row, m.col, m.row_span, m.col_span):
                return True
        return False

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        cs = self.canvas_size()

        # Background
        p.fillRect(self.rect(), QColor('#232323'))

        side_w = int(CHROME_SIDE_W * self.zoom_factor)
        title_h = int(CHROME_TITLE_H * self.zoom_factor)
        msg_h = int(CHROME_MSG_H * self.zoom_factor)

        # Blue left strip (Flame chrome)
        p.fillRect(0, 0, side_w, cs.height(), QColor(0, 110, 175))

        # Title bar
        title_rect = QRect(side_w, 0, cs.width() - side_w, title_h)
        p.fillRect(title_rect, QColor('#222222'))
        p.setPen(QColor('#b0b0b0'))
        title_font = QFont('Montserrat', 22, QFont.Light)
        p.setFont(title_font)

        name_text = self.config.script_name
        version_text = (self.config.script_version or '').strip()
        if version_text and not version_text.lower().startswith('v'):
            version_text = f'v{version_text}'

        text_rect = title_rect.adjusted(16, 0, -8, 0)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, name_text)

        # Draw version at half title size right after script name.
        if version_text:
            name_width = p.fontMetrics().horizontalAdvance(name_text)
            version_font = QFont('Montserrat', 16, QFont.Light)
            p.setFont(version_font)
            version_x = text_rect.x() + name_width + 10
            # Push version text slightly down so baseline aligns visually with title text.
            version_rect = QRect(version_x, text_rect.y() + 2, text_rect.width(), text_rect.height())
            p.drawText(version_rect,
                       Qt.AlignVCenter | Qt.AlignLeft,
                       version_text)

        # Message bar (same family as title bar)
        msg_y = title_h + int(self.config.grid_rows * self.config.row_height * self.zoom_factor)
        p.fillRect(QRect(side_w, msg_y, cs.width() - side_w, msg_h),
                   QColor('#222222'))

        # Main content area (between title and message bars) slightly brighter.
        content_h = msg_y - title_h
        if content_h > 0:
            p.fillRect(QRect(side_w, title_h, cs.width() - side_w, content_h), QColor('#2b2b2b'))

        # Grid cells (visibility toggle affects drawing only; snapping still active)
        if self.grid_visible:
            for row in range(self.config.grid_rows):
                for col in range(self.config.grid_columns):
                    r = self.cell_rect(row, col)
                    p.fillRect(r, QColor('#2d2d2d'))
                    p.setPen(QPen(QColor('#3a3a3a'), 1))
                    p.drawRect(r.adjusted(0, 0, -1, -1))

        p.end()

    # ── drag-and-drop ─────────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-pyflame-widget'):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat('application/x-pyflame-widget'):
            event.acceptProposedAction()

    def dropEvent(self, event):
        widget_type = (event.mimeData()
                       .data('application/x-pyflame-widget')
                       .data().decode())
        row, col = self._pos_to_cell(event.position().toPoint())
        self._add_widget(widget_type, row, col)
        event.acceptProposedAction()

    # ── selection ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
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

    # ── add / remove ──────────────────────────────────────────────────────────

    def _add_widget(self, widget_type, row, col):
        specs = WIDGET_SPECS.get(widget_type)
        if not specs:
            return
        if self._has_overlap(row, col, 1, 1):
            return
        default_props = {p.name: p.default for p in specs['props']}
        model = PlacedWidget(
            widget_type=widget_type,
            row=row, col=col,
            properties=default_props,
        )
        model.var_name = self._auto_var_name(widget_type)
        try:
            widget = WidgetContainer.make_widget(widget_type, default_props)
        except Exception as e:
            print(f'Error creating widget: {e}')
            return
        container = WidgetContainer(widget, model, self)
        container.setGeometry(self.cell_rect(row, col))
        container.show()
        self.containers.append(container)
        self.select_widget(container)
        self.content_changed.emit()

    def _auto_var_name(self, widget_type):
        raw = widget_type.replace('PyFlame', '')
        # Convert CamelCase widget names to snake_case var names.
        short = re.sub(r'(?<!^)(?=[A-Z])', '_', raw).lower()
        count = sum(1 for c in self.containers if c.model.widget_type == widget_type) + 1
        return f'{short}_{count}'

    def remove_selected(self):
        if not self.selected_container:
            return
        c = self.selected_container
        self.selected_container = None
        self.containers.remove(c)
        c.deleteLater()
        self.widget_selected.emit(None)
        self.content_changed.emit()

    def duplicate_selected(self):
        if not self.selected_container:
            return
        src = self.selected_container
        sm = src.model

        # Try nearby offsets first, then scan full grid.
        candidate_positions = [
            (sm.row, sm.col + 1),
            (sm.row + 1, sm.col),
            (sm.row + 1, sm.col + 1),
            (sm.row, sm.col - 1),
            (sm.row - 1, sm.col),
        ]
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
        model = PlacedWidget(
            widget_type=sm.widget_type,
            row=target[0],
            col=target[1],
            row_span=sm.row_span,
            col_span=sm.col_span,
            properties=new_props,
        )
        model.var_name = self._auto_var_name(sm.widget_type)

        try:
            widget = WidgetContainer.make_widget(sm.widget_type, new_props)
        except Exception as e:
            print(f'Error duplicating widget: {e}')
            return

        container = WidgetContainer(widget, model, self)
        container.setGeometry(self.cell_rect(model.row, model.col, model.row_span, model.col_span))
        container.show()
        self.containers.append(container)
        self.select_widget(container)
        self.content_changed.emit()

    def nudge_selected(self, d_row: int, d_col: int):
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

    # ── grid insert ───────────────────────────────────────────────────────────

    _MENU_STYLE = (
        'QMenu { background: #2d2d2d; color: #c8c8c8;'
        '        border: 1px solid #555; padding: 2px; }'
        'QMenu::item { padding: 4px 20px 4px 12px; }'
        'QMenu::item:selected { background: #0078d7; color: white; }'
        'QMenu::item:disabled { color: #555; }'
        'QMenu::separator { height: 1px; background: #444; margin: 3px 6px; }'
    )

    def _show_grid_menu(self, global_pos, row, col):
        menu = QMenu(self)
        menu.setStyleSheet(self._MENU_STYLE)

        mw = self.window()
        if hasattr(mw, 'action_undo') and hasattr(mw, 'action_redo'):
            menu.addAction('Undo', mw.action_undo)
            menu.addAction('Redo', mw.action_redo)
            menu.addSeparator()

        menu.addAction('Add Row Above',   lambda: self._insert_row(row, above=True))
        menu.addAction('Add Row Below',   lambda: self._insert_row(row, above=False))
        del_row = menu.addAction('Delete Row',  lambda: self._delete_row(row))
        del_row.setEnabled(self.config.grid_rows > 1)
        menu.addSeparator()
        menu.addAction('Add Column Left',  lambda: self._insert_col(col, left=True))
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

    def _delete_row(self, del_row):
        if self.config.grid_rows <= 1:
            return
        # Remove widgets occupying this row, shift others down
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

    def _delete_col(self, del_col):
        if self.config.grid_columns <= 1:
            return
        # Remove widgets occupying this column, shift others left
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

    # ── config update ─────────────────────────────────────────────────────────

    def update_config(self, config: WindowConfig):
        self.config = config
        sz = self.canvas_size()
        self.setMinimumSize(sz)
        self.resize(sz)
        self.update()
        for c in self.containers:
            m = c.model
            # Clamp to new grid size
            m.col = min(m.col, config.grid_columns - 1)
            m.row = min(m.row, config.grid_rows - 1)
            m.col_span = min(m.col_span, config.grid_columns - m.col)
            m.row_span = min(m.row_span, config.grid_rows - m.row)
            fixed = WIDGET_SPECS.get(m.widget_type, {}).get('fixed_axes', set())
            if {'h', 'w'} <= set(fixed):
                m.row_span = 1
                m.col_span = 1
            c.setGeometry(self.cell_rect(m.row, m.col, m.row_span, m.col_span))
        # zoom controls are handled by the main window UI

    def set_zoom(self, zoom: float):
        self.zoom_factor = max(0.5, min(2.0, float(zoom)))
        self.update_config(self.config)

    def zoom_in(self):
        self.set_zoom(self.zoom_factor + 0.1)

    def zoom_out(self):
        self.set_zoom(self.zoom_factor - 0.1)

    def zoom_reset(self):
        self.set_zoom(1.0)

    # ── keyboard ──────────────────────────────────────────────────────────────

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


# ==============================================================================
# PannableScrollArea
# ==============================================================================

class PannableScrollArea(QScrollArea):
    """Scroll area with middle-mouse drag panning."""

    def __init__(self):
        super().__init__()
        self._panning = False
        self._pan_start = None
        self._h_start = 0
        self._v_start = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self._h_start = self.horizontalScrollBar().value()
            self._v_start = self.verticalScrollBar().value()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(self._h_start - delta.x())
            self.verticalScrollBar().setValue(self._v_start - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ==============================================================================
# Preview helper widgets
# ==============================================================================

class ProgressBarPreview(QWidget):
    """Simple preview: centered blue bar with equal outer padding."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        pad = 5
        inner_w = max(1, w - (pad * 2))
        inner_h_space = max(1, h - (pad * 2))
        # Make the bar slightly thinner (2px less on top and bottom visual footprint).
        bar_h = max(1, (inner_h_space // 2) - 4)
        bar_y = (h - bar_h) // 2

        p.fillRect(QRect(pad, bar_y, inner_w, bar_h), QColor('#2f7fbf'))
        p.end()


# ==============================================================================
# WidgetPalette
# ==============================================================================

class WidgetPalette(QListWidget):
    """Draggable list of available widget types in one alphabetical list."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        items = sorted(
            ((wtype, spec['display']) for wtype, spec in WIDGET_SPECS.items()),
            key=lambda x: x[1].lower(),
        )

        for wtype, display in items:
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, wtype)
            item.setForeground(QColor('#c8c8c8'))
            self.addItem(item)

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None or not item.data(Qt.UserRole):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData('application/x-pyflame-widget',
                     item.data(Qt.UserRole).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


# ==============================================================================
# PropertiesPanel
# ==============================================================================

class PropertiesPanel(QWidget):
    """Dynamically-built form showing properties of the selected widget."""

    properties_changed = Signal()

    def __init__(self):
        super().__init__()
        self.container: WidgetContainer | None = None
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.title_label = QLabel('Widget Properties')
        self.title_label.setStyleSheet(
            'color: #888; font-size: 11px; padding: 4px 4px 2px;'
        )
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

    # ── public API ────────────────────────────────────────────────────────────

    def show_properties(self, container: WidgetContainer):
        self.container = container
        self._rebuild()

    def clear(self):
        self.container = None
        self._rebuild()

    # ── rebuild form ──────────────────────────────────────────────────────────

    def _rebuild(self):
        self._building = True
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self.container is None:
            self.title_label.setText('Widget Properties')
            self.inner_layout.addStretch()
            self._building = False
            return

        model = self.container.model
        specs = WIDGET_SPECS.get(model.widget_type, {})
        self.title_label.setText(f'{specs.get("display", model.widget_type)} Properties')

        # Var name
        self._add_group('Variable', [('var_name', 'str', model.var_name, [])])

        # Widget properties
        if specs.get('props'):
            rows = [(p.name, p.kind, model.properties.get(p.name, p.default), p.options)
                    for p in specs['props']]
            self._add_group('Properties', rows, is_props=True)

        # Grid position
        grid_rows = [
            ('row',      'int', model.row,      []),
            ('col',      'int', model.col,      []),
        ]
        fixed = WIDGET_SPECS.get(model.widget_type, {}).get('fixed_axes', set())
        if not ({'h', 'w'} <= set(fixed)):
            grid_rows += [
                ('rowspan',  'int', model.row_span, []),
                ('colspan',  'int', model.col_span, []),
            ]
        self._add_group('Grid Position', grid_rows, is_grid=True)

        self.inner_layout.addStretch()
        self._building = False

    def _add_group(self, title, rows, is_props=False, is_grid=False):
        grp = QGroupBox(title)
        grp.setStyleSheet(self._group_style())
        form = QFormLayout(grp)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(4)
        form.setLabelAlignment(Qt.AlignRight)

        for row in rows:
            name, kind, val, opts = row
            w = self._make_input(name, kind, val, opts, is_props=is_props, is_grid=is_grid)
            form.addRow(f'{name}:', w)

        self.inner_layout.addWidget(grp)

    def _make_input(self, name, kind, val, opts, is_props=False, is_grid=False):
        s = self._input_style()
        if kind == 'str':
            w = QLineEdit(str(val) if val is not None else '')
            w.setStyleSheet(s)
            if name == 'var_name':
                w.textChanged.connect(lambda t: self._on_var_changed(t))
            else:
                w.textChanged.connect(lambda t, n=name: self._on_prop(n, t))
            return w

        elif kind == 'enum':
            w = QComboBox()
            w.setStyleSheet(s)
            w.addItems(opts)
            if str(val) in opts:
                w.setCurrentText(str(val))
            w.currentTextChanged.connect(lambda t, n=name: self._on_prop(n, t))
            return w

        elif kind == 'bool':
            w = QCheckBox()
            w.setChecked(bool(val))
            w.stateChanged.connect(lambda st, n=name: self._on_prop(n, bool(st)))
            return w

        elif kind == 'int':
            w = QSpinBox()
            w.setStyleSheet(s)
            w.setRange(-999999, 999999)
            try:
                w.setValue(int(val))
            except (TypeError, ValueError):
                w.setValue(0)
            if is_grid:
                w.valueChanged.connect(lambda v, n=name: self._on_grid(n, v))
            else:
                w.valueChanged.connect(lambda v, n=name: self._on_prop(n, v))
            return w

        elif kind == 'connect':
            callbacks  = ['(none)'] + _parse_template_callbacks()
            w = QComboBox()
            w.setStyleSheet(s)
            w.addItems(callbacks)
            current = val if val else '(none)'
            if current in callbacks:
                w.setCurrentText(current)
            w.currentTextChanged.connect(
                lambda t, n=name: self._on_prop(n, None if t == '(none)' else t)
            )
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
            w.currentTextChanged.connect(
                lambda t, n=name: self._on_prop(n, None if t == 'None' else t)
            )
            return w

        elif kind == 'list':
            w = QPlainTextEdit()
            w.setStyleSheet(s)
            w.setMaximumHeight(72)
            if isinstance(val, list):
                w.setPlainText('\n'.join(str(x) for x in val))
            else:
                w.setPlainText(str(val) if val else '')
            w.textChanged.connect(
                lambda n=name, widget=w:
                    self._on_prop(n, [x.strip()
                                      for x in widget.toPlainText().splitlines()
                                      if x.strip()])
            )
            return w

        else:
            w = QLineEdit(str(val) if val else '')
            w.setStyleSheet(s)
            w.textChanged.connect(lambda t, n=name: self._on_prop(n, t))
            return w

    # ── change handlers ───────────────────────────────────────────────────────

    def _on_prop(self, name, value):
        if self._building or not self.container:
            return
        model = self.container.model
        model.properties[name] = value

        # Keep slider values valid while editing so widget doesn't fallback.
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

        # Keep widget fully inside the grid bounds.
        m.row_span = max(1, min(m.row_span, cfg.grid_rows))
        m.col_span = max(1, min(m.col_span, cfg.grid_columns))
        m.row = max(0, min(m.row, cfg.grid_rows - m.row_span))
        m.col = max(0, min(m.col, cfg.grid_columns - m.col_span))

        # Prevent overlap with other widgets.
        if canvas._has_overlap(m.row, m.col, m.row_span, m.col_span, ignore_container=self.container):
            m.row, m.col, m.row_span, m.col_span = prev

        r = self.container.canvas.cell_rect(m.row, m.col, m.row_span, m.col_span)
        self.container.setGeometry(r)

        # Refresh form values in case we clamped/reverted anything.
        self.show_properties(self.container)
        self.properties_changed.emit()

    def _on_var_changed(self, text):
        if self._building or not self.container:
            return
        self.container.model.var_name = text
        self.properties_changed.emit()

    def _recreate_widget(self):
        if not self.container:
            return
        m = self.container.model
        try:
            new_w = WidgetContainer.make_widget(m.widget_type, m.properties)
            self.container.replace_inner_widget(new_w)
        except Exception as e:
            print(f'Error recreating widget: {e}')

    # ── styles ────────────────────────────────────────────────────────────────

    def _group_style(self):
        return (
            'QGroupBox { color: #888; border: 1px solid #3a3a3a; border-radius: 3px;'
            ' margin-top: 8px; font-size: 10px; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }'
        )

    def _input_style(self):
        return (
            'background: #2d2d2d; border: 1px solid #3a3a3a;'
            ' color: #c8c8c8; padding: 2px;'
        )


# ==============================================================================
# WindowConfigBar
# ==============================================================================

class WindowConfigBar(QWidget):
    """Two-row config bar: script metadata on row 1, window options on row 2."""

    config_changed = Signal(object)   # emits WindowConfig
    LICENSE_TYPES  = list(LICENSE_DATA.keys())

    def __init__(self, config: WindowConfig):
        super().__init__()
        self.config    = config
        self._updating = False

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(8, 3, 8, 3)
        vbox.setSpacing(2)

        es = ('background: #2d2d2d; border: 1px solid #3a3a3a;'
              ' color: #c8c8c8; padding: 1px 4px;')
        ls = 'color: #888; font-size: 10px;'

        def lbl(t):
            w = QLabel(t)
            w.setStyleSheet(ls)
            return w

        # ── Row 1: Script metadata ────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        row1.addWidget(lbl('Script Name:'))
        self.script_name = QLineEdit(config.script_name)
        self.script_name.setStyleSheet(es)
        self.script_name.setFixedWidth(140)
        self.script_name.setFixedHeight(22)
        self.script_name.textChanged.connect(self._on_change)
        row1.addWidget(self.script_name)

        row1.addWidget(lbl('Written By:'))
        self.written_by = QLineEdit(config.written_by)
        self.written_by.setStyleSheet(es)
        self.written_by.setFixedWidth(140)
        self.written_by.setFixedHeight(22)
        self.written_by.textChanged.connect(self._on_change)
        row1.addWidget(self.written_by)

        row1.addWidget(lbl('Script Version:'))
        self.version = QLineEdit(config.script_version)
        self.version.setStyleSheet(es)
        self.version.setMaximumWidth(80)
        self.version.setFixedHeight(22)
        self.version.textChanged.connect(self._on_change)
        row1.addWidget(self.version)

        row1.addWidget(lbl('Flame Version:'))
        self.flame_version = QLineEdit(config.flame_version)
        self.flame_version.setStyleSheet(es)
        self.flame_version.setFixedWidth(95)
        self.flame_version.setFixedHeight(22)
        self.flame_version.setToolTip('Use digits and dots only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1')
        self._flame_validator = QRegularExpressionValidator(QRegularExpression(r'^\d+(?:\.\d+){0,2}$'))
        self.flame_version.setValidator(self._flame_validator)
        self.flame_version.textChanged.connect(self._on_change)
        row1.addWidget(self.flame_version)

        row1.addWidget(lbl('Hooks:'))

        self._hook_button = QPushButton()
        self._hook_button.setStyleSheet(
            es + ' text-align: left; padding: 1px 8px; min-width: 160px;'
        )
        self._hook_button.setFixedHeight(22)
        self._hook_button.clicked.connect(self._show_hooks_menu)

        hook_menu_style = (
            'QMenu { background: #2d2d2d; color: #c8c8c8;'
            '        border: 1px solid #555; padding: 2px; }'
            'QMenu::item { padding: 4px 20px 4px 8px; }'
            'QMenu::item:selected { background: #0078d7; color: white; }'
            'QMenu::indicator { width: 13px; height: 13px; }'
        )
        self._hooks_menu = QMenu(self)
        self._hooks_menu.setStyleSheet(hook_menu_style)

        self._hook_actions: dict[str, QAction] = {}
        for hook, label in HOOK_DISPLAY.items():
            action = QAction(label, self._hooks_menu)
            action.setCheckable(True)
            action.setChecked(hook in config.hook_types)
            action.triggered.connect(self._on_hook_toggled)
            self._hooks_menu.addAction(action)
            self._hook_actions[hook] = action

        self._update_hook_button()
        row1.addWidget(self._hook_button)

        row1.addWidget(lbl('License:'))
        self.license_type = QComboBox()
        self.license_type.addItems(self.LICENSE_TYPES)
        self.license_type.setCurrentText(config.license_type)
        self.license_type.setStyleSheet(es)
        self.license_type.setMinimumWidth(110)
        self.license_type.setFixedHeight(22)
        self.license_type.currentTextChanged.connect(self._on_change)
        row1.addWidget(self.license_type)

        row1.addStretch()
        vbox.addLayout(row1)
        vbox.addSpacing(22)

        # ── Row 2: Window / grid options ──────────────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2.addWidget(lbl('Flame Window:'))

        row2.addWidget(lbl('Cols:'))
        self.grid_cols = QSpinBox()
        self.grid_cols.setRange(1, 20)
        self.grid_cols.setValue(config.grid_columns)
        self.grid_cols.setStyleSheet(es)
        self.grid_cols.setMaximumWidth(55)
        self.grid_cols.setFixedHeight(22)
        self.grid_cols.valueChanged.connect(self._on_change)
        row2.addWidget(self.grid_cols)

        row2.addWidget(lbl('Rows:'))
        self.grid_rows = QSpinBox()
        self.grid_rows.setRange(1, 20)
        self.grid_rows.setValue(config.grid_rows)
        self.grid_rows.setStyleSheet(es)
        self.grid_rows.setMaximumWidth(55)
        self.grid_rows.setFixedHeight(22)
        self.grid_rows.valueChanged.connect(self._on_change)
        row2.addWidget(self.grid_rows)

        row2.addStretch()
        vbox.addLayout(row2)
        vbox.addSpacing(22)

    # ── hook dropdown ─────────────────────────────────────────────────────────

    def _show_hooks_menu(self):
        pos = self._hook_button.mapToGlobal(QPoint(0, self._hook_button.height()))
        self._hooks_menu.exec(pos)

    def _update_hook_button(self):
        selected = [HOOK_DISPLAY[h] for h, a in self._hook_actions.items() if a.isChecked()]
        self._hook_button.setText(', '.join(selected) if selected else 'None')

    def _on_hook_toggled(self):
        self._update_hook_button()
        self._on_change()

    # ── change / load ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_flame_version_supported(version_text: str) -> bool:
        if not version_text:
            return False
        parts = version_text.split('.')
        if any((not p.isdigit()) for p in parts):
            return False
        # compare as (major, minor, patch) with missing pieces as 0
        nums = [int(p) for p in parts][:3]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums) >= (2025, 1, 0)

    def _set_flame_version_error(self, is_error: bool):
        base = 'background: #2d2d2d; border: 1px solid #3a3a3a; color: #c8c8c8; padding: 1px 4px;'
        err = 'background: #3a1f1f; border: 1px solid #b94a48; color: #ffd7d7; padding: 1px 4px;'
        self.flame_version.setStyleSheet(err if is_error else base)
        if is_error:
            self.flame_version.setToolTip('Invalid Flame Version. Use numeric version only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1.')
        else:
            self.flame_version.setToolTip('Use digits and dots only (e.g. 2025.1, 2025.3.2, 2026, 2026.1). Minimum supported is 2025.1')

    def _on_change(self):
        if self._updating:
            return

        flame_version_text = self.flame_version.text().strip()
        flame_ok = self._is_flame_version_supported(flame_version_text)
        self._set_flame_version_error(not flame_ok)

        if not flame_ok:
            return

        self.config.script_name  = self.script_name.text()
        self.config.written_by   = self.written_by.text()
        self.config.script_version = self.version.text()
        self.config.flame_version = flame_version_text
        self.config.hook_types   = [h for h, a in self._hook_actions.items()
                                     if a.isChecked()]
        self.config.license_type = self.license_type.currentText()
        self.config.grid_columns = self.grid_cols.value()
        self.config.grid_rows    = self.grid_rows.value()
        self.config_changed.emit(self.config)

    def load_config(self, config: WindowConfig):
        self._updating = True
        self.config = config
        self.script_name.setText(config.script_name)
        self.written_by.setText(config.written_by)
        self.version.setText(config.script_version)
        self.flame_version.setText(config.flame_version)
        self._set_flame_version_error(not self._is_flame_version_supported(config.flame_version))
        for hook, action in self._hook_actions.items():
            action.setChecked(hook in config.hook_types)
        self._update_hook_button()
        self.license_type.setCurrentText(config.license_type)
        self.grid_cols.setValue(config.grid_columns)
        self.grid_rows.setValue(config.grid_rows)
        self._updating = False


# ==============================================================================
# CodeGenerator
# ==============================================================================

class CodeGenerator:

    # Widget type → comment section label
    _SECTION_LABELS = {
        'PyFlameLabel':           'Labels',
        'PyFlameEntry':           'Entries',
        'PyFlameEntryBrowser':    'Entries',
        'PyFlameButton':          'Buttons',
        'PyFlamePushButton':      'Buttons',
        'PyFlameMenu':            'Menus',
        'PyFlameColorMenu':       'Menus',
        'PyFlameTokenMenu':       'Menus',
        'PyFlameSlider':          'Sliders',
        'PyFlameListWidget':      'List Widgets',
        'PyFlameTreeWidget':      'Tree Widgets',
        'PyFlameTextEdit':        'Text Edits',
        'PyFlameTextBrowser':     'Text Browsers',
        'PyFlameProgressBarWidget': 'Progress Bars',
        'PyFlameHorizontalLine':  'Lines',
        'PyFlameVerticalLine':    'Lines',
    }

    @classmethod
    def generate(cls, config: WindowConfig, widgets: list[PlacedWidget],
                 tab_order: list[str] | None = None) -> str:
        today     = datetime.date.today().strftime('%m.%d.%y')
        year      = str(datetime.date.today().year)
        snake     = _to_snake(config.script_name)
        classname = ''.join(w.title() for w in config.script_name.split())
        lic       = LICENSE_DATA.get(config.license_type, LICENSE_DATA['GPL-3.0'])

        # Read template
        tmpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'script_template', 'script_template.py')
        with open(tmpl_path, 'r') as _f:
            tmpl = _f.read()

        # License header block (ends with \n\n to produce blank line before docstring)
        if lic['header']:
            lic_header = '\n'.join(lic['header']) + '\n\n'
        else:
            lic_header = '\n'

        # Widget declarations block
        widget_decl = cls._build_widget_declarations(widgets)

        # Tab order block
        if tab_order:
            tab_lines = [
                '        # Set Entry Tab-key Order',
                '        self.window.tab_order = [',
            ]
            for var in tab_order:
                tab_lines.append(f'            self.{var},')
            tab_lines += ['            ]', '']
            tab_block = '\n'.join(tab_lines) + '\n'
        else:
            tab_block = ''

        # Widget layout block
        layout_lines = []
        for w in sorted(widgets, key=lambda x: (x.row, x.col)):
            var = w.var_name or 'widget'
            if w.row_span > 1 or w.col_span > 1:
                layout_lines.append(
                    f'        self.window.grid_layout.addWidget('
                    f'self.{var}, {w.row}, {w.col}, {w.row_span}, {w.col_span})'
                )
            else:
                layout_lines.append(
                    f'        self.window.grid_layout.addWidget('
                    f'self.{var}, {w.row}, {w.col})'
                )
        layout_block = '\n'.join(layout_lines) + '\n' if layout_lines else ''

        # set_focus for first non-read-only entry widget
        entry_widgets = [
            w for w in widgets
            if w.widget_type in ('PyFlameEntry', 'PyFlameEntryBrowser')
        ]
        set_focus = ''
        first_focusable = None
        for w in entry_widgets:
            read_only = bool((w.properties or {}).get('read_only', False))
            if not read_only:
                first_focusable = w
                break
        if first_focusable:
            first_var = first_focusable.var_name or 'entry'
            set_focus = f'        self.{first_var}.set_focus()\n'

        # Flame menu hook functions
        flame_menus = '\n'.join(cls._menu_hook(config, classname))

        # Apply all substitutions
        subs = {
            '<<<SCRIPT_NAME>>>':       config.script_name,
            '<<<WRITTEN_BY>>>':        config.written_by,
            '<<<YEAR>>>':              year,
            '<<<LICENSE_HEADER>>>':    lic_header,
            '<<<SCRIPT_VERSION>>>':    config.script_version,
            '<<<FLAME_VERSION>>>':     config.flame_version,
            '<<<DATE>>>':              today,
            '<<<LICENSE_DOCSTRING>>>': lic['docstring'],
            '<<<SCRIPT_TYPE>>>':       cls._script_type_label(config.hook_types),
            '<<<MENU_PATH>>>':         cls._menu_path(config),
            '<<<SNAKE_NAME>>>':        snake,
            '<<<CLASS_NAME>>>':        classname,
            '<<<GRID_COLUMNS>>>':      str(config.grid_columns),
            '<<<GRID_ROWS>>>':         str(config.grid_rows),
            '<<<WIDGET_DECLARATIONS>>>': widget_decl,
            '<<<TAB_ORDER>>>':         tab_block,
            '<<<WIDGET_LAYOUT>>>':     layout_block,
            '<<<SET_FOCUS>>>':         set_focus,
            '<<<FLAME_MENUS>>>':       flame_menus,
        }
        for marker, value in subs.items():
            tmpl = tmpl.replace(marker, value)
        return tmpl

    @classmethod
    def _build_widget_declarations(cls, widgets: list[PlacedWidget]) -> str:
        """Return the widget instantiation block as a string (empty string if no widgets)."""
        if not widgets:
            return ''
        type_order = list(WIDGET_SPECS.keys())
        grouped: dict[str, list[PlacedWidget]] = {}
        for w in widgets:
            grouped.setdefault(w.widget_type, []).append(w)
        sorted_types = sorted(
            grouped.keys(),
            key=lambda t: type_order.index(t) if t in type_order else 99,
        )
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


    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _script_type_label(hook_types: list) -> str:
        types = [HOOK_TO_TYPE.get(h, h) for h in hook_types]
        return ', '.join(types) if types else 'Batch'

    @staticmethod
    def _menu_path(config: WindowConfig) -> str:
        name  = config.script_name
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
        """Emit one scope function per unique scope needed across all selected hooks."""
        lines   = []
        emitted = set()
        for hook in hook_types:
            scope_fn = HOOK_SCOPE.get(hook)
            if scope_fn is None or scope_fn in emitted:
                continue
            lines += SCOPE_DEFS[scope_fn]
            lines.append('')
            emitted.add(scope_fn)
        return lines

    @staticmethod
    def _menu_hook(config: WindowConfig, classname: str) -> list:
        """Emit one hook function per selected hook."""
        name  = config.script_name
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
        """Convert props to Python-source string representations."""
        specs = WIDGET_SPECS.get(widget_type, {})
        prop_defs = {p.name: p for p in specs.get('props', [])}
        result = {}
        for key, val in props.items():
            if key not in prop_defs:
                continue
            pdef = prop_defs[key]
            if pdef.kind == 'connect':
                # Emit as an unquoted Python identifier; skip if unset.
                # For PyFlameButton, this will be emitted when user selected a callback;
                # otherwise _build_widget_declarations adds a commented TODO hint.
                if val:
                    result[key] = str(val)
            elif pdef.kind == 'token_dest':
                if val:
                    result[key] = f'self.{val}'
            elif pdef.kind == 'enum':
                if widget_type == 'PyFlameColorMenu' and key == 'color':
                    result[key] = repr(str(val) if val is not None else 'No Color')
                else:
                    enum_class = ENUM_PROP_MAP.get(key, '')
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


# ==============================================================================
# ProjectSerializer
# ==============================================================================

class ProjectSerializer:

    @staticmethod
    def save(path: str, config: WindowConfig, widgets: list[PlacedWidget]) -> None:
        data = {
            'config': {
                'script_name':    config.script_name,
                'written_by':     config.written_by,
                'script_version': config.script_version,
                'flame_version':  config.flame_version,
                'hook_types':     config.hook_types,
                'license_type':   config.license_type,
                'grid_columns':   config.grid_columns,
                'grid_rows':      config.grid_rows,
                'column_width':   config.column_width,
                'row_height':     config.row_height,
            },
            'widgets': [
                {
                    'widget_type': w.widget_type,
                    'row':         w.row,
                    'col':         w.col,
                    'row_span':    w.row_span,
                    'col_span':    w.col_span,
                    'properties':  w.properties,
                    'var_name':    w.var_name,
                }
                for w in widgets
            ],
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load(path: str) -> tuple[WindowConfig, list[PlacedWidget]]:
        with open(path) as f:
            data = json.load(f)
        cfg = data.get('config', {})
        # Backward compat: old files stored hook_type as a string
        raw_hooks = cfg.get('hook_types', cfg.get('hook_type', 'get_batch_custom_ui_actions'))
        if isinstance(raw_hooks, str):
            raw_hooks = [raw_hooks]

        config = WindowConfig(
            script_name    = cfg.get('script_name',    'My Script'),
            written_by     = cfg.get('written_by',     'Your Name'),
            script_version = cfg.get('script_version', 'v1.0.0'),
            flame_version  = cfg.get('flame_version',  '2025.1'),
            hook_types     = raw_hooks,
            license_type   = cfg.get('license_type',   'GPL-3.0'),
            grid_columns   = cfg.get('grid_columns',   4),
            grid_rows      = cfg.get('grid_rows',      3),
            column_width   = cfg.get('column_width',   150),
            row_height     = cfg.get('row_height',     28),
        )
        widgets = []
        for wd in data.get('widgets', []):
            w = PlacedWidget(
                widget_type = wd.get('widget_type', ''),
                row         = wd.get('row',         0),
                col         = wd.get('col',         0),
                row_span    = wd.get('row_span',    1),
                col_span    = wd.get('col_span',    1),
                properties  = wd.get('properties',  {}),
                var_name    = wd.get('var_name',    ''),
            )
            widgets.append(w)
        return config, widgets


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


# ==============================================================================
# Help
# ==============================================================================

class HelpDialog(QDialog):
    def __init__(self, parent=None, initial_file: str | None = None):
        super().__init__(parent)
        self.setWindowTitle('Help')
        self.resize(900, 640)
        self.setStyleSheet(_app_stylesheet())

        self.help_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'help')
        self.help_files = {
            'Getting Started': 'getting-started.md',
            'Keyboard Shortcuts': 'keyboard-shortcuts.md',
        }

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        self.nav = QListWidget()
        for title in self.help_files.keys():
            self.nav.addItem(title)
        self.nav.currentTextChanged.connect(self._load_topic)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setStyleSheet(
            'background: #1a1a1a; color: #c8c8c8; border: 1px solid #3a3a3a;'
            ' font-family: "Montserrat", "Arial"; font-size: 13px;'
        )

        splitter.addWidget(self.nav)
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 680])

        layout.addWidget(splitter)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # Select initial section
        idx = 0
        if initial_file:
            files = list(self.help_files.values())
            if initial_file in files:
                idx = files.index(initial_file)
        self.nav.setCurrentRow(idx)

    def _load_topic(self, title: str):
        filename = self.help_files.get(title)
        if not filename:
            return
        path = os.path.join(self.help_dir, filename)
        if not os.path.exists(path):
            self.viewer.setPlainText(f'Help file missing:\n{path}')
            return
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.viewer.setMarkdown(content)


# ==============================================================================
# PyFlameBuilder — Main Window
# ==============================================================================

class PyFlameBuilder(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self.config = WindowConfig()
        self._dirty = False
        self._save_path: str | None = None

        self._preview_auto = True
        self._preview_visible = True
        self._preview_center_on_change = True
        self._last_preview_code = ''
        self._preview_timer = QTimer(self)

        self._history_limit = 10
        self._history: list[dict] = []
        self._history_index = -1
        self._restoring_history = False
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self.setStyleSheet(_app_stylesheet())
        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._update_title()
        self._record_history_state()
        self._update_undo_redo_actions()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.config_bar = WindowConfigBar(self.config)

        # Canvas in a scroll area
        self.canvas = CanvasWidget(self.config)
        self.canvas_scroll = PannableScrollArea()
        self.canvas_scroll.setWidget(self.canvas)
        self.canvas_scroll.setWidgetResizable(False)
        self.canvas_scroll.setAlignment(Qt.AlignCenter)
        self.canvas_scroll.setStyleSheet('QScrollArea { background: #171717; }')

        # Palette
        self.palette = WidgetPalette()
        self.palette_panel = QWidget()
        palette_layout = QVBoxLayout(self.palette_panel)
        palette_layout.setContentsMargins(4, 4, 4, 4)
        palette_layout.setSpacing(4)
        palette_title = QLabel('Widgets')
        palette_title.setStyleSheet('color: #888; font-size: 11px; padding: 4px 4px 2px;')
        palette_layout.addWidget(palette_title)
        palette_layout.addWidget(self.palette)

        # Properties
        self.props = PropertiesPanel()

        # Right pane: palette (top) + properties (bottom)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.palette_panel)
        right.addWidget(self.props)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)

        # Live preview panel (left)
        self.preview_panel = QWidget()
        pv = QVBoxLayout(self.preview_panel)
        pv.setContentsMargins(6, 6, 6, 6)
        pv.setSpacing(6)

        preview_title = QLabel('Live Code Preview')
        preview_title.setStyleSheet('color: #888; font-size: 11px; padding: 2px 2px 0px;')
        pv.addWidget(preview_title)

        preview_controls = QHBoxLayout()
        self.preview_auto_check = QCheckBox('Auto')
        self.preview_auto_check.setChecked(True)
        self.preview_auto_check.toggled.connect(self._set_preview_auto)
        self.preview_copy_btn = QPushButton('Copy')
        self.preview_copy_btn.clicked.connect(self._copy_preview)
        self.preview_close_btn = QPushButton('✕')
        self.preview_close_btn.setFixedWidth(28)
        self.preview_close_btn.clicked.connect(lambda: self._set_preview_visible(False))
        preview_controls.addWidget(self.preview_auto_check)
        preview_controls.addStretch()
        preview_controls.addWidget(self.preview_copy_btn)
        preview_controls.addWidget(self.preview_close_btn)
        pv.addLayout(preview_controls)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_text.setStyleSheet(self._preview_style())
        pv.addWidget(self.preview_text)

        # Center pane: canvas area + local bottom zoom controls
        center_pane = QWidget()
        center_layout = QVBoxLayout(center_pane)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self.canvas_scroll)

        zoom_bar = QWidget()
        zoom_layout = QHBoxLayout(zoom_bar)
        zoom_layout.setContentsMargins(8, 4, 8, 4)
        zoom_layout.setSpacing(6)
        self.grid_toggle_btn = QPushButton('Grid: Off')
        self.grid_toggle_btn.setFixedHeight(22)
        self.grid_toggle_btn.clicked.connect(self.action_toggle_grid_visibility)
        zoom_layout.addWidget(self.grid_toggle_btn)

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
        center_layout.addWidget(zoom_bar)

        # Main horizontal splitter
        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.addWidget(self.preview_panel)
        self.main_split.addWidget(center_pane)
        self.main_split.addWidget(right)
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

    def _separator(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet('background: #3a3a3a;')
        return f

    def _build_menu(self):
        mb = self.menuBar()
        mb.setNativeMenuBar(False)
        fm = mb.addMenu('File')

        new_a = QAction('New', self)
        new_a.setShortcut(QKeySequence.New)
        new_a.triggered.connect(self._new)
        fm.addAction(new_a)

        load_a = QAction('Load...', self)
        load_a.setShortcut(QKeySequence.Open)
        load_a.triggered.connect(self._open)
        fm.addAction(load_a)

        self._recent_menu = fm.addMenu('Load Recent')
        self._rebuild_recent_menu()

        fm.addSeparator()

        save_a = QAction('Save', self)
        save_a.setShortcut(QKeySequence.Save)
        save_a.triggered.connect(self._save)
        fm.addAction(save_a)

        saveas_a = QAction('Save As...', self)
        saveas_a.setShortcut(QKeySequence('Ctrl+Shift+S'))
        saveas_a.triggered.connect(self._save_as)
        fm.addAction(saveas_a)

        fm.addSeparator()

        preview_a = QAction('Preview Code...', self)
        preview_a.setShortcut(QKeySequence('Ctrl+G'))
        preview_a.triggered.connect(self._generate_code)
        fm.addAction(preview_a)

        generate_a = QAction('Generate Script...', self)
        generate_a.setShortcut(QKeySequence('Ctrl+Shift+G'))
        generate_a.triggered.connect(self._generate_script)
        fm.addAction(generate_a)

        fm.addSeparator()

        exit_a = QAction('Exit', self)
        exit_a.setShortcut(QKeySequence.Quit)
        exit_a.triggered.connect(self.close)
        fm.addAction(exit_a)

        self.edit_menu = mb.addMenu('Edit')
        self.undo_action = QAction('Undo', self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.triggered.connect(self.action_undo)

        self.redo_action = QAction('Redo', self)
        self.redo_action.setShortcut(QKeySequence('Ctrl+Shift+Z'))
        self.redo_action.triggered.connect(self.action_redo)

        self._refresh_edit_menu()
        self.edit_menu.aboutToShow.connect(self._refresh_edit_menu)

        vm = mb.addMenu('View')
        self.toggle_preview_action = QAction('Show Live Code Preview', self)
        self.toggle_preview_action.setCheckable(True)
        self.toggle_preview_action.setChecked(True)
        self.toggle_preview_action.toggled.connect(self._set_preview_visible)
        vm.addAction(self.toggle_preview_action)

        vm.addSeparator()
        zoom_in_action = QAction('Zoom In', self)
        zoom_in_action.setShortcut(QKeySequence('Ctrl+='))
        zoom_in_action.triggered.connect(self.action_zoom_in)
        vm.addAction(zoom_in_action)

        zoom_out_action = QAction('Zoom Out', self)
        zoom_out_action.setShortcut(QKeySequence('Ctrl+-'))
        zoom_out_action.triggered.connect(self.action_zoom_out)
        vm.addAction(zoom_out_action)

        zoom_reset_action = QAction('Actual Size (100%)', self)
        zoom_reset_action.setShortcut(QKeySequence('Ctrl+0'))
        zoom_reset_action.triggered.connect(self.action_zoom_reset)
        vm.addAction(zoom_reset_action)

        zoom_fit_action = QAction('Fit Canvas', self)
        zoom_fit_action.setShortcut(QKeySequence('Ctrl+9'))
        zoom_fit_action.triggered.connect(self.action_zoom_fit)
        vm.addAction(zoom_fit_action)

        hm = mb.addMenu('Help')

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
        self.config_bar.config_changed.connect(self._on_config_changed)
        self.canvas.widget_selected.connect(self._on_widget_selected)
        self.canvas.widget_moved.connect(self._on_widget_moved)
        self.canvas.grid_changed.connect(self._on_grid_changed)
        self.canvas.content_changed.connect(self._on_canvas_content_changed)
        self.props.properties_changed.connect(self._on_properties_changed)
        self._refresh_preview()

    # ── signal handlers ───────────────────────────────────────────────────────

    _RIGHT_MIN = 260
    _RIGHT_MAX = 520

    def _clamp_right_panel(self):
        sizes = self.main_split.sizes()
        if len(sizes) < 3:
            return
        right = max(self._RIGHT_MIN, min(self._RIGHT_MAX, sizes[2]))
        if right != sizes[2]:
            total = sum(sizes)
            left = sizes[0]
            center = max(300, total - left - right)
            self.main_split.setSizes([left, center, right])

    def _on_grid_changed(self, config):
        self.config = config
        self.config_bar.load_config(config)
        self._dirty = True
        self._update_title()
        self._schedule_preview_update()
        self._record_history_state()

    def _on_config_changed(self, config):
        self.canvas.update_config(config)
        self._dirty = True
        self._update_title()
        self._schedule_preview_update()
        self._record_history_state()

    def _on_widget_selected(self, container):
        if container is None:
            self.props.clear()
        else:
            self.props.show_properties(container)

    def _on_widget_moved(self, container):
        # Refresh properties panel so grid position fields update
        if container is not None:
            self.props.show_properties(container)
        self._dirty_mark()
        self._schedule_preview_update(center_on_change=False)
        self._record_history_state()

    def _on_canvas_content_changed(self):
        self._dirty_mark()
        self._schedule_preview_update(center_on_change=True)
        self._record_history_state()

    def _on_properties_changed(self):
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
        self._preview_visible = bool(visible)
        self.preview_panel.setVisible(self._preview_visible)

        if self._preview_visible:
            self.main_split.setSizes([420, 900, 320])
            self._refresh_preview()
        else:
            self.main_split.setSizes([0, 1320, 320])

        if hasattr(self, 'toggle_preview_action'):
            self.toggle_preview_action.blockSignals(True)
            self.toggle_preview_action.setChecked(self._preview_visible)
            self.toggle_preview_action.blockSignals(False)

    def _copy_preview(self):
        QApplication.clipboard().setText(self.preview_text.toPlainText())
        self.preview_copy_btn.setText('Copied!')
        QTimer.singleShot(900, lambda: self.preview_copy_btn.setText('Copy'))

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

    def action_toggle_grid_visibility(self):
        self.canvas.grid_visible = not self.canvas.grid_visible
        self.grid_toggle_btn.setText('Grid: On' if self.canvas.grid_visible else 'Grid: Off')
        self.canvas.update()

    def action_open_help(self, initial_file: str | None = None):
        dlg = HelpDialog(self, initial_file=initial_file)
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
            f'background: #1a1a1a; color: #c8c8c8; border: {border};'
            ' font-family: "Courier New", monospace; font-size: 12px;'
        )

    def _flash_preview_frame(self):
        self.preview_text.setStyleSheet(self._preview_style(framed=True))
        QTimer.singleShot(700, lambda: self.preview_text.setStyleSheet(self._preview_style()))

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

    def _refresh_preview(self):
        models = [c.model for c in self.canvas.containers]
        try:
            code = CodeGenerator.generate(self.config, models, tab_order=None)
        except Exception as e:
            code = f'# Preview generation error\n# {e}'

        changed = code != self._last_preview_code
        changed_line = self._first_changed_line(self._last_preview_code, code)
        added_code = changed and len(code) > len(self._last_preview_code)

        vbar = self.preview_text.verticalScrollBar()
        hbar = self.preview_text.horizontalScrollBar()
        prev_v = vbar.value()
        prev_h = hbar.value()

        self.preview_text.setPlainText(code)
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
        self._preview_center_on_change = True

        if added_code:
            self._flash_preview_frame()

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
                license_type=cfg.get('license_type', 'GPL-3.0'),
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
                    container.show()
                    self.canvas.containers.append(container)
                except Exception as e:
                    print(f'Error restoring widget: {e}')

            self.props.clear()
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

    # ── File menu actions ─────────────────────────────────────────────────────

    # ── recent files ──────────────────────────────────────────────────────────

    _MAX_RECENT = 5

    def _settings(self):
        return QSettings('PyFlameUIBuilder', 'PyFlameUIBuilder')

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

    def _new(self):
        if not self._check_unsaved():
            return
        for c in list(self.canvas.containers):
            c.deleteLater()
        self.canvas.containers.clear()
        self.canvas.selected_container = None
        self.config = WindowConfig()
        self.config_bar.load_config(self.config)
        self.canvas.update_config(self.config)
        self.props.clear()
        self._save_path = None
        self._clean_mark()
        self._refresh_preview()
        self._history = []
        self._history_index = -1
        self._record_history_state()
        self._update_undo_redo_actions()

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

    def _load_project(self, path: str):
        try:
            config, widgets = ProjectSerializer.load(path)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to load project:\n{e}')
            return

        for c in list(self.canvas.containers):
            c.deleteLater()
        self.canvas.containers.clear()
        self.canvas.selected_container = None

        self.config = config
        self.config_bar.load_config(config)
        self.canvas.update_config(config)

        for model in widgets:
            if model.widget_type not in WIDGET_SPECS:
                print(f'Skipping unknown widget type: {model.widget_type}')
                continue
            try:
                widget = WidgetContainer.make_widget(model.widget_type, model.properties)
                container = WidgetContainer(widget, model, self.canvas)
                container.setGeometry(
                    self.canvas.cell_rect(model.row, model.col, model.row_span, model.col_span)
                )
                container.show()
                self.canvas.containers.append(container)
            except Exception as e:
                print(f'Error loading {model.widget_type}: {e}')

        self.props.clear()
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
            models = [c.model for c in self.canvas.containers]
            ProjectSerializer.save(self._save_path, self.config, models)
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
        models    = [c.model for c in self.canvas.containers]
        tab_order = self._prompt_tab_order(models)
        code = CodeGenerator.generate(self.config, models, tab_order=tab_order)

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

    def _generate_script(self):
        if not os.path.isdir(TEMPLATE_DIR):
            QMessageBox.critical(self, 'Error',
                f'Template folder not found:\n{TEMPLATE_DIR}')
            return

        output_dir = QFileDialog.getExistingDirectory(
            self, 'Select Output Directory', '',
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not output_dir:
            return

        snake      = _to_snake(self.config.script_name)
        script_dir = os.path.join(output_dir, snake)

        if os.path.exists(script_dir):
            msg = QMessageBox(self)
            msg.setWindowTitle('Folder Exists')
            msg.setText(f'A folder named "{snake}" already exists at:\n{output_dir}\n\nOverwrite it?')
            msg.setIcon(QMessageBox.NoIcon)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            if msg.exec() != QMessageBox.Yes:
                return
            shutil.rmtree(script_dir)

        try:
            # Copy template
            shutil.copytree(TEMPLATE_DIR, script_dir)

            # Remove builder-only template source file from generated output
            generated_template_py = os.path.join(script_dir, 'script_template.py')
            if os.path.exists(generated_template_py):
                os.remove(generated_template_py)

            # Rename lib/pyflame_lib.py → lib/pyflame_lib_{snake}.py
            lib_src = os.path.join(script_dir, 'lib', 'pyflame_lib.py')
            lib_dst = os.path.join(script_dir, 'lib', f'pyflame_lib_{snake}.py')
            if os.path.exists(lib_src):
                os.rename(lib_src, lib_dst)

            # Write generated script
            models    = [c.model for c in self.canvas.containers]
            tab_order = self._prompt_tab_order(models)
            code      = CodeGenerator.generate(self.config, models, tab_order=tab_order)
            with open(os.path.join(script_dir, f'{snake}.py'), 'w') as f:
                f.write(code)

            # Write LICENSE to script root (if a license was selected)
            if self.config.license_type != 'None':
                self._write_license_file(script_dir, self.config.license_type)

        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to generate script:\n{e}')
            return

        self._reveal_in_finder(script_dir)

        msg = QMessageBox(self)
        msg.setWindowTitle('Script Generated')
        msg.setText(f'Script generated successfully:\n{script_dir}\n\n(Revealed in Finder)')
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

def _init_logging() -> logging.Logger:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'pyflame_builder.log')

    logger = logging.getLogger('pyflame_builder')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')

    has_file = any(isinstance(h, RotatingFileHandler) for h in logger.handlers)
    has_stdout = any(
        isinstance(h, logging.StreamHandler) and getattr(h, 'stream', None) is sys.stdout
        for h in logger.handlers
    )

    if not has_file:
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if not has_stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


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


def _load_fonts():
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'fonts')
    for fname in ('Montserrat-Regular.ttf', 'Montserrat-Light.ttf', 'Montserrat-Thin.ttf'):
        QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))


def main():
    logger = _init_logging()
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
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    _set_macos_app_name(APP_NAME)
    _load_fonts()
    app.setFont(QFont('Montserrat', 10))
    window = PyFlameBuilder()
    window.show()
    rc = app.exec()
    logger.info('Shutting down %s with exit code %s', APP_NAME, rc)
    sys.exit(rc)


if __name__ == '__main__':
    main()
