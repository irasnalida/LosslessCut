"""Small helpers for locating and running ffmpeg/ffprobe."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keep helper processes from flashing a console window on Windows.
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    def __init__(self, message: str, command: Iterable[str] | None = None, stderr: str = ""):
        super().__init__(message)
        self.command = list(command or [])
        self.stderr = stderr

    @property
    def detail(self) -> str:
        command = " ".join(self.command)
        parts = [str(self)]
        if command:
            parts.append(f"Command: {command}")
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n\n".join(parts)


def find_binary(name: str) -> str | None:
    """Return an absolute path for *name* from PATH, if present."""
    return shutil.which(name)


def ffmpeg_path() -> str:
    path = find_binary("ffmpeg")
    if not path:
        raise FFmpegError(
            "ffmpeg was not found on PATH. Install it and make sure the ffmpeg "
            "executable is available from the command line."
        )
    return path


def ffprobe_path() -> str:
    path = find_binary("ffprobe")
    if not path:
        raise FFmpegError(
            "ffprobe was not found on PATH. It is normally installed together "
            "with ffmpeg."
        )
    return path


def subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "creationflags": _CREATE_FLAGS,
    }
    if os.name != "nt":
        kwargs.pop("creationflags")
    return kwargs


def run_json(command: list[str], timeout: float | None = 120.0) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            timeout=timeout,
            check=False,
            **subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"Could not run {command[0]!r}.", command) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"{command[0]} timed out.", command) from exc

    stdout = result.stdout.decode("utf-8", "replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", "replace") if result.stderr else ""
    if result.returncode != 0:
        raise FFmpegError(
            f"{Path(command[0]).name} failed with exit code {result.returncode}.",
            command,
            stderr,
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegError(
            f"{Path(command[0]).name} returned invalid JSON.", command, stderr or stdout
        ) from exc


def run_capture(command: list[str], timeout: float | None = 120.0) -> bytes:
    try:
        result = subprocess.run(
            command,
            timeout=timeout,
            check=False,
            **subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"Could not run {command[0]!r}.", command) from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"{command[0]} timed out.", command) from exc

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if result.stderr else ""
        raise FFmpegError(
            f"{Path(command[0]).name} failed with exit code {result.returncode}.",
            command,
            stderr,
        )
    return result.stdout or b""


def probe_json(path: Path, extra_args: list[str] | None = None) -> dict[str, Any]:
    command = [ffprobe_path(), "-v", "error", "-of", "json"]
    command.extend(extra_args or [])
    command.append(str(path))
    return run_json(command)


@dataclass(frozen=True)
class BinaryStatus:
    ffmpeg: str | None
    ffprobe: str | None

    @property
    def ready(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    @property
    def message(self) -> str:
        if self.ready:
            return "ffmpeg and ffprobe are ready."
        missing = [
            name for name, value in (("ffmpeg", self.ffmpeg), ("ffprobe", self.ffprobe)) if not value
        ]
        return (
            "Missing from PATH: "
            + ", ".join(missing)
            + ". Install ffmpeg and restart the application."
        )


def check_binaries() -> BinaryStatus:
    return BinaryStatus(find_binary("ffmpeg"), find_binary("ffprobe"))
