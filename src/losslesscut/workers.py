"""Background worker helpers for blocking ffprobe work."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .ffmpeg_utils import FFmpegError


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str, str)


class Worker(QRunnable):
    """Run a callable in QThreadPool and report its result via signals."""

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except FFmpegError as exc:
            self.signals.failed.emit(str(exc), exc.detail)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - defensive UI boundary
            self.signals.failed.emit(str(exc) or exc.__class__.__name__, traceback.format_exc())
        else:
            self.signals.finished.emit(result)
