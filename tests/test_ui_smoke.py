from __future__ import annotations

from pathlib import Path

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

    window.media = sample_media
    window.keyframes = list(sample_media.keyframes)
    window.segments = [Segment(0.0, sample_media.duration)]
    window.selected_segment = 0
    window.current_time = 3.0
    window._split_at_playhead()
    assert len(window.segments) == 2
    assert window.segments[0].end == 3.0
    window.close()
