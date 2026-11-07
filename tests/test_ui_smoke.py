from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

import losslesscut.main_window as main_window_module
from losslesscut.models import Segment
from losslesscut.segments import SegmentPanel
from losslesscut.timeline import SEGMENT_HEIGHT, SEGMENT_TOP, TimelinePanel


def test_timeline_renders(qtbot) -> None:
    panel = TimelinePanel()
    qtbot.addWidget(panel)
    panel.resize(1000, 140)
    panel.set_media(10.0, [0.0, 1.0, 2.5, 4.0, 6.0, 8.0, 10.0], 30.0)
    panel.set_segments([Segment(0.0, 4.0), Segment(6.0, 10.0)], 0)
    panel.set_current_time(2.5)
    panel.timeline.zoom_by(2.0)
    image = panel.grab().toImage()
    assert not image.isNull()
    assert image.width() == 1000


def test_segment_panel_renders(qtbot, sample_media) -> None:
    panel = SegmentPanel()
    qtbot.addWidget(panel)
    panel.resize(340, 500)
    panel.set_segments(
        [Segment(1.0, 2.0), Segment(3.0, 4.5)],
        sample_media,
        1,
    )
    assert panel.count_label.text() == "2"
    assert "Total:" in panel.total_label.text()
    image = panel.grab().toImage()
    assert not image.isNull()


def test_segment_panel_reports_snapped_start(qtbot, sample_media) -> None:
    panel = SegmentPanel()
    qtbot.addWidget(panel)
    panel.resize(340, 500)
    panel.set_segments(
        [Segment(1.0, 2.0, requested_start=1.4), Segment(3.0, 4.5)],
        sample_media,
        0,
    )

    snapped = panel._cards[0]
    texts = [label.text() for label in snapped.findChildren(QLabel)]
    assert any("0.400s before your mark" in text for text in texts)
    assert "00:00:01.400" in snapped.toolTip()
    assert snapped.minimumHeight() == 84
    assert snapped.maximumHeight() == 84
    assert panel._cards[1].minimumHeight() == 66
    assert not panel.grab().toImage().isNull()


def test_timeline_marks_included_footage(qtbot) -> None:
    panel = TimelinePanel()
    qtbot.addWidget(panel)
    panel.resize(1000, 200)
    panel.timeline.resize(1000, 200)
    panel.set_media(10.0, [], 30.0)
    panel.set_segments([Segment(3.0, 6.0, requested_start=4.0)], 0)

    image = panel.timeline.grab().toImage()
    assert image.width() == 1000

    def amber_pixels(start: int, end: int) -> int:
        count = 0
        for x in range(start, end):
            for y in range(SEGMENT_TOP + 8, SEGMENT_TOP + SEGMENT_HEIGHT - 8):
                pixel = image.pixelColor(x, y)
                if pixel.red() > 100 and pixel.red() > pixel.blue() + 10:
                    count += 1
        return count

    # The requested mark was 4.0s; the export starts at 3.0s, so 3.0-4.0 is shaded.
    assert amber_pixels(305, 395) > 50
    assert amber_pixels(420, 590) < 5

    panel.timeline._hover_y = SEGMENT_TOP + 10
    assert panel.timeline._segment_at(350) == 0
    assert panel.timeline._segment_at(290) == -1


def test_main_window_smoke(qtbot, monkeypatch, tmp_path: Path, sample_media) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle() == "LosslessCut"
    assert not window.export_action.isEnabled()
    assert not window.play_button.icon().isNull()
    assert not window.split_action.icon().isNull()
    assert not window.export_action.icon().isNull()
    assert not window.open_action.icon().isNull()
    assert not window.mark_start_button.icon().isNull()
    assert not window.mark_end_button.icon().isNull()
    assert not window.mark_start_action.icon().isNull()
    assert not window.mark_end_action.icon().isNull()
    assert not window.mark_start_button.isEnabled()
    assert not window.mark_end_button.isEnabled()

    window.media = sample_media
    window.keyframes = list(sample_media.keyframes)
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    window.current_time = 3.0
    window._split_at_playhead()
    assert len(window.segments) == 2
    assert window.segments[0].end == 3.0
    assert [segment.start for segment in window.segments] == sorted(
        segment.start for segment in window.segments
    )
    window.close()


def test_mark_segment_start_and_end(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.keyframes = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    monkeypatch.setattr(window.preview, "seek", lambda *args, **kwargs: None)

    # Marking a start replaces the untouched full-length segment.
    window.current_time = 2.4
    window._mark_segment_start()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 3.0)]
    assert window.segments[0].requested_start == pytest.approx(2.4)
    assert window.selected_segment == 0
    assert window.current_time == pytest.approx(2.0)
    message = window.statusBar().currentMessage()
    assert "snapped back 0.400s" in message
    assert "00:00:02.400" in message

    # Marking the end cuts exactly at the playhead, not the next keyframe.
    window.current_time = 4.6
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 4.6)]
    assert window.segments[0].requested_start == pytest.approx(2.4)
    assert window.selected_segment == 0
    assert "00:00:04.600" in window.statusBar().currentMessage()

    # Extend-only: a playhead before the current end leaves it unchanged.
    window.current_time = 3.0
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 4.6)]

    # An earlier start is appended and sorted before existing segments.
    window.current_time = 0.2
    window._mark_segment_start()
    assert [(s.start, s.end) for s in window.segments] == [(0.0, 1.0), (2.0, 4.6)]
    assert window.segments[0].requested_start == pytest.approx(0.2)
    assert window.selected_segment == 0

    # Repeating the same start selects the existing segment.
    window.current_time = 0.2
    window._mark_segment_start()
    assert len(window.segments) == 2
    assert window.selected_segment == 0

    # With no selection, mark-end extends the chronologically last segment.
    window.selected_segment = -1
    window.current_time = 5.5
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(0.0, 1.0), (2.0, 5.5)]
    assert window.selected_segment == 1

    # With no segments, mark-end is a no-op.
    window.segments = []
    window.selected_segment = -1
    window.current_time = 2.0
    window._mark_segment_end()
    assert window.segments == []

    window.close()


def test_mark_start_on_keyframe_reports_no_snap(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.keyframes = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    monkeypatch.setattr(window.preview, "seek", lambda *args, **kwargs: None)

    window.current_time = 2.0
    window._mark_segment_start()

    assert [(s.start, s.end) for s in window.segments] == [(2.0, 3.0)]
    assert window.segments[0].requested_start is None
    assert "snapped" not in window.statusBar().currentMessage()
    window.close()


def test_mark_start_keeps_segments_sorted(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.keyframes = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    monkeypatch.setattr(window.preview, "seek", lambda *args, **kwargs: None)

    window.current_time = 5.2
    window._mark_segment_start()
    window.current_time = 2.2
    window._mark_segment_start()

    assert [(s.start, s.end) for s in window.segments] == [(2.0, 3.0), (5.0, 6.0)]
    assert window.selected_segment == 0
    window.close()


def test_image_drop_keeps_segments_sorted(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.keyframes = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    window.segments = [Segment(4.0, 5.0)]
    window.selected_segment = 0
    monkeypatch.setattr(window.preview, "seek", lambda *args, **kwargs: None)

    image = tmp_path / "T00'00'02'500.png"
    image.write_bytes(b"")
    window._add_segments_from_images([image])

    assert [(s.start, s.end) for s in window.segments] == [(2.0, 3.0), (4.0, 5.0)]
    assert window.selected_segment == 0
    assert "00:00:02.000" in window.statusBar().currentMessage()
    window.close()


def test_image_drop_creates_keyframe_segment(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.keyframes = list(sample_media.keyframes)
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    monkeypatch.setattr(window.preview, "seek", lambda *args, **kwargs: None)

    image = tmp_path / "Outer Banks - T00'00'02'500.png"
    image.write_bytes(b"")

    window._keyframes_loading = True
    window._queue_or_add_images([image])
    assert window._pending_images == [image]
    window._keyframes_loading = False
    window._flush_pending_images()

    assert len(window.segments) == 1
    assert window.segments[0].start == pytest.approx(2.0)
    assert window.segments[0].end == pytest.approx(3.0)
    assert window.selected_segment == 0

    # Dropping the same image again selects rather than duplicates.
    window._add_segments_from_images([image])
    assert len(window.segments) == 1

    # An edited segment list is appended to instead of replaced.
    window.segments = [Segment(0.0, 1.0)]
    window.selected_segment = 0
    window._add_segments_from_images([image])
    assert len(window.segments) == 2
    assert window.segments[-1].start == pytest.approx(2.0)

    # Timestamps outside the video are ignored.
    outside = tmp_path / "T00'00'09'000.png"
    outside.write_bytes(b"")
    window._add_segments_from_images([outside])
    assert len(window.segments) == 2

    window.close()


def test_start_export_cancels_on_snapped_segment(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    window.segments = [Segment(1.0, 2.0, requested_start=1.6)]
    window.output_dir = tmp_path
    monkeypatch.setattr(window, "_confirm_snapped_export", lambda segments: False)

    class FailExporter:
        def __init__(self, *args, **kwargs):
            raise AssertionError("exporter should not start")

    monkeypatch.setattr(main_window_module, "Exporter", FailExporter)
    window._start_export()

    assert window._exporting is False
    assert "cancelled" in window.statusBar().currentMessage().lower()
    window.close()


def test_confirm_snapped_export_skips_dialog_without_snap(
    qtbot, monkeypatch, tmp_path: Path, sample_media
) -> None:
    def make_settings(*args, **kwargs):
        return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(main_window_module, "QSettings", make_settings)
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.media = sample_media
    monkeypatch.setattr(main_window_module, "QMessageBox", None)

    assert window._confirm_snapped_export([Segment(0.0, 1.0)]) is True
    window.close()
