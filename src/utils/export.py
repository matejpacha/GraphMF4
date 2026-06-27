"""Bitmap export utilities.

Uses Qt's QWidget.grab() to capture any widget into a QPixmap and saves
it to disk. Supported formats: PNG, BMP, JPEG (determined by file extension).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget


def export_widget_to_bitmap(widget: QWidget, path: str | Path) -> None:
    """Capture *widget* and write it to *path*.

    The output format is inferred from the file extension.
    Raises RuntimeError if the save fails.
    """
    path = Path(path)
    pixmap = widget.grab()
    if not pixmap.save(str(path)):
        raise RuntimeError(
            f"QPixmap.save() failed for '{path}'. "
            "Check that the directory exists and the format is supported."
        )
