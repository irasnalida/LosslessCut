from __future__ import annotations

import os
from pathlib import Path

from losslesscut import ffmpeg_utils


def _binary_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _write_binary(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _freeze(
    monkeypatch,
    executable: Path,
    bundle: Path | None = None,
) -> None:
    monkeypatch.setattr(ffmpeg_utils.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ffmpeg_utils.sys, "executable", str(executable))
    if bundle is None:
        monkeypatch.delattr(ffmpeg_utils.sys, "_MEIPASS", raising=False)
    else:
        monkeypatch.setattr(ffmpeg_utils.sys, "_MEIPASS", str(bundle), raising=False)


def test_find_binary_prefers_env_override(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    env_dir = tmp_path / "env"
    _write_binary(app_dir / "ffmpeg" / _binary_name("ffmpeg"))
    env_binary = _write_binary(env_dir / _binary_name("ffmpeg"))
    _freeze(monkeypatch, app_dir / "LosslessCut.exe", app_dir / "_internal")
    monkeypatch.setenv("LOSSLESSCUT_FFMPEG_DIR", str(env_dir))

    assert ffmpeg_utils.find_binary("ffmpeg") == str(env_binary)


def test_find_binary_prefers_beside_executable(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    folder_binary = _write_binary(app_dir / "ffmpeg" / _binary_name("ffmpeg"))
    _write_binary(app_dir / _binary_name("ffmpeg"))
    _freeze(monkeypatch, app_dir / "LosslessCut.exe", app_dir / "_internal")
    monkeypatch.delenv("LOSSLESSCUT_FFMPEG_DIR", raising=False)

    assert ffmpeg_utils.find_binary("ffmpeg") == str(folder_binary)


def test_find_binary_uses_executable_directory(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    exe_binary = _write_binary(app_dir / _binary_name("ffprobe"))
    _freeze(monkeypatch, app_dir / "LosslessCut.exe", app_dir / "_internal")
    monkeypatch.delenv("LOSSLESSCUT_FFMPEG_DIR", raising=False)

    assert ffmpeg_utils.find_binary("ffprobe") == str(exe_binary)


def test_find_binary_uses_bundle_directory(monkeypatch, tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    bundle_binary = _write_binary(
        app_dir / "_internal" / "ffmpeg" / _binary_name("ffmpeg")
    )
    _freeze(monkeypatch, app_dir / "LosslessCut.exe", app_dir / "_internal")
    monkeypatch.delenv("LOSSLESSCUT_FFMPEG_DIR", raising=False)

    assert ffmpeg_utils.find_binary("ffmpeg") == str(bundle_binary)


def test_find_binary_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.setattr(ffmpeg_utils, "binary_search_dirs", list)
    monkeypatch.setattr(
        ffmpeg_utils.shutil, "which", lambda name: f"/tools/{name}"
    )

    assert ffmpeg_utils.find_binary("ffmpeg") == "/tools/ffmpeg"


def test_binary_search_dirs_ignores_bundle_when_not_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delattr(ffmpeg_utils.sys, "frozen", raising=False)
    monkeypatch.delenv("LOSSLESSCUT_FFMPEG_DIR", raising=False)
    monkeypatch.setattr(
        ffmpeg_utils.os, "environ", {"PATH": str(tmp_path)}
    )

    assert ffmpeg_utils.binary_search_dirs() == []
