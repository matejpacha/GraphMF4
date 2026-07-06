"""Dockable channel list panel for GraphMF4.

Shows channels belonging to the currently active GraphWidget.
Supports drag-and-drop reordering, visibility toggle via check state,
colour indicator, and per-item Edit / Remove actions.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.project import ChannelConfig

if TYPE_CHECKING:
    from ui.graph_widget import GraphWidget

_log = logging.getLogger(__name__)

_ICON_SIZE = 14
_USER_KEY = Qt.ItemDataRole.UserRole


def _color_icon(color: str) -> QIcon:
    """Small solid-color square icon for the channel list."""
    px = QPixmap(_ICON_SIZE, _ICON_SIZE)
    px.fill(QColor(color if color else "#888888"))
    return QIcon(px)


class ChannelListDock(QDockWidget):
    """Dockable panel listing channels of the active graph.

    Call :meth:`set_graph` whenever the active graph changes.
    Call :meth:`refresh` after any structural change to the channel list.
    """

    def __init__(self, parent=None) -> None:
        super().__init__("Channels", parent)
        self.setObjectName("ChannelListDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._graph: GraphWidget | None = None
        self._updating: bool = False   # guard against feedback loops

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── top action buttons ──────────────────────────────────────────
        top = QHBoxLayout()
        self._add_btn = QPushButton("+ Signals")
        self._add_btn.setToolTip("Add signals from an MF4 file")
        self._add_btn.clicked.connect(self._on_add)
        top.addWidget(self._add_btn)

        self._stack_btn = QPushButton("Stack ↕")
        self._stack_btn.setToolTip(
            "Auto-stack visible digital channels into equal horizontal lanes.\n"
            "Mark channels as Digital via the ✎ editor first."
        )
        self._stack_btn.clicked.connect(self._on_stack)
        top.addWidget(self._stack_btn)
        layout.addLayout(top)

        # ── channel list ───────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self._list.setAlternatingRowColors(True)
        self._list.setToolTip(
            "Drag rows to reorder channels\n"
            "Check box = show / hide curve\n"
            "Drop channel from Signal Browser to add"
        )
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        # Accept external channel drops from SignalListDock
        self._list.viewport().setAcceptDrops(True)
        self._list.viewport().installEventFilter(self)
        layout.addWidget(self._list)

        # ── per-item action buttons ─────────────────────────────────────
        bot = QHBoxLayout()
        bot.addStretch()
        self._edit_btn = QPushButton("✎ Edit")
        self._edit_btn.setEnabled(False)
        self._edit_btn.setToolTip("Edit appearance of the selected channel")
        self._edit_btn.clicked.connect(self._on_edit)
        bot.addWidget(self._edit_btn)

        self._remove_btn = QPushButton("✕ Remove")
        self._remove_btn.setEnabled(False)
        self._remove_btn.setToolTip("Remove the selected channel from the graph")
        self._remove_btn.clicked.connect(self._on_remove)
        bot.addWidget(self._remove_btn)
        layout.addLayout(bot)

        self.setWidget(root)


    def set_graph(self, graph: GraphWidget | None) -> None:
        """Switch the panel to display *graph*'s channels (or clear if None)."""
        self._graph = graph
        if graph is not None:
            self.setWindowTitle(f"Channels — {graph._config.title}")
        else:
            self.setWindowTitle("Channels")
        self._rebuild()

    def refresh(self) -> None:
        """Rebuild the list, preserving the current selection row."""
        sel = self._list.currentRow()
        self._rebuild()
        if 0 <= sel < self._list.count():
            self._list.setCurrentRow(sel)
    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        """Accept channel drops from SignalListDock on the list viewport."""
        if obj is self._list.viewport():
            from ui.signal_list_dock import CHANNEL_MIME_TYPE, decode_channel_mime_multi
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasFormat(CHANNEL_MIME_TYPE):
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.Drop:
                if event.mimeData().hasFormat(CHANNEL_MIME_TYPE):
                    for result in decode_channel_mime_multi(event.mimeData()):
                        self._handle_channel_drop(*result)
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _handle_channel_drop(
        self,
        file_path: str,
        channel_name: str,
        group_index: int,
        channel_index: int,
    ) -> None:
        """Add a dropped channel to the currently active graph."""
        if self._graph is None:
            return
        ch_cfg = ChannelConfig(
            file_path=file_path,
            channel_name=channel_name,
            group_index=group_index,
            channel_index=channel_index,
        )
        self._graph.add_channel(ch_cfg)
    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        self._updating = True
        try:
            self._list.clear()
            if self._graph is None:
                return
            for ch_cfg in self._graph._config.channels:
                self._list.addItem(self._make_item(ch_cfg))
        finally:
            self._updating = False
        self._on_selection_changed()

    def _make_item(self, ch_cfg: ChannelConfig) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(_USER_KEY, self._ch_key(ch_cfg))
        item.setText(ch_cfg.label or ch_cfg.channel_name)
        item.setIcon(_color_icon(ch_cfg.color))
        item.setCheckState(
            Qt.CheckState.Checked if ch_cfg.visible else Qt.CheckState.Unchecked
        )
        tooltip = (
            f"{ch_cfg.channel_name}\n"
            f"Scale: ×{ch_cfg.y_scale:g}  Offset: +{ch_cfg.y_offset:g}"
            + ("  [Digital]" if ch_cfg.digital else "")
        )
        item.setToolTip(tooltip)
        if ch_cfg.digital:
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
        return item

    @staticmethod
    def _ch_key(ch_cfg: ChannelConfig) -> str:
        return f"{ch_cfg.file_path}::{ch_cfg.channel_name}::{ch_cfg.group_index}"

    def _ch_at(self, row: int) -> ChannelConfig | None:
        if self._graph is None or row < 0:
            return None
        chs = self._graph._config.channels
        return chs[row] if row < len(chs) else None

    # ──────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────

    def _on_add(self) -> None:
        if self._graph is not None:
            self._graph.request_add_signals.emit()

    def _on_stack(self) -> None:
        if self._graph is not None:
            self._graph._on_stack_digital_clicked()

    def _on_edit(self) -> None:
        ch_cfg = self._ch_at(self._list.currentRow())
        if ch_cfg is not None and self._graph is not None:
            self._graph._edit_channel(ch_cfg)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        ch_cfg = self._ch_at(self._list.row(item))
        if ch_cfg is not None and self._graph is not None:
            self._graph._edit_channel(ch_cfg)

    def _on_remove(self) -> None:
        ch_cfg = self._ch_at(self._list.currentRow())
        if ch_cfg is not None and self._graph is not None:
            self._graph._remove_channel(ch_cfg)

    def _on_selection_changed(self) -> None:
        has = bool(self._list.selectedItems()) and self._graph is not None
        self._edit_btn.setEnabled(has)
        self._remove_btn.setEnabled(has)

    def _on_context_menu(self, pos: QPoint) -> None:
        """Show right-click context menu for selected channels."""
        if self._graph is None:
            return
        selected_rows = [self._list.row(it) for it in self._list.selectedItems()]
        if not selected_rows:
            return
        selected_cfgs = [ch for row in selected_rows if (ch := self._ch_at(row)) is not None]
        if not selected_cfgs:
            return

        menu = QMenu(self._list)

        all_digital = all(c.digital for c in selected_cfgs)
        toggle_label = (
            "Převést na analogový" if all_digital else "Převést na digitální"
        )
        act_toggle = menu.addAction(toggle_label)

        action = menu.exec(self._list.viewport().mapToGlobal(pos))
        if action is act_toggle:
            self._toggle_digital(selected_cfgs, not all_digital)

    def _toggle_digital(self, cfgs: list[ChannelConfig], digital: bool) -> None:
        """Set the digital flag on *cfgs* and replot."""
        for ch_cfg in cfgs:
            ch_cfg.digital = digital
            self._graph._replot_channel(ch_cfg)  # type: ignore[union-attr]
        self._graph.channels_changed.emit()  # type: ignore[union-attr]
        self._graph.config_changed.emit()  # type: ignore[union-attr]
        self.refresh()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Visibility toggled via check box."""
        if self._updating or self._graph is None:
            return
        row = self._list.row(item)
        ch_cfg = self._ch_at(row)
        if ch_cfg is None:
            return
        visible = item.checkState() == Qt.CheckState.Checked
        if ch_cfg.visible != visible:
            self._graph._toggle_visibility(ch_cfg, visible)

    def _on_rows_moved(self, _src_parent, src_start: int, src_end: int,
                       _dst_parent, dst_row: int) -> None:
        """User reordered channels via drag-and-drop — sync to GraphConfig."""
        if self._updating or self._graph is None:
            return
        # Qt has already moved the item in the model.
        # Read new order from list widget using the stable key stored in UserRole.
        key_to_ch = {self._ch_key(ch): ch for ch in self._graph._config.channels}
        new_channels: list[ChannelConfig] = []
        for i in range(self._list.count()):
            key = self._list.item(i).data(_USER_KEY)
            if key in key_to_ch:
                new_channels.append(key_to_ch[key])
        if len(new_channels) == len(self._graph._config.channels):
            self._graph._config.channels[:] = new_channels
            self._graph.replot_channels()
            self._graph.config_changed.emit()
