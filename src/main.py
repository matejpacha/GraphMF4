"""Entry point for GraphMF4."""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

# Ensure src/ is on sys.path when running as `python src/main.py`
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def _resource_path(*parts: str) -> Path:
    """Resolve a resource path that works both in dev and in a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base.joinpath(*parts)


def _setup_logging() -> None:
    """Write INFO+ logs to %APPDATA%/GraphMF4/graphmf4.log (EXE and dev)."""
    log_dir = Path.home() / "AppData" / "Roaming" / "GraphMF4"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "graphmf4.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    # Also catch completely unhandled exceptions
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook


def main() -> None:
    _setup_logging()
    logging.info("GraphMF4 starting (Python %s, frozen=%s)", sys.version, getattr(sys, "frozen", False))
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GraphMF4")
    app.setOrganizationName("GraphMF4")
    # Fusion style respects QPalette on all platforms (needed for dark theme)
    app.setStyle("Fusion")

    icon_path = _resource_path("icon", "mf4_icon_multi.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # If a project file is passed on the command line, open it
    if len(sys.argv) > 1:
        project_path = sys.argv[1]
        if Path(project_path).is_file():
            window.open_project_from_path(project_path)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
