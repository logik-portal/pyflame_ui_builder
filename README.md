# PyFlame UI Builder

**Version:** 1.1.1<br>
**Author:** Michael Vaglienty<br>
**License:** GPL-3.0<br>
**GitHub:** https://github.com/logik-portal/pyflame-ui-builder<br>

A desktop UI builder for Autodesk Flame Python scripts.

Generates a ready-to-use Flame script with custom UI built from PyFlame UI widgets.

By default windows created with this script will close inside of Flame by hitting escape.

**Script logic will need to be added after creation.**

**Scripts created with PyFlame UI Builder require at least Flame 2025.1**

## Platform Support

- **Runs on MacOS only**
- Generated scripts work on Mac and Linux

## Requirements

- Python 3.11+
- PySide6

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 pyflame_ui_builder.py
```

## Basic workflow

1. Set script details in the top bar.
2. Set Flame Window columns/rows in the **Properties** panel (shown when no widget is selected). Columns and rows can be adjusted later there or via right-click actions in the Flame Window UI.
3. Add widgets to layout by dragging the widget name from the widegts panel to the Flame Window UI (including Collections widgets like Table, Tree Widget, and List Widget).
4. Set widget sizing when available. Some widgets can span multiple grid squares. Resizeable widgets will have handles once dropped in the Flame Window UI.
5.  Adjust widget properties in Widget Property panel.
6. Use **Preview: On/Off** in the bottom bar to switch between edit mode and interactive preview mode.
   - Preview mode enables direct widget interaction and prevents adding new widgets until turned off.
5. Export script via **File → Export Script...**. Set the Flame Python path as the location. Commonly /opt/Autodesk/shared/python.
6. Start Flame to preview the new window.
7. Add custom logic to widgets/script in code editor of your choice. A stub file for the pyflame library is included with the script to assist working with the widgets in your code editor.

## Example files

Two example files can be loaded from /pyflame_ui_builder/examples

## Screenshots

<p align="center">
  <img src="docs/screenshots/screenshot_01.png" alt="Main UI" width="900">
</p>

<p align="center">
  <img src="docs/screenshots/screenshot_01.png" alt="Main UI" width="900">
</p>

## Note

Files created by **File → Save** are not meant to be loaded into Flame. They are just project files for PyFlame UI Builder.
To create a script that can be loaded in Flame go to **File → Export Script...**.

During export, if duplicate window names are detected, you will be warned and can choose to cancel or continue.

## Canvas controls

- Left mouse drag on selected widget: move/resize (where allowed)
- Right-click widget: context menu actions (Undo, optional Redo, Duplicate, Delete)
- Arrow keys: nudge selected widget by one grid cell

## Multi-window tabs

- The canvas now supports multiple script windows via tabs.
- Add a tab via tab context menu or the `+` button on the tab row.
- Remove current tab via tab context menu or the `−` button on the tab row.
- Rename tabs by double-clicking tab label or from tab context menu.
- Saving `.pfb` includes all windows; loading supports old single-window `.pfb` files and auto-migrates them.

## Grid / zoom

Use the bottom control row in the canvas pane for Grid toggle and zoom controls.
Grid is **Off by default**.
Grid visibility only affects drawing; snapping remains active.

## Code preview editing

- The **Live Code Preview** panel is editable with exception of the UI code.

## Help

- Available in the **Help** menu.
- **File → Export UI Code Only...** exports only protected UI Window Build blocks (`[Start Window Build]` → `[End Window Build]`).
- Keep generated markers intact in exported scripts so protected UI sections can be updated safely.

## License

GNU General Public License v3.0 (GPL-3.0) (see `LICENSE`).
