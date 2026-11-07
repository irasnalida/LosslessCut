# LosslessCut

A desktop video cutter that removes sections **without re-encoding**. It is inspired by
[LosslessCut](https://github.com/mifi/lossless-cut) and built with Python, PySide6 and
ffmpeg.

![LosslessCut screenshot](docs/screenshot.png)

## Features

- Open a video with the file dialog or drag and drop it onto the window.
- Keyframe discovery directly from the video packets (with a decoded-frame fallback).
- Zoomable, scrollable timeline showing:
  - adaptive time ruler
  - keyframe boundaries
  - colored segment blocks
  - draggable playhead
- Mark segment starts and ends at the playhead, split at the nearest keyframe, delete unwanted parts, and export the rest.
- Create a segment by dropping a screenshot whose filename contains a `Thh'mm'ss'ms` timestamp.
- Export each segment as a separate file, or concatenate the selected segments into one file.
- Lossless output using `ffmpeg -c copy`; the video is never re-encoded.
- Dark Fusion theme with a segment list, duration/frame/size estimates and total duration.
- Silent, frame-accurate preview decoded by ffmpeg. Works with any codec ffmpeg can decode.
- Background metadata/keyframe scanning, real export progress and cancellation.

## Bundled assets

The application ships its visual assets so it works fully offline:

- [Inter](https://github.com/rsms/inter) 4.1 for the UI typography (SIL Open Font License 1.1).
- [Phosphor Icons](https://github.com/phosphor-icons/core) 2.0.8 regular weight for the
  interface icons (MIT).

Versions and licenses are documented in `src/losslesscut/assets/README.md`.
`scripts/fetch_assets.py` refreshes the pinned assets.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` available on `PATH`

The built executable does not need Python. It finds ffmpeg in an `ffmpeg\` folder
beside the executable, through `LOSSLESSCUT_FFMPEG_DIR`, or on `PATH`.

On Windows, for example:

```powershell
winget install Gyan.FFmpeg
```

Verify with:

```powershell
ffmpeg -version
ffprobe -version
```

## Setup

```powershell
uv sync
```

Run the application:

```powershell
uv run losslesscut
```

or:

```powershell
uv run python main.py
```

You can also pass a file directly:

```powershell
uv run losslesscut "C:\Videos\movie.mp4"
```

## Building a standalone executable

Build a folder-based executable with PyInstaller:

```powershell
uv sync
uv run python scripts/build_exe.py
```

The result is `dist\LosslessCut\LosslessCut.exe`. The folder contains the Python
runtime, PySide6, and the bundled fonts/icons, so the target machine does not need
Python installed.

Options:

```powershell
# Keep a console window for debugging
uv run python scripts/build_exe.py --console

# Copy ffmpeg and ffprobe from PATH into dist\LosslessCut\ffmpeg
uv run python scripts/build_exe.py --with-ffmpeg

# Use specific binaries
uv run python scripts/build_exe.py --with-ffmpeg --ffmpeg-dir C:\tools\ffmpeg\bin

# Verify the frozen app (exit code 0 means everything loaded)
dist\LosslessCut\LosslessCut.exe --self-check
```

ffmpeg is not bundled by default. At runtime it is searched in this order:

1. `LOSSLESSCUT_FFMPEG_DIR`
2. `ffmpeg\` beside the executable
3. the executable directory
4. `PATH`

`build\` and `dist\` are ignored by git. Regenerate the application icon with:

```powershell
uv run python scripts/make_app_icon.py
```

## Usage

1. Open a video or drag it onto the window.
2. Wait for the keyframe scan to finish. The status bar shows the keyframe count.
3. Navigate the timeline and preview:
   - click or drag on the timeline to seek
   - use the mouse wheel to zoom around the cursor
   - Shift+wheel or middle-drag to pan
   - use the frame and keyframe buttons below the timeline
4. Move the playhead inside the full-length segment and press **S** (or **Split at
   playhead**). The split is snapped to the nearest keyframe boundary.
5. Select a segment card and press **Delete** to remove it.
6. Choose an output folder with the **Output** button.
7. Pick **Separate files** or **Merge into one file**, then click **Export**.

Existing files are never overwritten; a numeric suffix is added instead.

Segments are always kept in start-time order. That order drives the segment numbering, the
separate file names, and the merged concatenation.

### Marking segments at the playhead

The two hand buttons flanking the playback controls build segments without splitting:

- **Mark start** (`[`, left hand) starts a new segment at the keyframe at or before the
  playhead. It initially ends at the next keyframe.
- **Mark end** (`]`, right hand) extends the selected segment to the first keyframe at or
  after the playhead. It never moves an end backward, so place the playhead past the
  current end.

Marking a start on the untouched full-length segment replaces it. Once other segments
exist, new starts are appended and selected. If the same interval already exists, it is
selected instead of duplicated. Overlapping segments are allowed, matching
screenshot-created segments.

### Creating segments from screenshots

Drop an image whose filename contains a media-player timestamp in the form
`Thh'mm'ss'ms`. For example:

```text
Outer Banks (2020) - S01E09 - The Bell Tower [WEBDL-1080p][EAC3 5.1][h265]-HONE-T00'38'07'285.png
```

The image itself is not read. `T00'38'07'285` is parsed as `00:38:07.285` and the
keyframe interval containing that time becomes a segment. If the timestamp lands exactly
on a keyframe, that keyframe starts the segment. The new segment is selected and the
preview jumps to the timestamp.

- The untouched full-length segment is replaced by the first dropped screenshot segment;
  later images are appended.
- Dropping an identical interval selects the existing segment instead of duplicating it.
- Several images can be dropped at once.
- Images dropped while the keyframe scan is running are queued and applied when it finishes.
- Supported image extensions: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+O` | Open video |
| `Space` | Play / pause silent preview |
| `Left` / `Right` | Step one frame |
| `Shift+Left` / `Shift+Right` | Jump one second |
| `Up` / `Down` | Previous / next keyframe |
| `Home` / `End` | Go to start / end |
| `[` | Mark a segment start at the playhead |
| `]` | Extend the selected segment to the playhead |
| `S` | Split the active segment at the nearest keyframe |
| `Delete` / `Backspace` | Delete the selected segment |
| `Ctrl+E` | Export segments using the selected mode |
| `Ctrl+Shift+E` | Export all segments merged into one file |
| `+` / `-` | Zoom timeline in / out |
| `F` | Fit the whole video in the timeline |
| `F11` | Toggle full screen |
| `Ctrl+C` | Copy the current timecode |
| `Ctrl+Q` | Quit |

## How the lossless cut works

Every segment boundary is a keyframe timestamp. Export runs ffmpeg with stream copy:

```text
ffmpeg -ss START -i INPUT -t DURATION -map 0 -c copy \
       -avoid_negative_ts make_zero OUTPUT
```

Because the video and audio packets are copied rather than decoded and re-encoded, the
output quality is identical to the source and exports are very fast. A few details follow
from that:

- The cut starts exactly at a keyframe.
- Audio may extend slightly past the requested end because compressed audio frames do not
  align with video frames. This is normal for stream-copy cuts.
- **All tracks** is enabled by default, so audio and subtitle streams are copied too.
  Disable it if the output container cannot hold every stream.
- Merged exports use the source container when it is concat-friendly, otherwise MKV.
  Streams that are incompatible with the chosen container will produce an ffmpeg error.

The preview is deliberately silent and frame-accurate: ffmpeg decodes still frames for
scrubbing and a raw-video stream for playback. No QtMultimedia codecs are involved, so a
file that ffmpeg can read can be previewed even if the operating system cannot play it.

## Project layout

```text
src/losslesscut/
  app.py            application entry point
  theme.py          dark Fusion palette, Inter font and stylesheet
  icons.py          Phosphor SVG loading, recolouring and caching
  assets/           bundled Inter fonts, Phosphor icons and licenses
  models.py         media/segment models, timecode and snapping helpers
  ffmpeg_utils.py   binary discovery and subprocess helpers
  ffprobe.py        metadata and keyframe discovery
  preview.py        ffmpeg frame preview and silent playback
  timeline.py       zoomable custom-painted timeline
  segments.py       segment card list
  exporter.py       lossless cut/merge jobs with progress and cancel
  workers.py        background probe workers
  main_window.py    window, menus, drag and drop, export flow
scripts/
  fetch_assets.py   downloads the pinned font and icon assets
tests/              unit, ffmpeg integration and Qt smoke tests
```

## Tests

```powershell
uv run pytest
```

The integration tests generate a small H.264/AAC sample with ffmpeg and verify metadata,
keyframe discovery, frame extraction, separate export and merged export. They are skipped
automatically when ffmpeg is not available.

## Known limitations

- Only keyframe-aligned boundaries are offered, by design.
- Preview has no audio.
- The timeline shows one video track; exporting still copies all selected streams.
- Very unusual containers may reject stream-copy output; choose a compatible container or
  disable **All tracks**.
