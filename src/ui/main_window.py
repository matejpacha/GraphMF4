"""Main application window.

Responsibilities:
  - Project lifecycle (new / open / save / save-as)
  - MF4 file management (open files, track loaded paths)
  - Graph panel management (add / remove GraphWidgets)
  - Dispatch signal-selection dialog and attach results to a graph
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QSettings, QSize
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMenu,
    QMessageBox,
    QStyle,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.mf4_reader import MF4Reader
from core.project import PROJECT_FILE_EXTENSION, GraphConfig, ProjectConfig
from ui.channel_list_dock import ChannelListDock
from ui.graph_widget import GraphWidget
from ui.signal_list_dock import SignalListDock
from ui.signal_selector_dialog import SignalSelectorDialog
from ui.replace_file_dialog import ReplaceFileDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._project: ProjectConfig = ProjectConfig()
        self._project_path: Optional[Path] = None
        self._dirty: bool = False
        self._x_sync: bool = False
        self._x_syncing: bool = False   # re-entrancy guard for X-axis sync
        self._cursor_syncing: bool = False  # re-entrancy guard for cursor sync
        self._abs_time: bool = False        # global clock / absolute-time mode
        self._mf4_reader = MF4Reader()
        self._graph_widgets: list[GraphWidget] = []
        self._active_threads: list = []   # keeps thread refs alive until done
        self._widget_to_subwin: dict = {}  # GraphWidget -> QMdiSubWindow
        self._subwin_to_widget: dict = {}  # QMdiSubWindow -> GraphWidget

        self._setup_ui()
        self._channel_dock = ChannelListDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._channel_dock)
        self._signal_list_dock = SignalListDock(self._mf4_reader, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._signal_list_dock)
        self._signal_list_dock.channel_requested.connect(self._on_signal_requested)
        self._mdi_area.subWindowActivated.connect(self._on_subwindow_activated)
        self._setup_menu()
        self._setup_toolbar()
        self._restore_window_state()
        self._update_title()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setMinimumSize(960, 640)

        self._mdi_area = QMdiArea()
        self._mdi_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mdi_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mdi_area.setBackground(Qt.lightGray)
        self.setCentralWidget(self._mdi_area)
        self.setStatusBar(QStatusBar())
        self.setAcceptDrops(True)   # receive channel drops from SignalListDock

    def _setup_menu(self) -> None:
        mb = self.menuBar()

        # File -------------------------------------------------------
        file_menu = mb.addMenu("&File")
        file_menu.addAction(self._action("&New Project", self._new_project, "Ctrl+N"))
        file_menu.addAction(self._action("&Open Project\u2026", self._open_project, "Ctrl+O"))
        self._recent_menu: QMenu = file_menu.addMenu("Recent &Projects")
        self._build_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(self._action("&Save Project", self._save_project, "Ctrl+S"))
        file_menu.addAction(
            self._action("Save Project &As…", self._save_project_as, "Ctrl+Shift+S")
        )
        file_menu.addSeparator()
        file_menu.addAction(self._action("Open Data &File\u2026", self._open_mf4_file, "Ctrl+F"))
        file_menu.addAction(self._action("Re&place Data File\u2026", self._replace_mf4_file))
        file_menu.addAction(self._action("&Reload All Data", self._reload_all_data, "F5"))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", self.close, "Alt+F4"))

        # View -------------------------------------------------------
        view_menu = mb.addMenu("&View")
        view_menu.addAction(self._action("&Add Graph", self._add_graph, "Ctrl+G"))
        view_menu.addSeparator()
        _ch_panel_action = self._channel_dock.toggleViewAction()
        _ch_panel_action.setText("&Channel Panel")
        _ch_panel_action.setShortcut("Ctrl+Shift+P")
        view_menu.addAction(_ch_panel_action)
        _sig_list_action = self._signal_list_dock.toggleViewAction()
        _sig_list_action.setText("&Signal Browser")
        _sig_list_action.setShortcut("Ctrl+Shift+B")
        view_menu.addAction(_sig_list_action)
        view_menu.addSeparator()
        self._sync_x_action = QAction("Sync &X-axes", self)
        self._sync_x_action.setCheckable(True)
        self._sync_x_action.setToolTip(
            "Keep X-axis range identical across all graphs (Ctrl+Shift+X)"
        )
        self._sync_x_action.setShortcut("Ctrl+Shift+X")
        self._sync_x_action.toggled.connect(self._on_sync_x_toggled)
        view_menu.addAction(self._sync_x_action)
        self._abs_time_action = QAction("&Clock (Absolute Time)", self)
        self._abs_time_action.setCheckable(True)
        self._abs_time_action.setToolTip(
            "Show X-axis as wall-clock time (HH:MM:SS) instead of relative seconds (Ctrl+Shift+C)"
        )
        self._abs_time_action.setShortcut("Ctrl+Shift+C")
        self._abs_time_action.toggled.connect(self._on_abs_time_toggled)
        view_menu.addAction(self._abs_time_action)
        view_menu.addSeparator()
        self._dark_action = QAction("&Dark Theme", self)
        self._dark_action.setCheckable(True)
        self._dark_action.setShortcut("Ctrl+Shift+D")
        self._dark_action.toggled.connect(self._apply_theme)
        view_menu.addAction(self._dark_action)
        view_menu.addSeparator()
        view_menu.addAction(self._action("Stack &Vertically", self._arrange_vertical))
        view_menu.addAction(self._action("&Tile", self._arrange_tile))
        view_menu.addAction(
            self._action("Cas&cade", lambda: self._mdi_area.cascadeSubWindows())
        )

        # Help -------------------------------------------------------
        help_menu = mb.addMenu("&Help")
        help_menu.addAction(self._action("&Settings\u2026", self._show_settings))
        help_menu.addSeparator()
        help_menu.addAction(self._action("&About", self._show_about))

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        sp = QStyle.StandardPixmap
        st = self.style()

        new_act = self._action("New", self._new_project)
        new_act.setIcon(st.standardIcon(sp.SP_FileIcon))
        new_act.setToolTip("New Project (Ctrl+N)")
        tb.addAction(new_act)

        open_act = self._action("Open", self._open_project)
        open_act.setIcon(st.standardIcon(sp.SP_DirOpenIcon))
        open_act.setToolTip("Open Project (Ctrl+O)")
        tb.addAction(open_act)

        save_act = self._action("Save", self._save_project)
        save_act.setIcon(st.standardIcon(sp.SP_DialogSaveButton))
        save_act.setToolTip("Save Project (Ctrl+S)")
        tb.addAction(save_act)

        tb.addSeparator()

        open_mf4_act = self._action("Open Data File", self._open_mf4_file)
        open_mf4_act.setIcon(st.standardIcon(sp.SP_FileLinkIcon))
        open_mf4_act.setToolTip("Open Data File (Ctrl+F)")
        tb.addAction(open_mf4_act)

        replace_act = self._action("Replace Data File", self._replace_mf4_file)
        replace_act.setIcon(st.standardIcon(sp.SP_BrowserReload))
        replace_act.setToolTip("Replace Data File")
        tb.addAction(replace_act)

        reload_act = self._action("Reload Data", self._reload_all_data)
        reload_act.setIcon(self._make_icon("\u21ba", "#d62728"))
        reload_act.setToolTip("Reload All Data from disk (F5)")
        reload_act.setShortcut("F5")
        tb.addAction(reload_act)

        add_graph_act = self._action("Add Graph", self._add_graph)
        add_graph_act.setIcon(self._make_icon("+", "#2ca02c"))
        add_graph_act.setToolTip("Add Graph (Ctrl+G)")
        tb.addAction(add_graph_act)

        tb.addSeparator()

        self._sync_x_action.setIcon(self._make_icon("\u21c4", "#1f77b4"))
        self._abs_time_action.setIcon(self._make_icon("\u23f1", "#9467bd"))
        self._dark_action.setIcon(self._make_icon("\u25d1", "#555555"))
        tb.addAction(self._sync_x_action)
        tb.addAction(self._abs_time_action)
        tb.addAction(self._dark_action)

    @staticmethod
    def _make_icon(symbol: str, bg_color: str, size: int = 20) -> QIcon:
        """Create a small round icon with *symbol* centred on a *bg_color* circle."""
        from PySide6.QtGui import QFont
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(bg_color)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.setPen(QColor("white"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(size - 7)
        painter.setFont(font)
        painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, symbol)
        painter.end()
        return QIcon(px)

    def _action(self, text: str, slot, shortcut: str = "") -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        return act

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def _new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._mf4_reader.close_all()
        self._project = ProjectConfig()
        self._project_path = None
        self._rebuild_graphs()
        self._set_dirty(False)
        self._refresh_signal_list()

    def _open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            filter=f"GraphMF4 Project (*{PROJECT_FILE_EXTENSION});;All Files (*)",
        )
        if path:
            self.open_project_from_path(path)

    def open_project_from_path(self, path: str) -> None:
        """Public entry point used by main.py for command-line file argument."""
        try:
            self._mf4_reader.close_all()
            project = ProjectConfig.load(path)

            # Collect every MF4 path the project references (project list + channel configs)
            all_paths: set[str] = set(project.mf4_files)
            for graph in project.graphs:
                for ch in graph.channels:
                    all_paths.add(ch.file_path)

            missing = sorted(p for p in all_paths if not Path(p).is_file())
            relocations: dict[str, str] = {}

            if missing:
                from ui.missing_files_dialog import MissingFilesDialog
                dlg = MissingFilesDialog(
                    missing, parent=self, start_dir=str(Path(path).parent)
                )
                if not dlg.exec():   # user chose "Cancel (abort load)"
                    return
                relocations = dlg.relocations()
                if relocations:
                    self._apply_relocations(project, relocations)

            self._project = project
            self._project_path = Path(path)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.statusBar().showMessage("Loading project\u2026", 0)
            try:
                self._rebuild_graphs()
            finally:
                QApplication.restoreOverrideCursor()
            # Sync global Clock toggle from the loaded project (use first graph's mode)
            if project.graphs:
                abs_mode = project.graphs[0].x_axis_mode == "absolute"
                self._abs_time = abs_mode
                self._abs_time_action.blockSignals(True)
                self._abs_time_action.setChecked(abs_mode)
                self._abs_time_action.blockSignals(False)
            # Mark dirty only when paths were actually changed by relocation
            self._set_dirty(bool(relocations))
            self._add_to_recent(path)
            self.statusBar().showMessage(f"Loaded: {path}", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open project:\n{exc}")

    def _save_project(self) -> None:
        if self._project_path is None:
            self._save_project_as()
        else:
            self._do_save(self._project_path)

    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            filter=f"GraphMF4 Project (*{PROJECT_FILE_EXTENSION});;All Files (*)",
        )
        if path:
            self._do_save(Path(path))

    def _do_save(self, path: Path) -> None:
        try:
            self._sync_configs_from_widgets()
            self._project.save(path)
            self._project_path = path
            self._set_dirty(False)
            self._add_to_recent(path)
            self.statusBar().showMessage(f"Saved: {path}", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save project:\n{exc}")

    # ------------------------------------------------------------------
    # Recent Projects
    # ------------------------------------------------------------------

    _RECENT_KEY = "recent_projects"
    _RECENT_MAX = 10

    def _load_recent(self) -> list[str]:
        raw = QSettings("GraphMF4", "GraphMF4").value(self._RECENT_KEY, "[]")
        try:
            return [str(p) for p in json.loads(raw)]
        except Exception:
            return []

    def _save_recent(self, paths: list[str]) -> None:
        QSettings("GraphMF4", "GraphMF4").setValue(self._RECENT_KEY, json.dumps(paths))

    def _add_to_recent(self, path: str | Path) -> None:
        p = str(Path(path).resolve())
        recent = [x for x in self._load_recent() if x != p]
        recent.insert(0, p)
        self._save_recent(recent[: self._RECENT_MAX])
        self._build_recent_menu()

    def _build_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = self._load_recent()
        if not recent:
            act = self._recent_menu.addAction("(no recent projects)")
            act.setEnabled(False)
            return
        for path in recent:
            p = Path(path)
            exists = p.is_file()
            label = p.name if exists else f"{p.name}  \u2717"
            act = QAction(label, self)
            act.setToolTip(path)
            act.setStatusTip(path)
            act.setEnabled(exists)
            act.triggered.connect(lambda _checked, pp=path: self.open_project_from_path(pp))
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear_act = QAction("Clear Recent", self)
        clear_act.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_act)

    def _clear_recent(self) -> None:
        self._save_recent([])
        self._build_recent_menu()

    # ------------------------------------------------------------------
    # MF4 file management
    # ------------------------------------------------------------------

    def _open_mf4_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Measurement File(s)",
            filter="Measurement Files (*.mf4 *.MF4 *.mdf *.MDF);;All Files (*)",
        )
        for path in paths:
            if path not in self._project.mf4_files:
                self._load_mf4_async(path)

    def _replace_mf4_file(self) -> None:
        """Replace one MF4 file with another, remapping channel configs in-place."""
        if not self._project.mf4_files:
            QMessageBox.information(
                self, "No MF4 Files", "No MF4 files are loaded in this project."
            )
            return

        dlg = ReplaceFileDialog(self._project.mf4_files, self)
        if not dlg.exec():
            return

        old_path = dlg.old_path()
        new_path = dlg.new_path()
        if not new_path or old_path == new_path:
            return

        # Load channel list from new file (also caches the MDF handle)
        new_channels = None
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            new_channels = self._mf4_reader.get_channel_list(new_path)
        except Exception as exc:
            QMessageBox.critical(
                self, "Error", f"Cannot read replacement file:\n{exc}"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        new_ch_map = {ch.name: ch for ch in new_channels}

        # Remap every ChannelConfig that referenced old_path
        found: list[str] = []
        missing: list[str] = []
        for graph in self._project.graphs:
            to_remove = []
            for ch in graph.channels:
                if ch.file_path != old_path:
                    continue
                if ch.channel_name in new_ch_map:
                    info = new_ch_map[ch.channel_name]
                    ch.file_path = new_path
                    ch.group_index = info.group_index
                    ch.channel_index = info.channel_index
                    if ch.channel_name not in found:
                        found.append(ch.channel_name)
                else:
                    to_remove.append(ch)
                    if ch.channel_name not in missing:
                        missing.append(ch.channel_name)
            for ch in to_remove:
                graph.channels.remove(ch)

        # Update project file list
        if old_path in self._project.mf4_files:
            self._project.mf4_files[
                self._project.mf4_files.index(old_path)
            ] = new_path

        # Unload old file; new file is already cached from get_channel_list
        self._mf4_reader.unload_file(old_path)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._rebuild_graphs()
        finally:
            QApplication.restoreOverrideCursor()

        self._set_dirty(True)
        self._show_replace_log(old_path, new_path, found, missing)

    def _show_replace_log(
        self,
        old_path: str,
        new_path: str,
        found: list[str],
        missing: list[str],
    ) -> None:
        old_name = Path(old_path).name
        new_name = Path(new_path).name
        lines: list[str] = [
            f"Replaced:  {old_name}",
            f"      ↳  {new_name}",
            "",
        ]
        if found:
            lines.append(f"Replaced signals ({len(found)}):")
            for name in found:
                lines.append(f"  ✓  {name}")
        if missing:
            if found:
                lines.append("")
            lines.append(f"Missing signals ({len(missing)}) — removed from graphs:")
            for name in missing:
                lines.append(f"  ✗  {name}")
        if not found and not missing:
            lines.append("No channels in any graph referenced this file.")

        dlg = QDialog(self)
        dlg.setWindowTitle("File Replacement Log")
        dlg.setMinimumSize(520, 360)
        lay = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 9pt;"
        )
        text.setPlainText("\n".join(lines))
        lay.addWidget(text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        dlg.exec()

    def _load_mf4_async(self, path: str) -> None:
        """Open one MF4 file on a worker thread; show a progress dialog while waiting."""
        from ui.loader_thread import MF4LoadThread

        name = Path(path).name
        progress = QProgressDialog(self)
        progress.setWindowTitle("Opening MF4 File")
        progress.setLabelText(f"Loading {name}\u2026")
        progress.setRange(0, 0)          # indeterminate (animated busy bar)
        progress.setCancelButton(None)   # cancelling a partial MDF parse is unsafe
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(400) # only show dialog if loading takes > 400 ms

        thread = MF4LoadThread(path)
        self._active_threads.append(thread)

        def on_done(mdf, resolved_path: str) -> None:
            self._mf4_reader.inject(resolved_path, mdf)
            if path not in self._project.mf4_files:
                self._project.mf4_files.append(path)
            self._set_dirty(True)
            self._refresh_signal_list()
            self.statusBar().showMessage(f"Loaded Data File: {name}", 3000)
            progress.close()
            _cleanup()

        def on_error(msg: str, _path: str) -> None:
            progress.close()
            QMessageBox.critical(self, "Error", f"Failed to open Data File:\n{msg}")
            _cleanup()

        def _cleanup() -> None:
            if thread in self._active_threads:
                self._active_threads.remove(thread)

        thread.load_finished.connect(on_done)
        thread.load_error.connect(on_error)
        thread.start()
        progress.exec()

    # ------------------------------------------------------------------
    # Graph management
    # ------------------------------------------------------------------

    def _add_graph(self) -> None:
        cfg = GraphConfig(
            title=f"Graph {len(self._project.graphs) + 1}",
            x_axis_mode="absolute" if self._abs_time else "relative",
        )
        self._project.graphs.append(cfg)
        widget = self._make_graph_widget(cfg)
        self._graph_widgets.append(widget)
        self._set_dirty(True)

    def _make_graph_widget(self, cfg: GraphConfig) -> GraphWidget:
        widget = GraphWidget(cfg, self._mf4_reader, self)
        widget.request_remove.connect(lambda w=widget: self._remove_graph(w))
        widget.request_add_signals.connect(lambda w=widget: self._open_signal_selector(w))
        widget.config_changed.connect(lambda: self._set_dirty(True))
        widget.x_range_changed.connect(
            lambda xmin, xmax, w=widget: self._on_x_range_changed(w, xmin, xmax)
        )
        widget.cursor_moved.connect(
            lambda x, w=widget: self._on_cursor_moved(w, x)
        )
        widget.delta_cursor_moved.connect(
            lambda x, w=widget: self._on_delta_cursor_moved(w, x)
        )
        widget.channels_changed.connect(
            lambda w=widget: self._on_channels_changed(w)
        )

        sub = QMdiSubWindow()
        sub.setWidget(widget)
        sub.setWindowTitle(cfg.title)
        sub.setAttribute(Qt.WA_DeleteOnClose, False)  # we manage deletion
        sub.resize(700, 450)
        self._mdi_area.addSubWindow(sub)
        sub.show()

        # Restore saved MDI position/size if available
        if cfg.win_geometry and len(cfg.win_geometry) == 4:
            x, y, w, h = cfg.win_geometry
            sub.move(x, y)
            sub.resize(w, h)

        self._widget_to_subwin[widget] = sub
        self._subwin_to_widget[sub] = widget
        sub.installEventFilter(self)

        # Apply current theme to the new widget
        if self._dark_action.isChecked():
            widget.apply_theme(True)

        # Keep MDI title bar in sync with internal title edits
        widget.config_changed.connect(
            lambda w=widget, s=sub: s.setWindowTitle(w._config.title)
        )
        return widget

    def _remove_graph(self, widget: GraphWidget) -> None:
        if widget in self._graph_widgets:
            idx = self._graph_widgets.index(widget)
            self._graph_widgets.remove(widget)
            self._project.graphs.pop(idx)
            sub = self._widget_to_subwin.pop(widget, None)
            if sub:
                self._subwin_to_widget.pop(sub, None)
                sub.deleteLater()
            if self._channel_dock._graph is widget:
                self._channel_dock.set_graph(None)
            self._set_dirty(True)

    def _open_signal_selector(self, graph_widget: GraphWidget) -> None:
        if not self._project.mf4_files:
            QMessageBox.information(
                self,
                "No Data Files",
                "Open a data file first (File → Open Data File…).",
            )
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dlg = SignalSelectorDialog(self._project.mf4_files, self._mf4_reader, self)
        finally:
            QApplication.restoreOverrideCursor()
        if dlg.exec():
            for ch_cfg in dlg.selected_channels():
                graph_widget.add_channel(ch_cfg)
            self._set_dirty(True)

    def _rebuild_graphs(self) -> None:
        for sub in list(self._mdi_area.subWindowList()):
            self._mdi_area.removeSubWindow(sub)
            sub.deleteLater()
        self._graph_widgets.clear()
        self._widget_to_subwin.clear()
        self._subwin_to_widget.clear()

        for cfg in self._project.graphs:
            # Pre-load MF4 files referenced by this graph
            for ch in cfg.channels:
                if not self._mf4_reader.is_loaded(ch.file_path):
                    try:
                        self._mf4_reader.load_file(ch.file_path)
                    except Exception:
                        pass  # Missing files are handled gracefully in GraphWidget
            widget = self._make_graph_widget(cfg)
            self._graph_widgets.append(widget)

        # Auto-arrange only when no window has saved geometry
        if not any(cfg.win_geometry for cfg in self._project.graphs):
            self._arrange_vertical()

        # Dock doesn't receive subWindowActivated reliably during programmatic rebuild —
        # explicitly point it at the first graph (or clear it when project is empty).
        self._channel_dock.set_graph(
            self._graph_widgets[0] if self._graph_widgets else None
        )
        self._refresh_signal_list()

    def _sync_configs_from_widgets(self) -> None:
        """Pull current view state (zoom, legend, MDI geometry) from each widget into the model."""
        for i, widget in enumerate(self._graph_widgets):
            if i < len(self._project.graphs):
                cfg = widget.get_config()
                sub = self._widget_to_subwin.get(widget)
                if sub and not sub.isMaximized() and not sub.isMinimized():
                    pos = sub.pos()
                    size = sub.size()
                    cfg.win_geometry = [pos.x(), pos.y(), size.width(), size.height()]
                self._project.graphs[i] = cfg

    @staticmethod
    def _apply_relocations(project: ProjectConfig, relocations: dict[str, str]) -> None:
        """Update every path reference in *project* according to *relocations* mapping."""
        for old, new in relocations.items():
            if old in project.mf4_files:
                project.mf4_files[project.mf4_files.index(old)] = new
            for graph in project.graphs:
                for ch in graph.channels:
                    if ch.file_path == old:
                        ch.file_path = new

    # ------------------------------------------------------------------
    # MDI window management
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        """Intercept QMdiSubWindow close events so _remove_graph cleans up properly."""
        widget = self._subwin_to_widget.get(obj)
        if widget is not None and event.type() == QEvent.Type.Close:
            self._remove_graph(widget)
            return True   # consumed — _remove_graph handles deletion via deleteLater
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        from ui.signal_list_dock import CHANNEL_MIME_TYPE
        if event.mimeData().hasFormat(CHANNEL_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        from ui.signal_list_dock import CHANNEL_MIME_TYPE, decode_channel_mime_multi
        if event.mimeData().hasFormat(CHANNEL_MIME_TYPE):
            results = decode_channel_mime_multi(event.mimeData())
            if results:
                # Walk up the widget hierarchy from the widget under the cursor
                # to find a GraphWidget — works regardless of MDI coordinate quirks.
                from PySide6.QtWidgets import QApplication
                global_pos = self.mapToGlobal(event.position().toPoint())
                widget_under = QApplication.widgetAt(global_pos)
                target = None
                w = widget_under
                while w is not None:
                    if isinstance(w, GraphWidget):
                        target = w
                        break
                    w = w.parent()

                # Fallbacks: last active graph → first graph → create new
                if target is None:
                    target = self._channel_dock._graph
                if target is None:
                    if not self._graph_widgets:
                        self._add_graph()
                    target = self._graph_widgets[0] if self._graph_widgets else None

                if target is not None:
                    from core.project import ChannelConfig
                    for file_path, channel_name, group_index, channel_index in results:
                        ch_cfg = ChannelConfig(
                            file_path=file_path,
                            channel_name=channel_name,
                            group_index=group_index,
                            channel_index=channel_index,
                        )
                        target.add_channel(ch_cfg)
                    if self._channel_dock._graph is not target:
                        self._channel_dock.set_graph(target)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _arrange_vertical(self) -> None:
        """Stack all subwindows in a single column filling the MDI area width."""
        subs = self._mdi_area.subWindowList()
        if not subs:
            return
        vp = self._mdi_area.viewport()
        area_w = vp.width()
        area_h = vp.height()
        h = max(300, area_h // len(subs))
        for i, sub in enumerate(subs):
            sub.move(0, i * h)
            sub.resize(area_w, h)

    def _arrange_tile(self) -> None:
        """Tile all subwindows in a grid from top-left to bottom-right."""
        subs = self._mdi_area.subWindowList()
        if not subs:
            return
        n = len(subs)
        vp = self._mdi_area.viewport()
        area_w = vp.width()
        area_h = vp.height()
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        w = area_w // cols
        h = area_h // rows
        for i, sub in enumerate(subs):
            col = i % cols
            row = i // cols
            sub.move(col * w, row * h)
            sub.resize(w, h)

    # ------------------------------------------------------------------
    # X-axis sync
    # ------------------------------------------------------------------

    def _on_sync_x_toggled(self, checked: bool) -> None:
        self._x_sync = checked
        if checked and len(self._graph_widgets) > 1:
            # Immediately align all graphs to the first graph's current X range
            xmin, xmax = self._graph_widgets[0].get_x_range()
            for w in self._graph_widgets[1:]:
                w.set_x_range(xmin, xmax)

    def _on_abs_time_toggled(self, checked: bool) -> None:
        """Switch all graphs between relative [s] and absolute wall-clock time X-axis."""
        self._abs_time = checked
        for w in self._graph_widgets:
            w.set_abs_time(checked)

    def _on_x_range_changed(self, source: GraphWidget, xmin: float, xmax: float) -> None:
        """Propagate X range from *source* to all other graphs when sync is active."""
        if not self._x_sync or self._x_syncing:
            return
        self._x_syncing = True
        try:
            for w in self._graph_widgets:
                if w is not source:
                    w.set_x_range(xmin, xmax)
        finally:
            self._x_syncing = False

    def _refresh_signal_list(self) -> None:
        """Sync the Signal Browser dock with the current project's loaded files."""
        self._signal_list_dock.set_files(self._project.mf4_files)

    def _on_signal_requested(self, file_path: str, ch_info) -> None:
        """Add *ch_info* from *file_path* to the currently active graph.

        If no graph exists yet, one is created automatically.
        """
        from core.project import ChannelConfig
        active = self._channel_dock._graph
        if active is None:
            if not self._graph_widgets:
                self._add_graph()
            active = self._graph_widgets[0] if self._graph_widgets else None
        if active is None:
            return
        ch_cfg = ChannelConfig(
            file_path=file_path,
            channel_name=ch_info.name,
            group_index=ch_info.group_index,
            channel_index=ch_info.channel_index,
        )
        active.add_channel(ch_cfg)
        # Dock may not be showing this graph yet (e.g. no MDI click occurred or a
        # new graph was just created) — point it at the active graph explicitly.
        if self._channel_dock._graph is not active:
            self._channel_dock.set_graph(active)

    def _on_subwindow_activated(self, sub) -> None:
        """Update Channel Panel to show the newly active graph's channels."""
        widget = self._subwin_to_widget.get(sub) if sub else None
        self._channel_dock.set_graph(widget)

    def _on_channels_changed(self, source: GraphWidget) -> None:
        """Refresh Channel Panel when the active graph's channel list changes."""
        if self._channel_dock._graph is source:
            self._channel_dock.refresh()

    def _on_cursor_moved(self, source: GraphWidget, x: float) -> None:
        """Propagate cursor position from *source* to all other graphs with active cursors."""
        if not self._x_sync or self._cursor_syncing:
            return
        self._cursor_syncing = True
        try:
            for w in self._graph_widgets:
                if w is not source:
                    w.set_cursor_pos(x)
        finally:
            self._cursor_syncing = False

    def _on_delta_cursor_moved(self, source: GraphWidget, x: float) -> None:
        """Propagate delta cursor position from *source* to all other graphs with active delta cursors."""
        if not self._x_sync or self._cursor_syncing:
            return
        self._cursor_syncing = True
        try:
            for w in self._graph_widgets:
                if w is not source:
                    w.set_delta_cursor_pos(x)
        finally:
            self._cursor_syncing = False

    # ------------------------------------------------------------------
    # Dirty state
    # ------------------------------------------------------------------

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_title()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "The project has unsaved changes. Discard them?",
            QMessageBox.Discard | QMessageBox.Cancel,
        )
        return reply == QMessageBox.Discard

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_title(self) -> None:
        name = self._project_path.stem if self._project_path else self._project.name
        dirty_marker = " *" if self._dirty else ""
        self.setWindowTitle(f"GraphMF4 – {name}{dirty_marker}")

    def _show_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=self)
        if dlg.exec():
            self._replot_all_graphs()

    def _replot_all_graphs(self) -> None:
        """Re-plot all channels in every graph (e.g. after settings change)."""
        for widget in self._graph_widgets:
            widget.replot_channels()

    def _reload_all_data(self) -> None:
        """Reload the current project from disk (same as opening it from Recent Projects)."""
        if self._project_path is None:
            QMessageBox.information(
                self,
                "Reload",
                "Save the project first before reloading.",
            )
            return
        self.open_project_from_path(str(self._project_path))

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About GraphMF4",
            "<b>GraphMF4</b><br>Interactive MF4/MDF signal viewer<br><br>"
            "Built with Python, PySide6, pyqtgraph, and asammdf.",
        )

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self, dark: bool) -> None:
        """Toggle between light and dark theme for the whole application."""
        app = QApplication.instance()
        if dark:
            palette = QPalette()
            c = lambda r, g, b: QColor(r, g, b)
            palette.setColor(QPalette.ColorRole.Window,          c(45,  45,  45))
            palette.setColor(QPalette.ColorRole.WindowText,      c(220, 220, 220))
            palette.setColor(QPalette.ColorRole.Base,            c(30,  30,  30))
            palette.setColor(QPalette.ColorRole.AlternateBase,   c(45,  45,  45))
            palette.setColor(QPalette.ColorRole.ToolTipBase,     c(45,  45,  45))
            palette.setColor(QPalette.ColorRole.ToolTipText,     c(220, 220, 220))
            palette.setColor(QPalette.ColorRole.Text,            c(220, 220, 220))
            palette.setColor(QPalette.ColorRole.Button,          c(55,  55,  55))
            palette.setColor(QPalette.ColorRole.ButtonText,      c(220, 220, 220))
            palette.setColor(QPalette.ColorRole.BrightText,      c(255, 80,  80))
            palette.setColor(QPalette.ColorRole.Link,            c(70,  150, 230))
            palette.setColor(QPalette.ColorRole.Highlight,       c(42,  130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, c(255, 255, 255))
            app.setPalette(palette)
            self._mdi_area.setBackground(QColor(30, 30, 30))
        else:
            app.setPalette(app.style().standardPalette())
            self._mdi_area.setBackground(Qt.lightGray)
        for widget in self._graph_widgets:
            widget.apply_theme(dark)

    # ------------------------------------------------------------------
    # Window state persistence
    # ------------------------------------------------------------------

    def _restore_window_state(self) -> None:
        settings = QSettings("GraphMF4", "GraphMF4")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        # Restore sync-X toggle (must happen after _sync_x_action is created)
        if settings.value("sync_x", False, type=bool):
            self._sync_x_action.setChecked(True)
        if settings.value("abs_time", False, type=bool):
            self._abs_time_action.setChecked(True)
        # Restore dark theme (toggled signal calls _apply_theme automatically)
        if settings.value("dark_theme", False, type=bool):
            self._dark_action.setChecked(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        settings = QSettings("GraphMF4", "GraphMF4")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("sync_x", self._x_sync)
        settings.setValue("abs_time", self._abs_time)
        settings.setValue("dark_theme", self._dark_action.isChecked())
        self._mf4_reader.close_all()
        super().closeEvent(event)
