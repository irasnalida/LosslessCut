"""Media probing via ffprobe."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .ffmpeg_utils import FFmpegError, probe_json
from .models import MediaInfo, StreamInfo, dedupe_keyframes, parse_fraction


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def probe_media(path: Path) -> MediaInfo:
    """Read container, stream and duration information for *path*."""
    path = Path(path)
    data = probe_json(path, ["-show_format", "-show_streams"])
    format_info: dict[str, Any] = data.get("format") or {}
    raw_streams: list[dict[str, Any]] = data.get("streams") or []

    streams: list[StreamInfo] = []
    for raw in raw_streams:
        codec_type = str(raw.get("codec_type") or "")
        fps = 0.0
        if codec_type == "video":
            fps = parse_fraction(raw.get("avg_frame_rate"))
            if fps <= 0:
                fps = parse_fraction(raw.get("r_frame_rate"))
        tags = raw.get("tags") or {}
        rotation = _float(tags.get("rotate"))
        for side_data in raw.get("side_data_list") or []:
            if side_data.get("rotation") is not None:
                rotation = _float(side_data.get("rotation"))
                break
        streams.append(
            StreamInfo(
                index=_int(raw.get("index")),
                codec_type=codec_type,
                codec_name=str(raw.get("codec_name") or "unknown"),
                codec_long_name=str(raw.get("codec_long_name") or ""),
                width=_int(raw.get("width")),
                height=_int(raw.get("height")),
                fps=fps,
                sample_rate=_int(raw.get("sample_rate")),
                channels=_int(raw.get("channels")),
                bit_rate=_int(raw.get("bit_rate")),
                language=str(tags.get("language") or ""),
                rotation=rotation,
            )
        )

    duration = _float(format_info.get("duration"))
    if duration <= 0:
        stream_durations = [
            _float(raw.get("duration"))
            for raw in raw_streams
            if _float(raw.get("duration")) > 0
        ]
        duration = max(stream_durations, default=0.0)
    if duration <= 0:
        raise FFmpegError(f"Could not determine the duration of {path.name!r}.")

    start_time = _float(format_info.get("start_time"))
    size = _int(format_info.get("size"))
    bit_rate = _int(format_info.get("bit_rate"))

    media = MediaInfo(
        path=path,
        duration=duration,
        start_time=start_time,
        size=size,
        format_name=str(format_info.get("format_name") or ""),
        bit_rate=bit_rate,
        streams=streams,
    )
    if media.video is None:
        raise FFmpegError(f"{path.name!r} does not contain a video stream.")
    return media


def _keyframes_from_packets(path: Path) -> list[float]:
    data = probe_json(
        path,
        [
            "-select_streams",
            "v:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,dts_time,flags",
        ],
    )
    times: list[float] = []
    for packet in data.get("packets") or []:
        flags = str(packet.get("flags") or "")
        if "K" not in flags:
            continue
        value = _float(packet.get("pts_time"), float("nan"))
        if not math.isfinite(value):
            value = _float(packet.get("dts_time"), float("nan"))
        if math.isfinite(value):
            times.append(value)
    return times


def _keyframes_from_frames(path: Path) -> list[float]:
    data = probe_json(
        path,
        [
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,pts_time,key_frame",
        ],
    )
    times: list[float] = []
    for frame in data.get("frames") or []:
        if _int(frame.get("key_frame"), 1) == 0:
            continue
        value = _float(frame.get("best_effort_timestamp_time"), float("nan"))
        if not math.isfinite(value):
            value = _float(frame.get("pts_time"), float("nan"))
        if math.isfinite(value):
            times.append(value)
    return times


def probe_keyframes(media: MediaInfo) -> list[float]:
    """Return keyframe timestamps relative to the start of the video.

    Packet flags are the fast path. Some containers do not mark key packets,
    so a decoded-frame scan is used as a fallback.
    """
    try:
        raw = _keyframes_from_packets(media.path)
    except FFmpegError:
        raw = []
    if not raw:
        try:
            raw = _keyframes_from_frames(media.path)
        except FFmpegError:
            raw = []
    keyframes = dedupe_keyframes(raw, media.duration, media.start_time)
    if not keyframes:
        keyframes = [0.0]
    return keyframes
