"""Generate the application icon from the bundled Phosphor scissors glyph."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src" / "losslesscut" / "assets" / "icons"
OUTPUT = ROOT / "src" / "losslesscut" / "assets" / "app.ico"

SIZE = 256
BACKGROUND = "#202326"
ACCENT = "#39b9c9"


def main() -> int:
    _app = QGuiApplication([])
    source = (ICON_DIR / "scissors.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(source.replace("currentColor", ACCENT).encode()))
    if not renderer.isValid():
        raise SystemExit(f"Could not load {ICON_DIR / 'scissors.svg'}")

    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BACKGROUND))
    painter.drawRoundedRect(QRectF(8, 8, SIZE - 16, SIZE - 16), 52, 52)
    renderer.render(painter, QRectF(48, 48, SIZE - 96, SIZE - 96))
    painter.end()

    if not image.save(str(OUTPUT), "ICO"):
        raise SystemExit(f"Could not write {OUTPUT}")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
