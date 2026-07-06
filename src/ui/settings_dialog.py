"""Application settings dialog.

Currently exposes signal downsampling parameters.  Additional settings
sections can be added as QGroupBox blocks in the future.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from utils.downsample import DOWNSAMPLE_TARGET, DOWNSAMPLE_THRESHOLD

_SETTINGS_ORG = "GraphMF4"
_SETTINGS_APP = "GraphMF4"


def load_downsample_settings() -> tuple[bool, int, int]:
    """Return (enabled, threshold, target) from persistent storage."""
    s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    enabled   = s.value("downsample/enabled",   True,                type=bool)
    threshold = s.value("downsample/threshold", DOWNSAMPLE_THRESHOLD, type=int)
    target    = s.value("downsample/target",    DOWNSAMPLE_TARGET,    type=int)
    return enabled, threshold, target


def load_opengl_setting() -> bool:
    """Return whether OpenGL rendering is enabled (requires app restart to take effect)."""
    s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    return s.value("render/opengl", False, type=bool)


class SettingsDialog(QDialog):
    """Modal settings dialog.  Reads from and writes to QSettings on OK."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Downsampling ───────────────────────────────────────────────
        ds_box = QGroupBox("Signal Downsampling (LTTB)")
        form = QFormLayout(ds_box)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._ds_enabled = QCheckBox("Enable automatic downsampling")
        self._ds_enabled.toggled.connect(self._on_enabled_toggled)
        form.addRow(self._ds_enabled)

        self._ds_threshold = QSpinBox()
        self._ds_threshold.setRange(1_000, 10_000_000)
        self._ds_threshold.setSingleStep(10_000)
        self._ds_threshold.setGroupSeparatorShown(True)
        self._ds_threshold.setSuffix(" samples")
        self._ds_threshold.setToolTip(
            "Channels with more samples than this value will be downsampled."
        )
        form.addRow("Threshold:", self._ds_threshold)

        self._ds_target = QSpinBox()
        self._ds_target.setRange(100, 50_000)
        self._ds_target.setSingleStep(500)
        self._ds_target.setGroupSeparatorShown(True)
        self._ds_target.setSuffix(" samples")
        self._ds_target.setToolTip(
            "Number of samples to keep after downsampling.\n"
            "5 000 is sufficient for a 4K display."
        )
        form.addRow("Target points:", self._ds_target)

        hint = QLabel(
            "LTTB (Largest-Triangle-Three-Buckets) preserves visual peaks and "
            "transitions while reducing the number of plotted points.\n"
            "Changes are applied immediately after clicking OK."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(hint)

        root.addWidget(ds_box)
        # ── Rendering ───────────────────────────────────────────────────────────────
        render_box = QGroupBox("Rendering")
        render_form = QFormLayout(render_box)
        render_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._opengl_cb = QCheckBox("Use OpenGL hardware acceleration")
        self._opengl_cb.setToolTip(
            "Enables pyqtgraph OpenGL rendering.\n"
            "Dramatically faster with many channels, but may cause visual artefacts\n"
            "on some GPU drivers (dashed lines, transparency).\n"
            "Restart the application for this setting to take effect."
        )
        render_form.addRow(self._opengl_cb)

        opengl_hint = QLabel(
            "\u26a0\ufe0f Requires application restart to take effect. "
            "Disable if you experience rendering glitches."
        )
        opengl_hint.setWordWrap(True)
        opengl_hint.setStyleSheet("color: gray; font-size: 11px;")
        render_form.addRow(opengl_hint)

        root.addWidget(render_box)
        # ── Buttons ────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        enabled, threshold, target = load_downsample_settings()
        self._ds_enabled.setChecked(enabled)
        self._ds_threshold.setValue(threshold)
        self._ds_target.setValue(target)
        self._on_enabled_toggled(enabled)
        self._opengl_cb.setChecked(load_opengl_setting())

    def _save_and_accept(self) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue("downsample/enabled",   self._ds_enabled.isChecked())
        s.setValue("downsample/threshold", self._ds_threshold.value())
        s.setValue("downsample/target",    self._ds_target.value())
        s.setValue("render/opengl",        self._opengl_cb.isChecked())
        self.accept()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_enabled_toggled(self, checked: bool) -> None:
        self._ds_threshold.setEnabled(checked)
        self._ds_target.setEnabled(checked)
