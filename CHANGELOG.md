# Changelog

## [1.1.1] - 03.05.26

### Fixed

- Misc bugs fixed.

## [1.1.0] - 03.04.26

### Added
- Added Window Margins to window properties to adjust space between edge of window and wigets.
- Added missing Table widget.
- Added Undo/Redo - Up to last 10 steps
- Multiple windows can now be created using +/- next to window name.
- Added new export option - Export UI Code Only.
- Misc enhancements to app UI.
- Window naming convention update: tab/window name now maps to generated method `create_<window_name>` and window object `self.<window_name>`.
- Renaming a window tab now updates generated method/object names and rewrites matching references in Live Code Preview (`create_<old>` and `self.<old>`).
- Window tabs can now be renamed by double-clicking the tab label.

### Compatibility
- Backward-compatible loader for legacy single-window `.pfb` files with automatic default backfill/migration.

### Changed
- Major maintainability refactor from monolithic script into modular packages (`app/`, `models/`, `services/`, `ui/`) while keeping `pyflame_ui_builder.py` as the runnable entrypoint.
- Added architecture documentation at `docs/architecture.md`.

## [1.0.0] - 02.24.26

### Added
- Initial release!
