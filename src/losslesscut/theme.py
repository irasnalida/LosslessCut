"""Dark Fusion palette, bundled Inter typography and stylesheet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

FONT_DIR = Path(__file__).with_name("assets") / "fonts"
FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
)
_FONT_FAMILY: str | None = None
_FONTS_LOADED = False


def load_fonts() -> str | None:
    """Register the bundled Inter faces and return the family name."""
    global _FONT_FAMILY, _FONTS_LOADED
    if _FONTS_LOADED:
        return _FONT_FAMILY
    _FONTS_LOADED = True
    for name in FONT_FILES:
        path = FONT_DIR / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    families = set(QFontDatabase.families())
    for candidate in ("Inter", "Inter Variable"):
        if candidate in families:
            _FONT_FAMILY = candidate
            break
    return _FONT_FAMILY


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    family = load_fonts()
    font = QFont(app.font())
    if family:
        font.setFamily(family)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(_STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202326"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7eaec"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#16191b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#24282c"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2c3136"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f2f4f5"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e7eaec"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b3035"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e7eaec"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff6b6b"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#39b9c9"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0e93a5"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7b8389"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6b7277"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6b7277")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#6b7277")
    )
    app.setPalette(palette)


_STYLESHEET = """
QWidget {
    color: #e7eaec;
    font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog {
    background: #202326;
}
QMenuBar {
    background: #25292d;
    border-bottom: 1px solid #15181a;
    padding: 2px;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background: #343a40;
}
QMenu {
    background: #262b2f;
    border: 1px solid #3a4147;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #0e93a5;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #3a4147;
    margin: 4px 8px;
}
QToolBar {
    background: #25292d;
    border: none;
    border-bottom: 1px solid #15181a;
    spacing: 6px;
    padding: 5px 8px;
}
QToolBar::separator {
    background: #3a4147;
    width: 1px;
    margin: 4px 6px;
}
QStatusBar {
    background: #25292d;
    border-top: 1px solid #15181a;
    color: #aeb6bc;
}
QStatusBar::item {
    border: none;
}
QToolTip {
    background: #2c3136;
    color: #f2f4f5;
    border: 1px solid #4a5259;
    padding: 4px 6px;
}
QPushButton {
    background: #2b3035;
    border: 1px solid #3b4248;
    border-radius: 4px;
    padding: 5px 12px;
    min-height: 20px;
    font-weight: 500;
}
QPushButton:hover {
    background: #373e44;
    border-color: #4a535b;
}
QPushButton:pressed {
    background: #22272b;
}
QPushButton:checked {
    background: #0e93a5;
    border-color: #18a9bc;
    color: #ffffff;
}
QPushButton:disabled {
    background: #24282c;
    border-color: #30363b;
    color: #6b7277;
}
QPushButton#exportButton {
    background: #0e93a5;
    border-color: #18a9bc;
    color: #ffffff;
    font-weight: 600;
    padding: 7px 14px;
}
QPushButton#exportButton:hover {
    background: #10a5b8;
}
QPushButton#exportButton:disabled {
    background: #2b3035;
    border-color: #3b4248;
    color: #6b7277;
}
QPushButton#flatButton {
    background: transparent;
    border: 1px solid transparent;
    padding: 3px 6px;
}
QPushButton#flatButton:hover {
    background: #343a40;
    border-color: #444c53;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px;
}
QToolButton:hover {
    background: #343a40;
    border-color: #444c53;
}
QToolButton:pressed {
    background: #22272b;
}
QToolButton:disabled {
    background: transparent;
    border-color: transparent;
}
QCheckBox {
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #4a535b;
    border-radius: 3px;
    background: #16191b;
}
QCheckBox::indicator:checked {
    background: #0e93a5;
    border-color: #18a9bc;
}
QLineEdit, QDoubleSpinBox, QSpinBox {
    background: #16191b;
    border: 1px solid #3b4248;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #0e93a5;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: #18a9bc;
}
QComboBox {
    background: #2b3035;
    border: 1px solid #3b4248;
    border-radius: 4px;
    padding: 4px 24px 4px 8px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #4a535b;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #262b2f;
    border: 1px solid #3a4147;
    selection-background-color: #0e93a5;
    outline: none;
}
QScrollBar:horizontal {
    background: #1a1d20;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #464e55;
    min-width: 24px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #5a646c;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar:vertical {
    background: #1a1d20;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #464e55;
    min-height: 24px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #5a646c;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter::handle {
    background: #15181a;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    background: transparent;
    border: none;
}
QLabel#sectionTitle {
    color: #aeb6bc;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#emptyHint {
    color: #7b8389;
    font-size: 13px;
}
QLabel#muted {
    color: #8b949b;
}
QLabel#totalLabel {
    color: #cfd5d9;
    font-weight: 600;
}
QFrame#panel {
    background: #24282c;
    border: 1px solid #15181a;
}
QProgressDialog {
    background: #202326;
}
QProgressBar {
    background: #16191b;
    border: 1px solid #3b4248;
    border-radius: 4px;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    background: #0e93a5;
    border-radius: 3px;
}
"""
