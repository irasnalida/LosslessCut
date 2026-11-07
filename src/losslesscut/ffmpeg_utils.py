"""Small helpers for locating and running ffmpeg/ffprobe."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def binary_search_dirs() -> list[Path]:
    """Return the directories searched for bundled ffmpeg binaries.

    Frozen builds check an explicit override first, then an ``ffmpeg`` folder
    beside the executable, the executable directory itself, and the
    PyInstaller bundle directory.
    """
    directories: list[Path] = []
    override = os.environ.get("LOSSLESSCUT_FFMPEG_DIR")
    if override:
        directories.append(Path(override))
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        directories.extend((executable_dir / "ffmpeg", executable_dir))
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            bundle = Path(bundle_dir)
            directories.extend((bundle / "ffmpeg", bundle))
    return directories


def find_binary(name: str) -> str | None:
    """Return an absolute path for *name* from the bundle or PATH."""
    filename = f"{name}.exe" if os.name == "nt" else name
    for directory in binary_search_dirs():
        candidate = directory / filename
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def ffmpeg_path() -> str:
    path = find_binary("ffmpeg")
    if not path:
        raise FFmpegError(
            "ffmpeg was not found. Put it in the ffmpeg folder next to the "
            "application, set LOSSLESSCUT_FFMPEG_DIR, or install it on PATH."
        )
    return path


def ffprobe_path() -> str:
    path = find_binary("ffprobe")
    if not path:
        raise FFmpegError(
            "ffprobe was not found. Put it in the ffmpeg folder next to the "
            "application, set LOSSLESSCUT_FFMPEG_DIR, or install it on PATH."
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
            "Missing: "
            + ", ".join(missing)
            + ". Put them in the ffmpeg folder next to the application, set "
            "LOSSLESSCUT_FFMPEG_DIR, or install them on PATH."
        )


def check_binaries() -> BinaryStatus:
    return BinaryStatus(find_binary("ffmpeg"), find_binary("ffprobe"))
