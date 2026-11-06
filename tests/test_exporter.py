from __future__ import annotations

from pathlib import Path

import pytest

from losslesscut.exporter import (
    Exporter,
    concat_args,
    cut_args,
    merged_suffix,
    unique_path,
)
from losslesscut.ffprobe import probe_media
from losslesscut.models import Segment


def test_cut_args_stream_copy(tmp_path: Path) -> None:
    output = tmp_path / "out.mp4"
    args = cut_args(Path("input.mkv"), 1.0, 2.0, output, all_tracks=True)
    assert "-ss" in args
    assert "-t" in args
    assert args[args.index("-c") + 1] == "copy"
    assert "-map" in args and args[args.index("-map") + 1] == "0"
    assert "-movflags" in args
    assert args[-1] == str(output)


def test_cut_args_video_audio_only(tmp_path: Path) -> None:
    args = cut_args(Path("input.mp4"), 0.0, 1.0, tmp_path / "out.mkv", all_tracks=False)
    assert "0:v:0" in args
    assert "0:a?" in args


def test_concat_args(tmp_path: Path) -> None:
    args = concat_args(tmp_path / "list.txt", tmp_path / "out.mp4")
    assert "-f" in args and args[args.index("-f") + 1] == "concat"
    assert "-safe" in args
    assert "-c" in args and args[args.index("-c") + 1] == "copy"


def test_merged_suffix() -> None:
    assert merged_suffix(".mp4") == ".mp4"
    assert merged_suffix(".mkv") == ".mkv"
    assert merged_suffix(".avi") == ".mkv"


def test_unique_path(tmp_path: Path) -> None:
    first = unique_path(tmp_path, "clip", ".mp4")
    assert first.name == "clip.mp4"
    first.write_bytes(b"x")
    second = unique_path(tmp_path, "clip", ".mp4")
    assert second.name == "clip_1.mp4"


@pytest.mark.integration
def test_export_separate(qtbot, sample_media, tmp_path: Path) -> None:
    output = tmp_path / "separate"
    exporter = Exporter(
        sample_media,
        [Segment(1.0, 2.0), Segment(3.0, 4.0)],
        output,
        mode="separate",
    )
    with qtbot.waitSignal(exporter.finished, timeout=60000) as blocker:
        exporter.start()
    paths = [Path(value) for value in blocker.args[0]]
    assert len(paths) == 2
    for path in paths:
        assert path.exists() and path.stat().st_size > 0
        media = probe_media(path)
        assert media.duration == pytest.approx(1.0, abs=0.25)
        assert media.video_codec == "h264"


@pytest.mark.integration
def test_export_merged(qtbot, sample_media, tmp_path: Path) -> None:
    output = tmp_path / "merged"
    exporter = Exporter(
        sample_media,
        [Segment(1.0, 2.0), Segment(3.0, 4.0)],
        output,
        mode="merge",
    )
    with qtbot.waitSignal(exporter.finished, timeout=60000) as blocker:
        exporter.start()
    paths = [Path(value) for value in blocker.args[0]]
    assert len(paths) == 1
    assert paths[0].exists()
    media = probe_media(paths[0])
    assert media.duration == pytest.approx(2.0, abs=0.35)


@pytest.mark.integration
def test_export_rejects_empty_segments(qtbot, sample_media, tmp_path: Path) -> None:
    exporter = Exporter(sample_media, [], tmp_path, mode="separate")
    with qtbot.waitSignal(exporter.failed, timeout=5000) as blocker:
        exporter.start()
    assert "no enabled segments" in blocker.args[0].lower()
