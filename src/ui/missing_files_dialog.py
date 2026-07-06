"""Dialog shown when MF4 files referenced in a project cannot be found.

Displays each missing path and lets the user browse to its new location.
Files left un-relocated are skipped silently (their channels show no data).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class MissingFilesDialog(QDialog):
    """Lists missing MF4 files and lets the user optionally relocate each one.

    After ``exec()``, call :meth:`relocations` to get a ``{old: new}`` mapping
    for every file the user successfully located.
    """

    def __init__(
        self,
        missing_paths: list[str],
        parent=None,
        start_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self._missing = missing_paths
        self._start_dir = start_dir
        # Maps old_path -> (QLineEdit for new path, status QLabel)
        self._edits: dict[str, QLineEdit] = {}
        self._status_labels: dict[str, QLabel] = {}

        self.setWindowTitle("Missing MF4 Files")
        self.setMinimumWidth(640)
        self.setMinimumHeight(280)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- header ----
        n = len(self._missing)
        msg = QLabel(
            f"<b>{n} MF4 file{'s' if n > 1 else ''} referenced in this project "
            f"could not be found.</b><br>"
            "Locate the files using the <b>Browse…</b> buttons, or click "
            "<b>Continue</b> to open the project without the missing signals."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        # ---- scrollable file list ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.StyledPanel)

        container = QWidget()
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setSpacing(6)
        self._container_layout.setContentsMargins(6, 6, 6, 6)

        for path in self._missing:
            self._container_layout.addWidget(self._make_row(path))

        self._container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # ---- buttons ----
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continue")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel (abort load)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_row(self, old_path: str) -> QWidget:
        row = QFrame()
        row.setFrameShape(QFrame.StyledPanel)
        row.setStyleSheet("QFrame { background: #fff8f8; }")
        rl = QVBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        rl.setSpacing(4)

        # Status label (shows missing / relocated state)
        status_lbl = QLabel(self._missing_text(old_path))
        status_lbl.setToolTip(old_path)
        status_lbl.setWordWrap(True)
        rl.addWidget(status_lbl)
        self._status_labels[old_path] = status_lbl

        # Browse row
        browse_row = QHBoxLayout()

        edit = QLineEdit()
        edit.setPlaceholderText("Not relocated — signals will be skipped")
        edit.setReadOnly(True)
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        browse_row.addWidget(edit, 1)
        self._edits[old_path] = edit

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(lambda _checked, op=old_path: self._browse(op))
        browse_row.addWidget(browse_btn)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(26)
        clear_btn.setToolTip("Clear relocation")
        clear_btn.clicked.connect(lambda _checked, op=old_path: self._clear(op))
        browse_row.addWidget(clear_btn)

        rl.addLayout(browse_row)
        return row

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse(self, old_path: str) -> None:
        # Prefer: start_dir passed by caller → parent of old path → cwd
        start = (
            self._start_dir
            or (str(Path(old_path).parent) if Path(old_path).parent.exists() else "")
        )
        suggested = Path(old_path).name
        new_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Locate: {suggested}",
            start,
            "Measurement Files (*.mf4 *.MF4 *.mdf *.MDF);;All Files (*)",
        )
        if new_path:
            self._edits[old_path].setText(new_path)
            self._status_labels[old_path].setText(self._relocated_text(old_path, new_path))
            # Update start_dir for next browse
            self._start_dir = str(Path(new_path).parent)

    def _clear(self, old_path: str) -> None:
        self._edits[old_path].clear()
        self._status_labels[old_path].setText(self._missing_text(old_path))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _missing_text(old_path: str) -> str:
        return (
            f'<span style="color:#c00;">&#9888; Missing: '
            f"<b>{Path(old_path).name}</b></span>"
        )

    @staticmethod
    def _relocated_text(old_path: str, new_path: str) -> str:
        return (
            f'<span style="color:#080;">&#10003; Relocated: '
            f"<b>{Path(old_path).name}</b> → {new_path}</span>"
        )

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def relocations(self) -> dict[str, str]:
        """Return ``{old_path: new_path}`` for every successfully relocated file.

        Only entries where the new path actually exists on disk are included.
        """
        return {
            old: edit.text().strip()
            for old, edit in self._edits.items()
            if edit.text().strip() and Path(edit.text().strip()).is_file()
        }
