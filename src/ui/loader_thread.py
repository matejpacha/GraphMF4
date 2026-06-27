"""Background QThread for opening MF4 files without freezing the UI.

Usage::
    thread = MF4LoadThread(path)
    thread.load_finished.connect(on_done)   # (MDF, resolved_path_str)
    thread.load_error.connect(on_error)     # (error_str, original_path_str)
    thread.start()
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal


class MF4LoadThread(QThread):
    """Parses an MF4 file on a worker thread.

    Signals
    -------
    load_finished(mdf, resolved_path)
        Emitted on success with the open ``MDF`` handle and its resolved path.
    load_error(message, original_path)
        Emitted on failure with the error message and the original path string.
    """

    load_finished = Signal(object, str)   # (MDF handle, resolved absolute path)
    load_error = Signal(str, str)         # (error message, original path)

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def run(self) -> None:
        try:
            from asammdf import MDF  # import inside thread to avoid GIL issues at module load
            resolved = str(Path(self._path).resolve())
            mdf = MDF(resolved)
            self.load_finished.emit(mdf, resolved)
        except Exception as exc:
            self.load_error.emit(str(exc), self._path)
