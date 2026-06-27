"""Signal selector dialog.

Allows the user to pick one or more channels from one of the loaded MF4 files.
The selected channels are returned as a list of ChannelConfig objects (without
color assigned — the caller is responsible for assigning colors).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QComboBox,
)

from core.mf4_reader import ChannelInfo, MF4Reader
from core.project import ChannelConfig


class SignalSelectorDialog(QDialog):
    """Multi-select dialog for choosing channels from an MF4 file."""

    def __init__(
        self,
        mf4_files: list[str],
        reader: MF4Reader,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._files = mf4_files
        self._reader = reader
        self._channels: list[ChannelInfo] = []

        self.setWindowTitle("Select Signals")
        self.setMinimumSize(520, 440)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # File selector
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("MF4 File:"))
        self._file_combo = QComboBox()
        for f in self._files:
            self._file_combo.addItem(f)
        self._file_combo.currentIndexChanged.connect(self._load_channels)
        file_row.addWidget(self._file_combo, 1)
        layout.addLayout(file_row)

        # Text filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Type to filter channels…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_edit, 1)
        layout.addLayout(filter_row)

        # Channel list (multi-select)
        self._channel_list = QListWidget()
        self._channel_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._channel_list.setAlternatingRowColors(True)
        layout.addWidget(self._channel_list)

        # Selection count label
        self._count_label = QLabel("0 channels selected")
        self._channel_list.itemSelectionChanged.connect(self._update_count)
        layout.addWidget(self._count_label)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Populate list for the first file
        self._load_channels()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _load_channels(self) -> None:
        file_path = self._file_combo.currentText()
        if not file_path:
            return
        self._channel_list.clear()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._channels = self._reader.get_channel_list(file_path)
        except Exception as exc:
            item = QListWidgetItem(f"Error reading file: {exc}")
            item.setFlags(Qt.NoItemFlags)
            self._channel_list.addItem(item)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self._filter_edit.text().strip().lower()
        self._channel_list.clear()
        for ch in self._channels:
            if text and text not in ch.name.lower():
                continue
            display = f"{ch.name}  [{ch.unit}]" if ch.unit else ch.name
            if ch.comment:
                display += f"  — {ch.comment[:60]}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, ch)
            self._channel_list.addItem(item)
        self._update_count()

    def _update_count(self) -> None:
        n = len(self._channel_list.selectedItems())
        self._count_label.setText(f"{n} channel{'s' if n != 1 else ''} selected")

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def selected_channels(self) -> list[ChannelConfig]:
        """Return ChannelConfig objects for the selected list entries."""
        file_path = self._file_combo.currentText()
        result: list[ChannelConfig] = []
        for item in self._channel_list.selectedItems():
            ch: ChannelInfo = item.data(Qt.UserRole)
            result.append(
                ChannelConfig(
                    file_path=file_path,
                    channel_name=ch.name,
                    group_index=ch.group_index,
                    channel_index=ch.channel_index,
                    label=ch.name,
                    # color is assigned by GraphWidget.add_channel()
                )
            )
        return result
