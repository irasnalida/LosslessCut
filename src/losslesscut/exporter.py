"""Lossless stream-copy export using ffmpeg."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .ffmpeg_utils import FFmpegError, ffmpeg_path
from .models import MediaInfo, Segment, format_timecode, next_keyframe

_MP4_LIKE = {".mp4", ".m4v", ".mov"}
_CONCAT_FRIENDLY = {".mp4", ".m4v", ".mov", ".mkv", ".ts", ".m2ts", ".webm"}
# Seek this far into the GOP so ffmpeg's Matroska seek does not back up one
# extra keyframe when the target sits on the keyframe itself.
_SEEK_GOP_FRACTION = 0.9
# Keep the seek target before the export end so -ss/-to stays valid.
_SEEK_END_MARGIN = 0.05


@dataclass(frozen=True)
class ExportJob:
    start: float
    end: float
    output: Path

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def seek_start(
    start: float,
    end: float,
    next_keyframe: float | None = None,
    gop_end: float | None = None,
) -> float:
    """Return the input seek target for a cut starting at the keyframe *start*.

    ffmpeg can land on the previous keyframe when the input seek target is at
    or immediately after a keyframe (seen with some Matroska files). Seeking
    later inside the same GOP avoids that while the copied output still begins
    at *start*. Returns *start* when the GOP bounds are unknown.
    """
    start = max(0.0, start)
    bound = next_keyframe if next_keyframe is not None else gop_end
    if bound is None or bound <= start:
        return start
    target = start + (bound - start) * _SEEK_GOP_FRACTION
    target = min(target, end - _SEEK_END_MARGIN)
    return max(start, target)


def cut_args(
    source: Path,
    start: float,
    end: float,
    output: Path,
    all_tracks: bool = True,
    next_keyframe: float | None = None,
    gop_end: float | None = None,
) -> list[str]:
    """ffmpeg arguments for one lossless segment."""
    seek = seek_start(start, end, next_keyframe, gop_end)
    args = [
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-ss",
        f"{seek:.6f}",
        # -to is an input option here: an absolute source time that also works
        # when the seek target is later than the segment start. Output-side -to
        # would count from the seek target instead.
        "-to",
        f"{max(start, end):.6f}",
        "-i",
        str(source),
    ]
    if all_tracks:
        args += ["-map", "0"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a?"]
    args += [
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-map_chapters",
        "-1",
    ]
    if output.suffix.lower() in _MP4_LIKE:
        args += ["-movflags", "+faststart"]
    args.append(str(output))
    return args


def snapped_export_message(segments: list[Segment]) -> str | None:
    """Describe segments whose lossless start was moved back to a keyframe."""
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        requested = segment.requested_start
        if requested is None:
            continue
        extra = max(0.0, requested - segment.start)
        lines.append(
            f"Segment {index}: starts at {format_timecode(segment.start)} "
            f"instead of {format_timecode(requested)} (+{extra:.3f}s included)"
        )
    return "\n".join(lines) if lines else None


def concat_args(list_file: Path, output: Path) -> list[str]:
    args = [
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
    ]
    if output.suffix.lower() in _MP4_LIKE:
        args += ["-movflags", "+faststart"]
    args.append(str(output))
    return args


def merged_suffix(source_suffix: str) -> str:
    suffix = source_suffix.lower()
    return suffix if suffix in _CONCAT_FRIENDLY else ".mkv"


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def next_output_index(directory: Path, stem: str, suffix: str) -> int:
    """Return the next free ``stem_NNN`` number in *directory*."""
    pattern = re.compile(
        rf"^{re.escape(stem)}_(\d{{3,}}){re.escape(suffix)}$", re.IGNORECASE
    )
    highest = 0
    if directory.is_dir():
        for path in directory.iterdir():
            match = pattern.match(path.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def _concat_escape(path: Path) -> str:
    return str(path).replace("'", "'\\''")


class Exporter(QObject):
    """Run one or more cuts, optionally concatenating the result."""

    progress = Signal(int, str)
    status = Signal(str)
    finished = Signal(list)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        media: MediaInfo,
        segments: list[Segment],
        output_dir: Path,
        mode: str = "separate",
        all_tracks: bool = True,
        keyframes_complete: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.media = media
        self.segments = [segment for segment in segments if segment.enabled and segment.duration > 0]
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.all_tracks = all_tracks
        self.keyframes_complete = keyframes_complete
        self._jobs: list[ExportJob] = []
        self._index = 0
        self._completed = 0.0
        self._total = sum(segment.duration for segment in self.segments)
        self._temp_dir: Path | None = None
        self._list_file: Path | None = None
        self._merge_output: Path | None = None
        self._outputs: list[Path] = []
        self._cancelled = False
        self._running = False
        self._current_job: ExportJob | None = None
        self._stderr = bytearray()
        self._stdout_buffer = ""
        self._last_out_time = 0.0

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

    # ------------------------------------------------------------------ setup
    def planned_outputs(self) -> list[Path]:
        result: list[Path] = []
        suffix = self.media.path.suffix or ".mkv"
        if self.mode == "merge":
            result.append(unique_path(self.output_dir, f"{self.media.path.stem}_merged", merged_suffix(suffix)))
            return result
        base = next_output_index(self.output_dir, self.media.path.stem, suffix)
        for offset, _segment in enumerate(self.segments):
            result.append(
                self.output_dir
                / f"{self.media.path.stem}_{base + offset:03d}{suffix}"
            )
        return result

    def _prepare(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        outputs = self.planned_outputs()
        if self.mode == "merge":
            self._merge_output = outputs[0]
            self._temp_dir = Path(tempfile.mkdtemp(prefix="losslesscut-"))
            suffix = self._merge_output.suffix or ".mkv"
            jobs = [
                ExportJob(
                    segment.start,
                    segment.end,
                    self._temp_dir / f"part_{index:03d}{suffix}",
                )
                for index, segment in enumerate(self.segments, start=1)
            ]
            self._list_file = self._temp_dir / "concat.txt"
            self._jobs = jobs
        else:
            self._jobs = [
                ExportJob(segment.start, segment.end, output)
                for segment, output in zip(self.segments, outputs, strict=True)
            ]

    def start(self) -> None:
        if self.segments:
            try:
                ffmpeg_path()
                self._prepare()
            except (FFmpegError, OSError) as exc:
                self.failed.emit(str(exc), getattr(exc, "detail", str(exc)))
                return
            self._running = True
            self._index = 0
            self._completed = 0.0
            self.progress.emit(0, "Starting export…")
            self._start_job()
        else:
            self.failed.emit("There are no enabled segments to export.", "")

    def cancel(self) -> None:
        if not self._running:
            return
        self._cancelled = True
        self.status.emit("Cancelling…")
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()

    # --------------------------------------------------------------- lifecycle
    def _start_job(self) -> None:
        if self._cancelled:
            self._cleanup_cancel()
            return
        if self._index >= len(self._jobs):
            if self.mode == "merge":
                self._start_concat()
            else:
                self._finish()
            return
        job = self._jobs[self._index]
        self._current_job = job
        self._last_out_time = 0.0
        self._stderr.clear()
        self._stdout_buffer = ""
        self.status.emit(
            f"Exporting segment {self._index + 1}/{len(self._jobs)}  "
            f"({format_timecode(job.start)} – {format_timecode(job.end)})"
        )
        following_keyframe = next_keyframe(self.media.keyframes, job.start)
        if following_keyframe is not None:
            gop_end = following_keyframe
        elif self.keyframes_complete:
            gop_end = self.media.duration
        else:
            gop_end = None
        self._launch(
            cut_args(
                self.media.path,
                job.start,
                job.end,
                job.output,
                all_tracks=self.all_tracks,
                next_keyframe=following_keyframe,
                gop_end=gop_end,
            )
        )

    def _start_concat(self) -> None:
        if self._cancelled:
            self._cleanup_cancel()
            return
        if self._list_file is None or self._merge_output is None:
            self._fail("Internal error: merge output was not prepared.")
            return
        lines = [f"file '{_concat_escape(job.output)}'" for job in self._jobs]
        try:
            self._list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            self._fail(f"Could not write the concat list: {exc}")
            return
        self.progress.emit(96, "Merging segments…")
        self.status.emit("Merging segments into one file…")
        self._current_job = ExportJob(0.0, self._total, self._merge_output)
        self._last_out_time = 0.0
        self._stderr.clear()
        self._stdout_buffer = ""
        self._launch(concat_args(self._list_file, self._merge_output))

    def _launch(self, args: list[str]) -> None:
        try:
            program = ffmpeg_path()
        except FFmpegError as exc:
            self._fail(str(exc), exc.detail)
            return
        self._process.setProgram(program)
        self._process.setArguments(args)
        self._process.start()
        if not self._process.waitForStarted(5000):
            self._fail("ffmpeg could not be started.", self._process.errorString())
            return
        self._running = True

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._cancelled:
            self._cleanup_cancel()
            return
        if not self._running:
            return
        job = self._current_job
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            detail = self._stderr.decode("utf-8", "replace").strip()
            self._fail(
                f"ffmpeg failed with exit code {exit_code}.",
                detail or self._process.errorString(),
            )
            return
        if job is not None and (not job.output.exists() or job.output.stat().st_size == 0):
            self._fail(f"ffmpeg did not create {job.output.name!r}.")
            return

        if self.mode == "merge" and self._index >= len(self._jobs):
            # This was the concat process.
            assert self._merge_output is not None
            self._outputs = [self._merge_output]
            self._finish()
            return

        if job is not None:
            self._completed += job.duration
            if self.mode == "separate":
                self._outputs.append(job.output)
        self._index += 1
        self._update_progress(job.duration if job else 0.0)
        self._start_job()

    def _finish(self) -> None:
        self._running = False
        self._current_job = None
        self._cleanup_temp()
        self.progress.emit(100, "Export complete")
        total = self._total
        self.status.emit(
            f"Exported {len(self._outputs)} file{'s' if len(self._outputs) != 1 else ''} "
            f"({format_timecode(total)})"
        )
        self.finished.emit(self._outputs)

    def _fail(self, message: str, detail: str = "") -> None:
        self._running = False
        current = self._current_job
        if current is not None:
            try:
                if current.output.exists():
                    current.output.unlink()
            except OSError:
                pass
        self._current_job = None
        self._cleanup_temp()
        self.status.emit("Export failed")
        self.failed.emit(message, detail or message)

    def _cleanup_temp(self) -> None:
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
            self._list_file = None

    def _cleanup_cancel(self) -> None:
        self._running = False
        current = self._current_job
        if current is not None and self.mode == "separate":
            try:
                if current.output.exists():
                    current.output.unlink()
            except OSError:
                pass
        self._current_job = None
        self._cleanup_temp()
        self._outputs = []
        self.status.emit("Export cancelled")
        self.cancelled.emit()

    # ------------------------------------------------------------------- io
    def _read_stdout(self) -> None:
        if not self._running:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            self._handle_progress_line(line.strip())

    def _read_stderr(self) -> None:
        chunk = bytes(self._process.readAllStandardError())
        if len(self._stderr) < 65536:
            self._stderr.extend(chunk[: 65536 - len(self._stderr)])

    def _handle_progress_line(self, line: str) -> None:
        if not line or "=" not in line:
            return
        key, value = line.split("=", 1)
        if key in {"out_time_us", "out_time_ms"}:
            try:
                self._last_out_time = max(0.0, int(value) / 1_000_000.0)
            except ValueError:
                return
        elif key == "out_time":
            match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
            if match:
                hours, minutes, seconds = match.groups()
                self._last_out_time = (
                    int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                )
        elif key == "speed":
            speed = value.strip()
            if speed and speed != "N/A":
                if self.mode == "merge" and self._index >= len(self._jobs):
                    self.status.emit(f"Merging segments  ·  {speed}")
                else:
                    self.status.emit(
                        f"Exporting segment {self._index + 1}/{len(self._jobs)}  ·  {speed}"
                    )
            return
        elif key != "progress":
            return
        if self.mode == "merge" and self._index >= len(self._jobs):
            return
        self._update_progress(self._last_out_time)

    def _update_progress(self, current_seconds: float) -> None:
        if self._total <= 0:
            return
        if self.mode == "merge" and self._index >= len(self._jobs):
            return
        job = self._current_job
        if job is not None:
            current_seconds = min(current_seconds, job.duration)
        done = self._completed + current_seconds
        percent = int(max(0.0, min(100.0, done / self._total * 100.0)))
        if self.mode == "merge":
            percent = min(percent, 95)
        self.progress.emit(percent, f"Exporting… {percent}%")

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if self._cancelled or not self._running:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._fail("ffmpeg could not be started.", self._process.errorString())
