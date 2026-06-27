"""Single graph panel widget.

Contains:
  - A pyqtgraph PlotWidget (zoom/pan via mouse wheel and drag built-in)
  - A header bar with title, legend toggle, "Add Signals", export, and remove buttons
  - Logic to plot ChannelConfig entries and sync view state back to GraphConfig
"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.mf4_reader import MF4Reader
from core.project import ChannelConfig, DEFAULT_COLORS, GraphConfig

if TYPE_CHECKING:
    pass


class _CtrlZoomViewBox(pg.ViewBox):
    """ViewBox that keeps normal left-drag pan and adds Ctrl+left-drag rubber-band zoom."""

    def mouseDragEvent(self, ev, axis=None):  # type: ignore[override]
        if ev.button() == Qt.LeftButton and (ev.modifiers() & Qt.ControlModifier):
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
    x_range_changed = Signal(float, float)   # emitted on user-driven X-axis changes
    cursor_moved = Signal(float)             # emitted when user drags the readout cursor

    def __init__(self, config: GraphConfig, reader: MF4Reader, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._config = config
        self._reader = reader
        self._color_idx = len(config.channels)   # start after already-assigned colors
        self._block_x_signal: bool = False       # prevents re-entrant X-sync loops
        self._block_cursor_signal: bool = False  # prevents re-entrant cursor-sync loops
        self._dark_mode: bool = False             # tracks current theme for cursor labels
        self._cursor_line: pg.InfiniteLine | None = None
        self._cursor_labels: dict[str, pg.TextItem] = {}
        self._file_epochs: dict[str, float] = {}  # file_path -> Unix epoch of start time

        # Maps "file_path::channel_name::group_idx" -> PlotDataItem
        self._plot_items: dict[str, pg.PlotDataItem] = {}

        self._setup_ui()
        self._load_channels()
        self._refresh_channels_panel()
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
        self._title_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

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

        self._cursor_btn = QPushButton("Cursor")
        self._cursor_btn.setCheckable(True)
        self._cursor_btn.setMaximumWidth(65)
        self._cursor_btn.setToolTip("Toggle readout cursor — drag the vertical line to read signal values")
        self._cursor_btn.toggled.connect(self._on_cursor_toggled)
        header.addWidget(self._cursor_btn)

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
        self._time_axis.set_abs_mode(abs_mode)
        self._plot_widget = pg.PlotWidget(
            viewBox=_CtrlZoomViewBox(),
            background="w",
            axisItems={"bottom": self._time_axis},
        )
        self._plot_widget.setToolTip("Scroll = zoom  |  Left drag = pan  |  Ctrl+left drag = zoom to region")
        self._plot_widget.setMinimumHeight(120)
        self._plot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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

        # ---- channel list panel ----
        self._channels_panel = QFrame()
        self._channels_panel.setFrameShape(QFrame.StyledPanel)
        self._channels_panel.setStyleSheet("QFrame { background: #f8f8f8; }")
        self._channels_layout = QVBoxLayout(self._channels_panel)
        self._channels_layout.setContentsMargins(4, 4, 4, 4)
        self._channels_layout.setSpacing(2)

        # Wrap in a scroll area so the channel list never covers the plot
        self._channels_scroll = QScrollArea()
        self._channels_scroll.setWidget(self._channels_panel)
        self._channels_scroll.setWidgetResizable(True)
        self._channels_scroll.setFrameShape(QFrame.NoFrame)
        self._channels_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._channels_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._channels_scroll.setMaximumHeight(180)   # cap height; scrolls when more channels
        self._channels_scroll.setMinimumHeight(0)      # allows collapse when parent is small
        layout.addWidget(self._channels_scroll)

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
        self._channels_panel.setStyleSheet(f"QFrame {{ background: {panel_bg}; }}")
        self._channels_scroll.viewport().setStyleSheet(f"background: {panel_bg};")
        self._title_label.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {title_color};"
        )
        self._title_edit.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {title_color};"
        )
        # Update cursor line pen if active
        if self._cursor_line is not None:
            self._cursor_line.setPen(pg.mkPen(
                "#ff9944" if dark else "#cc4400", width=1.5, style=Qt.DashLine
            ))

    # ------------------------------------------------------------------
    # Cursor (value readout)
    # ------------------------------------------------------------------

    def _on_cursor_toggled(self, checked: bool) -> None:
        if checked:
            vr = self._plot_widget.viewRange()
            x_center = (vr[0][0] + vr[0][1]) / 2
            self._cursor_line = pg.InfiniteLine(
                pos=x_center, angle=90, movable=True,
                pen=pg.mkPen("#cc4400", width=1.5, style=Qt.DashLine),
            )
            self._cursor_line.sigPositionChanged.connect(self._update_cursor_labels)
            self._cursor_line.sigPositionChanged.connect(self._on_cursor_pos_changed)
            self._plot_widget.sigRangeChanged.connect(self._update_cursor_labels)
            self._plot_widget.addItem(self._cursor_line)
            self._update_cursor_labels()
        else:
            if self._cursor_line is not None:
                self._plot_widget.removeItem(self._cursor_line)
                self._cursor_line = None
            try:
                self._plot_widget.sigRangeChanged.disconnect(self._update_cursor_labels)
            except RuntimeError:
                pass
            for lbl in self._cursor_labels.values():
                self._plot_widget.removeItem(lbl)
            self._cursor_labels.clear()

    def _on_cursor_pos_changed(self, line: pg.InfiniteLine) -> None:
        """Forward cursor position to MainWindow for optional sync across graphs."""
        if not self._block_cursor_signal:
            self.cursor_moved.emit(line.value())

    def set_cursor_pos(self, x: float) -> None:
        """Move the readout cursor to *x* without re-emitting cursor_moved."""
        if self._cursor_line is None:
            return
        self._block_cursor_signal = True
        try:
            self._cursor_line.setPos(x)
        finally:
            self._block_cursor_signal = False

    def _update_cursor_labels(self, *_) -> None:  # *_ absorbs sigRangeChanged args
        if self._cursor_line is None:
            return
        x = self._cursor_line.value()

        # Remove all existing labels first
        for lbl in self._cursor_labels.values():
            self._plot_widget.removeItem(lbl)
        self._cursor_labels.clear()

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
            if x_data is None or len(x_data) < 2:
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
            self._plot_widget.addItem(text_item)
            self._cursor_labels[key] = text_item

        # --- Phase 4: time label at the bottom of the view -------------------
        self._add_cursor_time_label(x)

    def _add_cursor_time_label(self, x: float) -> None:
        """Add a formatted time TextItem at the bottom of the view for cursor position *x*."""
        if self._config.x_axis_mode == "absolute":
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
        self._plot_widget.addItem(time_item)
        self._cursor_labels["__time__"] = time_item

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

    def _plot_channel(self, ch_cfg: ChannelConfig) -> None:
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

            item = self._plot_widget.plot(
                x_data,
                samples,
                name=label,
                pen=pg.mkPen(ch_cfg.color, width=1.5),
            )
            item.setVisible(ch_cfg.visible)

            key = self._channel_key(ch_cfg)
            self._plot_items[key] = item

        except Exception as exc:
            # Show a visible error curve placeholder so the user knows what failed
            print(f"[GraphWidget] Cannot plot '{ch_cfg.channel_name}': {exc}")

    def add_channel(self, ch_cfg: ChannelConfig) -> None:
        """Add a new channel to the graph (called by MainWindow after dialog)."""
        if not ch_cfg.color:
            ch_cfg.color = self._next_color()
        self._color_idx += 1
        self._config.channels.append(ch_cfg)
        self._plot_channel(ch_cfg)
        self._refresh_channels_panel()
        self._update_cursor_labels()
        self.config_changed.emit()

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
        if not self._block_x_signal:
            self.x_range_changed.emit(float(x_range[0]), float(x_range[1]))

    def set_x_range(self, xmin: float, xmax: float) -> None:
        """Set X range without emitting x_range_changed (called during sync)."""
        self._block_x_signal = True
        try:
            self._plot_widget.setXRange(xmin, xmax, padding=0)
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
            if event.type() == QEvent.MouseButtonDblClick:
                self._start_rename()
                return True
        elif obj is self._title_edit:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key_Escape:
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

    # ------------------------------------------------------------------
    # Channel list panel
    # ------------------------------------------------------------------

    def _refresh_channels_panel(self) -> None:
        """Rebuild the channel rows from scratch."""
        # Remove all existing row widgets
        while self._channels_layout.count():
            item = self._channels_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._config.channels:
            placeholder = QLabel('No signals — click "+ Signals" to add')
            placeholder.setStyleSheet("color: #999; font-style: italic;")
            placeholder.setAlignment(Qt.AlignCenter)
            self._channels_layout.addWidget(placeholder)
        else:
            for ch_cfg in self._config.channels:
                self._channels_layout.addWidget(self._make_channel_row(ch_cfg))

    def _make_channel_row(self, ch_cfg: ChannelConfig) -> QWidget:
        """Build a compact row widget for one channel."""
        row = QWidget()
        row.setStyleSheet("QWidget { background: transparent; }")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(2, 1, 2, 1)
        rl.setSpacing(4)

        # Color swatch button — click to change color directly
        color_btn = QPushButton()
        color_btn.setFixedSize(18, 18)
        color_btn.setCursor(Qt.PointingHandCursor)
        color_btn.setToolTip("Click to change color")
        self._apply_color_btn_style(color_btn, ch_cfg.color)
        color_btn.clicked.connect(lambda _checked, cfg=ch_cfg, btn=color_btn: self._quick_color(cfg, btn))
        rl.addWidget(color_btn)

        # Visibility checkbox
        vis_cb = QCheckBox()
        vis_cb.setChecked(ch_cfg.visible)
        vis_cb.setToolTip("Show / hide curve")
        vis_cb.toggled.connect(lambda checked, cfg=ch_cfg: self._toggle_visibility(cfg, checked))
        rl.addWidget(vis_cb)

        # Label
        lbl = QLabel(ch_cfg.label or ch_cfg.channel_name)
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lbl.setToolTip(f"{ch_cfg.channel_name}  ·  {ch_cfg.file_path}")
        rl.addWidget(lbl, 1)

        # Scale/offset hint (shown only when non-default)
        if ch_cfg.y_scale != 1.0 or ch_cfg.y_offset != 0.0:
            hint = QLabel(f"×{ch_cfg.y_scale:g}  +{ch_cfg.y_offset:g}")
            hint.setStyleSheet("color: #888; font-size: 10px;")
            rl.addWidget(hint)

        # Edit button
        edit_btn = QPushButton("✎")
        edit_btn.setFixedSize(24, 22)
        edit_btn.setToolTip("Edit channel appearance")
        edit_btn.clicked.connect(lambda _checked, cfg=ch_cfg: self._edit_channel(cfg))
        rl.addWidget(edit_btn)

        # Remove button
        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(22, 22)
        rm_btn.setToolTip("Remove from graph")
        rm_btn.clicked.connect(lambda _checked, cfg=ch_cfg: self._remove_channel(cfg))
        rl.addWidget(rm_btn)

        return row

    @staticmethod
    def _apply_color_btn_style(btn: QPushButton, color: str) -> None:
        btn.setStyleSheet(
            f"background-color: {color}; border: 1px solid #555; border-radius: 2px;"
        )

    def _quick_color(self, ch_cfg: ChannelConfig, btn: QPushButton) -> None:
        """Open a color picker and immediately replot if a color is chosen."""
        color = QColorDialog.getColor(QColor(ch_cfg.color), self, "Pick Color")
        if color.isValid():
            ch_cfg.color = color.name().upper()
            self._apply_color_btn_style(btn, ch_cfg.color)
            self._replot_channel(ch_cfg)
            # Refresh to update scale hint text color btn (label row rebuild)
            self._refresh_channels_panel()
            self.config_changed.emit()

    def _toggle_visibility(self, ch_cfg: ChannelConfig, visible: bool) -> None:
        ch_cfg.visible = visible
        item = self._plot_items.get(self._channel_key(ch_cfg))
        if item is not None:
            item.setVisible(visible)
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
            self._replot_channel(ch_cfg)
            self._refresh_channels_panel()
            self.config_changed.emit()

    def _remove_channel(self, ch_cfg: ChannelConfig) -> None:
        key = self._channel_key(ch_cfg)
        old_item = self._plot_items.pop(key, None)
        if old_item is not None:
            self._legend.removeItem(old_item)
            self._plot_widget.removeItem(old_item)
        if ch_cfg in self._config.channels:
            self._config.channels.remove(ch_cfg)
        self._refresh_channels_panel()
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
        self._time_axis.set_abs_mode(enabled)
        self._plot_widget.setLabel("bottom", "Time" if enabled else self._config.x_label)
        # Coordinate system changes — clear stored range so view auto-fits
        self._config.x_range = None
        self._replot_all_channels()
        self._plot_widget.autoRange()
        self.config_changed.emit()

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
