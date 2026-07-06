"""Dialog for replacing one MF4 file in the project with another."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class ReplaceFileDialog(QDialog):
    """Lets the user select which MF4 file to replace and browse for the replacement."""

    def __init__(self, mf4_files: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace MF4 File")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- original file ------------------------------------------
        layout.addWidget(QLabel("File to replace:"))
        self._old_combo = QComboBox()
        self._old_combo.addItems(mf4_files)
        layout.addWidget(self._old_combo)

        # ---- replacement file ---------------------------------------
        layout.addWidget(QLabel("Replace with:"))
        row = QHBoxLayout()
        self._new_edit = QLineEdit()
        self._new_edit.setPlaceholderText("Browse for a replacement MF4 file…")
        self._new_edit.setReadOnly(True)
        row.addWidget(self._new_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        # ---- buttons ------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        self._ok_btn.setEnabled(False)

    # ------------------------------------------------------------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Replacement MF4 File",
            filter="Measurement Files (*.mf4 *.MF4 *.mdf *.MDF);;All Files (*)",
        )
        if path:
            self._new_edit.setText(path)
            self._ok_btn.setEnabled(True)

    def old_path(self) -> str:
        return self._old_combo.currentText()

    def new_path(self) -> str:
        return self._new_edit.text()
