from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import losslesscut.main_window as main_window_module
from losslesscut.models import Segment
from losslesscut.segments import SegmentPanel
from losslesscut.timeline import TimelinePanel


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
    assert window.selected_segment == 0
    assert window.current_time == pytest.approx(2.0)

    # Marking the end extends the selected segment to the next keyframe.
    window.current_time = 4.6
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 5.0)]
    assert window.selected_segment == 0

    # Extend-only: a playhead before the current end leaves it unchanged.
    window.current_time = 3.0
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 5.0)]

    # A later start is appended instead of replacing other segments.
    window.current_time = 0.2
    window._mark_segment_start()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 5.0), (0.0, 1.0)]
    assert window.selected_segment == 1

    # Repeating the same start selects the existing segment.
    window.current_time = 0.2
    window._mark_segment_start()
    assert len(window.segments) == 2
    assert window.selected_segment == 1

    # With no selection, mark-end extends the last segment.
    window.selected_segment = -1
    window.current_time = 4.2
    window._mark_segment_end()
    assert [(s.start, s.end) for s in window.segments] == [(2.0, 5.0), (0.0, 5.0)]
    assert window.selected_segment == 1

    # With no segments, mark-end is a no-op.
    window.segments = []
    window.selected_segment = -1
    window.current_time = 2.0
    window._mark_segment_end()
    assert window.segments == []

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
