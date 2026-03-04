# Architecture (v1.1.0)

## Overview

PyFlame UI Builder is split into UI + model + service layers.

- `pyflame_ui_builder.py` — app shell and UI orchestration
- `models/` — typed in-memory data models
- `ui/` — reusable view widgets/panels
- `services/` — pure-ish logic for import/export/serialization/analysis
- `assets/script_template/` — export template source

## Service boundaries

### `services/project_serializer.py`
Responsible for `.pfb` save/load only.

- Guarantees backward compatibility for schema v1 (single-window)
- Current save schema is v2 (multi-window)
- Applies safe defaults for missing fields

### `services/script_analysis.py`
Responsible for importing existing script structure.

- Detects classes + window-build methods
- Prefers `[Start Window Build]` markers
- Falls back across AST/regex paths for malformed scripts

### `services/workflow.py`
Responsible for import flow transformations used by UI handlers.

- Converts analyzer metadata into typed window/widget models
- Builds consistent import summary text
- Keeps orchestration logic out of the main window class

### `services/export_workflow.py`
Responsible for export orchestration decisions.

- Prepares destination script tree from template
- Decides whether to export generated code or user-edited preview code
- Encapsulates imported-session safety logic that prevents malformed indent carry-over

### `services/code_generator.py`
Responsible for deterministic source generation from models.

- Renders template substitutions
- Builds window methods and widget declarations
- Generates menu hook functions

## Preview API (local)

Local-only API for automation/debugging while app is open.

- `GET /api/health`
- `GET /api/preview`
- `POST /api/preview`
- `POST /api/new`
- `POST /api/import`
- `POST /api/export`

Design intent: expand this API later to expose full config + per-widget field values.

## Current testing strategy

- `tools/validate_script_import.py` for quick one-off import checks
- `tests/test_import_smoke.py` + fixtures for regression protection
- Code-level compile checks on touched files before commit
