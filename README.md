# PyFlame UI Builder

**Version:** 1.0.0<br>
**Author:** Michael Vaglienty<br>
**License:** GPL-3.0<br>
**GitHub:** https://github.com/logik-portal/pyflame-ui-builder<br>

A desktop UI builder for Autodesk Flame Python scripts.

Generates a ready-to-use Flame script with custom UI built from PyFlame UI widgets.

**Script logic will need to be added after creation.**

By default windows created with this script will close inside of Flame by hitting escape.

## Platform Support

- **Runs on MacOS only**
- Generated scripts work on Mac and Linux

## Requirements

- Python 3.11+
- PySide6
- macOS only (optional): `pyobjc-framework-Cocoa`

## Help

**Available in the **Help** menu.

Help content is sourced from:
- `docs/help/getting-started.md`
- `docs/help/keyboard-shortcuts.md`

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python3 pyflame_ui_builder.py
```

## License

GNU General Public License v3.0 (GPL-3.0) (see `LICENSE`).
