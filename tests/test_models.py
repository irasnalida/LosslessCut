from __future__ import annotations

import pytest

from losslesscut.models import (
    Segment,
    dedupe_keyframes,
    format_size,
    format_timecode,
    keyframe_at_or_after,
    keyframe_at_or_before,
    nearest_keyframe,
    next_keyframe,
    parse_image_timestamp,
    parse_timecode,
    previous_keyframe,
    segment_for_keyframe_gap,
    split_segment,
)


def test_timecode_round_trip() -> None:
    assert format_timecode(0) == "00:00:00.000"
    assert format_timecode(3661.234) == "01:01:01.234"
    assert parse_timecode("01:01:01.234") == pytest.approx(3661.234)
    assert parse_timecode("1:02.5") == pytest.approx(62.5)
    assert parse_timecode("12.25") == pytest.approx(12.25)
    assert parse_timecode("00:00:01,500") == pytest.approx(1.5)


def test_timecode_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        parse_timecode("not a time")
    with pytest.raises(ValueError):
        parse_timecode("1:2:3:4")


def test_format_size() -> None:
    assert format_size(0) == "0 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024 * 3) == "3.0 MB"


def test_dedupe_keyframes_normalizes_and_adds_zero() -> None:
    values = dedupe_keyframes([10.0, 11.5, 11.5, 13.0], duration=5.0, start_time=10.0)
    assert values == [0.0, 1.5, 3.0]


def test_keyframe_navigation() -> None:
    frames = [0.0, 1.0, 2.5, 5.0]
    assert previous_keyframe(frames, 2.5) == 1.0
    assert next_keyframe(frames, 2.5) == 5.0
    assert nearest_keyframe(frames, 2.1) == 2.5
    assert nearest_keyframe(frames, 0.4) == 0.0
    assert nearest_keyframe(frames, 1.5, minimum=0.1, maximum=2.4) == 1.0


def test_split_segment_snaps_to_nearest_keyframe() -> None:
    segment = Segment(0.0, 6.0, requested_start=0.4)
    result = split_segment(segment, 2.9, [0.0, 1.0, 3.0, 6.0], fps=30.0)
    assert result is not None
    left, right = result
    assert (left.start, left.end) == (0.0, 3.0)
    assert (right.start, right.end) == (3.0, 6.0)
    assert left.requested_start == pytest.approx(0.4)
    assert right.requested_start is None


def test_split_segment_rejects_edges_and_no_inner_keyframe() -> None:
    assert split_segment(Segment(0.0, 6.0), 0.0, [0.0, 3.0, 6.0]) is None
    assert split_segment(Segment(0.0, 6.0), 6.0, [0.0, 3.0, 6.0]) is None
    assert split_segment(Segment(0.0, 2.0), 1.0, [0.0, 3.0, 6.0]) is None


def test_keyframe_at_or_before_and_after() -> None:
    keyframes = [0.0, 2.0, 4.0, 6.0]

    assert keyframe_at_or_before(keyframes, 3.0) == 2.0
    assert keyframe_at_or_before(keyframes, 2.0) == 2.0
    assert keyframe_at_or_before(keyframes, -1.0) is None
    assert keyframe_at_or_before([], 1.0) is None

    assert keyframe_at_or_after(keyframes, 3.0) == 4.0
    assert keyframe_at_or_after(keyframes, 4.0) == 4.0
    assert keyframe_at_or_after(keyframes, 7.0) is None
    assert keyframe_at_or_after([], 1.0) is None


def test_segment_stats() -> None:
    segment = Segment(1.0, 4.0)
    assert segment.duration == 3.0
    assert segment.frame_count(30.0) == 90
    assert segment.estimated_size(8_000_000) == 3_000_000
    assert segment.contains(2.0)
    assert not segment.contains(4.1)


def test_parse_image_timestamp() -> None:
    name = (
        "Outer Banks (2020) - S01E09 - The Bell Tower "
        "[WEBDL-1080p][EAC3 5.1][h265]-HONE-T00'38'07'285.png"
    )
    assert parse_image_timestamp(name) == pytest.approx(2287.285)
    assert parse_image_timestamp("clip T01'02'03'4.mkv") == pytest.approx(3723.4)
    assert parse_image_timestamp("clip t00'00'00'000.png") == 0.0
    assert parse_image_timestamp("clip T00'00'00'28.png") == pytest.approx(0.28)
    assert parse_image_timestamp("clip T00\u201900\u201900\u2019285.png") == pytest.approx(0.285)


@pytest.mark.parametrize(
    "name",
    [
        "screenshot.png",
        "T00'60'00'000.png",
        "T00'00'60'000.png",
        "T00-00-00-000.png",
    ],
)
def test_parse_image_timestamp_rejects_invalid_names(name: str) -> None:
    assert parse_image_timestamp(name) is None


def test_segment_for_keyframe_gap() -> None:
    keyframes = [0.0, 2.0, 4.0, 6.0]

    between = segment_for_keyframe_gap(keyframes, 3.0, 8.0)
    assert between is not None
    assert (between.start, between.end) == (2.0, 4.0)

    on_keyframe = segment_for_keyframe_gap(keyframes, 2.0, 8.0)
    assert on_keyframe is not None
    assert (on_keyframe.start, on_keyframe.end) == (2.0, 4.0)

    at_start = segment_for_keyframe_gap(keyframes, 0.0, 8.0)
    assert at_start is not None
    assert (at_start.start, at_start.end) == (0.0, 2.0)

    at_end = segment_for_keyframe_gap(keyframes, 7.5, 8.0)
    assert at_end is not None
    assert (at_end.start, at_end.end) == (6.0, 8.0)

    assert segment_for_keyframe_gap(keyframes, 9.0, 8.0) is None
    assert segment_for_keyframe_gap([0.0], 3.0, 8.0) == Segment(0.0, 8.0)
    assert segment_for_keyframe_gap([], 3.0, 8.0) == Segment(0.0, 8.0)
