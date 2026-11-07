"""Generate the application icon from the bundled Phosphor scissors fill glyph."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "losslesscut" / "assets"
OUTPUT = ROOT / "src" / "losslesscut" / "assets" / "app.ico"

SIZE = 256
MARGIN = 16
ACCENT = "#39b9c9"


def main() -> int:
    _app = QGuiApplication([])
    source_path = ICON_DIR / "icon.svg"
    source = source_path.read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(source.replace("currentColor", ACCENT).encode()))
    if not renderer.isValid():
        raise SystemExit(f"Could not load {source_path}")

    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(MARGIN, MARGIN, SIZE - MARGIN * 2, SIZE - MARGIN * 2))
    painter.end()

    if not image.save(str(OUTPUT), "ICO"):
        raise SystemExit(f"Could not write {OUTPUT}")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
