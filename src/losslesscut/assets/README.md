# Bundled assets

These files are bundled with LosslessCut so the application works offline.

## Fonts

- **Inter 4.1** by Rasmus Andersson — <https://github.com/rsms/inter>
- License: SIL Open Font License 1.1 (`fonts/OFL.txt`)
- Files: `Inter-Regular.ttf`, `Inter-Medium.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf`

## Icons

- **Phosphor Core 2.0.8** (regular and fill weights) — <https://github.com/phosphor-icons/core>
- License: MIT (`icons/LICENSE.txt`)
- `icon.svg` is the dedicated application icon source; the SVGs in `icons/` are
  used by the UI.
- `app.ico` is generated from `icon.svg` on a transparent background by
  `scripts/make_app_icon.py`.

## Refreshing

`scripts/fetch_assets.py` downloads the pinned versions above:

```powershell
uv run python scripts/fetch_assets.py --force
```
