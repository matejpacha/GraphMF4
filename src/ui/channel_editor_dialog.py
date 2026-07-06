"""Dialog for editing a single channel's appearance settings.

Editable fields:
  - Label (display name shown in legend)
  - Color (via QColorDialog)
  - Y scale (multiplier: plotted = raw × scale + offset)
  - Y offset
  - Visible (show/hide the curve)
"""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.project import ChannelConfig


class ChannelAppearanceDialog(QDialog):
    """Modal dialog for editing ChannelConfig appearance fields.

    Usage::
        dlg = ChannelAppearanceDialog(ch_cfg, parent)
        if dlg.exec():
            updated = dlg.result_config()
    """

    def __init__(self, channel_cfg: ChannelConfig, parent=None) -> None:
        super().__init__(parent)
        self._cfg = copy.copy(channel_cfg)   # work on a copy; only apply on OK
        self.setWindowTitle("Channel Appearance")
        self.setMinimumWidth(380)
        self.setMaximumWidth(500)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- read-only info ----
        info = QFrame()
        info.setFrameShape(QFrame.StyledPanel)
        info.setStyleSheet("QFrame { background: #f0f0f0; }")
        from PySide6.QtWidgets import QVBoxLayout as _VBox
        info_l = _VBox(info)
        info_l.setContentsMargins(8, 6, 8, 6)
        info_l.setSpacing(2)
        ch_name_lbl = QLabel(f"<b>{self._cfg.channel_name}</b>")
        info_l.addWidget(ch_name_lbl)
        file_lbl = QLabel(Path(self._cfg.file_path).name)
        file_lbl.setStyleSheet("color: #666; font-size: 11px;")
        info_l.addWidget(file_lbl)
        layout.addWidget(info)

        # ---- form ----
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(0, 4, 0, 4)
        form.setVerticalSpacing(8)

        # Label
        self._label_edit = QLineEdit(self._cfg.label)
        self._label_edit.setPlaceholderText(self._cfg.channel_name)
        self._label_edit.setToolTip("Name shown in the graph legend")
        form.addRow("Label:", self._label_edit)

        # Color
        self._color_btn = QPushButton()
        self._color_btn.setFixedHeight(28)
        self._color_btn.setCursor(Qt.PointingHandCursor)
        self._color_btn.setToolTip("Click to pick a color")
        self._refresh_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        form.addRow("Color:", self._color_btn)

        # Visible
        self._visible_cb = QCheckBox("Show curve in graph")
        self._visible_cb.setChecked(self._cfg.visible)
        form.addRow("Visibility:", self._visible_cb)

        # Y scale
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(-1_000_000, 1_000_000)
        self._scale_spin.setDecimals(6)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setValue(self._cfg.y_scale)
        self._scale_spin.setToolTip("Multiplier applied to raw samples")
        form.addRow("Y scale:", self._scale_spin)

        # Y offset
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-1_000_000_000, 1_000_000_000)
        self._offset_spin.setDecimals(6)
        self._offset_spin.setSingleStep(1.0)
        self._offset_spin.setValue(self._cfg.y_offset)
        self._offset_spin.setToolTip("Offset added after scaling")
        form.addRow("Y offset:", self._offset_spin)

        # Digital mode
        self._digital_cb = QCheckBox("Digital signal (step rendering + auto-stack)")
        self._digital_cb.setChecked(self._cfg.digital)
        self._digital_cb.setToolTip(
            "Render as a step waveform (square wave).\n"
            "Use the 'Stack \u21d5' button in the graph header to automatically\n"
            "place each digital channel in its own horizontal lane."
        )
        form.addRow("Mode:", self._digital_cb)

        layout.addLayout(form)

        # ---- formula hint ----
        hint = QLabel("plotted value = raw × <b>scale</b> + <b>offset</b>")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        # ---- dialog buttons ----
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_color_btn(self) -> None:
        r, g, b = QColor(self._cfg.color).getRgb()[:3]
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        text_color = "#000" if brightness > 128 else "#fff"
        self._color_btn.setStyleSheet(
            f"background-color: {self._cfg.color}; color: {text_color};"
            " border: 1px solid #888; border-radius: 3px;"
        )
        self._color_btn.setText(self._cfg.color.upper())

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._cfg.color), self, "Pick Color")
        if color.isValid():
            self._cfg.color = color.name().upper()
            self._refresh_color_btn()

    def _commit(self) -> None:
        text = self._label_edit.text().strip()
        self._cfg.label = text if text else self._cfg.channel_name
        self._cfg.visible = self._visible_cb.isChecked()
        self._cfg.y_scale = self._scale_spin.value()
        self._cfg.y_offset = self._offset_spin.value()
        self._cfg.digital = self._digital_cb.isChecked()
        self.accept()

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def result_config(self) -> ChannelConfig:
        """Return the edited config copy.  Call only after exec() → Accepted."""
        return self._cfg
