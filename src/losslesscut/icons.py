"""Phosphor SVG icons rendered and recoloured for the dark theme."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = Path(__file__).with_name("assets")
ICON_DIR = ASSETS_DIR / "icons"

DEFAULT_COLOR = "#d7dcdf"
MUTED_COLOR = "#9aa3a9"
DISABLED_COLOR = "#6b7277"
ACCENT_COLOR = "#39b9c9"

ICON_FILES: dict[str, str] = {
    "arrow-counter-clockwise": "arrow-counter-clockwise.svg",
    "arrows-out": "arrows-out.svg",
    "caret-double-left": "caret-double-left.svg",
    "caret-double-right": "caret-double-right.svg",
    "caret-left": "caret-left.svg",
    "caret-right": "caret-right.svg",
    "export": "export.svg",
    "folder-open": "folder-open.svg",
    "folder-simple": "folder-simple.svg",
    "git-merge": "git-merge.svg",
    "hand-pointing": "hand-pointing.svg",
    "magnifying-glass-minus": "magnifying-glass-minus.svg",
    "magnifying-glass-plus": "magnifying-glass-plus.svg",
    "pause": "pause.svg",
    "play": "play.svg",
    "scissors": "scissors.svg",
    "scissors-fill": "scissors-fill.svg",
    "skip-back": "skip-back.svg",
    "skip-forward": "skip-forward.svg",
    "trash": "trash.svg",
    "x": "x.svg",
}


def available_icons() -> tuple[str, ...]:
    return tuple(sorted(ICON_FILES))


def _render(source: str, color: str, size: int) -> QPixmap:
    svg = source.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    if renderer.isValid():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
        painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


@lru_cache(maxsize=256)
def icon(name: str, color: str = DEFAULT_COLOR, size: int = 20) -> QIcon:
    """Return a recoloured Phosphor icon.

    ``currentColor`` in the SVG is replaced with *color* before rendering, so
    the same bundled file works on every surface. A grey disabled pixmap is
    registered as well, letting Qt dim icons automatically.
    """
    try:
        filename = ICON_FILES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown icon {name!r}") from exc
    path = ICON_DIR / filename
    if not path.exists():
        return QIcon()

    source = path.read_text(encoding="utf-8")
    result = QIcon()
    result.addPixmap(_render(source, color, size), QIcon.Mode.Normal)
    result.addPixmap(_render(source, DISABLED_COLOR, size), QIcon.Mode.Disabled)
    return result
