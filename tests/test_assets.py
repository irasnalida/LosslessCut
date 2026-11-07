from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase, QIcon

from losslesscut.icons import ICON_FILES, icon
from losslesscut.theme import load_fonts


def test_inter_font_is_bundled(qapp) -> None:
    family = load_fonts()
    assert family == "Inter"
    assert "Inter" in QFontDatabase.families()


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
