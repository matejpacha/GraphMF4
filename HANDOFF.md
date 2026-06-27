# GraphMF4 — AI Handoff Document

> **Purpose:** This document gives an AI coding assistant (GitHub Copilot, Claude, etc.)
> everything it needs to continue developing this project without prior context.

---

## 1. Project Summary

**GraphMF4** is a Windows 10/11 desktop application that loads MF4 (ASAM MDF version 4)
measurement files, lets the user select signals, and plots them in interactive graphs.
Key capabilities: zoom/pan, legend toggle, multi-graph layout, per-channel appearance
settings, project save/load, and bitmap export.

---

## 2. Language and Platform

| | |
|-|-|
| Language | Python 3.11+ |
| Target OS | Windows 10 / 11 (64-bit) |
| GUI framework | PySide6 6.6+ (Qt 6) |
| Plotting | pyqtgraph 0.13+ |
| MF4 I/O | asammdf 7.3+ |
| Numerics | NumPy 1.26+ |

---

## 3. Repository Layout

```
GraphMF4/
├── src/
│   ├── main.py                        Entry point; creates QApplication; opens MainWindow
│   ├── core/
│   │   ├── project.py                 Data models (ProjectConfig, GraphConfig, ChannelConfig)
│   │   │                              + JSON load/save for the .gmf4proj project file
│   │   ├── mf4_reader.py              MF4 file I/O wrapper (caches open MDF handles)
│   │   └── graph_model.py             Placeholder for future graph-level business logic
│   ├── ui/
│   │   ├── main_window.py             QMainWindow; project lifecycle; MDI graph management
│   │   ├── graph_widget.py            Single graph panel (pyqtgraph + header buttons)
│   │   ├── signal_selector_dialog.py  Channel picker dialog (multi-select + text filter)
│   │   ├── channel_editor_dialog.py   Per-channel appearance editor (color, scale, offset, label)
│   │   ├── missing_files_dialog.py    Dialog shown on project load when MF4 files are missing
│   │   ├── loader_thread.py           QThread for background MF4 file loading
│   │   └── replace_file_dialog.py     Dialog to replace one MF4 file with another
│   └── utils/
│       └── export.py                  Bitmap export via QWidget.grab()
├── tests/
│   ├── test_project.py                Unit tests — ProjectConfig serialization
│   └── test_mf4_reader.py             Unit tests — MF4Reader (uses in-memory MDF)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── README.md
└── HANDOFF.md                         ← this file
```

---

## 4. Data Models (`src/core/project.py`)

```
ProjectConfig
  ├── version: str               File-format version string, e.g. "1.0"
  ├── name: str                  Human-readable project name
  ├── mf4_files: list[str]       Absolute paths of all loaded MF4 files
  └── graphs: list[GraphConfig]

GraphConfig
  ├── id: str                    UUID (stable across save/load)
  ├── title: str
  ├── channels: list[ChannelConfig]
  ├── x_range: list[float] | None    [x_min, x_max]; None = auto-fit
  ├── y_range: list[float] | None    [y_min, y_max]; None = auto-fit
  ├── show_legend: bool
  ├── legend_position: str       "top-right" (used for future legend dragging)
  ├── x_label: str               e.g. "Time [s]"
  ├── y_label: str
  └── win_geometry: list[int] | None   [x, y, w, h] in MDI-area coordinates; None = auto-arrange

ChannelConfig
  ├── file_path: str             Absolute path to source MF4 file
  ├── channel_name: str          asammdf channel name
  ├── group_index: int           asammdf group index (needed for disambiguation)
  ├── channel_index: int         asammdf channel index within group
  ├── color: str                 Hex color, e.g. "#1f77b4"
  ├── y_scale: float             Multiplier applied to raw samples
  ├── y_offset: float            Offset added after scaling: value = raw * y_scale + y_offset
  ├── visible: bool
  └── label: str                 Display name shown in legend
```

**Serialization:** `ProjectConfig.to_dict()` → `json.dump` → `.gmf4proj` file.
`ProjectConfig.from_dict()` / `ProjectConfig.load(path)` for deserialization.
`dataclasses.asdict()` is used internally; nested objects are reconstructed manually.

---

## 5. Key Design Decisions

### 5.1 pyqtgraph over matplotlib
pyqtgraph is a native Qt widget. Zoom, pan, and cursor interactions work
out of the box without embedding a figure canvas. It is also significantly
faster for large arrays.

### 5.2 MF4 file handle caching
`MF4Reader._cache` maps `str(Path(path).resolve())` → `MDF` instance.
Files are parsed once per session. `close_all()` is called on exit and
when a new project is opened.

### 5.3 Model ownership
`GraphWidget` holds a **live reference** to its `GraphConfig`. Before
saving, `MainWindow._sync_configs_from_widgets()` calls
`GraphWidget.get_config()` on each widget to pull the current view ranges
back into the model.

### 5.4 Signal-based decoupling
`GraphWidget` emits **five** signals:
- `request_remove` — tells MainWindow to remove and destroy the widget
- `request_add_signals` — tells MainWindow to open the signal selector dialog
- `config_changed` — tells MainWindow to set the dirty flag
- `x_range_changed(float, float)` — propagated by MainWindow when Sync X-axes is active
- `cursor_moved(float)` — emitted when user drags the readout cursor; MainWindow propagates it to all other widgets that have an active cursor when Sync X-axes is on

This keeps GraphWidget unaware of its parent's layout.

### 5.6 MDI window layout
Each `GraphWidget` lives inside a `QMdiSubWindow` within a `QMdiArea`.
Subwindows can be freely dragged, resized, minimized, and maximized.
`GraphConfig.win_geometry` ([x, y, w, h]) persists the MDI position/size
across save/load. On project load without saved geometry, `_arrange_vertical()`
stacks all subwindows in a single column. View menu provides: **Stack Vertically**,
**Tile**, **Cascade**.

### 5.7 MF4 file replacement
`MainWindow._replace_mf4_file()` lets the user swap one MF4 source file for
another while keeping the graph layout intact. It:
1. Reads the new file's channel list via `MF4Reader.get_channel_list()`.
2. Remaps every matching `ChannelConfig` (updates `file_path`, `group_index`,
   `channel_index`).
3. Removes `ChannelConfig` entries whose `channel_name` is absent in the new file.
4. Rebuilds graphs and shows a log dialog listing replaced and missing signals.

### 5.8 Ctrl+drag rubber-band zoom
`_CtrlZoomViewBox(pg.ViewBox)` subclass in `graph_widget.py` intercepts
`mouseDragEvent`: when Ctrl+left button is held it activates pyqtgraph's built-in
rubber-band zoom (`rbScaleBox` + `showAxRect`). Normal left drag remains pan.
Used via `pg.PlotWidget(viewBox=_CtrlZoomViewBox(), background="w")`.

### 5.9 Value readout cursor
Each `GraphWidget` has a **Cursor** toggle button in its header. When active:
- A draggable `pg.InfiniteLine` (orange, dashed) is added to the plot.
- On every position change, `_update_cursor_labels()` runs:
  1. Interpolates Y value at cursor X for every visible channel (`np.interp`).
  2. Creates a `pg.TextItem` per channel (channel colour + semi-transparent fill).
  3. Sorts labels by Y value descending; walks top-to-bottom pushing each label
     down by `18 px × (data_range / view_height_px)` if it would overlap the one
     above — keeps labels readable at any zoom level.
- Cursor sync across graphs (when Sync X-axes is active) is the **next pending item**.

### 5.10 File-based logging
`main.py._setup_logging()` configures a `FileHandler` writing to
`%APPDATA%\GraphMF4\graphmf4.log` at DEBUG level, active in both dev and EXE.
A `sys.excepthook` captures completely unhandled exceptions.
`MF4Reader.load_file()` and `read_signal()` log INFO / DEBUG / EXCEPTION entries,
making EXE issues diagnosable without a console window.

### 5.11 canmatrix + PyInstaller
MF4 files with embedded CAN logging need `canmatrix` to decode DBC databases.
`canmatrix` registers its format plugins (`dbc`, `csv`, …) via `pkg_resources`
entry points — which PyInstaller doesn't discover without package metadata.
Fix in `GraphMF4.spec`: `collect_all('canmatrix')` + `copy_metadata('canmatrix')`
bundles all submodules **and** the dist-info, so entry points are found at runtime.

### 5.12 get_channel_list — metadata only
`MF4Reader.get_channel_list()` reads `ch.name`, `ch.unit`, `ch.comment` directly
from the in-memory channel objects — it does **not** call `mdf.get()` per channel.
Original code called `mdf.get()` (full data read) just to obtain unit/comment;
this silently dropped channels whose data decoding failed (e.g. missing optional
asammdf dependency in the EXE). Metadata attributes are always safe to read.

---

## 6. Signal Flow: Adding a Channel

```
User clicks "+ Signals" in GraphWidget header
  → GraphWidget emits request_add_signals
    → MainWindow._open_signal_selector(graph_widget)
      → opens SignalSelectorDialog(mf4_files, reader)
        → user picks channels → dialog.exec() returns Accept
          → MainWindow calls dlg.selected_channels()
            → returns list[ChannelConfig] (no color set)
              → MainWindow calls graph_widget.add_channel(ch_cfg) for each
                → GraphWidget assigns color, appends to config.channels, plots curve
                  → GraphWidget emits config_changed
                    → MainWindow sets _dirty = True
```

---

## 7. Implementation Status

### Implemented (skeleton — compiles, logic is correct)
- [x] `ProjectConfig` / `GraphConfig` / `ChannelConfig` with full JSON round-trip
- [x] `MF4Reader` with file caching, channel enumeration, signal reading
- [x] `MainWindow`: project CRUD, MF4 file loading, graph add/remove, dirty tracking,
      window state persistence via QSettings, command-line project argument
- [x] `GraphWidget`: pyqtgraph PlotWidget, legend toggle, header buttons, export,
      `get_config()` for state sync
- [x] `SignalSelectorDialog`: file picker combo, text filter, multi-select, unit display
- [x] `export_widget_to_bitmap()` via `QWidget.grab()`
- [x] Unit tests for project serialization and MF4 reader

### Not yet implemented (prioritized)

| Priority | Feature | Notes |
|----------|---------|-------|
| ~~High~~ | ~~**Channel appearance editor**~~ | ✅ Done — `src/ui/channel_editor_dialog.py`; inline channel panel in `GraphWidget` with color swatch, visibility toggle, ✎ edit, ✕ remove per channel |
| ~~High~~ | ~~**Graph title rename**~~ | ✅ Done — double-click on title label → inline `QLineEdit` (Enter = confirm, Escape = cancel); implemented via `eventFilter` + `QStackedWidget` in `GraphWidget` header |
| ~~Medium~~ | ~~**Missing MF4 file handling**~~ | ✅ Done — `src/ui/missing_files_dialog.py`; on project load all referenced paths are checked; missing ones listed in a dialog with Browse buttons; user can relocate or continue without them; `_apply_relocations()` updates all `ChannelConfig.file_path` and `mf4_files` list |
| ~~Medium~~ | ~~**Linked X-axes**~~ | ✅ Done — "Sync X-axes" toggle in toolbar + View menu (Ctrl+Shift+X); `GraphWidget.x_range_changed` signal propagated by `MainWindow._on_x_range_changed`; loop prevented by `_block_x_signal` flag in widget + `_x_syncing` guard in MainWindow; state persisted in QSettings |
| ~~Medium~~ | ~~**Large file progress**~~ | ✅ Done — `src/ui/loader_thread.py` (`MF4LoadThread(QThread)`); opening MF4 runs `MDF(path)` on a worker thread; indeterminate `QProgressDialog` shown during load (appears only if > 400 ms); `MF4Reader.inject()` stores the result; project load shows wait cursor + status bar message |
| ~~Low~~ | ~~**Graph reordering / free layout**~~ | ✅ Done — `QMdiArea` + `QMdiSubWindow`; graphs are freely draggable/resizable MDI subwindows; MDI position/size saved in `GraphConfig.win_geometry`; View menu: Stack Vertically / Tile / Cascade; subwindow close intercepted via `eventFilter` |
| ~~Low~~ | ~~**Replace MF4 file**~~ | ✅ Done — `src/ui/replace_file_dialog.py`; File → Replace MF4 File…; remaps matching channels to new file, removes missing channels, shows replacement log dialog |
| ~~Low~~ | ~~**Windows file association**~~ | ✅ Done — handled by InnoSetup (`GraphMF4.iss`): `.gmf4proj` registered in HKCU via `[Registry]` + `[Code]` UserChoice section; no admin rights required |
| ~~Low~~ | ~~**Dark theme**~~ | ✅ Done — View → Dark Theme (Ctrl+Shift+D), checkable toggle; Fusion style; Qt QPalette for widgets; pyqtgraph `setBackground` + axis `setPen`/`setTextPen` per plot; MDI area background updated; preference persisted in QSettings |
| ~~Low~~ | ~~**Ctrl+drag zoom**~~ | ✅ Done — `_CtrlZoomViewBox` in `graph_widget.py`; Ctrl+left drag = rubber-band region zoom; normal left drag still pans; tooltip on PlotWidget documents all mouse shortcuts |
| ~~Low~~ | ~~**Value readout cursor**~~ | ✅ Done — "Cursor" toggle button per graph; draggable orange `pg.InfiniteLine`; `pg.TextItem` labels at each signal intersection with interpolated value + unit; 3-phase overlap prevention algorithm (sort → gap check → push down) |
| ~~Low~~ | ~~**Busy cursor for + Signals**~~ | ✅ Done — `QApplication.setOverrideCursor(Qt.WaitCursor)` in `_open_signal_selector()` (wraps dialog creation) and inside `SignalSelectorDialog._load_channels()` (wraps `get_channel_list` on file switch) |
| ~~Medium~~ | ~~**Cursor sync across graphs**~~ | ✅ Done — `cursor_moved(float)` signal on `GraphWidget`; `_on_cursor_pos_changed()` emits it unless `_block_cursor_signal`; `set_cursor_pos(x)` moves cursor silently (only when already active); `MainWindow._on_cursor_moved()` guarded by `_cursor_syncing` propagates to all other widgets with an active cursor when Sync X-axes is on |
| Medium | **ProjectConfig input validation** | `ProjectConfig.from_dict()` / `load()` are the JSON deserialization boundary. Add explicit checks: unknown `version` string → warn or raise; missing required keys → `ValueError` with field name; wrong type (e.g. `color` is int) → descriptive error. Currently any malformed `.gmf4proj` produces cryptic `KeyError` / `AttributeError`. |
| Medium | **Signal downsampling (LTTB)** | `GraphWidget` renders raw samples directly into pyqtgraph. MF4 files can contain millions of samples per channel, causing UI freezes and slow redraws. Implement Largest-Triangle-Three-Buckets (LTTB) or min/max decimation in `MF4Reader.read_signal()` (or as a post-read step in `GraphWidget.add_channel()`), triggered when sample count exceeds a threshold (e.g. 50 000 points). |
| Low | **Export data to CSV** | `utils/export.py` only exports bitmaps. Add File → Export Data… that writes visible signals in the current X-range to a CSV (timestamp column + one column per channel). Use `numpy.savetxt` or `csv.writer`; respect `y_scale` / `y_offset`. |
| Low | **Drag & drop MF4 files** | Allow dragging `.mf4` / `.MF4` files from Explorer onto the `MainWindow` / `QMdiArea`. Implement `dragEnterEvent` + `dropEvent` on `MainWindow`; call the existing `_load_mf4_file()` path for each dropped file. |
| Low | **Relative paths in project file** | `ChannelConfig.file_path` and `ProjectConfig.mf4_files` store absolute paths, so `.gmf4proj` files are not portable across machines or drive letters. On save, store paths relative to the `.gmf4proj` file location; on load, resolve back to absolute. Keep a compatibility fallback for existing absolute-path projects. |
| Low | **Undo / Redo (QUndoStack)** | Adding/removing channels and graphs is currently irreversible. Introduce a `QUndoStack` in `MainWindow` and wrap the mutating operations (`add_channel`, `remove_channel`, `add_graph`, `remove_graph`) in `QUndoCommand` subclasses. Wire Ctrl+Z / Ctrl+Y and add Undo/Redo entries to the Edit menu. |
| Low | **UI tests (pytest-qt)** | `tests/` only covers model-layer serialization and `MF4Reader`. Add headless widget tests using `pytest-qt` (`qtbot` fixture + `QApplication` in conftest). Minimum coverage: `GraphWidget` add/remove channel, `SignalSelectorDialog` filter, `MainWindow` project open/save round-trip. |
| High | **Delta cursor (ΔX / ΔY)** | A second draggable `pg.InfiniteLine` alongside the existing cursor. A `TextItem` overlay shows Δt (time difference) and ΔY (value difference) between the two cursor positions for each visible channel. Toggle via a second "Δ Cursor" button in the graph header; only active when the primary cursor is also on. Sync across graphs follows the same `cursor_moved` / `_cursor_syncing` pattern as the primary cursor. |
| High | **Statistics panel** | Below the channel list panel (or as a collapsible overlay), show min / max / mean / RMS for every visible channel computed over the **current view X-range**. Recomputed on `sigRangeChanged`. Values are read from `item.xData` / `item.yData` sliced to `viewRange()[0]`; RMS = `np.sqrt(np.mean(y**2))`. Respects `y_scale` / `y_offset` (data is already scaled when plotted). |
| High | **Recent Projects menu** | `File → Recent Projects` submenu listing the last 10 opened `.gmf4proj` paths, stored in `QSettings` under key `recent_projects` (JSON list). Updated on every successful `open_project_from_path()` and `_do_save()`. Missing paths shown grayed out. Cleared by a "Clear Recent" entry at the bottom. |
| Medium | **Copy graph to clipboard** | A `Copy` button in the `GraphWidget` header (or `Ctrl+C` shortcut when the subwindow is active) that calls `QApplication.clipboard().setPixmap(self._plot_widget.grab())`. Faster than File → Export for sharing screenshots. |
| Medium | **Right-click context menu on plot** | `contextMenuEvent` override on the `PlotWidget` (or `_CtrlZoomViewBox.raiseContextMenu` suppressed + custom menu). Entries: **Fit to data** (`plotWidget.autoRange()`), **Copy to clipboard**, **Add horizontal reference line**, **Export…**. Keeps toolbar clean while exposing discoverability. |
| Medium | **Channel reordering via drag** | Drag-and-drop reordering of rows in `_channels_panel`. Easiest implementation: replace the hand-built `QVBoxLayout` rows with a `QListWidget` (drag-and-drop enabled); `model().rowsMoved` → reorder `GraphConfig.channels` to match and re-plot in new order. Affects legend order and Z-order of curves. |
| Low | **Move channel between graphs** | Drag a channel row from one `GraphWidget`'s channel panel and drop it onto another graph's panel or title bar. `GraphWidget` emits a new `request_move_channel(ch_cfg)` signal; `MainWindow` removes it from the source graph and calls `target_widget.add_channel(ch_cfg)`. |
| Low | **Horizontal reference line** | An addable draggable `pg.InfiniteLine(angle=0)` marking a fixed Y value (threshold, spec limit). Added via context menu or a toolbar button. A `pg.TextItem` label next to the line shows the current Y value and updates on drag. Stored in `GraphConfig` as an optional `reference_lines: list[float]` field. |
| Low | **Y-axis double-click reset** | Double-clicking the **left (Y) axis** calls `ViewBox.autoRange(items=list(_plot_items.values()))` for Y only (X range unchanged). Symmetric with pyqtgraph's built-in right-click "View All" but scoped to Y so the user's X zoom is preserved. |
| Low | **Status bar: graph / channel count** | Right-hand section of `MainWindow`'s status bar shows e.g. `3 graphs · 12 channels · 2 files`. Updated in a new `_update_status_counts()` helper called after any topology change (add/remove graph or channel, open/close MF4). |
| Low | **Toolbar icons** | Replace plain-text `QAction` labels in the toolbar with `QIcon`. Use `QStyle.standardIcon(QStyle.SP_*)` for generic actions (New, Open, Save) and small bundled SVGs for app-specific ones (Add Graph, Sync X-axes, Cursor). Improves toolbar readability at small widths. |

---

## 8. Running and Testing

```powershell
# Setup (once)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run the app
python src/main.py

# Run tests (requires dev dependencies)
pip install -r requirements-dev.txt
pytest
```

---

## 9. Coding Conventions

- `from __future__ import annotations` in every module
- PySide6 only — never mix with PyQt5 / PyQt6
- Private methods: `_prefixed_with_underscore`
- No Qt in the model layer (`core/`) — pure Python dataclasses
- Line length: 100 characters (black + ruff configured in `pyproject.toml`)
- Type hints everywhere; `Optional[X]` is fine (or `X | None` with the future import)
- Use `Path` for all file operations; convert to `str` only where an API demands it
- Error messages shown to the user via `QMessageBox.critical()` in the UI layer;
  the model/core layer raises plain exceptions

---

## 10. Dependencies Summary

```
PySide6      — Qt 6 bindings (widgets, signals, file dialogs, settings)
pyqtgraph    — interactive plot widget (zoom/pan built-in, fast rendering)
asammdf      — ASAM MDF 3/4 reader/writer (industry standard Python library)
numpy        — array operations (timestamps, samples, scaling)
```
