"""Download the bundled Inter font and Phosphor icon assets.

The application ships with these files so it never needs network access at
runtime. Re-run this script to refresh them:

    uv run python scripts/fetch_assets.py --force

Sources:
  * Inter 4.1 - https://github.com/rsms/inter (SIL Open Font License 1.1)
  * Phosphor Core 2.0.8 - https://github.com/phosphor-icons/core (MIT)
"""

from __future__ import annotations

import argparse
import io
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "losslesscut" / "assets"
FONT_DIR = ASSETS / "fonts"
ICON_DIR = ASSETS / "icons"

INTER_VERSION = "4.1"
INTER_URL = (
    f"https://github.com/rsms/inter/releases/download/v{INTER_VERSION}/Inter-{INTER_VERSION}.zip"
)
INTER_FONTS = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
)

PHOSPHOR_VERSION = "2.0.8"
PHOSPHOR_BASE = f"https://raw.githubusercontent.com/phosphor-icons/core/v{PHOSPHOR_VERSION}"
ICON_NAMES = (
    "arrow-counter-clockwise",
    "arrows-out",
    "caret-double-left",
    "caret-double-right",
    "caret-left",
    "caret-right",
    "export",
    "folder-open",
    "folder-simple",
    "git-merge",
    "magnifying-glass-minus",
    "magnifying-glass-plus",
    "pause",
    "play",
    "scissors",
    "skip-back",
    "skip-forward",
    "trash",
    "x",
)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "losslesscut-assets"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def _write(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        print(f"skip  {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"write {path.relative_to(ROOT)}")


def fetch_fonts(force: bool) -> None:
    print(f"Fetching Inter {INTER_VERSION}…")
    archive = zipfile.ZipFile(io.BytesIO(_download(INTER_URL)))
    for name in INTER_FONTS:
        entry = next(
            (item for item in archive.infolist() if item.filename.endswith(f"extras/ttf/{name}")),
            None,
        )
        if entry is None:
            raise SystemExit(f"Inter archive does not contain extras/ttf/{name}")
        _write(FONT_DIR / name, archive.read(entry), force)

    license_entry = next(
        (item for item in archive.infolist() if item.filename.endswith("LICENSE.txt")),
        None,
    )
    if license_entry is None:
        raise SystemExit("Inter archive does not contain LICENSE.txt")
    _write(FONT_DIR / "OFL.txt", archive.read(license_entry), force)


def fetch_icons(force: bool) -> None:
    print(f"Fetching Phosphor Core {PHOSPHOR_VERSION}…")
    for name in ICON_NAMES:
        url = f"{PHOSPHOR_BASE}/assets/regular/{name}.svg"
        _write(ICON_DIR / f"{name}.svg", _download(url), force)
    _write(ICON_DIR / "LICENSE.txt", _download(f"{PHOSPHOR_BASE}/LICENSE"), force)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite files that already exist",
    )
    args = parser.parse_args()
    fetch_fonts(args.force)
    fetch_icons(args.force)
    print("Assets are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
