# <<<SCRIPT_NAME>>>
# Copyright (c) <<<YEAR>>> <<<WRITTEN_BY>>>
<<<LICENSE_HEADER>>>"""
Script Name:    <<<SCRIPT_NAME>>>
Script Version: <<<SCRIPT_VERSION>>>
Flame Version:  <<<FLAME_VERSION>>>
Written by:     <<<WRITTEN_BY>>>
Creation Date:  <<<DATE>>>
Update Date:    <<<DATE>>>

License:        <<<LICENSE_DOCSTRING>>>

Script Type:    <<<SCRIPT_TYPE>>>

Description:

    Description goes here.

Menus:

    <<<MENU_PATH>>>

To install:

    Copy script into /opt/Autodesk/shared/python/<<<SNAKE_NAME>>>

Updates:

    <<<SCRIPT_VERSION>>> <<<DATE>>>
        - Initial release.
"""

# ==============================================================================
# [Imports]
# ==============================================================================

import os
import flame
from lib.pyflame_lib_<<<SNAKE_NAME>>> import *

# ==============================================================================
# [Constants]
# ==============================================================================

SCRIPT_NAME    = '<<<SCRIPT_NAME>>>'
SCRIPT_VERSION = '<<<SCRIPT_VERSION>>>'
SCRIPT_PATH    = os.path.abspath(os.path.dirname(__file__))

# ==============================================================================
# [Main Script]
# ==============================================================================

class <<<CLASS_NAME>>>:

    def __init__(self, selection) -> None:

        pyflame.print_title(f'{SCRIPT_NAME} {SCRIPT_VERSION}')

        # Check script path, if path is incorrect, stop script.
        if not pyflame.verify_script_install():
            return

        # Open main window
        self.main_window()

    def main_window(self) -> None:
        """
        Main Window
        ===========

        Main window for script.
        """

        def do_something() -> None:
            """
            Dummy function to be called when return/enter is pressed.
            Replace with your own function or method.
            """

            self.window.close()
            print('Do something...')

        def close_window() -> None:
            """
            Close window when escape is pressed.
            """

            self.window.close()

        # ------------------------------------------------------------------------------
        # [Start Window Build]
        # ------------------------------------------------------------------------------

        # Window
        self.window = PyFlameWindow(
            title=f'{SCRIPT_NAME} <small>{SCRIPT_VERSION}',
            parent=None,
            return_pressed=do_something,
            escape_pressed=close_window,
            grid_layout_columns=<<<GRID_COLUMNS>>>,
            grid_layout_rows=<<<GRID_ROWS>>>,
            )

<<<WIDGET_DECLARATIONS>>><<<TAB_ORDER>>>        # ------------------------------------------------------------------------------
        # [Widget Layout]
        # ------------------------------------------------------------------------------

<<<WIDGET_LAYOUT>>>

<<<SET_FOCUS>>>        # ------------------------------------------------------------------------------
        # [End Window Build]
        # ------------------------------------------------------------------------------

# ==============================================================================
# [Flame Menus]
# ==============================================================================

<<<FLAME_MENUS>>>
