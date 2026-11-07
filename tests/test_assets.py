from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase, QIcon, QImage

from losslesscut.icons import ASSETS_DIR, ICON_FILES, icon
from losslesscut.theme import load_fonts


def test_inter_font_is_bundled(qapp) -> None:
    family = load_fonts()
    assert family == "Inter"
    assert "Inter" in QFontDatabase.families()


def test_app_icon_is_bundled(qapp) -> None:
    path = ASSETS_DIR / "app.ico"
    assert path.exists()
    rendered = QIcon(str(path))
    assert not rendered.isNull()
    assert not rendered.pixmap(32, 32).isNull()


def test_app_icon_has_transparent_background(qapp) -> None:
    image = QImage(str(ASSETS_DIR / "app.ico")).convertToFormat(
        QImage.Format.Format_ARGB32
    )
    assert not image.isNull()
    width, height = image.width(), image.height()
    corners = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    for x, y in corners:
        assert image.pixelColor(x, y).alpha() == 0
    assert image.pixelColor(width // 2, height // 2).alpha() > 0


@pytest.mark.parametrize("name", sorted(ICON_FILES))
def test_phosphor_icon_renders(qapp, name: str) -> None:
    rendered = icon(name)
    assert isinstance(rendered, QIcon)
    assert not rendered.isNull()
    pixmap = rendered.pixmap(20, 20)
    assert not pixmap.isNull()
    assert pixmap.width() == 20
    disabled = rendered.pixmap(20, 20, QIcon.Mode.Disabled)
    assert not disabled.isNull()


def test_unknown_icon_name_raises() -> None:
    with pytest.raises(KeyError):
        icon("not-a-real-icon")
