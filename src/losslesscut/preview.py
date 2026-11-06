"""Frame-accurate video preview powered by ffmpeg.

QtMultimedia is deliberately not used here. Stills are extracted on demand
and playback is a raw-video pipe decoded by ffmpeg, which makes the preview
work with any codec ffmpeg can decode.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from .ffmpeg_utils import FFmpegError, ffmpeg_path, run_capture
from .models import MediaInfo, format_timecode
from .workers import Worker

_MAX_STILL = (1280, 720)
_MAX_PLAYBACK = (960, 540)


def fit_size(source_width: int, source_height: int, limits: tuple[int, int]) -> tuple[int, int]:
    """Fit source dimensions inside limits without upscaling."""
    if source_width <= 0 or source_height <= 0:
        return limits
    scale = min(limits[0] / source_width, limits[1] / source_height, 1.0)
    width = max(2, round(source_width * scale))
    height = max(2, round(source_height * scale))
    return width, height


def extract_frame(path: Path, at: float, width: int, height: int) -> QImage:
    """Decode exactly one frame at *at* seconds."""
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, at):.6f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"scale={width}:{height}:flags=fast_bilinear",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    data = run_capture(command, timeout=60.0)
    frame_size = width * height * 3
    if len(data) < frame_size:
        # Seeking exactly to the end of a stream can produce no frame.
        if at > 0.002:
            return extract_frame(path, max(0.0, at - 0.002), width, height)
        raise FFmpegError("ffmpeg did not return a frame at this position.", command)
    image = QImage(data[:frame_size], width, height, width * 3, QImage.Format.Format_RGB888)
    return image.copy()


class FrameExtractor(QObject):
    """Extract still frames asynchronously, coalescing rapid seek requests."""

    frame_ready = Signal(float, object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._cache: OrderedDict[tuple[int, int, int], QImage] = OrderedDict()
        self._cache_limit = 16
        self._pending: tuple[float, int, int] | None = None
        self._running = False
        self._token = 0
        self._worker: Worker | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._dispatch)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def set_media(self, path: Path | None) -> None:
        self._path = Path(path) if path else None
        self._cache.clear()
        self._pending = None
        self._token += 1
        self._running = False
        self._timer.stop()
        if self._worker is not None:
            self._worker = None

    def invalidate(self) -> None:
        self._cache.clear()

    def shutdown(self) -> None:
        """Stop queued work before the owning widget is destroyed."""
        self._path = None
        self._pending = None
        self._token += 1
        self._timer.stop()
        self._cache.clear()
        self._pool.waitForDone(3000)
        self._worker = None
        self._running = False

    def request(self, at: float, width: int, height: int, immediate: bool = False) -> None:
        if self._path is None:
            return
        key = (round(max(0.0, at) * 1000), width, height)
        self._token += 1
        self._pending = (max(0.0, at), width, height)
        if key in self._cache:
            image = self._cache.pop(key)
            self._cache[key] = image
            self._pending = None
            self.frame_ready.emit(at, image)
            return
        if immediate:
            self._timer.stop()
            self._dispatch()
        elif not self._timer.isActive():
            self._timer.start()

    def _dispatch(self) -> None:
        if self._running or self._pending is None or self._path is None:
            return
        at, width, height = self._pending
        self._pending = None
        key = (round(at * 1000), width, height)
        if key in self._cache:
            image = self._cache.pop(key)
            self._cache[key] = image
            self.frame_ready.emit(at, image)
            QTimer.singleShot(0, self._dispatch)
            return

        self._running = True
        token = self._token
        worker = Worker(extract_frame, self._path, at, width, height)
        worker.setAutoDelete(False)
        worker.signals.finished.connect(
            lambda image, t=at, tok=token, k=key: self._on_done(tok, k, t, image)
        )
        worker.signals.failed.connect(lambda msg, detail, tok=token: self._on_failed(tok, msg))
        self._worker = worker
        self._pool.start(worker)

    def _on_done(self, token: int, key: tuple[int, int, int], at: float, image: object) -> None:
        self._running = False
        self._worker = None
        if token == self._token and isinstance(image, QImage):
            self._cache[key] = image
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_limit:
                self._cache.popitem(last=False)
            self.frame_ready.emit(at, image)
        QTimer.singleShot(0, self._dispatch)

    def _on_failed(self, token: int, message: str) -> None:
        self._running = False
        self._worker = None
        if token == self._token:
            self.failed.emit(message)
        QTimer.singleShot(0, self._dispatch)


class PlaybackWorker(QThread):
    """Decode a silent raw-video stream from ffmpeg and pace it to wall time."""

    frame_ready = Signal(object, float)
    failed = Signal(str)
    finished_playback = Signal()

    def __init__(
        self,
        path: Path,
        start_time: float,
        width: int,
        height: int,
        fps: float,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self.start_time = max(0.0, start_time)
        self.width = width
        self.height = height
        self.fps = fps if fps > 0 else 30.0
        self._stop = threading.Event()
        self._ack = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def acknowledge(self) -> None:
        self._ack.set()

    def stop(self) -> None:
        self._stop.set()
        self._ack.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self) -> None:  # pragma: no cover - exercised manually and via smoke tests
        command = [
            ffmpeg_path(),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{self.start_time:.6f}",
            "-i",
            str(self.path),
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"scale={self.width}:{self.height}:flags=fast_bilinear,fps={self.fps:.6f}",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        frame_size = self.width * self.height * 3
        process: subprocess.Popen[bytes] | None = None
        frames = 0
        failure: str | None = None
        try:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except FileNotFoundError as exc:
                failure = f"Could not start ffmpeg: {exc}"
            else:
                with self._lock:
                    self._process = process
                assert process.stdout is not None
                started = time.perf_counter()
                index = 0
                while not self._stop.is_set():
                    data = process.stdout.read(frame_size)
                    if not data or len(data) < frame_size:
                        break
                    target = started + index / self.fps
                    now = time.perf_counter()
                    if target > now:
                        if self._stop.wait(target - now):
                            break
                    elif now - target > 0.75:
                        # The UI cannot keep up; skip this frame entirely.
                        index += 1
                        continue

                    image = QImage(
                        data,
                        self.width,
                        self.height,
                        self.width * 3,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    self._ack.clear()
                    self.frame_ready.emit(image, self.start_time + index / self.fps)
                    deadline = time.perf_counter() + 0.75
                    while (
                        not self._ack.is_set()
                        and not self._stop.is_set()
                        and time.perf_counter() < deadline
                    ):
                        self._ack.wait(0.02)
                    frames += 1
                    index += 1
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - defensive boundary
            failure = f"Preview decoding failed: {exc}"
        finally:
            with self._lock:
                self._process = None
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    pass
                stderr = b""
                if process.stderr is not None:
                    try:
                        stderr = process.stderr.read() or b""
                    except OSError:
                        stderr = b""
                if (
                    failure is None
                    and not self._stop.is_set()
                    and process.returncode not in (0, None)
                    and stderr.strip()
                ):
                    failure = stderr.decode("utf-8", "replace").strip()

        if self._stop.is_set():
            return
        if failure is not None:
            self.failed.emit(failure)
        elif frames == 0:
            self.failed.emit("Preview playback produced no frames.")
        else:
            self.finished_playback.emit()


class VideoPreview(QWidget):
    """Paint ffmpeg-decoded frames, letterboxed in a dark surface."""

    position_changed = Signal(float)
    playback_started = Signal()
    playback_paused = Signal()
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._media: MediaInfo | None = None
        self._image: QImage | None = None
        self._status = "Open a video to begin"
        self._current_time = 0.0
        self._playing = False
        self._worker: PlaybackWorker | None = None
        self._extractor = FrameExtractor(self)
        self._extractor.frame_ready.connect(self._on_still)
        self._extractor.failed.connect(self._on_extract_failed)

    # ------------------------------------------------------------------ state
    @property
    def media(self) -> MediaInfo | None:
        return self._media

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def is_playing(self) -> bool:
        return self._playing

    def set_media(self, media: MediaInfo) -> None:
        self.stop()
        self._media = media
        self._image = None
        self._current_time = 0.0
        self._status = "Loading preview…"
        self._extractor.set_media(media.path)
        self.update()
        self._request_still(0.0, immediate=True)

    def clear(self) -> None:
        self.stop()
        self._media = None
        self._image = None
        self._current_time = 0.0
        self._status = "Open a video to begin"
        self._extractor.set_media(None)
        self.update()

    def seek(self, at: float, immediate: bool = True) -> None:
        if self._media is None:
            return
        at = min(max(0.0, at), max(0.0, self._media.duration - 1e-4))
        if self._playing:
            self.pause(request_still=False)
        self._current_time = at
        self._status = ""
        self._request_still(at, immediate=immediate)
        self.update()

    def play(self) -> None:
        if self._media is None or self._playing:
            return
        if self._current_time >= self._media.duration - 1e-3:
            self._current_time = 0.0
        display_width, display_height = self._media.display_size
        width, height = fit_size(display_width, display_height, _MAX_PLAYBACK)
        worker = PlaybackWorker(
            self._media.path,
            self._current_time,
            width,
            height,
            self._media.fps,
            self,
        )
        worker.frame_ready.connect(self._on_playback_frame)
        worker.failed.connect(self._on_playback_failed)
        worker.finished_playback.connect(self._on_playback_finished)
        self._worker = worker
        self._playing = True
        self._status = ""
        self.update()
        worker.start()
        self.playback_started.emit()

    def pause(self, request_still: bool = True) -> None:
        if not self._playing:
            return
        self._playing = False
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.stop()
            worker.wait(3000)
        self._status = ""
        if request_still:
            self._request_still(self._current_time, immediate=True)
        self.update()
        self.playback_paused.emit()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(3000)
            self._worker = None
        if self._playing:
            self._playing = False
            self.playback_paused.emit()

    def shutdown(self) -> None:
        """Release playback and still-frame workers before closing."""
        self.stop()
        self._extractor.shutdown()

    def toggle_playback(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def step_frames(self, count: int) -> None:
        if self._media is None:
            return
        if self._playing:
            self.pause(request_still=False)
        fps = self._media.fps or 30.0
        self.seek(self._current_time + count / fps, immediate=True)

    # --------------------------------------------------------------- internal
    def _request_still(self, at: float, immediate: bool = False) -> None:
        if self._media is None:
            return
        width, height = fit_size(*self._media.display_size, _MAX_STILL)
        self._extractor.request(at, width, height, immediate=immediate)

    def _on_still(self, at: float, image: object) -> None:
        if not isinstance(image, QImage):
            return
        if self._playing:
            return
        self._image = image
        self._status = ""
        self.update()

    def _on_extract_failed(self, message: str) -> None:
        self._status = f"Preview unavailable\n{message.strip()}"
        self.update()
        self.error.emit(message)

    def _on_playback_frame(self, image: object, position: float) -> None:
        if not self._playing or not isinstance(image, QImage):
            if self._worker is not None:
                self._worker.acknowledge()
            return
        self._image = image
        self._current_time = position
        self.update()
        self.position_changed.emit(position)
        if self._worker is not None:
            self._worker.acknowledge()

    def _on_playback_failed(self, message: str) -> None:
        self._playing = False
        self._worker = None
        self._status = f"Playback unavailable\n{message.strip()}"
        self.update()
        self.playback_paused.emit()
        self.error.emit(message)

    def _on_playback_finished(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._worker = None
        self._request_still(self._current_time, immediate=True)
        self.update()
        self.playback_finished.emit()
        self.playback_paused.emit()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b0c0d"))
        if self._image is not None and not self._image.isNull():
            target = self._image.rect()
            target.setSize(self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio))
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(target, self._image)
        if not self._image or self._status:
            painter.setPen(QColor("#8b949b"))
            font = QFont(self.font())
            font.setPointSize(max(10, font.pointSize() + 1))
            painter.setFont(font)
            text_rect = QRect(24, 24, max(1, self.width() - 48), max(1, self.height() - 48))
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                self._status,
            )
        if self._playing:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e5484d"))
            painter.drawEllipse(16, 14, 8, 8)
            painter.setPen(QColor("#d7dcdf"))
            font = QFont(self.font())
            font.setBold(True)
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(30, 22, "PLAYING · SILENT")
        elif self._media is not None and self._image is not None:
            painter.setPen(QColor("#636b71"))
            font = QFont(self.font())
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(
                12,
                self.height() - 10,
                f"{format_timecode(self._current_time)}  ·  silent preview",
            )
        painter.end()
