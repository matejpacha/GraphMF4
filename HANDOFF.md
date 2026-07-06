# GraphMF4 — AI Handoff Document

> **Purpose:** This document gives an AI coding assistant (GitHub Copilot, Claude, etc.)
> everything it needs to continue developing this project without prior context.

---

## 1. Project Summary

**GraphMF4** is a Windows 10/11 desktop application that loads MF4/MDF (ASAM MDF version 3/4)
measurement files, lets the user select signals, and plots them in interactive graphs.
Key capabilities: zoom/pan, legend toggle, multi-graph layout, per-channel appearance
settings, project save/load, bitmap export, digital signal stacking, and dockable channel panel.

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
│   ├── version.py                     Single source of truth for app version string
│   ├── core/
│   │   ├── project.py                 Data models (ProjectConfig, GraphConfig, ChannelConfig)
│   │   │                              + JSON load/save for the .gmf4proj project file
│   │   ├── mf4_reader.py              MF4 file I/O wrapper (caches open MDF handles)
│   │   └── graph_model.py             Placeholder for future graph-level business logic
│   ├── ui/
│   │   ├── main_window.py             QMainWindow; project lifecycle; MDI graph management
│   │   ├── graph_widget.py            Single graph panel (pyqtgraph + header buttons)
│   │   ├── channel_list_dock.py       Dockable channel list (reorder, visibility, edit, stack digital, drop target)
│   │   ├── signal_list_dock.py        Dockable signal browser (file combo, filter, drag source + CHANNEL_MIME_TYPE)
│   │   ├── signal_selector_dialog.py  Channel picker dialog (multi-select + text filter)
│   │   ├── channel_editor_dialog.py   Per-channel appearance editor (color, scale, offset, label, digital)
│   │   ├── missing_files_dialog.py    Dialog shown on project load when MF4 files are missing
│   │   ├── loader_thread.py           QThread for background MF4 file loading
│   │   ├── replace_file_dialog.py     Dialog to replace one MF4 file with another
│   │   └── settings_dialog.py         Application settings (downsampling, OpenGL)
│   └── utils/
│       ├── export.py                  Bitmap export via QWidget.grab()
│       └── downsample.py              LTTB signal downsampling (Largest-Triangle-Three-Buckets)
├── tests/
│   ├── test_project.py                Unit tests — ProjectConfig serialization
│   └── test_mf4_reader.py             Unit tests — MF4Reader (uses in-memory MDF)
├── LICENSE                            MIT license
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── build.ps1                          PyInstaller build script; auto-increments version; git commit dialog
├── GraphMF4.iss                       InnoSetup installer definition
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
  ├── show_labels: bool          Whether the "Labels" overlay is active (default False)
  ├── legend_position: str       "top-right" (used for future legend dragging)
  ├── x_label: str               e.g. "Time [s]"
  ├── y_label: str
  └── win_geometry: list[int] | None   [x, y, w, h] in MDI-area coordinates; None = auto-arrange

ChannelConfig
  ├── file_path: str             Absolute path to source MF4/MDF file
  ├── channel_name: str          asammdf channel name
  ├── group_index: int           asammdf group index (needed for disambiguation)
  ├── channel_index: int         asammdf channel index within group
  ├── color: str                 Hex color, e.g. "#1f77b4"
  ├── y_scale: float             Multiplier applied to raw samples
  ├── y_offset: float            Offset added after scaling: value = raw * y_scale + y_offset
  ├── visible: bool
  ├── label: str                 Display name shown in legend
  └── digital: bool              Step rendering (pg stepMode="right") + auto-stack support
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
`GraphWidget` emits **seven** signals:
- `request_remove` — tells MainWindow to remove and destroy the widget
- `request_add_signals` — tells MainWindow to open the signal selector dialog
- `config_changed` — tells MainWindow to set the dirty flag
- `channels_changed` — tells MainWindow/ChannelListDock to refresh the channel list (add/remove/edit)
- `x_range_changed(float, float)` — propagated by MainWindow when Sync X-axes is active
- `cursor_moved(float)` — emitted when user drags the readout cursor
- `delta_cursor_moved(float)` — emitted when user drags the delta cursor

This keeps GraphWidget unaware of its parent's layout.

### 5.6 MDI window layout
Each `GraphWidget` lives inside a `QMdiSubWindow` within a `QMdiArea`.
Subwindows can be freely dragged, resized, minimized, and maximized.
`GraphConfig.win_geometry` ([x, y, w, h]) persists the MDI position/size
across save/load. On project load without saved geometry, `_arrange_vertical()`
stacks all subwindows in a single column. View menu provides: **Stack Vertically**, **Tile**, **Cascade**.
The custom `_arrange_tile()` method (replacing `QMdiArea.tileSubWindows()`) tiles
windows in a `⌈√n⌉ × ⌈n/cols⌉` grid ordered top-left → bottom-right.

### 5.7 MF4 file replacement
`MainWindow._replace_mf4_file()` lets the user swap one MF4 source file for
another while keeping the graph layout intact. It:
1. Reads the new file's channel list via `MF4Reader.get_channel_list()`.
2. Remaps every matching `ChannelConfig` (updates `file_path`, `group_index`,
   `channel_index`).
3. Removes `ChannelConfig` entries whose `channel_name` is absent in the new file.
4. Rebuilds graphs and shows a log dialog listing replaced and missing signals.

### 5.8 Ctrl+drag rubber-band zoom + Shift+click XY crosshair
`_CtrlZoomViewBox(pg.ViewBox)` subclass in `graph_widget.py` intercepts mouse events:
- `mouseDragEvent`: Ctrl+left drag → rubber-band zoom (`rbScaleBox` + `showAxRect`); normal left drag → pan.
- `mouseClickEvent`: Shift+left click in XY mode (cursor active) → teleport crosshair intersection to clicked data position via `GraphWidget._move_xy_crosshair(x, y)`.

Instantiated via `pg.PlotWidget(viewBox=_CtrlZoomViewBox(self), ...)` — receives a `graph_widget` reference so it can call back into the widget on Shift+click.

### 5.9 Value readout cursor
Each `GraphWidget` has a **Cursor** toggle button in its header. When active:
- A draggable `pg.InfiniteLine` (orange, dashed) is added to the plot.
- On every position change, `_update_cursor_labels()` runs:
  1. Interpolates Y value at cursor X for every visible channel (`np.interp`).
  2. Creates a `pg.TextItem` per channel (channel colour + semi-transparent fill).
  3. Sorts labels by Y value descending; walks top-to-bottom pushing each label
     down by `18 px × (data_range / view_height_px)` if it would overlap the one
     above — keeps labels readable at any zoom level.
  4. Adds a time label (`_add_cursor_time_label`) at the bottom of the view.
- All cursor `TextItem`s are added with `ignoreBounds=True` so pyqtgraph does **not**
  include them in the Y auto-range calculation.  Without this flag the time label
  (placed at `y_bottom`) would trigger `sigRangeChanged` → `_update_cursor_labels` →
  new lower `y_bottom` → infinite downward scroll loop.
- `_update_cursor_labels` is guarded by `_in_cursor_update: bool` to block any
  re-entrant call from `sigRangeChanged`.
- **Orphan sweep**: `_sweep_orphan_text_items()` is called at the start of each
  `_do_update_cursor_labels` to remove any `pg.TextItem` in the scene not tracked by
  `_cursor_labels`, `_delta_labels`, or `_signal_labels`. Prevents visual ghost labels
  caused by `sigRangeChanged` triggering signal-label updates mid-cursor-update, leaving
  items in the Qt scene without a dict reference.
- Cursor sync across graphs: `cursor_moved(float)` signal propagated by `MainWindow`.
  **XY mode graphs are excluded from sync** (neither emit nor receive `cursor_moved`).

**XY mode cursor** — crosshair instead of single vertical line:
- Two `pg.InfiniteLine` instances: vertical (`_cursor_line`) + horizontal (`_cursor_h_line`).
- Labels: `"x = X.XXX"` at the bottom of the view; `"y = Y.XXX"` at the left edge.
- **Shift+left click** teleports the crosshair intersection to the clicked data position.
- Δ-cursor button is disabled in XY mode.
- `_add_cursor_time_label` detects XY mode and formats accordingly;
  `_add_cursor_y_label` places the Y label at `(x_left, y_cursor)` with `ignoreBounds=True`.

### 5.10 File-based logging
`main.py._setup_logging()` configures a `FileHandler` writing to
`%APPDATA%\GraphMF4\graphmf4.log` at DEBUG level, active in both dev and EXE.
A `sys.excepthook` captures completely unhandled exceptions.
`MF4Reader.load_file()` and `read_signal()` log INFO / DEBUG / EXCEPTION entries.
`GraphWidget._plot_channel()` uses `_log.exception()` (not a silent `print`) so any
channel plot failure is always captured with full traceback in the log file.

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

### 5.13 Application version
`src/version.py` is the **single source of truth** for the version string
(`__version__ = "MAJOR.MINOR.PATCH"`).  `build.ps1` auto-increments the PATCH
segment on every build and propagates the new value to:
- `src/version.py` — read at runtime by `main.py` for startup logging
- `pyproject.toml` — Python package metadata
- `GraphMF4.iss` — InnoSetup `#define AppVersion` (installer filename + Programs list)

After a successful PyInstaller build, `build.ps1` shows a WPF dialog with a
pre-filled commit message (`build: vX.Y.Z (YYYY-MM-DD)`) and a multiline text area
for additional notes.  Clicking **Commit** runs `git add` + `git commit`; **Skip**
bypasses VCS.

### 5.14 Signal downsampling (LTTB)
`src/utils/downsample.py` implements the **Largest-Triangle-Three-Buckets** algorithm
(`lttb(x, y, n_out, threshold) → (x_out, y_out)`).

`GraphWidget._plot_channel()` applies downsampling after scaling but before plotting:
```python
ds_enabled, ds_threshold, ds_target = load_downsample_settings()  # from QSettings
if ds_enabled:
    x_data, samples = lttb(x_data, samples, n_out=ds_target, threshold=ds_threshold)
```
If LTTB raises an exception the fallback is the full unsampled array (never silent data loss).

User-configurable parameters (persisted in `QSettings` under `downsample/`):
| Key | Default | Meaning |
|---|---|---|
| `downsample/enabled` | `True` | Global on/off switch |
| `downsample/threshold` | `10 000` | Apply when sample count exceeds this |
| `downsample/target` | `1 000` | Output point count |

Accessible via **Help → Settings…** (`src/ui/settings_dialog.py`).
Changes take effect immediately: `MainWindow._replot_all_graphs()` calls
`GraphWidget.replot_channels()` on every open graph after the dialog is accepted.

### 5.15 read_signal group/index fallback
`MF4Reader.read_signal()` first tries the fast path `mdf.get(name, group=g, index=i)`.
If that fails (e.g. the file was re-processed and the group layout changed — common
when asammdf encounters a full disk during CAN bus logging) it retries with
`mdf.get(name)` (name-only lookup) and logs a `WARNING`.  Both failure modes are
logged with full context so they are diagnosable from `graphmf4.log`.

### 5.16 MDF (v3/v4) file support
All file-open dialogs accept `*.mf4 *.MF4 *.mdf *.MDF`. `asammdf.MDF` detects the
format from the file header regardless of extension, so MDF 3.x and MDF 4.x files
both open transparently.

### 5.17 Render performance (clipToView + auto-downsampling)
`GraphWidget._plot_channel()` sets two options on every `PlotDataItem`:
- `item.setClipToView(True)` — clips the data array to the visible X range before
  rendering (huge speedup when zoomed in on a small portion of a long recording).
- `item.setDownsampling(auto=True, method="peak")` — pyqtgraph dynamically reduces
  the number of rendered points to match screen pixel count; `method="peak"` preserves
  signal amplitude extremes within each group.
LTTB target raised from 1 000 → **5 000** samples for better zoom detail.
Optional OpenGL rendering: **Help → Settings… → Rendering** checkbox; stored in
`QSettings` under `render/opengl`; applied in `main.py` before `MainWindow` is created
(requires restart).

### 5.18 Digital signal support
`ChannelConfig.digital: bool` (default `False`) marks a channel as a step/logic signal.
Effects when `digital=True`:
- `_plot_channel()` passes `stepMode="right"` to pyqtgraph → square-wave rendering.
- Channel editor (`channel_editor_dialog.py`) shows a *Digital signal* checkbox.
- `GraphWidget._on_stack_digital_clicked()` (also in `ChannelListDock`) auto-stacks
  all visible digital channels: reads raw data per channel, computes
  `y_scale = 0.8 / span` and `y_offset = row × 1.2` so each fits a 0.8-unit lane
  with 0.2-unit gap.

### 5.19 Dockable Channel Panel (`channel_list_dock.py`)
`ChannelListDock(QDockWidget)` replaces the old embedded per-graph channel rows.
- `set_graph(gw)` — called by `MainWindow._on_subwindow_activated()` + at end of
  `_rebuild_graphs()` to keep the dock in sync with the active MDI subwindow.
- `refresh()` — rebuilds `QListWidget` items; preserves the current selection row.
- `QListWidget` with `ExtendedSelection` + `DragDropMode.InternalMove` — Ctrl/Shift+click
  selects multiple channels; drag rows to reorder; `rowsMoved` maps new order back to
  `GraphConfig.channels` via a stable `file_path::channel_name::group_index` key in `UserRole`.
- **Right-click context menu** on selected items: *Převést na digitální / Převést na analogový*
  toggles `ChannelConfig.digital` on all selected channels and replots them.
- Check state = visibility; colour icon; italic = digital channel.
- Double-click or **✎ Edit** button → `GraphWidget._edit_channel()` (single item).
- **+ Signals** and **Stack ↕** buttons operate on the active graph.
- View → **Channel Panel** (Ctrl+Shift+P) toggles the dock.

### 5.20 Recent Projects menu
`File → Recent Projects` submenu lists the last 10 opened `.gmf4proj` files, stored
in `QSettings` under `recent_projects` (JSON list of absolute path strings).
Updated on every successful `open_project_from_path()` and `_do_save()`.
Missing paths shown disabled with `✗` suffix. **Clear Recent** entry at the bottom.

### 5.21 Signal Browser drag-and-drop
`SignalListDock` exposes a `_ChannelBrowserList(QListWidget)` subclass that overrides
`startDrag()` with `ExtendedSelection` — Ctrl/Shift+click selects multiple channels.
The drag payload is a **JSON array** of channel dicts (one per selected channel) under
the custom MIME type `application/x-graphmf4-channel` (`CHANNEL_MIME_TYPE`).

Helpers in `signal_list_dock.py`:
- `decode_channel_mime_multi(mime_data)` — returns `list[tuple[file_path, name, group, index]]`;
  handles both the new array format and legacy single-dict payloads.
- `decode_channel_mime(mime_data)` — thin wrapper returning the first element or `None`
  (kept for call sites that handle only one channel at a time).

Drop targets — both iterate over all tuples from `decode_channel_mime_multi`:
- **`ChannelListDock`**: `_list.viewport()` event filter adds each channel via
  `self._graph.add_channel()`.
- **`MainWindow`**: `dropEvent` identifies the target graph via `QApplication.widgetAt(global_pos)`
  + parent-chain walk; adds all dragged channels to the detected `GraphWidget`.

**+ Add to Active Graph** button similarly emits `channel_requested` for every selected item.

### 5.22 Reload All Data (F5)
`File → Reload All Data` (also toolbar button ↺, shortcut **F5**) re-opens the current
project file from disk via `MainWindow._reload_all_data()` → `open_project_from_path(str(self._project_path))`.
This is identical to selecting the project from the Recent Projects menu: MF4 cache is
cleared, graphs are rebuilt, and view ranges are reset to fit the data.
If the project has not been saved yet (`_project_path is None`), a message is shown.

---

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
- [x] `src/version.py` + `build.ps1` auto-increment + InnoSetup propagation
- [x] `LICENSE` (MIT) — referenced in `pyproject.toml` and shown in installer
- [x] `src/utils/downsample.py` — LTTB algorithm; applied in `GraphWidget._plot_channel()`
- [x] `src/ui/settings_dialog.py` — Help → Settings… exposes downsampling params
- [x] Cursor infinite-scroll bug fixed (`ignoreBounds=True` + `_in_cursor_update` guard)
- [x] `MF4Reader.read_signal()` name-only fallback when group/index lookup fails

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
| ~~Medium~~ | ~~**Signal downsampling (LTTB)**~~ | ✅ Done — `src/utils/downsample.py`; LTTB applied in `GraphWidget._plot_channel()` after scaling; configurable threshold + target via **Help → Settings…** (`src/ui/settings_dialog.py`); LTTB failure falls back to full data; `GraphWidget.replot_channels()` re-plots all channels after settings change |
| Low | **Export data to CSV** | `utils/export.py` only exports bitmaps. Add File → Export Data… that writes visible signals in the current X-range to a CSV (timestamp column + one column per channel). Use `numpy.savetxt` or `csv.writer`; respect `y_scale` / `y_offset`. |
| Low | **Drag & drop MF4 files** | Allow dragging `.mf4` / `.MF4` files from Explorer onto the `MainWindow` / `QMdiArea`. Implement `dragEnterEvent` + `dropEvent` on `MainWindow`; call the existing `_load_mf4_file()` path for each dropped file. |
| Low | **Relative paths in project file** | `ChannelConfig.file_path` and `ProjectConfig.mf4_files` store absolute paths, so `.gmf4proj` files are not portable across machines or drive letters. On save, store paths relative to the `.gmf4proj` file location; on load, resolve back to absolute. Keep a compatibility fallback for existing absolute-path projects. |
| Low | **Undo / Redo (QUndoStack)** | Adding/removing channels and graphs is currently irreversible. Introduce a `QUndoStack` in `MainWindow` and wrap the mutating operations (`add_channel`, `remove_channel`, `add_graph`, `remove_graph`) in `QUndoCommand` subclasses. Wire Ctrl+Z / Ctrl+Y and add Undo/Redo entries to the Edit menu. |
| Low | **UI tests (pytest-qt)** | `tests/` only covers model-layer serialization and `MF4Reader`. Add headless widget tests using `pytest-qt` (`qtbot` fixture + `QApplication` in conftest). Minimum coverage: `GraphWidget` add/remove channel, `SignalSelectorDialog` filter, `MainWindow` project open/save round-trip. |
| ~~High~~ | ~~**Delta cursor (ΔX / ΔY)**~~ | ✅ Done — "Δ Cursor" toggle button per graph (enabled only when primary Cursor is active); second draggable `pg.InfiniteLine` (blue dashed); `_do_update_delta_labels()` draws a signed ΔY label per channel at the delta cursor position and a `Δt = ±X.XXX s` label at the bottom; overlap prevention mirrors the primary cursor 3-phase algorithm; `delta_cursor_moved` signal propagated by `MainWindow._on_delta_cursor_moved()` using the same `_cursor_syncing` guard; `apply_theme` updates the delta cursor pen colour. |
| High | **Statistics panel** | Below the channel list panel (or as a collapsible overlay), show min / max / mean / RMS for every visible channel computed over the **current view X-range**. Recomputed on `sigRangeChanged`. Values are read from `item.xData` / `item.yData` sliced to `viewRange()[0]`; RMS = `np.sqrt(np.mean(y**2))`. Respects `y_scale` / `y_offset` (data is already scaled when plotted). |
| ~~High~~ | ~~**Recent Projects menu**~~ | ✅ Done — `File → Recent Projects` submenu; last 10 paths in `QSettings["recent_projects"]` (JSON); updated on open and save; missing paths disabled with `✗`; **Clear Recent** at the bottom; `_build_recent_menu()` rebuilt on every change. |
| Medium | **Copy graph to clipboard** | A `Copy` button in the `GraphWidget` header (or `Ctrl+C` shortcut when the subwindow is active) that calls `QApplication.clipboard().setPixmap(self._plot_widget.grab())`. Faster than File → Export for sharing screenshots. |
| Medium | **Right-click context menu on plot** | `contextMenuEvent` override on the `PlotWidget` (or `_CtrlZoomViewBox.raiseContextMenu` suppressed + custom menu). Entries: **Fit to data** (`plotWidget.autoRange()`), **Copy to clipboard**, **Add horizontal reference line**, **Export…**. Keeps toolbar clean while exposing discoverability. |
| ~~Medium~~ | ~~**Channel reordering via drag**~~ | ✅ Done — `ChannelListDock` (`src/ui/channel_list_dock.py`); `QListWidget` with `InternalMove` drag-drop; `rowsMoved` maps new order back via stable `file_path::channel_name::group_index` key; replots via `replot_channels()`; double-click → channel editor. |
| Medium | **X vs Y chart** | Support for a single signal set as horizontal axis and multiple signals plot, inlcuding correct axis titles. |
| ~~Medium~~ | ~~**Singal list panel**~~ | ✅ Done — `src/ui/signal_list_dock.py` (`SignalListDock(QDockWidget)`); View → **Signal Browser** (Ctrl+Shift+B); left-side dock; file combo + text filter + `QListWidget`; double-click or **+ Add to Active Graph** → `channel_requested` signal → `MainWindow._on_signal_requested()`; **drag-and-drop** from the list onto any graph (or channel panel) encodes channel info as `application/x-graphmf4-channel` MIME payload (`CHANNEL_MIME_TYPE`); `MainWindow.dropEvent` uses `QApplication.widgetAt()` + parent-chain walk to identify the `GraphWidget` under the cursor — always drops into the graph the user is hovering over regardless of which graph is currently active; `ChannelListDock.eventFilter` accepts the same drops on the channel list viewport. |
| ~~Medium~~ | ~~**Optional signal name labels**~~ | ✅ Done — "Labels" toggle button per graph; when active, a `pg.TextItem` per visible channel is placed at the left edge of the view (`x = x_left`) at the interpolated Y value of the signal; same 3-phase overlap prevention algorithm as cursor labels; `ignoreBounds=True` prevents Y auto-range interference; connected to `sigRangeChanged` so labels track pan/zoom; refreshed from all data mutation sites via `_maybe_update_signal_labels()`; **state persisted** in `GraphConfig.show_labels` (default `False`) — button initialised from config on load, saved on toggle via `config_changed`. |
| Low | **Move channel between graphs** | Drag a channel row from one `GraphWidget`'s channel panel and drop it onto another graph's panel or title bar. `GraphWidget` emits a new `request_move_channel(ch_cfg)` signal; `MainWindow` removes it from the source graph and calls `target_widget.add_channel(ch_cfg)`. |
| Low | **Horizontal reference line** | An addable draggable `pg.InfiniteLine(angle=0)` marking a fixed Y value (threshold, spec limit). Added via context menu or a toolbar button. A `pg.TextItem` label next to the line shows the current Y value and updates on drag. Stored in `GraphConfig` as an optional `reference_lines: list[float]` field. |
| Low | **Y-axis double-click reset** | Double-clicking the **left (Y) axis** calls `ViewBox.autoRange(items=list(_plot_items.values()))` for Y only (X range unchanged). Symmetric with pyqtgraph's built-in right-click "View All" but scoped to Y so the user's X zoom is preserved. |
| Low | **Status bar: graph / channel count** | Right-hand section of `MainWindow`'s status bar shows e.g. `3 graphs · 12 channels · 2 files`. Updated in a new `_update_status_counts()` helper called after any topology change (add/remove graph or channel, open/close MF4). |
| ~~Low~~ | ~~**Toolbar icons**~~ | ✅ Done — `_setup_toolbar()` sets `ToolButtonTextBesideIcon` + 20×20 px icons; New/Open/Save/Open MF4/Replace use `QStyle.standardIcon(SP_*)`; Add Graph / Sync X-axes / Abs Time / Dark Theme use `_make_icon(symbol, bg_color)` — a static helper that draws a coloured circle with a white glyph via `QPainter` on `QPixmap`. |
| High | **Virtual signals with MATH functions** | Virtual signals can be added to a graph, where one or multiple actual signals can be used in a math script to provide a graphical interpretation of calculated values. |
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
