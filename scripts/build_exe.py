"""Build a standalone LosslessCut executable with PyInstaller."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASSETS = SRC / "losslesscut" / "assets"
ENTRY = ROOT / "main.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "LosslessCut"


def _binary_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _check_prerequisites() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit(
            "PyInstaller is not installed. Run `uv sync` and try again."
        )
    required = (
        ASSETS / "fonts" / "Inter-Regular.ttf",
        ASSETS / "icons" / "hand-pointing.svg",
        ASSETS / "app.ico",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "Missing bundled assets:\n  "
            + "\n  ".join(missing)
            + "\nRun `uv run python scripts/fetch_assets.py` and "
            "`uv run python scripts/make_app_icon.py`."
        )


def _copy_ffmpeg(target_dir: Path, source_dir: Path | None) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        filename = _binary_name(name)
        if source_dir is not None:
            source = source_dir / filename
            if not source.is_file():
                raise SystemExit(f"{filename} was not found in {source_dir}.")
        else:
            found = shutil.which(name)
            if not found:
                raise SystemExit(
                    f"{name} was not found on PATH. Install it or pass --ffmpeg-dir."
                )
            source = Path(found)
        destination = target_dir / filename
        shutil.copy2(source, destination)
        print(f"copied {source} -> {destination}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--console",
        action="store_true",
        help="keep a console window for debugging",
    )
    parser.add_argument(
        "--with-ffmpeg",
        action="store_true",
        help="copy ffmpeg and ffprobe into an ffmpeg folder beside the executable",
    )
    parser.add_argument(
        "--ffmpeg-dir",
        type=Path,
        help="directory containing ffmpeg and ffprobe (requires --with-ffmpeg)",
    )
    args = parser.parse_args()
    if args.ffmpeg_dir is not None and not args.with_ffmpeg:
        parser.error("--ffmpeg-dir requires --with-ffmpeg")

    _check_prerequisites()
    BUILD.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--noupx",
        "--name",
        APP_NAME,
        "--paths",
        str(SRC),
        "--add-data",
        f"{ASSETS}{os.pathsep}losslesscut/assets",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        "--icon",
        str(ASSETS / "app.ico"),
    ]
    if not args.console:
        command.append("--windowed")
    command.append(str(ENTRY))

    print("Running:", " ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    executable = DIST / APP_NAME / _binary_name(APP_NAME)
    if not executable.exists():
        raise SystemExit(f"Expected {executable} to exist after the build.")

    if args.with_ffmpeg:
        _copy_ffmpeg(executable.parent / "ffmpeg", args.ffmpeg_dir)

    size_mb = sum(
        path.stat().st_size for path in executable.parent.rglob("*") if path.is_file()
    ) / (1024 * 1024)
    print(f"\nBuilt {executable} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
