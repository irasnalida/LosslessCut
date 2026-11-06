"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    app = QApplication(args)
    app.setApplicationName("LosslessCut")
    app.setApplicationDisplayName("LosslessCut")
    app.setOrganizationName("LosslessCut")
    app.setOrganizationDomain("losslesscut.local")
    apply_theme(app)

    window = MainWindow()
    window.show()

    if len(args) > 1:
        candidate = Path(args[1])
        if candidate.exists():
            window.open_path(candidate)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
