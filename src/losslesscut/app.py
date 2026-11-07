"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ffmpeg_utils import check_binaries
from .icons import ASSETS_DIR, available_icons, icon
from .main_window import MainWindow
from .theme import apply_theme, load_fonts


def _self_check() -> int:
    """Verify that the frozen application can load its bundled resources."""
    fonts = load_fonts()
    names = available_icons()
    missing_icons = [name for name in names if icon(name).isNull()]
    app_icon_path = ASSETS_DIR / "app.ico"
    app_icon_ok = app_icon_path.exists() and not QIcon(str(app_icon_path)).isNull()
    binaries = check_binaries()

    print(f"fonts: {fonts or 'missing'}")
    print(f"icons: {len(names) - len(missing_icons)}/{len(names)}")
    if missing_icons:
        print("missing icons: " + ", ".join(missing_icons))
    print(f"app icon: {'ok' if app_icon_ok else 'missing'}")
    print(f"ffmpeg: {binaries.ffmpeg or 'missing'}")
    print(f"ffprobe: {binaries.ffprobe or 'missing'}")

    healthy = (
        fonts == "Inter"
        and not missing_icons
        and app_icon_ok
        and binaries.ready
    )
    return 0 if healthy else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    self_check = "--self-check" in args
    args = [arg for arg in args if arg != "--self-check"]

    app = QApplication(args)
    app.setApplicationName("LosslessCut")
    app.setApplicationDisplayName("LosslessCut")
    app.setOrganizationName("LosslessCut")
    app.setOrganizationDomain("losslesscut.local")
    apply_theme(app)

    if self_check:
        return _self_check()

    app_icon_path = ASSETS_DIR / "app.ico"
    if app_icon_path.exists():
        app.setWindowIcon(QIcon(str(app_icon_path)))

    window = MainWindow()
    window.show()

    candidates = [arg for arg in args[1:] if not arg.startswith("--")]
    if candidates:
        candidate = Path(candidates[0])
        if candidate.exists():
            window.open_path(candidate)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
