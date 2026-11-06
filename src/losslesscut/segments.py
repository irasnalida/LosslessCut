"""Segment export list panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import MediaInfo, Segment, format_size, format_timecode
from .timeline import SEGMENT_COLORS


class SegmentCard(QFrame):
    clicked = Signal()
    double_clicked = Signal()
    remove_requested = Signal()

    def __init__(self, index: int, segment: Segment, media: MediaInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(66)

        color = SEGMENT_COLORS[index % len(SEGMENT_COLORS)]
        badge = QLabel(str(index + 1), self)
        badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {color}; color: white; border-radius: 11px; font-weight: 700;"
        )

        range_label = QLabel(
            f"{format_timecode(segment.start)}  –  {format_timecode(segment.end)}", self
        )
        range_label.setStyleSheet("font-weight: 600; color: #e7eaec;")

        stats = (
            f"Duration {format_timecode(segment.duration)}"
            f"  ·  {segment.frame_count(media.fps):,} frames"
            f"  ·  ~{format_size(segment.estimated_size(media.estimated_bitrate))}"
        )
        stats_label = QLabel(stats, self)
        stats_label.setObjectName("muted")
        stats_label.setStyleSheet("color: #939da4; font-size: 11px;")

        remove_button = QToolButton(self)
        remove_button.setText("✕")
        remove_button.setToolTip("Remove this segment")
        remove_button.setCursor(Qt.CursorShape.ArrowCursor)
        remove_button.setStyleSheet(
            "QToolButton { border: none; background: transparent; color: #879198; "
            "font-size: 11px; padding: 2px; } "
            "QToolButton:hover { color: #ff6b6b; }"
        )
        remove_button.clicked.connect(self.remove_requested)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(range_label)
        text_layout.addWidget(stats_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 6, 7)
        layout.setSpacing(8)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_layout, 1)
        layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignTop)

        self._apply_style(False)

    def _apply_style(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "QFrame#segmentCard { background: #2f373c; border: 2px solid #18a9bc; "
                "border-radius: 6px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#segmentCard { background: #292e33; border: 1px solid #3b4248; "
                "border-radius: 6px; }"
            )

    def set_selected(self, selected: bool) -> None:
        self._apply_style(selected)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class SegmentPanel(QFrame):
    selection_changed = Signal(int)
    export_requested = Signal()
    remove_requested = Signal(int)
    segment_activated = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setMinimumWidth(290)
        self.setMaximumWidth(420)
        self._cards: list[SegmentCard] = []
        self._selected = -1

        title = QLabel("SEGMENTS TO EXPORT", self)
        title.setObjectName("sectionTitle")
        self.count_label = QLabel("0", self)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setFixedSize(22, 18)
        self.count_label.setStyleSheet(
            "background: #343b41; border-radius: 4px; color: #cfd5d9; font-weight: 700;"
        )
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.count_label)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setSpacing(2)
        self.list.setUniformItemSizes(True)
        self.list.currentRowChanged.connect(self._on_row_changed)
        self.list.itemDoubleClicked.connect(
            lambda item: self.segment_activated.emit(self.list.row(item))
        )

        empty = QLabel(
            "No segments yet.\nSplit the full-length segment at a keyframe to start cutting.",
            self,
        )
        empty.setObjectName("emptyHint")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.empty_label = empty

        self.total_label = QLabel("Total: 00:00:00.000", self)
        self.total_label.setObjectName("totalLabel")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Separate files", "separate")
        self.mode_combo.addItem("Merge into one file", "merge")
        self.mode_combo.setToolTip("Export each segment, or concatenate them into one video")

        self.export_button = QPushButton("Export", self)
        self.export_button.setObjectName("exportButton")
        self.export_button.setToolTip("Export the listed segments (Ctrl+E)")

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        footer.addWidget(self.mode_combo, 1)
        footer.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.total_label)
        layout.addLayout(footer)

        self.export_button.clicked.connect(self.export_requested)

    # ------------------------------------------------------------------ data
    def set_segments(
        self, segments: list[Segment], media: MediaInfo | None, selected: int = -1
    ) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        self._cards.clear()
        if media is not None:
            for index, segment in enumerate(segments):
                item = QListWidgetItem()
                card = SegmentCard(index, segment, media, self.list)
                card.set_selected(index == selected)
                card.clicked.connect(lambda idx=index: self._select_row(idx))
                card.double_clicked.connect(
                    lambda idx=index: self.segment_activated.emit(idx)
                )
                card.remove_requested.connect(lambda idx=index: self.remove_requested.emit(idx))
                item.setSizeHint(card.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, card)
                self._cards.append(card)
        self.empty_label.setVisible(not segments)
        self.list.setVisible(bool(segments))
        self.count_label.setText(str(len(segments)))
        self.total_label.setText(f"Total: {format_timecode(sum(s.duration for s in segments))}")
        self._selected = selected
        if 0 <= selected < self.list.count():
            self.list.setCurrentRow(selected)
        else:
            self.list.setCurrentRow(-1)
        self.list.blockSignals(False)

    def set_selected(self, index: int) -> None:
        if index == self._selected:
            return
        self._selected = index
        for i, card in enumerate(self._cards):
            card.set_selected(i == index)
        self.list.blockSignals(True)
        self.list.setCurrentRow(index if 0 <= index < self.list.count() else -1)
        self.list.blockSignals(False)

    def set_exporting(self, exporting: bool) -> None:
        self.export_button.setEnabled(not exporting)
        self.mode_combo.setEnabled(not exporting)
        self.export_button.setText("Exporting…" if exporting else "Export")

    def export_mode(self) -> str:
        return str(self.mode_combo.currentData() or "separate")

    def _select_row(self, index: int) -> None:
        if 0 <= index < self.list.count():
            self.list.setCurrentRow(index)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        self._selected = row
        for index, card in enumerate(self._cards):
            card.set_selected(index == row)
        self.selection_changed.emit(row)
