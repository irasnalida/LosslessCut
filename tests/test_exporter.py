from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from losslesscut.exporter import (
    Exporter,
    concat_args,
    cut_args,
    merged_suffix,
    next_output_index,
    seek_start,
    snapped_export_message,
    unique_path,
)
from losslesscut.ffprobe import probe_media
from losslesscut.models import Segment


def _video_packets(path: Path) -> list[dict[str, object]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe is not available")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time,size,flags",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return list(json.loads(result.stdout)["packets"])


def test_cut_args_stream_copy(tmp_path: Path) -> None:
    output = tmp_path / "out.mp4"
    args = cut_args(Path("input.mkv"), 1.0, 2.0, output, all_tracks=True)
    assert args[args.index("-ss") + 1] == "1.000000"
    assert "-to" in args and args[args.index("-to") + 1] == "2.000000"
    assert "-t" not in args
    assert args[args.index("-c") + 1] == "copy"
    assert "-map" in args and args[args.index("-map") + 1] == "0"
    assert "-movflags" in args
    assert args[-1] == str(output)


def test_cut_args_video_audio_only(tmp_path: Path) -> None:
    args = cut_args(Path("input.mp4"), 0.0, 1.0, tmp_path / "out.mkv", all_tracks=False)
    assert "0:v:0" in args
    assert "0:a?" in args


def test_seek_start_stays_inside_gop() -> None:
    assert seek_start(2.0, 6.0, next_keyframe=3.0) == pytest.approx(2.9)


def test_seek_start_avoids_previous_keyframe_snap() -> None:
    # Regression: seeking exactly at 146.563 made ffmpeg start at 144.186.
    assert seek_start(146.563, 150.0, next_keyframe=151.318) == pytest.approx(149.95)


def test_seek_start_clamps_to_the_export_end() -> None:
    assert seek_start(2.0, 2.02, next_keyframe=3.0) == pytest.approx(2.0)
    assert seek_start(2.0, 2.06, next_keyframe=3.0) == pytest.approx(2.01)


def test_seek_start_uses_gop_end_for_the_last_gop() -> None:
    assert seek_start(5.0, 6.0, gop_end=6.0) == pytest.approx(5.9)


def test_seek_start_without_gop_bounds() -> None:
    assert seek_start(2.0, 6.0) == pytest.approx(2.0)
    assert seek_start(2.0, 6.0, gop_end=1.0) == pytest.approx(2.0)


def test_cut_args_seek_inside_gop(tmp_path: Path) -> None:
    args = cut_args(
        Path("input.mkv"),
        146.563,
        150.0,
        tmp_path / "out.mkv",
        next_keyframe=151.318,
    )
    assert args[args.index("-ss") + 1] == "149.950000"
    assert args[args.index("-to") + 1] == "150.000000"


def test_snapped_export_message() -> None:
    assert snapped_export_message([Segment(0.0, 1.0)]) is None
    message = snapped_export_message(
        [Segment(146.563, 150.0, requested_start=148.27)]
    )
    assert message is not None
    assert "Segment 1" in message
    assert "00:02:26.563" in message
    assert "00:02:28.270" in message
    assert "+1.707s included" in message


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


def test_next_output_index(tmp_path: Path) -> None:
    assert next_output_index(tmp_path, "clip", ".mp4") == 1

    (tmp_path / "clip_001.mp4").write_bytes(b"")
    (tmp_path / "clip_002.mp4").write_bytes(b"")
    (tmp_path / "other_009.mp4").write_bytes(b"")
    (tmp_path / "clip_notes.mp4").write_bytes(b"")
    assert next_output_index(tmp_path, "clip", ".mp4") == 3

    (tmp_path / "clip_0100.mp4").write_bytes(b"")
    assert next_output_index(tmp_path, "clip", ".mp4") == 101


def test_planned_outputs_continue_numbering(sample_media, tmp_path: Path) -> None:
    (tmp_path / "sample_001.mp4").write_bytes(b"")
    exporter = Exporter(
        sample_media,
        [Segment(1.0, 2.0), Segment(3.0, 4.0)],
        tmp_path,
        mode="separate",
    )

    outputs = exporter.planned_outputs()
    assert [path.name for path in outputs] == ["sample_002.mp4", "sample_003.mp4"]


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
    assert [path.name for path in paths] == ["sample_001.mp4", "sample_002.mp4"]
    for path in paths:
        assert path.exists() and path.stat().st_size > 0
        media = probe_media(path)
        assert media.duration == pytest.approx(1.0, abs=0.25)
        assert media.video_codec == "h264"


@pytest.mark.integration
def test_export_starts_at_snapped_keyframe(
    qtbot, sample_media, tmp_path: Path
) -> None:
    output = tmp_path / "snapped"
    exporter = Exporter(
        sample_media,
        [Segment(1.0, 2.0, requested_start=1.6)],
        output,
        mode="separate",
        keyframes_complete=True,
    )
    with qtbot.waitSignal(exporter.finished, timeout=60000) as blocker:
        exporter.start()
    path = Path(blocker.args[0][0])

    source = _video_packets(sample_media.path)
    keyframe_size = next(
        int(packet["size"])
        for packet in source
        if "K" in str(packet["flags"])
        and float(packet["pts_time"]) == pytest.approx(1.0, abs=0.02)
    )
    exported = _video_packets(path)
    assert int(exported[0]["size"]) == keyframe_size
    span = float(exported[-1]["pts_time"]) - float(exported[0]["pts_time"])
    assert span == pytest.approx(1.0, abs=0.15)


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
