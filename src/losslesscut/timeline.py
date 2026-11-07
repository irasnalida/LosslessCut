"""Custom-painted, zoomable keyframe timeline."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygon,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

from .icons import MUTED_COLOR, icon
from .models import Segment, format_short_time

RULER_HEIGHT = 26
SEGMENT_TOP = 28
SEGMENT_HEIGHT = 46
KEYFRAME_TOP = 78
KEYFRAME_HEIGHT = 24
TIMELINE_HEIGHT = KEYFRAME_TOP + KEYFRAME_HEIGHT

SEGMENT_COLORS = (
    "#0e93a5",
    "#c58a2e",
    "#6b7ad6",
    "#b45fa8",
    "#5e9f63",
    "#bf5f5f",
    "#4f9bb8",
    "#9a7b4f",
)


def nice_interval(target: float) -> float:
    """Return a 1/2/5 * 10^n step near *target*."""
    if target <= 0 or not math.isfinite(target):
        return 1.0
    exponent = math.floor(math.log10(target))
    base = target / (10**exponent)
    for candidate in (1.0, 2.0, 5.0, 10.0):
        if base <= candidate:
            return candidate * (10**exponent)
    return 10 ** (exponent + 1)


class TimelineWidget(QWidget):
    """Paint keyframes, segments and the playhead over a shared time axis."""

    seek_requested = Signal(float)
    segment_selected = Signal(int)
    view_changed = Signal(float, float, float)  # pixels/second, start, zoom factor

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(TIMELINE_HEIGHT)
        self.setMaximumHeight(TIMELINE_HEIGHT)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._duration = 0.0
        self._keyframes: list[float] = []
        self._segments: list[Segment] = []
        self._selected = -1
        self._current_time = 0.0
        self._fps = 0.0

        self._pps = 1.0
        self._start = 0.0
        self._has_view = False
        self._hover_x = -1
        self._scrubbing = False
        self._panning = False
        self._pan_x = 0.0
        self._pan_start = 0.0

    # ------------------------------------------------------------------ data
    @property
    def duration(self) -> float:
        return self._duration

    @property
    def pps(self) -> float:
        return self._pps

    @property
    def view_start(self) -> float:
        return self._start

    @property
    def view_duration(self) -> float:
        if self._pps <= 0:
            return 0.0
        return self.width() / self._pps

    @property
    def zoom_factor(self) -> float:
        fit = self._fit_pps()
        return self._pps / fit if fit > 0 else 1.0

    def set_media(self, duration: float, keyframes: list[float], fps: float) -> None:
        self._duration = max(0.0, duration)
        self._keyframes = sorted(keyframes)
        self._segments = []
        self._selected = -1
        self._current_time = 0.0
        self._fps = fps
        self._has_view = False
        self.fit()

    def set_segments(self, segments: list[Segment], selected: int = -1) -> None:
        self._segments = list(segments)
        self._selected = selected if 0 <= selected < len(segments) else -1
        self.update()

    def set_keyframes(self, keyframes: list[float]) -> None:
        self._keyframes = sorted(keyframes)
        self.update()

    def ensure_time_visible(self, value: float) -> None:
        if self._duration <= 0:
            return
        x = self.time_to_x(value)
        if -4 <= x <= self.width() + 4:
            return
        self._start = value - self.view_duration * 0.2
        self._clamp_view()
        self.update()
        self._emit_view()

    def set_current_time(self, value: float) -> None:
        self._current_time = max(0.0, min(value, self._duration if self._duration > 0 else value))
        self.update()

    def set_view_start(self, start: float) -> None:
        self._start = start
        self._clamp_view()
        self.update()
        self._emit_view()

    def set_zoom_factor(self, factor: float, anchor: float | None = None) -> None:
        if self._duration <= 0:
            return
        anchor_time = anchor if anchor is not None else self._start + self.view_duration / 2
        target = max(0.05, min(2000.0, factor))
        self._pps = max(1e-4, self._fit_pps() * target)
        self._start = anchor_time - (self.view_duration / 2)
        self._clamp_view()
        self.update()
        self._emit_view()

    def zoom_by(self, factor: float, anchor_x: float | None = None) -> None:
        if self._duration <= 0:
            return
        x = self.width() / 2 if anchor_x is None else anchor_x
        anchor_time = self.x_to_time(x)
        new_pps = self._pps * factor
        fit = self._fit_pps()
        max_pps = min(6000.0, max(600.0, self._fps * 20.0))
        new_pps = max(fit * 0.5, min(new_pps, max_pps))
        self._pps = new_pps
        self._start = anchor_time - x / self._pps
        self._clamp_view()
        self.update()
        self._emit_view()

    def fit(self) -> None:
        if self._duration <= 0 or self.width() <= 0:
            self._pps = 1.0
            self._start = 0.0
            self._has_view = False
            self.update()
            return
        self._pps = self._fit_pps()
        self._start = 0.0
        self._has_view = True
        self.update()
        self._emit_view()

    # -------------------------------------------------------------- geometry
    def time_to_x(self, value: float) -> float:
        return (value - self._start) * self._pps

    def x_to_time(self, x: float) -> float:
        if self._pps <= 0:
            return 0.0
        return self._start + x / self._pps

    def _fit_pps(self) -> float:
        if self._duration <= 0 or self.width() <= 0:
            return 1.0
        return max(1e-4, self.width() / self._duration)

    def _visible_duration(self) -> float:
        return self.width() / self._pps if self._pps > 0 else 0.0

    def _clamp_view(self) -> None:
        if self._duration <= 0:
            self._start = 0.0
            return
        visible = self._visible_duration()
        max_start = max(0.0, self._duration - visible)
        self._start = max(0.0, min(self._start, max_start))

    def _emit_view(self) -> None:
        self.view_changed.emit(self._pps, self._start, self.zoom_factor)

    def _segment_at(self, x: float) -> int:
        if not (SEGMENT_TOP <= self._mouse_y <= SEGMENT_TOP + SEGMENT_HEIGHT):
            return -1
        for index, segment in enumerate(self._segments):
            x1 = self.time_to_x(segment.start)
            x2 = self.time_to_x(segment.end)
            if x1 - 2 <= x <= x2 + 2:
                return index
        return -1

    @property
    def _mouse_y(self) -> int:
        return getattr(self, "_hover_y", -1)

    # ---------------------------------------------------------------- events
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._duration > 0 and not self._has_view:
            self.fit()
        else:
            self._clamp_view()
            self._emit_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._duration <= 0:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._start -= delta / 120.0 * (self.view_duration * 0.15)
            self._clamp_view()
            self.update()
            self._emit_view()
        else:
            factor = 1.25 if delta > 0 else 1 / 1.25
            self.zoom_by(factor, event.position().x())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._duration <= 0:
            return
        x = event.position().x()
        y = event.position().y()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_x = x
            self._pan_start = self._start
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._scrubbing = True
            self._hover_y = int(y)
            index = self._segment_at(x)
            if index >= 0:
                self.segment_selected.emit(index)
            self._seek_to_x(x)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._hover_x = int(event.position().x())
        self._hover_y = int(event.position().y())
        if self._panning:
            dx = event.position().x() - self._pan_x
            self._start = self._pan_start - dx / self._pps
            self._clamp_view()
            self._emit_view()
        elif self._scrubbing:
            self._seek_to_x(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
        if event.button() == Qt.MouseButton.LeftButton:
            self._scrubbing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_x = -1
        self._hover_y = -1
        self.update()
        super().leaveEvent(event)

    def _seek_to_x(self, x: float) -> None:
        value = max(0.0, min(self.x_to_time(x), self._duration))
        self.seek_requested.emit(value)

    # ----------------------------------------------------------------- paint
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        width = self.width()
        painter.fillRect(self.rect(), QColor("#1a1d20"))
        if self._duration <= 0:
            painter.setPen(QColor("#6f777d"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No video loaded")
            painter.end()
            return

        self._paint_ruler(painter, width)
        self._paint_segments(painter)
        self._paint_keyframes(painter, width)
        self._paint_playhead(painter)
        painter.end()

    def _paint_ruler(self, painter: QPainter, width: int) -> None:
        painter.fillRect(QRect(0, 0, width, RULER_HEIGHT), QColor("#202427"))
        painter.setPen(QPen(QColor("#343a3f"), 1))
        painter.drawLine(0, RULER_HEIGHT - 1, width, RULER_HEIGHT - 1)

        target = 100.0 / max(self._pps, 1e-4)
        interval = nice_interval(target)
        first = math.floor(self._start / interval) * interval
        value = first
        font = QFont(self.font())
        font.setPointSize(8)
        painter.setFont(font)
        while value <= self._start + self.view_duration + interval:
            x = self.time_to_x(value)
            if -50 <= x <= width + 50:
                painter.setPen(QPen(QColor("#596167"), 1))
                painter.drawLine(int(x), RULER_HEIGHT - 7, int(x), RULER_HEIGHT - 1)
                painter.setPen(QColor("#a5adb2"))
                label = self._ruler_label(value, interval)
                painter.drawText(int(x) + 4, RULER_HEIGHT - 9, label)
                if interval / 5 * self._pps >= 8:
                    for step in range(1, 5):
                        minor = value + interval * step / 5
                        mx = self.time_to_x(minor)
                        painter.setPen(QPen(QColor("#3b4247"), 1))
                        painter.drawLine(int(mx), RULER_HEIGHT - 4, int(mx), RULER_HEIGHT - 1)
            value += interval

    def _ruler_label(self, value: float, interval: float) -> str:
        seconds = max(0.0, value)
        minutes = int(seconds // 60)
        secs = seconds - minutes * 60
        hours = minutes // 60
        minutes = minutes % 60
        if interval < 1.0:
            return f"{minutes}:{secs:04.1f}"
        if hours > 0 or self._duration >= 3600:
            return f"{hours}:{minutes:02d}:{int(secs):02d}"
        return f"{minutes}:{int(secs):02d}"

    def _paint_segments(self, painter: QPainter) -> None:
        band = QRect(0, SEGMENT_TOP, self.width(), SEGMENT_HEIGHT)
        painter.fillRect(band, QColor("#171a1c"))
        for index, segment in enumerate(self._segments):
            x1 = self.time_to_x(segment.start)
            x2 = self.time_to_x(segment.end)
            if x2 < -4 or x1 > self.width() + 4:
                continue
            left = max(-2.0, x1)
            right = min(self.width() + 2.0, x2)
            if right - left < 1:
                right = left + 1
            color = QColor(SEGMENT_COLORS[index % len(SEGMENT_COLORS)])
            if not segment.enabled:
                color.setAlpha(70)
            else:
                color.setAlpha(210 if index == self._selected else 160)
            rect = QRectF(left + 1, SEGMENT_TOP + 5, max(1.0, right - left - 2), SEGMENT_HEIGHT - 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 5, 5)

            if index == self._selected:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#f2f5f6"), 2))
                painter.drawRoundedRect(rect, 5, 5)

            if right - left >= 18:
                badge = QRectF(left + 5, SEGMENT_TOP + 9, 18, 18)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 95))
                painter.drawRoundedRect(badge, 4, 4)
                font = QFont(self.font())
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), str(index + 1))
            if right - left >= 105:
                font = QFont(self.font())
                font.setPointSize(8)
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255, 210))
                label = format_short_time(segment.duration)
                painter.drawText(
                    QRectF(left + 28, SEGMENT_TOP + 8, right - left - 34, 20),
                    int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter),
                    label,
                )

        if self._hover_x >= 0:
            painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
            painter.drawLine(self._hover_x, RULER_HEIGHT, self._hover_x, self.height())

    def _paint_keyframes(self, painter: QPainter, width: int) -> None:
        band = QRect(0, KEYFRAME_TOP, width, KEYFRAME_HEIGHT)
        painter.fillRect(band, QColor("#15181a"))
        if not self._keyframes:
            return
        visible = self._keyframes[
            bisect_left(self._keyframes, self._start - 0.01) : bisect_right(
                self._keyframes, self._start + self.view_duration + 0.01
            )
        ]
        if not visible:
            return
        spacing = self._pps * (
            (visible[-1] - visible[0]) / max(1, len(visible) - 1) if len(visible) > 1 else 1.0
        )
        if spacing >= 3.0:
            painter.setPen(QPen(QColor("#5f6a71"), 1))
            for value in visible:
                x = int(self.time_to_x(value))
                painter.drawLine(x, KEYFRAME_TOP + 4, x, KEYFRAME_TOP + KEYFRAME_HEIGHT - 3)
        else:
            counts = [0] * max(1, width)
            for value in visible:
                x = int(self.time_to_x(value))
                if 0 <= x < width:
                    counts[x] += 1
            for x, count in enumerate(counts):
                if count:
                    alpha = min(255, 80 + count * 55)
                    painter.fillRect(
                        x, KEYFRAME_TOP + 7, 1, KEYFRAME_HEIGHT - 12, QColor(80, 160, 175, alpha)
                    )
        painter.setPen(QPen(QColor("#2c3237"), 1))
        painter.drawLine(0, KEYFRAME_TOP, width, KEYFRAME_TOP)
        painter.drawLine(0, self.height() - 1, width, self.height() - 1)

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self.time_to_x(self._current_time)
        if x < -8 or x > self.width() + 8:
            return
        painter.setPen(QPen(QColor(0, 0, 0, 140), 4))
        painter.drawLine(int(x) + 1, 0, int(x) + 1, self.height())
        painter.setPen(QPen(QColor("#f2f5f6"), 2))
        painter.drawLine(int(x), 0, int(x), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f2f5f6"))
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(int(x) - 6, 0),
                    QPoint(int(x) + 6, 0),
                    QPoint(int(x), 8),
                ]
            )
        )


class TimelinePanel(QWidget):
    """Timeline plus its scrollbar and zoom controls."""

    seek_requested = Signal(float)
    segment_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timeline = TimelineWidget(self)
        self.scroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self.scroll.setRange(0, 0)
        self.scroll.setSingleStep(100)
        self.zoom_out_button = QPushButton(self)
        self.zoom_in_button = QPushButton(self)
        self.fit_button = QPushButton(self)
        self.zoom_out_button.setIcon(icon("magnifying-glass-minus", MUTED_COLOR, 15))
        self.zoom_in_button.setIcon(icon("magnifying-glass-plus", MUTED_COLOR, 15))
        self.fit_button.setIcon(icon("arrows-out", MUTED_COLOR, 15))
        self.zoom_label = QLabel("1.0x", self)
        self.zoom_label.setMinimumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setObjectName("muted")

        for button, name in (
            (self.zoom_out_button, "Zoom out"),
            (self.zoom_in_button, "Zoom in"),
            (self.fit_button, "Fit the whole video"),
        ):
            button.setObjectName("flatButton")
            button.setFixedSize(28, 22)
            button.setIconSize(QSize(15, 15))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(name)
        self.zoom_out_button.setToolTip("Zoom out (−)")
        self.zoom_in_button.setToolTip("Zoom in (+)")
        self.fit_button.setToolTip("Fit the whole video (F)")

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 0, 8, 4)
        controls.setSpacing(4)
        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.zoom_label)
        controls.addWidget(self.zoom_in_button)
        controls.addWidget(self.fit_button)
        controls.addSpacing(8)
        controls.addWidget(self.scroll, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.timeline)
        layout.addLayout(controls)

        self.timeline.seek_requested.connect(self.seek_requested)
        self.timeline.segment_selected.connect(self.segment_selected)
        self.timeline.view_changed.connect(self._on_view_changed)
        self.scroll.valueChanged.connect(self._on_scroll)
        self.zoom_in_button.clicked.connect(lambda: self.timeline.zoom_by(1.5))
        self.zoom_out_button.clicked.connect(lambda: self.timeline.zoom_by(1 / 1.5))
        self.fit_button.clicked.connect(self.timeline.fit)
        self._updating_scroll = False

    def set_media(self, duration: float, keyframes: list[float], fps: float) -> None:
        self.timeline.set_media(duration, keyframes, fps)
        if duration <= 0:
            self._updating_scroll = True
            self.scroll.setRange(0, 0)
            self.scroll.setValue(0)
            self._updating_scroll = False
            self.zoom_label.setText("1.0x")

    def set_segments(self, segments: list[Segment], selected: int = -1) -> None:
        self.timeline.set_segments(segments, selected)

    def set_keyframes(self, keyframes: list[float]) -> None:
        self.timeline.set_keyframes(keyframes)

    def set_current_time(self, value: float) -> None:
        self.timeline.set_current_time(value)

    def ensure_time_visible(self, value: float) -> None:
        self.timeline.ensure_time_visible(value)

    def fit(self) -> None:
        self.timeline.fit()

    def zoom_by(self, factor: float) -> None:
        self.timeline.zoom_by(factor)

    def _on_view_changed(self, pps: float, start: float, factor: float) -> None:
        duration = self.timeline.duration
        visible = self.timeline.view_duration
        max_start = max(0.0, duration - visible)
        self._updating_scroll = True
        self.scroll.setRange(0, int(max_start * 1000))
        self.scroll.setPageStep(max(1, int(visible * 1000)))
        self.scroll.setValue(int(min(start, max_start) * 1000))
        self._updating_scroll = False
        self.zoom_label.setText(f"{factor:.1f}x" if factor < 10 else f"{factor:.0f}x")

    def _on_scroll(self, value: int) -> None:
        if self._updating_scroll:
            return
        self.timeline.set_view_start(value / 1000.0)
