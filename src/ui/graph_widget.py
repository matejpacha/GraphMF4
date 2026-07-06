"""Single graph panel widget.

Contains:
  - A pyqtgraph PlotWidget (zoom/pan via mouse wheel and drag built-in)
  - A header bar with title, legend toggle, "Add Signals", export, and remove buttons
  - Logic to plot ChannelConfig entries and sync view state back to GraphConfig
"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QRectF, Qt, QSettings, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.mf4_reader import MF4Reader
from core.project import ChannelConfig, DEFAULT_COLORS, GraphConfig
from utils.downsample import lttb, DOWNSAMPLE_THRESHOLD, DOWNSAMPLE_TARGET
from ui.settings_dialog import load_downsample_settings

_log = logging.getLogger(__name__)


class _CtrlZoomViewBox(pg.ViewBox):
    """ViewBox that keeps normal left-drag pan, Ctrl+left-drag rubber-band zoom,
    and Shift+left-click moves the XY crosshair to the clicked position."""

    def __init__(self, graph_widget=None, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._graph_widget = graph_widget

    def mouseClickEvent(self, ev) -> None:  # type: ignore[override]
        if (
            self._graph_widget is not None
            and self._graph_widget._config.xy_mode
            and self._graph_widget._cursor_line is not None
            and ev.button() == Qt.MouseButton.LeftButton
            and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            pos = self.mapSceneToView(ev.scenePos())
            self._graph_widget._move_xy_crosshair(pos.x(), pos.y())
            ev.accept()
        else:
            super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None):  # type: ignore[override]
        if ev.button() == Qt.MouseButton.LeftButton and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            ev.accept()
            if ev.isFinish():
                self.rbScaleBox.hide()
                r = QRectF(
                    pg.Point(ev.buttonDownPos(ev.button())),
                    pg.Point(ev.pos()),
                ).normalized()
                r = self.childGroup.mapRectFromParent(r)
                self.showAxRect(r)
                self.axHistoryPointer += 1
                self.axHistory = self.axHistory[: self.axHistoryPointer] + [r]
            else:
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
        else:
            super().mouseDragEvent(ev, axis=axis)


class _TimeAxisItem(pg.AxisItem):
    """AxisItem that shows relative seconds *or* local wall-clock time (HH:MM:SS)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._abs_mode: bool = False

    def set_abs_mode(self, enabled: bool) -> None:
        self._abs_mode = enabled
        self.picture = None  # invalidate cached paint
        self.update()

    def tickStrings(self, values, scale, spacing):  # type: ignore[override]
        if not self._abs_mode:
            return super().tickStrings(values, scale, spacing)
        result = []
        for v in values:
            try:
                dt = datetime.datetime.fromtimestamp(v)
                result.append(dt.strftime("%H:%M:%S"))
            except (OSError, OverflowError, ValueError):
                result.append("")
        return result


class GraphWidget(QWidget):
    """A self-contained graph panel backed by a GraphConfig."""

    request_remove = Signal()
    request_add_signals = Signal()
    config_changed = Signal()
    channels_changed = Signal()          # emitted when channel list is structurally modified
    x_range_changed = Signal(float, float)
    cursor_moved = Signal(float)
    delta_cursor_moved = Signal(float)

    def __init__(self, config: GraphConfig, reader: MF4Reader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._reader = reader
        self._color_idx = len(config.channels)   # start after already-assigned colors
        self._block_x_signal: bool = False       # prevents re-entrant X-sync loops
        self._block_cursor_signal: bool = False  # prevents re-entrant cursor-sync loops
        self._in_cursor_update: bool = False     # prevents sigRangeChanged feedback loop
        self._dark_mode: bool = False             # tracks current theme for cursor labels
        self._cursor_line: pg.InfiniteLine | None = None
        self._cursor_h_line: pg.InfiniteLine | None = None   # horizontal crosshair (XY mode)
        self._cursor_labels: dict[str, pg.TextItem] = {}
        self._delta_cursor_line: pg.InfiniteLine | None = None
        self._delta_labels: dict[str, pg.TextItem] = {}
        self._block_delta_signal: bool = False
        self._signal_labels: dict[str, pg.TextItem] = {}
        self._in_signal_label_update: bool = False
        self._file_epochs: dict[str, float] = {}  # file_path -> Unix epoch of start time

        # Maps "file_path::channel_name::group_idx" -> PlotDataItem
        self._plot_items: dict[str, pg.PlotDataItem] = {}

        self._setup_ui()
        self._load_channels()
        self.setMinimumHeight(180)   # MDI subwindow lower bound: header + minimal plot

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # ---- header ----
        header = QHBoxLayout()

        # Title: QLabel (normal) + QLineEdit (rename mode) in a QStackedWidget
        self._title_stack = QStackedWidget()
        self._title_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._title_label = QLabel(self._config.title)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._title_label.setToolTip("Double-click to rename")
        self._title_label.installEventFilter(self)

        self._title_edit = QLineEdit(self._config.title)
        self._title_edit.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._title_edit.setToolTip("Press Enter to confirm, Escape to cancel")
        self._title_edit.editingFinished.connect(self._finish_rename)
        self._title_edit.installEventFilter(self)

        self._title_stack.addWidget(self._title_label)   # index 0 — normal
        self._title_stack.addWidget(self._title_edit)    # index 1 — editing
        self._title_stack.setCurrentIndex(0)

        header.addWidget(self._title_stack)
        header.addStretch()

        self._legend_btn = QPushButton("Legend")
        self._legend_btn.setCheckable(True)
        self._legend_btn.setChecked(self._config.show_legend)
        self._legend_btn.setMaximumWidth(70)
        self._legend_btn.setToolTip("Toggle legend visibility")
        self._legend_btn.toggled.connect(self._on_legend_toggled)
        header.addWidget(self._legend_btn)

        self._labels_btn = QPushButton("Labels")
        self._labels_btn.setCheckable(True)
        self._labels_btn.setChecked(self._config.show_labels)
        self._labels_btn.setMaximumWidth(60)
        self._labels_btn.setToolTip(
            "Show signal name labels on the left edge of the plot area"
        )
        self._labels_btn.toggled.connect(self._on_labels_toggled)
        header.addWidget(self._labels_btn)

        self._xy_btn = QPushButton("X/Y")
        self._xy_btn.setCheckable(True)
        self._xy_btn.setChecked(self._config.xy_mode)
        self._xy_btn.setMaximumWidth(40)
        self._xy_btn.setToolTip(
            "Toggle X vs Y mode \u2014 plot signals against a chosen channel instead of time"
        )
        self._xy_btn.toggled.connect(self._on_xy_toggled)
        header.addWidget(self._xy_btn)

        self._xy_combo = QComboBox()
        self._xy_combo.setMaximumWidth(160)
        self._xy_combo.setToolTip("Channel to use as the X axis")
        self._xy_combo.currentIndexChanged.connect(self._on_xy_channel_changed)
        self._xy_combo.setVisible(self._config.xy_mode)
        header.addWidget(self._xy_combo)

        self._cursor_btn = QPushButton("Cursor")
        self._cursor_btn.setCheckable(True)
        self._cursor_btn.setMaximumWidth(65)
        self._cursor_btn.setToolTip("Toggle readout cursor — drag the vertical line to read signal values")
        self._cursor_btn.toggled.connect(self._on_cursor_toggled)
        header.addWidget(self._cursor_btn)

        self._delta_cursor_btn = QPushButton("Δ Cursor")
        self._delta_cursor_btn.setCheckable(True)
        self._delta_cursor_btn.setMaximumWidth(75)
        self._delta_cursor_btn.setEnabled(False)
        self._delta_cursor_btn.setToolTip(
            "Toggle delta cursor — shows Δt and ΔY differences between the two cursor positions"
        )
        self._delta_cursor_btn.toggled.connect(self._on_delta_cursor_toggled)
        header.addWidget(self._delta_cursor_btn)

        add_btn = QPushButton("+ Signals")
        add_btn.setMaximumWidth(85)
        add_btn.setToolTip("Add signals from an MF4 file")
        add_btn.clicked.connect(self.request_add_signals)
        header.addWidget(add_btn)

        export_btn = QPushButton("Export…")
        export_btn.setMaximumWidth(75)
        export_btn.setToolTip("Export graph to bitmap")
        export_btn.clicked.connect(self._export_image)
        header.addWidget(export_btn)

        remove_btn = QPushButton("✕")
        remove_btn.setMaximumWidth(28)
        remove_btn.setToolTip("Remove this graph")
        remove_btn.clicked.connect(self.request_remove)
        header.addWidget(remove_btn)

        layout.addLayout(header)

        # ---- plot ----
        pg.setConfigOptions(antialias=True)
        self._time_axis = _TimeAxisItem(orientation="bottom")
        abs_mode = self._config.x_axis_mode == "absolute"
        # In XY mode the axis shows channel values — keep it in raw (non-time) mode
        self._time_axis.set_abs_mode(abs_mode and not self._config.xy_mode)
        self._plot_widget = pg.PlotWidget(
            viewBox=_CtrlZoomViewBox(self),
            background="w",
            axisItems={"bottom": self._time_axis},
        )
        self._plot_widget.setToolTip(
            "Scroll = zoom  |  Left drag = pan  |  Ctrl+left drag = zoom to region\n"
            "XY mode: Shift+click = move crosshair to cursor position"
        )
        self._plot_widget.setMinimumHeight(120)
        self._plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._plot_widget.setLabel("bottom", "Time" if abs_mode else self._config.x_label)

        if self._config.y_label:
            self._plot_widget.setLabel("left", self._config.y_label)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.25)

        # Legend
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        self._legend.setVisible(self._config.show_legend)

        # Restore saved view range
        if self._config.x_range:
            self._plot_widget.setXRange(*self._config.x_range, padding=0)
        if self._config.y_range:
            self._plot_widget.setYRange(*self._config.y_range, padding=0)

        # Emit config_changed when the user pans/zooms so dirty state is tracked
        self._plot_widget.sigRangeChanged.connect(lambda: self.config_changed.emit())
        # Emit x_range_changed specifically for X-axis sync (guarded to avoid loops)
        self._plot_widget.getViewBox().sigXRangeChanged.connect(self._on_vb_x_range_changed)

        layout.addWidget(self._plot_widget)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def apply_theme(self, dark: bool) -> None:
        """Switch the plot and channel panel between light and dark appearance."""
        self._dark_mode = dark
        if dark:
            plot_bg = "#1e1e1e"
            axis_color = QColor(200, 200, 200)
            panel_bg = "#2a2a2a"
            title_color = "#e0e0e0"
        else:
            plot_bg = "w"
            axis_color = QColor(0, 0, 0)
            panel_bg = "#f8f8f8"
            title_color = "#000000"
        self._plot_widget.setBackground(plot_bg)
        for axis_name in ("bottom", "left", "top", "right"):
            ax = self._plot_widget.getAxis(axis_name)
            pen = pg.mkPen(axis_color)
            ax.setPen(pen)
            ax.setTextPen(pen)
        self._title_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {title_color};"
        )
        self._title_edit.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {title_color};"
        )
        # Update cursor line pen if active
        if self._cursor_line is not None:
            _cursor_pen = pg.mkPen("#ff9944" if dark else "#cc4400", width=1.5, style=Qt.PenStyle.DashLine)
            self._cursor_line.setPen(_cursor_pen)
            if self._cursor_h_line is not None:
                self._cursor_h_line.setPen(_cursor_pen)
        if self._delta_cursor_line is not None:
            self._delta_cursor_line.setPen(pg.mkPen(
                "#44aaff" if dark else "#0055aa", width=1.5, style=Qt.PenStyle.DashLine
            ))
        self._maybe_update_signal_labels()

    # ------------------------------------------------------------------
    # Cursor (value readout)
    # ------------------------------------------------------------------

    def _on_cursor_toggled(self, checked: bool) -> None:
        if checked:
            vr = self._plot_widget.viewRange()
            x_center = (vr[0][0] + vr[0][1]) / 2
            cursor_pen = pg.mkPen("#cc4400", width=1.5, style=Qt.PenStyle.DashLine)
            self._cursor_line = pg.InfiniteLine(
                pos=x_center, angle=90, movable=True, pen=cursor_pen,
            )
            self._cursor_line.sigPositionChanged.connect(self._update_cursor_labels)
            self._cursor_line.sigPositionChanged.connect(self._on_cursor_pos_changed)
            self._plot_widget.sigRangeChanged.connect(self._update_cursor_labels)
            self._plot_widget.addItem(self._cursor_line, ignoreBounds=True)
            if self._config.xy_mode:
                y_center = (vr[1][0] + vr[1][1]) / 2
                self._cursor_h_line = pg.InfiniteLine(
                    pos=y_center, angle=0, movable=True, pen=cursor_pen,
                )
                self._cursor_h_line.sigPositionChanged.connect(self._update_cursor_labels)
                self._plot_widget.addItem(self._cursor_h_line, ignoreBounds=True)
            self._delta_cursor_btn.setEnabled(not self._config.xy_mode)
            self._update_cursor_labels()
        else:
            # Deactivate delta cursor first (before removing primary)
            if self._delta_cursor_btn.isChecked():
                self._delta_cursor_btn.setChecked(False)
            self._delta_cursor_btn.setEnabled(False)
            if self._cursor_h_line is not None:
                self._plot_widget.removeItem(self._cursor_h_line)
                self._cursor_h_line = None
            if self._cursor_line is not None:
                self._plot_widget.removeItem(self._cursor_line)
                self._cursor_line = None
            try:
                self._plot_widget.sigRangeChanged.disconnect(self._update_cursor_labels)
            except RuntimeError:
                pass
            for lbl in self._cursor_labels.values():
                lbl.hide()
                self._plot_widget.removeItem(lbl)
            self._cursor_labels.clear()

    def _on_cursor_pos_changed(self, line: pg.InfiniteLine) -> None:
        """Forward cursor position to MainWindow for optional sync across graphs."""
        if not self._block_cursor_signal and not self._config.xy_mode:
            self.cursor_moved.emit(line.value())

    def set_cursor_pos(self, x: float) -> None:
        """Move the readout cursor to *x* without re-emitting cursor_moved."""
        if self._cursor_line is None or self._config.xy_mode:
            return
        self._block_cursor_signal = True
        try:
            self._cursor_line.setPos(x)
        finally:
            self._block_cursor_signal = False

    def _on_delta_cursor_toggled(self, checked: bool) -> None:
        if checked:
            if self._cursor_line is None:
                return
            vr = self._plot_widget.viewRange()

            # Place delta cursor between primary cursor and right edge of view
            x_start = (self._cursor_line.value() + vr[0][1]) / 2
            self._delta_cursor_line = pg.InfiniteLine(
                pos=x_start, angle=90, movable=True,
                pen=pg.mkPen("#0055aa", width=1.5, style=Qt.PenStyle.DashLine),
            )
            self._delta_cursor_line.sigPositionChanged.connect(self._update_cursor_labels)
            self._delta_cursor_line.sigPositionChanged.connect(self._on_delta_cursor_pos_changed)
            self._plot_widget.addItem(self._delta_cursor_line, ignoreBounds=True)
            self._update_cursor_labels()
        else:
            if self._delta_cursor_line is not None:
                self._plot_widget.removeItem(self._delta_cursor_line)
                self._delta_cursor_line = None
            for lbl in self._delta_labels.values():
                lbl.hide()
                self._plot_widget.removeItem(lbl)
            self._delta_labels.clear()
            # Refresh primary labels (they no longer need to coexist with delta labels)
            self._update_cursor_labels()

    def _on_delta_cursor_pos_changed(self, line: pg.InfiniteLine) -> None:
        """Forward delta cursor position to MainWindow for optional sync across graphs."""
        if not self._block_delta_signal and not self._config.xy_mode:
            self.delta_cursor_moved.emit(line.value())

    def set_delta_cursor_pos(self, x: float) -> None:
        """Move the delta cursor to *x* without re-emitting delta_cursor_moved."""
        if self._delta_cursor_line is None or self._config.xy_mode:
            return
        self._block_delta_signal = True
        try:
            self._delta_cursor_line.setPos(x)
        finally:
            self._block_delta_signal = False

    def _update_cursor_labels(self, *_) -> None:  # *_ absorbs sigRangeChanged args
        if self._cursor_line is None:
            return
        if self._in_cursor_update:
            return
        self._in_cursor_update = True
        try:
            self._do_update_cursor_labels()
            if self._delta_cursor_line is not None:
                self._do_update_delta_labels()
        finally:
            self._in_cursor_update = False

    def _do_update_cursor_labels(self) -> None:
        x: float = float(self._cursor_line.value())  # type: ignore[union-attr]

        # Remove all tracked cursor labels
        for lbl in self._cursor_labels.values():
            lbl.hide()
            self._plot_widget.removeItem(lbl)
        self._cursor_labels.clear()
        self._sweep_orphan_text_items()

        # In XY mode show only axis-position labels (X at bottom, Y on left).
        # Per-channel interpolation is not meaningful since the axes are channel values.
        if self._config.xy_mode:
            self._add_cursor_time_label(x)   # X value at bottom
            if self._cursor_h_line is not None:
                self._add_cursor_y_label(float(self._cursor_h_line.value()))
            return

        # --- Phase 1: collect all intersecting labels -------------------------
        entries: list[tuple[float, str, pg.TextItem]] = []

        for ch_cfg in self._config.channels:
            if not ch_cfg.visible:
                continue
            key = self._channel_key(ch_cfg)
            item = self._plot_items.get(key)
            if item is None:
                continue
            x_data = item.xData
            y_data = item.yData
            if x_data is None or y_data is None or len(x_data) < 2:
                continue
            if x < x_data[0] or x > x_data[-1]:
                continue

            y_val = float(np.interp(x, x_data, y_data))

            # Extract unit from item name (format: "label [unit]")
            item_name = item.name() or ""
            unit_str = ""
            bracket = item_name.rfind("[")
            if bracket >= 0 and item_name.endswith("]"):
                unit_str = item_name[bracket + 1:-1]

            label_text = f"{y_val:.5g}"
            if unit_str:
                label_text += f" {unit_str}"

            color = QColor(ch_cfg.color)
            fill = QColor(color)
            fill.setAlpha(50)

            text_item = pg.TextItem(
                text=label_text,
                color=color,
                anchor=(0, 0.5),
                fill=pg.mkBrush(fill),
            )
            entries.append((y_val, key, text_item))

        if not entries:
            # No signal intersections — still show the time label
            self._add_cursor_time_label(x)
            return

        # --- Phase 2: resolve vertical overlap --------------------------------
        # Sort highest-on-screen first (descending y in data coords)
        entries.sort(key=lambda e: e[0], reverse=True)

        # Convert ~18 px label height to data-coordinate units
        vr = self._plot_widget.viewRange()
        view_h_px = max(self._plot_widget.height(), 1)
        min_gap = 18.0 * (vr[1][1] - vr[1][0]) / view_h_px

        adjusted_y: list[float] = [entries[0][0]]
        for i in range(1, len(entries)):
            prev_y = adjusted_y[i - 1]
            curr_y = entries[i][0]
            if prev_y - curr_y < min_gap:
                curr_y = prev_y - min_gap
            adjusted_y.append(curr_y)

        # --- Phase 3: place labels at (possibly adjusted) positions -----------
        for i, (_, key, text_item) in enumerate(entries):
            text_item.setPos(x, adjusted_y[i])
            self._plot_widget.addItem(text_item, ignoreBounds=True)  # type: ignore[call-arg]
            self._cursor_labels[key] = text_item

        # --- Phase 4: time label at the bottom of the view -------------------
        self._add_cursor_time_label(x)

    def _add_cursor_time_label(self, x: float) -> None:
        """Add a formatted time/X TextItem at the bottom of the view for cursor position *x*."""
        if self._config.xy_mode:
            # X axis is a channel value, not time
            time_str = f"x = {x:.5g}"
        elif self._config.x_axis_mode == "absolute":
            try:
                dt = datetime.datetime.fromtimestamp(x)
                time_str = dt.strftime("%H:%M:%S.%f")[:-3]   # millisecond precision
            except (OSError, OverflowError, ValueError):
                time_str = ""
        else:
            time_str = f"{x:.3f} s"

        if not time_str:
            return

        vr = self._plot_widget.viewRange()
        y_bottom = vr[1][0]
        if self._dark_mode:
            txt_color = QColor(220, 220, 220)
            fill_color = QColor(50, 50, 50, 200)
        else:
            txt_color = QColor(60, 60, 60)
            fill_color = QColor(240, 240, 240, 200)
        time_item = pg.TextItem(
            text=time_str,
            color=txt_color,
            anchor=(0.5, 1.0),   # centred on X, grows upward from y_bottom
            fill=pg.mkBrush(fill_color),
        )
        time_item.setPos(x, y_bottom)
        # ignoreBounds=True prevents pyqtgraph from expanding Y auto-range to include
        # this label — without it, placing the item at y_bottom triggers sigRangeChanged
        # which re-invokes _update_cursor_labels in an infinite downward-scrolling loop.
        self._plot_widget.addItem(time_item, ignoreBounds=True)  # type: ignore[call-arg]
        self._cursor_labels["__time__"] = time_item

    def _add_cursor_y_label(self, y: float) -> None:
        """Add a Y-axis value label at the left edge of the view (XY mode crosshair)."""
        vr = self._plot_widget.viewRange()
        x_left = vr[0][0]
        if self._dark_mode:
            txt_color = QColor(220, 220, 220)
            fill_color = QColor(50, 50, 50, 200)
        else:
            txt_color = QColor(60, 60, 60)
            fill_color = QColor(240, 240, 240, 200)
        y_item = pg.TextItem(
            text=f"y = {y:.5g}",
            color=txt_color,
            anchor=(0.0, 0.5),
            fill=pg.mkBrush(fill_color),
        )
        y_item.setPos(x_left, y)
        self._plot_widget.addItem(y_item, ignoreBounds=True)  # type: ignore[call-arg]
        self._cursor_labels["__y__"] = y_item

    def _move_xy_crosshair(self, x: float, y: float) -> None:
        """Teleport the XY crosshair to data position (x, y) on Shift+click."""
        if self._cursor_line is not None:
            self._block_cursor_signal = True
            try:
                self._cursor_line.setPos(x)
            finally:
                self._block_cursor_signal = False
        if self._cursor_h_line is not None:
            self._cursor_h_line.setPos(y)
        self._update_cursor_labels()

    def _sweep_orphan_text_items(self) -> None:
        """Remove any pg.TextItem in the scene not tracked by any label dict.

        Called as a failsafe at the start of each cursor label update so that
        items leaked by previous incomplete signal/cursor label cycles are cleaned
        up before new labels are added.
        """
        scene = self._plot_widget.scene()
        if scene is None:
            return
        tracked = (
            set(id(v) for v in self._cursor_labels.values())
            | set(id(v) for v in self._delta_labels.values())
            | set(id(v) for v in self._signal_labels.values())
        )
        orphans = [
            item for item in scene.items()
            if isinstance(item, pg.TextItem) and id(item) not in tracked
        ]
        if orphans:
            _log.warning("[CURSOR] sweeping %d orphan TextItem(s) from scene", len(orphans))
            for item in orphans:
                item.hide()
                self._plot_widget.removeItem(item)

    # ------------------------------------------------------------------
    # Delta cursor labels
    # ------------------------------------------------------------------

    def _do_update_delta_labels(self) -> None:
        """Draw ΔY labels at the delta cursor position plus a Δt label at the bottom."""
        # Remove previous delta labels
        for lbl in self._delta_labels.values():
            lbl.hide()
            self._plot_widget.removeItem(lbl)
        self._delta_labels.clear()

        if self._delta_cursor_line is None or self._cursor_line is None:
            return

        x_delta: float = float(self._delta_cursor_line.value())  # type: ignore[union-attr]
        x_primary: float = float(self._cursor_line.value())  # type: ignore[union-attr]
        dt: float = x_delta - x_primary

        # --- Phase 1: collect ΔY for each visible channel --------------------
        entries: list[tuple[float, str, pg.TextItem]] = []

        for ch_cfg in self._config.channels:
            if not ch_cfg.visible:
                continue
            key = self._channel_key(ch_cfg)
            item = self._plot_items.get(key)
            if item is None:
                continue
            x_data = item.xData
            y_data = item.yData
            if x_data is None or y_data is None or len(x_data) < 2:
                continue
            if not (x_data[0] <= x_delta <= x_data[-1]):
                continue

            y_at_delta = float(np.interp(x_delta, x_data, y_data))
            in_primary_range = x_data[0] <= x_primary <= x_data[-1]
            y_at_primary = float(np.interp(x_primary, x_data, y_data)) if in_primary_range else None

            # Extract unit from item name (format: "label [unit]")
            item_name = item.name() or ""
            unit_str = ""
            bracket = item_name.rfind("[")
            if bracket >= 0 and item_name.endswith("]"):
                unit_str = item_name[bracket + 1:-1]

            if y_at_primary is not None:
                dy = y_at_delta - y_at_primary
                label_text = f"Δ{dy:+.5g}"
            else:
                label_text = f"~{y_at_delta:.5g}"
            if unit_str:
                label_text += f" {unit_str}"

            color = QColor(ch_cfg.color)
            fill = QColor(color)
            fill.setAlpha(50)
            text_item = pg.TextItem(
                text=label_text,
                color=color,
                anchor=(0, 0.5),
                fill=pg.mkBrush(fill),
            )
            entries.append((y_at_delta, key, text_item))

        if not entries:
            self._add_delta_time_label(x_delta, dt)
            return

        # --- Phase 2: resolve vertical overlap --------------------------------
        entries.sort(key=lambda e: e[0], reverse=True)
        vr = self._plot_widget.viewRange()
        view_h_px = max(self._plot_widget.height(), 1)
        min_gap = 18.0 * (vr[1][1] - vr[1][0]) / view_h_px

        adjusted_y: list[float] = [entries[0][0]]
        for i in range(1, len(entries)):
            prev_y = adjusted_y[i - 1]
            curr_y = entries[i][0]
            if prev_y - curr_y < min_gap:
                curr_y = prev_y - min_gap
            adjusted_y.append(curr_y)

        # --- Phase 3: place labels at delta cursor position ------------------
        for i, (_, key, text_item) in enumerate(entries):
            text_item.setPos(x_delta, adjusted_y[i])
            self._plot_widget.addItem(text_item, ignoreBounds=True)  # type: ignore[call-arg]
            self._delta_labels[key] = text_item

        # --- Phase 4: Δt label at the bottom of the view --------------------
        self._add_delta_time_label(x_delta, dt)

    def _add_delta_time_label(self, x_delta: float, dt: float) -> None:
        """Add a Δt TextItem at the bottom of the view near the delta cursor."""
        dt_str = f"Δt = {dt:+.3f} s"

        vr = self._plot_widget.viewRange()
        y_bottom = vr[1][0]
        if self._dark_mode:
            txt_color = QColor(150, 200, 255)
            fill_color = QColor(0, 50, 100, 200)
        else:
            txt_color = QColor(0, 50, 150)
            fill_color = QColor(210, 230, 255, 200)
        dt_item = pg.TextItem(
            text=dt_str,
            color=txt_color,
            anchor=(0.5, 1.0),
            fill=pg.mkBrush(fill_color),
        )
        dt_item.setPos(x_delta, y_bottom)
        self._plot_widget.addItem(dt_item, ignoreBounds=True)  # type: ignore[call-arg]
        self._delta_labels["__dt__"] = dt_item

    # ------------------------------------------------------------------
    # Signal name labels
    # ------------------------------------------------------------------

    def _on_labels_toggled(self, checked: bool) -> None:
        self._config.show_labels = checked
        self.config_changed.emit()
        if checked:
            self._plot_widget.sigRangeChanged.connect(self._update_signal_labels)
            self._update_signal_labels()
        else:
            try:
                self._plot_widget.sigRangeChanged.disconnect(self._update_signal_labels)
            except RuntimeError:
                pass
            for lbl in self._signal_labels.values():
                lbl.hide()
                self._plot_widget.removeItem(lbl)
            self._signal_labels.clear()

    def _update_signal_labels(self, *_) -> None:
        if not self._labels_btn.isChecked():
            return
        if self._in_signal_label_update:
            return
        self._in_signal_label_update = True
        try:
            self._do_update_signal_labels()
        finally:
            self._in_signal_label_update = False

    def _do_update_signal_labels(self) -> None:
        """Place one TextItem per visible channel at the left edge of the current view."""
        for lbl in self._signal_labels.values():
            lbl.hide()
            self._plot_widget.removeItem(lbl)
        self._signal_labels.clear()

        vr = self._plot_widget.viewRange()
        x_left = vr[0][0]
        y_min, y_max = vr[1][0], vr[1][1]

        # --- Phase 1: collect entries ----------------------------------------
        entries: list[tuple[float, str, pg.TextItem]] = []

        for ch_cfg in self._config.channels:
            if not ch_cfg.visible:
                continue
            key = self._channel_key(ch_cfg)
            item = self._plot_items.get(key)
            if item is None:
                continue
            x_data = item.xData
            y_data = item.yData
            if x_data is None or y_data is None or len(x_data) < 2:
                continue
            # Skip channels entirely outside the visible X range
            if x_left > x_data[-1] or vr[0][1] < x_data[0]:
                continue

            x_query = max(float(x_data[0]), x_left)
            y_val = float(np.interp(x_query, x_data, y_data))

            label_text = ch_cfg.label or ch_cfg.channel_name
            color = QColor(ch_cfg.color)
            fill_color = QColor(30, 30, 30, 180) if self._dark_mode else QColor(255, 255, 255, 180)
            text_item = pg.TextItem(
                text=label_text,
                color=color,
                anchor=(0, 0.5),
                fill=pg.mkBrush(fill_color),
            )
            entries.append((y_val, key, text_item))

        if not entries:
            return

        # --- Phase 2: overlap prevention (same algorithm as cursor labels) ----
        entries.sort(key=lambda e: e[0], reverse=True)
        view_h_px = max(self._plot_widget.height(), 1)
        min_gap = 18.0 * (y_max - y_min) / view_h_px

        adjusted_y: list[float] = [entries[0][0]]
        for i in range(1, len(entries)):
            prev_y = adjusted_y[i - 1]
            curr_y = entries[i][0]
            if prev_y - curr_y < min_gap:
                curr_y = prev_y - min_gap
            adjusted_y.append(curr_y)

        # --- Phase 3: place labels -------------------------------------------
        for i, (_, key, text_item) in enumerate(entries):
            text_item.setPos(x_left, adjusted_y[i])
            self._plot_widget.addItem(text_item, ignoreBounds=True)  # type: ignore[call-arg]
            self._signal_labels[key] = text_item

    def _maybe_update_signal_labels(self) -> None:
        """Refresh signal labels only when the Labels toggle is active."""
        if self._labels_btn.isChecked():
            self._update_signal_labels()

    def _on_stack_digital_clicked(self) -> None:
        """Auto-assign y_scale/y_offset so visible digital channels stack in equal lanes."""
        digital_chs = [ch for ch in self._config.channels if ch.digital and ch.visible]
        if not digital_chs:
            return

        _LANE_HEIGHT = 0.8    # waveform height in output Y units
        _LANE_SPACING = 1.2   # centre-to-centre spacing between lanes

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for row, ch_cfg in enumerate(digital_chs):
                try:
                    sig = self._reader.read_signal(
                        ch_cfg.file_path, ch_cfg.channel_name,
                        ch_cfg.group_index, ch_cfg.channel_index,
                    )
                    raw = sig.samples
                    raw_min = float(raw.min()) if len(raw) > 0 else 0.0
                    raw_max = float(raw.max()) if len(raw) > 0 else 1.0
                    span = raw_max - raw_min
                    if span < 1e-9:           # constant signal — treat as boolean
                        ch_cfg.y_scale = _LANE_HEIGHT
                        ch_cfg.y_offset = float(row) * _LANE_SPACING
                    else:
                        ch_cfg.y_scale = _LANE_HEIGHT / span
                        ch_cfg.y_offset = float(row) * _LANE_SPACING - raw_min * ch_cfg.y_scale
                    key = self._channel_key(ch_cfg)
                    old_item = self._plot_items.pop(key, None)
                    if old_item is not None:
                        self._legend.removeItem(old_item)
                        self._plot_widget.removeItem(old_item)
                    self._plot_channel(ch_cfg)
                except Exception:
                    _log.exception("Stack digital: failed for '%s'", ch_cfg.channel_name)
        finally:
            QApplication.restoreOverrideCursor()

        self._maybe_update_signal_labels()
        self.channels_changed.emit()
        self._plot_widget.autoRange()
        self.config_changed.emit()

    # ------------------------------------------------------------------
    # Channel plotting
    # ------------------------------------------------------------------

    def _load_channels(self) -> None:
        for ch_cfg in self._config.channels:
            # Ensure color is set for channels loaded from older project files
            if not ch_cfg.color:
                ch_cfg.color = self._next_color()
                self._color_idx += 1
            self._plot_channel(ch_cfg)
        # Populate XY combo when loading a project that had xy_mode saved
        if self._config.xy_mode:
            self._rebuild_xy_combo()

    def _plot_channel(self, ch_cfg: ChannelConfig) -> None:
        if self._config.xy_mode and self._config.x_channel is not None:
            # The X-axis channel is the reference — skip plotting it as a Y signal
            if self._channel_key(ch_cfg) == self._channel_key(self._config.x_channel):
                return
            self._plot_channel_xy(ch_cfg)
            return
        try:
            sig = self._reader.read_signal(
                ch_cfg.file_path,
                ch_cfg.channel_name,
                ch_cfg.group_index,
                ch_cfg.channel_index,
            )
            samples = sig.samples * ch_cfg.y_scale + ch_cfg.y_offset
            label = ch_cfg.label or ch_cfg.channel_name
            if sig.unit:
                label = f"{label} [{sig.unit}]"

            # In absolute mode shift timestamps to Unix epoch so the DateAxis can format them
            x_data = sig.timestamps
            if self._config.x_axis_mode == "absolute":
                x_data = x_data + self._get_file_epoch(ch_cfg.file_path)

            # Downsample long channels so the UI stays responsive.
            n_raw = len(x_data)
            try:
                ds_enabled, ds_threshold, ds_target = load_downsample_settings()
                if ds_enabled:
                    x_data, samples = lttb(x_data, samples,
                                          n_out=ds_target, threshold=ds_threshold)
                if len(x_data) < n_raw:
                    _log.debug(
                        "LTTB: '%s' %d \u2192 %d samples (threshold=%d, target=%d)",
                        ch_cfg.channel_name, n_raw, len(x_data), ds_threshold, ds_target,
                    )
            except Exception:
                _log.exception("LTTB failed for '%s' — plotting full data", ch_cfg.channel_name)
                # x_data / samples retain their pre-lttb values; continue with full data

            plot_kw: dict = {"name": label, "pen": pg.mkPen(ch_cfg.color, width=1.5)}
            if ch_cfg.digital:
                plot_kw["stepMode"] = "right"
            item = self._plot_widget.plot(x_data, samples, **plot_kw)
            # Render-time adaptive downsampling: reduces draw calls to match screen
            # pixel count without touching the stored data.  method='peak' preserves
            # signal amplitude extremes (min+max per group).
            item.setDownsampling(auto=True, method="peak")
            # Only draw points that fall within the visible X range — huge speedup
            # when zoomed in on a small portion of a long recording.
            # item.setClipToView(True)
            item.setVisible(ch_cfg.visible)

            key = self._channel_key(ch_cfg)
            self._plot_items[key] = item
            _log.info("Plotted '%s' (%d samples)", ch_cfg.channel_name, len(x_data))

        except Exception:
            _log.exception("Cannot plot channel '%s'", ch_cfg.channel_name)

    def _plot_channel_xy(self, ch_cfg: ChannelConfig) -> None:
        """Plot *ch_cfg* samples against the configured x_channel samples."""
        x_cfg = self._config.x_channel
        if x_cfg is None:
            return
        try:
            # Read X channel (MF4Reader caches the handle)
            x_sig = self._reader.read_signal(
                x_cfg.file_path, x_cfg.channel_name,
                x_cfg.group_index, x_cfg.channel_index,
            )
            x_vals = x_sig.samples * x_cfg.y_scale + x_cfg.y_offset
            x_times = x_sig.timestamps

            # Read Y channel
            y_sig = self._reader.read_signal(
                ch_cfg.file_path, ch_cfg.channel_name,
                ch_cfg.group_index, ch_cfg.channel_index,
            )
            y_vals = y_sig.samples * ch_cfg.y_scale + ch_cfg.y_offset
            y_times = y_sig.timestamps

            # Interpolate Y onto X's timestamps so every (x, y) pair is coherent
            if not np.array_equal(x_times, y_times):
                t_min = max(float(x_times[0]), float(y_times[0]))
                t_max = min(float(x_times[-1]), float(y_times[-1]))
                mask = (x_times >= t_min) & (x_times <= t_max)
                x_plot = x_vals[mask]
                y_plot = np.interp(x_times[mask], y_times, y_vals)
            else:
                x_plot = x_vals
                y_plot = y_vals

            label = ch_cfg.label or ch_cfg.channel_name
            if y_sig.unit:
                label = f"{label} [{y_sig.unit}]"

            item = self._plot_widget.plot(
                x_plot, y_plot,
                name=label,
                pen=pg.mkPen(ch_cfg.color, width=1.5),
            )
            item.setDownsampling(auto=True, method="peak")
            # item.setClipToView(True)
            item.setVisible(ch_cfg.visible)

            self._plot_items[self._channel_key(ch_cfg)] = item

            # Set X axis label from the X channel (unit from signal)
            x_label = x_cfg.label or x_cfg.channel_name
            if x_sig.unit:
                x_label += f" [{x_sig.unit}]"
            self._plot_widget.setLabel("bottom", x_label)

        except Exception:
            _log.exception("Cannot plot '%s' in XY mode", ch_cfg.channel_name)

    def add_channel(self, ch_cfg: ChannelConfig) -> None:
        """Add a new channel to the graph (called by MainWindow after dialog)."""
        if not ch_cfg.color:
            ch_cfg.color = self._next_color()
        self._color_idx += 1
        self._config.channels.append(ch_cfg)
        self._plot_channel(ch_cfg)
        if self._config.xy_mode:
            self._rebuild_xy_combo()
        self._update_cursor_labels()
        self._maybe_update_signal_labels()
        self.channels_changed.emit()
        self.config_changed.emit()

    def replot_channels(self) -> None:
        """Remove all data curves and re-plot every channel from config.

        Called after global settings change (e.g. downsampling parameters).
        The current view range is preserved.
        """
        for item in list(self._plot_items.values()):
            self._plot_widget.removeItem(item)
        self._plot_items.clear()
        for ch_cfg in self._config.channels:
            self._plot_channel(ch_cfg)
        self._update_cursor_labels()
        self._maybe_update_signal_labels()

    def auto_fit_view(self) -> None:
        """Reset view to fit all plotted data; clears any saved zoom/pan ranges."""
        self._config.x_range = None
        self._config.y_range = None
        self._plot_widget.autoRange()

    def _next_color(self) -> str:
        """Return the first DEFAULT_COLORS entry not yet used by any channel in this graph.

        If all colors are already taken, falls back to cycling by _color_idx.
        """
        used = {ch.color.upper() for ch in self._config.channels}
        for color in DEFAULT_COLORS:
            if color.upper() not in used:
                return color
        # All 10 default colors exhausted — just cycle
        return DEFAULT_COLORS[self._color_idx % len(DEFAULT_COLORS)]

    # ------------------------------------------------------------------
    # Title rename
    # ------------------------------------------------------------------

    def _on_vb_x_range_changed(self, _vb, x_range: list) -> None:
        """Forward X-range changes to MainWindow for optional sync — guarded."""
        if not self._block_x_signal and not self._config.xy_mode:
            self.x_range_changed.emit(float(x_range[0]), float(x_range[1]))

    def set_x_range(self, xmin: float, xmax: float) -> None:
        """Set X range without emitting x_range_changed (called during sync)."""
        if self._config.xy_mode:
            return   # XY graphs are not part of the time-axis sync group
        self._block_x_signal = True
        try:
            self._plot_widget.setXRange(xmin, xmax, padding=0)  # type: ignore[call-arg]
        finally:
            self._block_x_signal = False

    def get_x_range(self) -> tuple[float, float]:
        vr = self._plot_widget.viewRange()
        return (float(vr[0][0]), float(vr[0][1]))

    # ------------------------------------------------------------------
    # Title rename
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self._title_label:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._start_rename()
                return True
        elif obj is self._title_edit:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._cancel_rename()
                return True
        return super().eventFilter(obj, event)

    def _start_rename(self) -> None:
        self._title_edit.setText(self._config.title)
        self._title_edit.selectAll()
        self._title_stack.setCurrentIndex(1)
        self._title_edit.setFocus()

    def _finish_rename(self) -> None:
        if self._title_stack.currentIndex() != 1:
            return   # guard against double-call from editingFinished after Escape
        text = self._title_edit.text().strip() or self._config.title
        self._config.title = text
        self._title_label.setText(text)
        self._title_stack.setCurrentIndex(0)
        self.config_changed.emit()

    def _cancel_rename(self) -> None:
        self._title_stack.setCurrentIndex(0)
        self._title_label.setFocus()

    def _toggle_visibility(self, ch_cfg: ChannelConfig, visible: bool) -> None:
        ch_cfg.visible = visible
        item = self._plot_items.get(self._channel_key(ch_cfg))
        if item is not None:
            item.setVisible(visible)
        self._maybe_update_signal_labels()
        self.config_changed.emit()

    def _edit_channel(self, ch_cfg: ChannelConfig) -> None:
        """Open the full appearance editor and apply changes if accepted."""
        from ui.channel_editor_dialog import ChannelAppearanceDialog
        dlg = ChannelAppearanceDialog(ch_cfg, self)
        if dlg.exec():
            updated = dlg.result_config()
            # Apply changes back into the live config object
            ch_cfg.label = updated.label
            ch_cfg.color = updated.color
            ch_cfg.y_scale = updated.y_scale
            ch_cfg.y_offset = updated.y_offset
            ch_cfg.visible = updated.visible
            ch_cfg.digital = updated.digital
            self._replot_channel(ch_cfg)
            self.channels_changed.emit()
            self.config_changed.emit()

    def _remove_channel(self, ch_cfg: ChannelConfig) -> None:
        key = self._channel_key(ch_cfg)
        old_item = self._plot_items.pop(key, None)
        if old_item is not None:
            self._legend.removeItem(old_item)
            self._plot_widget.removeItem(old_item)
        if ch_cfg in self._config.channels:
            self._config.channels.remove(ch_cfg)
        # If the removed channel was the X axis, turn off XY mode
        if (self._config.xy_mode and self._config.x_channel is not None
                and self._channel_key(ch_cfg) == self._channel_key(self._config.x_channel)):
            self._xy_btn.setChecked(False)  # triggers _on_xy_toggled(False)
        elif self._config.xy_mode:
            self._rebuild_xy_combo()
        self._maybe_update_signal_labels()
        self.channels_changed.emit()
        self.config_changed.emit()

    def _replot_channel(self, ch_cfg: ChannelConfig) -> None:
        """Remove the existing curve and re-draw with current ChannelConfig settings."""
        key = self._channel_key(ch_cfg)
        old_item = self._plot_items.pop(key, None)
        if old_item is not None:
            self._legend.removeItem(old_item)
            self._plot_widget.removeItem(old_item)
        self._plot_channel(ch_cfg)

    # ------------------------------------------------------------------
    # Header button slots
    # ------------------------------------------------------------------

    def _on_legend_toggled(self, visible: bool) -> None:
        self._config.show_legend = visible
        self._legend.setVisible(visible)
        self.config_changed.emit()

    def _on_time_mode_toggled(self, checked: bool) -> None:
        """[deprecated hook kept for internal reuse — call set_abs_time() instead]"""
        self.set_abs_time(checked)

    def set_abs_time(self, enabled: bool) -> None:
        """Switch this graph between relative [s] and absolute wall-clock time X-axis."""
        self._config.x_axis_mode = "absolute" if enabled else "relative"
        if not self._config.xy_mode:
            # In XY mode the bottom axis shows the X channel values, not time
            self._time_axis.set_abs_mode(enabled)
            self._plot_widget.setLabel("bottom", "Time" if enabled else self._config.x_label)
        # Coordinate system changes — clear stored range so view auto-fits
        self._config.x_range = None
        self._replot_all_channels()
        self._plot_widget.autoRange()
        self.config_changed.emit()

    # ------------------------------------------------------------------
    # X vs Y mode
    # ------------------------------------------------------------------

    def _on_xy_toggled(self, checked: bool) -> None:
        self._config.xy_mode = checked
        self._xy_combo.setVisible(checked)
        if checked:
            self._rebuild_xy_combo()
            # Disable time-formatting on the bottom axis — it shows channel values now
            self._time_axis.set_abs_mode(False)
            # Pick first channel as X if nothing is set
            if self._config.x_channel is None and self._config.channels:
                self._config.x_channel = self._config.channels[0]
                self._xy_combo.setCurrentIndex(0)
        else:
            self._config.x_channel = None
            # Restore time-axis mode and label
            abs_mode = self._config.x_axis_mode == "absolute"
            self._time_axis.set_abs_mode(abs_mode)
            self._plot_widget.setLabel("bottom", "Time" if abs_mode else self._config.x_label)
        self._config.x_range = None
        self._replot_all_channels()
        self._plot_widget.autoRange()
        self.config_changed.emit()

    def _on_xy_channel_changed(self, idx: int) -> None:
        if idx < 0 or not self._config.xy_mode:
            return
        ch = self._xy_combo.itemData(idx)
        if ch is not None:
            self._config.x_channel = ch
            self._config.x_range = None
            self._replot_all_channels()
            self._plot_widget.autoRange()
            self.config_changed.emit()

    def _rebuild_xy_combo(self) -> None:
        """Repopulate the X-channel combo from the current channel list."""
        self._xy_combo.blockSignals(True)
        self._xy_combo.clear()
        for ch_cfg in self._config.channels:
            label = ch_cfg.label or ch_cfg.channel_name
            self._xy_combo.addItem(label, userData=ch_cfg)
        # Restore previous selection
        if self._config.x_channel is not None:
            x = self._config.x_channel
            for i in range(self._xy_combo.count()):
                ch = self._xy_combo.itemData(i)
                if (ch.file_path == x.file_path and ch.channel_name == x.channel_name
                        and ch.group_index == x.group_index):
                    self._xy_combo.setCurrentIndex(i)
                    break
        self._xy_combo.blockSignals(False)

    def _replot_all_channels(self) -> None:
        """Remove every curve and redraw with x-data matching current axis mode."""
        for ch_cfg in list(self._config.channels):
            key = self._channel_key(ch_cfg)
            old_item = self._plot_items.pop(key, None)
            if old_item is not None:
                self._legend.removeItem(old_item)
                self._plot_widget.removeItem(old_item)
            self._plot_channel(ch_cfg)

    def _get_file_epoch(self, file_path: str) -> float:
        """Return (and cache) the Unix epoch offset for a given MF4 file."""
        if file_path not in self._file_epochs:
            try:
                self._file_epochs[file_path] = self._reader.get_file_start_time(file_path)
            except Exception:
                self._file_epochs[file_path] = 0.0
        return self._file_epochs[file_path]

    def _export_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Graph",
            self._config.title,
            filter="PNG Image (*.png);;BMP Image (*.bmp);;JPEG Image (*.jpg)",
        )
        if path:
            try:
                from utils.export import export_widget_to_bitmap
                export_widget_to_bitmap(self._plot_widget, path)
                self.parent().statusBar().showMessage(f"Exported: {path}", 3000)  # type: ignore[union-attr]
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))

    # ------------------------------------------------------------------
    # Config sync
    # ------------------------------------------------------------------

    def get_config(self) -> GraphConfig:
        """Return the config updated with the current view ranges."""
        vr = self._plot_widget.viewRange()
        self._config.x_range = list(vr[0])
        self._config.y_range = list(vr[1])
        return self._config

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _channel_key(ch_cfg: ChannelConfig) -> str:
        return f"{ch_cfg.file_path}::{ch_cfg.channel_name}::{ch_cfg.group_index}"
