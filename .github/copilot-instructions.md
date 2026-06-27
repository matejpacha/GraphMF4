# GraphMF4 — GitHub Copilot Instructions

## Project Overview
GraphMF4 is a Windows desktop app for loading, visualizing, and analyzing signals from
MF4 (ASAM MDF4) measurement files.

**Stack:** Python 3.11+ · PySide6 (Qt6) · pyqtgraph · asammdf · NumPy

## Repository Layout
```
src/
  main.py                   Entry point
  core/project.py           Data models (ProjectConfig, GraphConfig, ChannelConfig) + JSON I/O
  core/mf4_reader.py        MF4 file reader with caching (wraps asammdf)
  ui/main_window.py         QMainWindow
  ui/graph_widget.py        Single graph panel (pyqtgraph)
  ui/signal_selector_dialog.py  Channel picker dialog
  utils/export.py           Bitmap export
tests/
  test_project.py           ProjectConfig serialization tests
  test_mf4_reader.py        MF4Reader tests (in-memory MDF)
```

## Conventions
- `from __future__ import annotations` in every Python file
- PySide6 only — never PyQt5 / PyQt6
- No Qt imports in `core/` — keep model layer pure Python
- Private methods prefixed with `_`
- Line length: 100 characters (black + ruff)
- File paths: always use `pathlib.Path`; convert to `str` only where APIs require it
- User-facing errors: raise exceptions in `core/`, catch and display via `QMessageBox` in `ui/`

## Data Model
- `ChannelConfig`: one signal — file path, channel name, group/channel index, color,
  y_scale, y_offset, label, visible
- `GraphConfig`: one graph panel — list of ChannelConfig, x/y_range, show_legend, title
- `ProjectConfig`: root — list of GraphConfig, list of mf4_files, save/load JSON

## Key APIs
- `MF4Reader.get_channel_list(path)` → `list[ChannelInfo]`
- `MF4Reader.read_signal(path, name, group, index)` → `SignalData`
- `GraphWidget.add_channel(ch_cfg)` — adds and plots a channel live
- `GraphWidget.get_config()` — returns GraphConfig with current view ranges synced
- `ProjectConfig.save(path)` / `ProjectConfig.load(path)`

## Important Patterns
- `GraphWidget` never imports `MainWindow` — all back-communication uses Qt signals:
  `request_remove`, `request_add_signals`, `config_changed`
- Before saving, call `MainWindow._sync_configs_from_widgets()` to pull view state
- MDF file handles are cached in `MF4Reader._cache` by resolved absolute path

## Project File
Extension: `.gmf4proj`  
Format: indented UTF-8 JSON  
Version field: `"1.0"`  

## Next Steps (see HANDOFF.md §7 for full list)
1. Channel appearance editor (color, y_scale, y_offset, label)
2. Graph title rename (double-click on title label)
3. Missing MF4 file handling on project load
4. Linked X-axes (sync zoom across graphs)
