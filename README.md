<div align="center">

# 🗜️ image-shrinker

**Shrink images in your terminal — without making them look worse.**

A fast terminal UI and CLI that re-encodes images to JPEG, WebP, PNG or AVIF,
either at a fixed quality or by automatically finding the best quality/scale
that fits under a target file size.

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Pillow](https://img.shields.io/badge/pillow-%E2%89%A510.0-informational)](https://python-pillow.org/)
[![Textual](https://img.shields.io/badge/TUI-textual-5A3FD8)](https://textual.textualize.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Features](#-features) ·
[Install](#-installation) ·
[Usage](#-usage) ·
[Target-size mode](#-how-target-size-mode-works) ·
[Contributing](#-contributing)

</div>

<!-- Tip: add a screenshot or GIF of the TUI here
<p align="center"><img src="docs/screenshot.png" alt="image-shrinker TUI" width="800"></p>
-->

---

## ✨ Features

| | |
| --- | --- |
| 🖥️ **Terminal UI** | File queue, live preview, progress bar and log |
| 🎯 **Two modes** | `quality` — encode at a quality you choose<br>`target` — hit a max file size (binary-searches quality, then resolution) |
| 🎛️ **Presets** | Web (WebP) · Email (≤ 500 KB) · Social (1080) · Thumbnail · Lossless PNG |
| 🔄 **Formats** | Keep the original, or convert to JPEG / WebP / PNG / AVIF |
| 🏷️ **Metadata** | Optional EXIF retention, orientation respected |
| 🛡️ **Safety** | Dry-run estimates, skips already-optimal files, never overwrites unless asked |
| ⚡ **Parallel** | Multi-threaded with a configurable worker count |
| 📊 **Reports** | CSV export and one-key "open output folder" |
| 💾 **Persistent** | Settings are remembered between runs |

---

## 📦 Installation

**Requirements:** Python 3.10+, `pillow>=10.0`, `textual>=0.80`

```bash
git clone https://github.com/faridhafizh/image-shrinker.git
cd image-shrinker
pip install .
```

That installs the `imgshrink` command. For an editable install with the dev
tools (pytest, ruff), see [Contributing](#-contributing).

> [!NOTE]
> AVIF output needs a Pillow build with AVIF support. The app detects this
> automatically and hides the option when it's unavailable.

---

## 🚀 Usage

### Terminal UI

```bash
imgshrink
```

Start with files or folders already queued:

```bash
imgshrink ~/Pictures/holiday ~/Desktop/logo.png
```

`python -m imgshrink` and the old `python main.py` entry point behave the same.

### Headless CLI

```bash
# Fixed quality, convert to WebP, cap longest side at 2048 px
imgshrink --cli ~/Pictures --format webp --quality 80 --max-dim 2048

# Target mode: fit under 500 KB, write to ./optimized
imgshrink --cli ~/Pictures/hero.jpg --target 500 --out ./optimized
```

### CLI options

| Flag | Description |
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

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| `Ctrl+O` | Browse files / folders | `F8` | Remove selected row |
| `F5` | Compress | `F9` | Clear the queue |
| `F6` | Estimate (dry run) | `F4` | Open output folder |
| `F7` | Write CSV report | `Ctrl+Q` | Quit |

---

## 🎯 How target-size mode works

```mermaid
flowchart TD
    A[Start at full resolution] --> B[Binary-search the highest quality that fits]
    B -->|fits| Z[Write file ✅]
    B -->|even lowest quality is too big| C[Binary-search a downscale factor]
    C --> D[Re-run quality search on the scaled image]
    D -->|fits| Z
    D -->|still too big| E[Write smallest result found<br/>and flag it in the report ⚠️]
```

1. Find the highest quality that fits while keeping the full resolution.
2. If even the lowest quality is too big, binary-search a downscale factor.
3. Re-run the quality search on the scaled image.

If the target still can't be reached, the file is written at the smallest size
found and flagged in the report.

---

## 📁 Output naming

Results are written next to the original with a `.min` suffix:

| Input | Output |
| --- | --- |
| `photo.jpg` → same format | `photo.min.jpg` |
| `photo.jpg` → WebP | `photo.min.webp` |
| Name collision | `photo.min-1.webp`, `photo.min-2.webp`, … |

Files that wouldn't get smaller are reported as **`already optimal`** and left
untouched.

---

## 🤝 Contributing

Contributions are welcome — issues, bug reports and pull requests alike.
Keep changes focused, explain *why* they're needed, and see
[CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

<details>
<summary><b>Development setup</b></summary>

```bash
git clone https://github.com/faridhafizh/image-shrinker.git
cd image-shrinker
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows
.\.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

Install the project with its dev tools:

```bash
pip install -e ".[dev]"
```

That gives you the `imgshrink` command, plus `pytest` and `ruff`.

</details>

<details>
<summary><b>Project layout</b></summary>

| Path | Responsibility |
| --- | --- |
| `imgshrink/imaging.py` | Pixel work: load, resize, encode, target-size search |
| `imgshrink/constants.py` | Format tables and `human()` byte formatting |
| `imgshrink/config.py` | `Config`, presets, reading/writing settings |
| `imgshrink/paths.py` | Pasted-path parsing, folder walking, open-folder |
| `imgshrink/pipeline.py` | One file in → one file out, skip rules, CSV reports |
| `imgshrink/cli.py` | Flags, headless mode, entry points |
| `imgshrink/tui/app.py` | The Textual app: queue, preview, progress, actions |
| `imgshrink/tui/settings.py` | The settings form |
| `imgshrink/tui/widgets.py` | Terminal image preview |
| `imgshrink/tui/screens.py` | Folder picker modal |
| `imgshrink/tui/app.tcss` | Colours and spacing |

The engine (`imaging.py`, `pipeline.py`) never imports Textual and the TUI never
parses `argv`, so the two halves can be changed and tested independently.

</details>

### Checks

```bash
pytest
ruff check .
```

The suite is headless and drives the TUI through Textual's test driver. Please
test both the TUI and `--cli` paths before opening a pull request.

---

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify and distribute,
including commercially, as long as the copyright notice is kept.

<div align="center">

Made with ☕ by [faridhafizh](https://github.com/faridhafizh)

</div>
