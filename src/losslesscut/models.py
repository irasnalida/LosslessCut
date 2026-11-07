"""Pure data models and helpers shared by the UI and the ffmpeg layer."""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path


def parse_fraction(value: str | float | None) -> float:
    """Return a float from an ffprobe-style ``num/den`` fraction."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            den = float(denominator)
            return float(numerator) / den if den else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


@dataclass(frozen=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str = ""
    codec_long_name: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    bit_rate: int = 0
    language: str = ""
    rotation: float = 0.0

    @property
    def label(self) -> str:
        if self.codec_type == "video":
            return f"Video: {self.codec_name} {self.width}x{self.height} {self.fps:.3g} fps"
        if self.codec_type == "audio":
            channels = f"{self.channels}ch" if self.channels else ""
            rate = f"{self.sample_rate} Hz" if self.sample_rate else ""
            details = " ".join(part for part in (self.codec_name, channels, rate) if part)
            return f"Audio: {details}"
        if self.codec_type == "subtitle":
            return f"Subtitle: {self.codec_name}"
        return f"{self.codec_type.title()}: {self.codec_name}"


@dataclass
class MediaInfo:
    path: Path
    duration: float
    start_time: float
    size: int
    format_name: str
    bit_rate: int
    streams: list[StreamInfo] = field(default_factory=list)
    keyframes: list[float] = field(default_factory=list)

    @property
    def video(self) -> StreamInfo | None:
        return next((stream for stream in self.streams if stream.codec_type == "video"), None)

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [stream for stream in self.streams if stream.codec_type == "audio"]

    @property
    def subtitle_streams(self) -> list[StreamInfo]:
        return [stream for stream in self.streams if stream.codec_type == "subtitle"]

    @property
    def fps(self) -> float:
        video = self.video
        return video.fps if video and video.fps > 0 else 0.0

    @property
    def width(self) -> int:
        video = self.video
        return video.width if video else 0

    @property
    def height(self) -> int:
        video = self.video
        return video.height if video else 0

    @property
    def display_size(self) -> tuple[int, int]:
        """Width/height after applying the display rotation metadata."""
        video = self.video
        if video is None:
            return 0, 0
        if round(abs(video.rotation)) % 180 == 90:
            return video.height, video.width
        return video.width, video.height

    @property
    def video_codec(self) -> str:
        video = self.video
        return video.codec_name if video else ""

    @property
    def estimated_bitrate(self) -> int:
        if self.bit_rate > 0:
            return self.bit_rate
        return sum(stream.bit_rate for stream in self.streams if stream.bit_rate > 0)

    @property
    def keyframe_count(self) -> int:
        return len(self.keyframes)


@dataclass
class Segment:
    """An export range. Boundaries are always snapped to keyframes by the UI."""

    start: float
    end: float
    enabled: bool = True

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def contains(self, time: float, tolerance: float = 1e-6) -> bool:
        return self.start - tolerance <= time <= self.end + tolerance

    def frame_count(self, fps: float) -> int:
        if fps <= 0:
            return 0
        return round(self.duration * fps)

    def estimated_size(self, bitrate: int) -> int:
        if bitrate <= 0:
            return 0
        return int(self.duration * bitrate / 8)


def format_timecode(seconds: float, milliseconds: bool = True) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` (or ``HH:MM:SS``)."""
    if not math.isfinite(seconds):
        return "--:--:--"
    total_ms = round(max(0.0, seconds) * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if milliseconds:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_short_time(seconds: float) -> str:
    """Compact time for cards and status labels."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def format_size(byte_count: int) -> str:
    if byte_count <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(byte_count)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            precision = 1 if value < 10 and unit != "B" else 0
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{byte_count} B"


def parse_timecode(text: str) -> float:
    """Parse ``HH:MM:SS.mmm``, ``MM:SS.mmm`` or plain seconds."""
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        raise ValueError("empty timecode")
    parts = cleaned.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid timecode: {text!r}")
    try:
        values = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"invalid timecode: {text!r}") from exc
    total = 0.0
    for value in values:
        total = total * 60.0 + value
    if total < 0:
        raise ValueError("timecode cannot be negative")
    return total


def dedupe_keyframes(times: list[float], duration: float, start_time: float = 0.0) -> list[float]:
    """Normalize raw stream timestamps to source-relative seconds."""
    adjusted_values: list[float] = []
    for value in times:
        adjusted = value - start_time
        if not math.isfinite(adjusted):
            continue
        adjusted = min(max(0.0, adjusted), duration) if duration > 0 else max(0.0, adjusted)
        adjusted_values.append(adjusted)
    adjusted_values.sort()
    normalized: list[float] = []
    for adjusted in adjusted_values:
        if not normalized or adjusted - normalized[-1] > 0.001:
            normalized.append(adjusted)
    if duration > 0:
        normalized = [value for value in normalized if value <= duration + 0.001]
    if not normalized or normalized[0] > 0.001:
        normalized.insert(0, 0.0)
    return normalized


def previous_keyframe(times: list[float], value: float) -> float | None:
    index = bisect_left(times, value - 1e-6)
    if index <= 0:
        return None
    return times[index - 1]


def next_keyframe(times: list[float], value: float) -> float | None:
    index = bisect_right(times, value + 1e-6)
    if index >= len(times):
        return None
    return times[index]


_IMAGE_TIMESTAMP_RE = re.compile(r"[Tt](\d{2,})'(\d{2})'(\d{2})'(\d{1,3})")


def parse_image_timestamp(filename: str) -> float | None:
    """Parse ``Thh'mm'ss'ms`` from a screenshot name, e.g. ``T00'38'07'285``.

    The timestamp is returned in seconds relative to the start of the video.
    Several media players put this marker in screenshot filenames. Returns
    ``None`` when no valid marker is present.
    """
    text = str(filename).replace("\u2018", "'").replace("\u2019", "'")
    match = _IMAGE_TIMESTAMP_RE.search(text)
    if match is None:
        return None
    hours_text, minutes_text, seconds_text, fraction_text = match.groups()
    minutes = int(minutes_text)
    seconds = int(seconds_text)
    if minutes >= 60 or seconds >= 60:
        return None
    fraction = int(fraction_text) / (10 ** len(fraction_text))
    return int(hours_text) * 3600 + minutes * 60 + seconds + fraction


def segment_for_keyframe_gap(
    times: list[float],
    at: float,
    duration: float,
) -> Segment | None:
    """Return the keyframe interval containing *at*.

    The segment starts at the last keyframe at or before *at* and ends at the
    next keyframe. When *at* lands exactly on a keyframe, that keyframe starts
    the segment. Times outside the video or an empty interval return ``None``.
    """
    if not math.isfinite(at) or duration <= 0 or at < 0 or at > duration + 0.001:
        return None
    at = min(max(0.0, at), duration)
    index = bisect_right(times, at + 1e-6)
    if index <= 0:
        start = 0.0
        end = times[0] if times else duration
    else:
        start = times[index - 1]
        end = times[index] if index < len(times) else duration
    start = min(max(0.0, start), duration)
    end = min(max(0.0, end), duration)
    if end - start <= 1e-6:
        return None
    return Segment(start, end, True)


def nearest_keyframe(
    times: list[float],
    value: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """Find the closest keyframe, optionally constrained to an open interval."""
    if not times:
        return None
    lo = 0 if minimum is None else bisect_left(times, minimum)
    hi = len(times) if maximum is None else bisect_right(times, maximum)
    candidates = times[lo:hi]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: abs(candidate - value))


def split_segment(
    segment: Segment,
    at: float,
    keyframes: list[float],
    fps: float = 0.0,
) -> tuple[Segment, Segment] | None:
    """Split *segment* at the nearest keyframe strictly inside it."""
    frame = 1.0 / fps if fps > 0 else 0.001
    epsilon = max(frame, 0.001)
    if at <= segment.start + epsilon or at >= segment.end - epsilon:
        return None
    boundary = nearest_keyframe(
        keyframes,
        at,
        minimum=segment.start + epsilon,
        maximum=segment.end - epsilon,
    )
    if boundary is None:
        return None
    if boundary - segment.start < epsilon or segment.end - boundary < epsilon:
        return None
    return (
        Segment(segment.start, boundary, segment.enabled),
        Segment(boundary, segment.end, segment.enabled),
    )


def clamp_segment(segment: Segment, duration: float, keyframes: list[float]) -> Segment:
    start = min(max(0.0, segment.start), duration)
    end = min(max(start, segment.end), duration)
    if keyframes:
        start = min(keyframes, key=lambda value: abs(value - start))
        snapped_end = min(keyframes, key=lambda value: abs(value - end))
        if abs(snapped_end - end) < 0.05 or snapped_end <= end:
            end = snapped_end
    if end <= start:
        end = min(duration, start + (1.0 / 30.0))
    return Segment(start, end, segment.enabled)


def total_duration(segments: list[Segment]) -> float:
    return sum(segment.duration for segment in segments if segment.enabled)
