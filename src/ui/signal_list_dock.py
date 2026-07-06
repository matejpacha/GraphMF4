"""Dockable panel listing all channels available in the loaded MF4/MDF files.

The user selects a source file from the combo, optionally filters by name,
then double-clicks a channel (or presses **+ Add to Active Graph**) to emit
``channel_requested(file_path, ChannelInfo)`` which ``MainWindow`` forwards
to the currently active ``GraphWidget``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDockWidget,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.mf4_reader import ChannelInfo, MF4Reader

_log = logging.getLogger(__name__)

# Custom MIME type used for dragging channels between docks / onto the MDI area.
CHANNEL_MIME_TYPE = "application/x-graphmf4-channel"


def decode_channel_mime_multi(
    mime_data,
) -> list[tuple[str, str, int, int]]:
    """Decode a GraphMF4 channel drag payload (single or multi-channel).

    Returns a list of ``(file_path, channel_name, group_index, channel_index)``
    tuples, or an empty list on failure.
    """
    raw = mime_data.data(CHANNEL_MIME_TYPE)
    if raw is None or raw.isEmpty():
        return []
    try:
        data = json.loads(bytes(raw))
        # Payload is always a list; legacy single-dict payloads are also handled.
        if isinstance(data, dict):
            data = [data]
        return [
            (d["file_path"], d["channel_name"], d["group_index"], d["channel_index"])
            for d in data
        ]
    except Exception:
        return []


def decode_channel_mime(mime_data) -> tuple[str, str, int, int] | None:
    """Decode a single-channel payload (convenience wrapper for one-channel callers)."""
    results = decode_channel_mime_multi(mime_data)
    return results[0] if results else None


class _ChannelBrowserList(QListWidget):
    """QListWidget that encodes channel info as MIME data when a drag starts."""

    def __init__(self, dock: "SignalListDock") -> None:
        super().__init__()
        self._dock = dock
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def startDrag(self, supported_actions) -> None:  # type: ignore[override]
        if not self._dock._current_file:
            return
        selected_items = self.selectedItems()
        if not selected_items:
            return
        channels = []
        for item in selected_items:
            ch: ChannelInfo | None = item.data(Qt.ItemDataRole.UserRole)
            if ch is not None:
                channels.append({
                    "file_path": self._dock._current_file,
                    "channel_name": ch.name,
                    "group_index": ch.group_index,
                    "channel_index": ch.channel_index,
                })
        if not channels:
            return
        payload = json.dumps(channels).encode("utf-8")
        mime = QMimeData()
        mime.setData(CHANNEL_MIME_TYPE, QByteArray(payload))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SignalListDock(QDockWidget):
    """Dockable panel listing every channel available in the selected loaded file.

    Signals
    -------
    channel_requested(file_path: str, ch: ChannelInfo)
        Emitted when the user wants to add a channel to the active graph.
    """

    channel_requested = Signal(str, object)  # (file_path, ChannelInfo)

    def __init__(self, reader: MF4Reader, parent=None) -> None:
        super().__init__("Available Signals", parent)
        self.setObjectName("SignalListDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._reader = reader
        self._current_file: str = ""
        self._all_channels: list[ChannelInfo] = []

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── source file selector ──────────────────────────────────────
        layout.addWidget(QLabel("Source file:"))
        self._file_combo = QComboBox()
        self._file_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._file_combo.setToolTip("Select the loaded MF4/MDF file to browse")
        self._file_combo.currentIndexChanged.connect(self._on_file_changed)
        layout.addWidget(self._file_combo)

        # ── text filter ───────────────────────────────────────────────
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)

        # ── channel list ──────────────────────────────────────────────
        self._list = _ChannelBrowserList(self)
        self._list.setAlternatingRowColors(True)
        self._list.setToolTip(
            "Double-click to add a channel to the active graph\n"
            "Ctrl/Shift+click to select multiple channels"
        )
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        # ── add button ────────────────────────────────────────────────
        self._add_btn = QPushButton("+ Add to Active Graph")
        self._add_btn.setEnabled(False)
        self._add_btn.setToolTip(
            "Add selected channel(s) to the currently active graph\n"
            "(or double-click a channel in the list above)"
        )
        self._add_btn.clicked.connect(self._on_add_clicked)
        layout.addWidget(self._add_btn)

        self.setWidget(root)

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def set_files(self, paths: list[str]) -> None:
        """Repopulate the file combo; reload channel list when the selection changes."""
        prev = self._file_combo.currentData()

        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        for p in paths:
            self._file_combo.addItem(Path(p).name, userData=p)
        # Restore previous selection if still present, otherwise default to first
        idx = self._file_combo.findData(prev)
        self._file_combo.setCurrentIndex(max(0, idx) if self._file_combo.count() else -1)
        self._file_combo.blockSignals(False)

        if self._file_combo.count() > 0:
            self._on_file_changed(self._file_combo.currentIndex())
        else:
            self._current_file = ""
            self._all_channels = []
            self._list.clear()
            self._add_btn.setEnabled(False)

    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _on_file_changed(self, idx: int) -> None:
        if idx < 0:
            self._current_file = ""
            self._list.clear()
            return
        self._current_file = self._file_combo.itemData(idx) or ""
        self._load_channels()

    def _load_channels(self) -> None:
        self._list.clear()
        self._all_channels = []
        if not self._current_file:
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._all_channels = self._reader.get_channel_list(self._current_file)
        except Exception:
            _log.exception("SignalListDock: failed to read channels from %s", self._current_file)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._apply_filter(self._filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        lo = text.strip().lower()
        self._list.clear()
        for ch in self._all_channels:
            if lo and lo not in ch.name.lower():
                continue
            label = ch.name
            if ch.unit:
                label += f"  [{ch.unit}]"
            item = QListWidgetItem(label)
            tip = f"Name: {ch.name}"
            if ch.unit:
                tip += f"\nUnit: {ch.unit}"
            tip += f"\nGroup: {ch.group_index}  Index: {ch.channel_index}"
            if ch.comment:
                tip += f"\n{ch.comment}"
            item.setToolTip(tip)
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self._list.addItem(item)

    # ──────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────

    def _on_selection_changed(self) -> None:
        self._add_btn.setEnabled(bool(self._list.selectedItems()))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        ch: ChannelInfo | None = item.data(Qt.ItemDataRole.UserRole)
        if ch is not None and self._current_file:
            self.channel_requested.emit(self._current_file, ch)

    def _on_add_clicked(self) -> None:
        if not self._current_file:
            return
        for item in self._list.selectedItems():
            ch: ChannelInfo | None = item.data(Qt.ItemDataRole.UserRole)
            if ch is not None:
                self.channel_requested.emit(self._current_file, ch)
