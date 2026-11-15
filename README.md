# image-shrinker

A terminal UI and CLI for shrinking images while keeping them looking good.

Point it at files or folders and it re-encodes them to JPEG, WebP, PNG, or AVIF —
either at a fixed quality, or by automatically searching for the largest
quality/scale that still fits under a target file size.

## Features

- **Terminal UI** with a file queue, live preview, progress bar, and log
- **Two modes**
  - `quality` — encode at a quality you choose
  - `target` — hit a max file size (binary-searches quality, then resolution)
- **Presets** — Web (WebP), Email (≤500 KB), Social (1080), Thumbnail, Lossless PNG
- **Formats** — keep the original, or convert to JPEG / WebP / PNG / AVIF
- **Metadata handling** — optional EXIF retention, orientation respected
- **Safety** — dry-run estimate mode, skips files that are already optimal, never
  overwrites unless you ask it to
- **Parallel processing** — multi-threaded, configurable worker count
- **CSV reports** and one-key "open output folder"
- Settings persist between runs

## Requirements

- Python 3.10+
- `pillow>=10.0` and `textual>=0.80` (see `requirements.txt`)

```bash
pip install -r requirements.txt
```

AVIF output requires a Pillow build with AVIF support; the app detects this and
hides the option when unavailable.

## Usage

Launch the terminal UI:

```bash
python main.py
```

Start it with files or folders already queued:

```bash
python main.py ~/Pictures/holiday ~/Desktop/logo.png
```

Headless CLI mode:

```bash
python main.py --cli ~/Pictures --format webp --quality 80 --max-dim 2048
python main.py --cli ~/Pictures/hero.jpg --target 500 --out ./optimized
```

### Common options

| Flag | Meaning |
| --- | --- |
| `--cli` | Run headless, no TUI |
| `--format` | `keep`, `jpeg`, `webp`, `png`, `avif` |
| `--quality` | Fixed quality, 1–100 |
| `--target` | Max file size in KB (switches to target mode) |
| `--max-dim` | Longest side in pixels, `0` for no limit |
| `--out` | Output folder (default: next to the original) |
| `--overwrite` | Overwrite the original when the format is unchanged |
| `--keep-exif` | Preserve EXIF metadata |
| `--dry-run` | Estimate results without writing files |
| `--no-recursive` | Don't descend into subfolders |
| `--workers` | Number of parallel workers |
| `--preset` | Apply a preset first; other flags override it |

### TUI keybindings

| Key | Action |
| --- | --- |
| `Ctrl+O` | Browse for files or folders |
| `F5` | Compress |
| `F6` | Estimate (dry run) |
| `F7` | Write a CSV report |
| `F8` | Remove the selected row |
| `F9` | Clear the queue |
| `F4` | Open the output folder |
| `Ctrl+Q` | Quit |

## How target-size mode works

1. Search the highest quality that fits while keeping the full resolution.
2. If even the lowest quality is too big, binary-search a downscale factor.
3. Re-run the quality search on the scaled image.

If the target still can't be reached, the file is written at the smallest size
found and flagged in the report.

## Output naming

By default results are written next to the original with a suffix
(`photo.min.webp`, or `photo.min.jpg` when the format changes). Name collisions
get `-1`, `-2`, … appended. Files that would not get smaller are reported as
`already optimal` and left alone.

## Contributing

Contributions are welcome — issues, bug reports, and pull requests alike.
If you're sending a change, keep it focused and explain *why* it's needed.

```bash
git clone https://github.com/faridhafizh/image-shrinker.git
cd image-shrinker
python -m venv .venv
```

Activate the virtual environment (`.\.venv\Scripts\activate` on Windows,
`source .venv/bin/activate` elsewhere), then install the dependencies:

```bash
pip install -r requirements.txt
```

Run it with `python main.py` for the TUI, or `python main.py --cli <paths>` for
headless mode. Please test both paths before opening a pull request.

## License

Released under the [MIT License](LICENSE) — free to use, modify, and distribute,
including commercially, as long as the copyright notice is kept.
