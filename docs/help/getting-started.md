# Getting Started

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 pyflame_ui_builder.py
```

## Basic workflow

1. Set script details in the top bar.
2. Set size in columns and rows of Flame Window
3. Add widgets to layout and adjust any widget properties.
4. Preview generated code (optional).
5. Generate script via **File → Generate Script...**. Set the Flame Python path as the location.
   Commonly /opt/Autodesk/shared/python.

## Note

Files created by **File → Save** are not meant to be loaded into Flame. They are just project files for PyFlame UI Builder.

## Canvas controls

- Left mouse drag on selected widget: move/resize (where allowed)
- Right-click widget: context menu actions (Undo, optional Redo, Duplicate, Delete)
- Arrow keys: nudge selected widget by one grid cell

## Grid / zoom

Use the bottom control row in the canvas pane for Grid toggle and zoom controls.
Grid is **Off by default**.
Grid visibility only affects drawing; snapping remains active.
