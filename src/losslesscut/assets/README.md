# Bundled assets

These files are bundled with LosslessCut so the application works offline.

## Fonts

- **Inter 4.1** by Rasmus Andersson — <https://github.com/rsms/inter>
- License: SIL Open Font License 1.1 (`fonts/OFL.txt`)
- Files: `Inter-Regular.ttf`, `Inter-Medium.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf`

## Icons

- **Phosphor Core 2.0.8** (regular weight) — <https://github.com/phosphor-icons/core>
- License: MIT (`icons/LICENSE.txt`)
- Only the SVGs used by the UI are included.
- `app.ico` is generated from `icons/scissors.svg` by `scripts/make_app_icon.py`.

## Refreshing

`scripts/fetch_assets.py` downloads the pinned versions above:

```powershell
uv run python scripts/fetch_assets.py --force
```
