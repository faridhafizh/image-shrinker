#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

try:
    from PIL import Image, ImageOps, features
except ImportError:
    sys.exit("This tool needs Pillow.\nInstall it with:  pip install pillow")

# ====================================================================== engine

RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
QUANT_FASTOCTREE = getattr(getattr(Image, "Quantize", Image), "FASTOCTREE", 2)
QUANT_MEDIANCUT = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT", 0)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
SRC_FMT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP",
           ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".avif": "AVIF"}
HAS_AVIF = features.check("avif")
KEEPABLE = {"JPEG", "PNG", "WEBP"} | ({"AVIF"} if HAS_AVIF else set())
EXT_FOR = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png", "AVIF": ".avif"}
FORMATS = ["keep", "jpeg", "webp", "png"] + (["avif"] if HAS_AVIF else [])

# Mid-range probe quality used to drive the scale search in target mode.
PROBE_Q = {"JPEG": 80, "WEBP": 80, "AVIF": 60, "PNG": 200}  # PNG = colour count

PRESETS: dict[str, dict] = {
    "Custom":         {},
    "Web (WebP)":     {"fmt": "webp", "mode": "quality", "quality": 80, "max_dim": 2048},
    "Email (≤500 KB)": {"fmt": "jpeg", "mode": "target", "target_kb": 500, "max_dim": 1600},
    "Social (1080)":  {"fmt": "jpeg", "mode": "quality", "quality": 85, "max_dim": 1080},
    "Thumbnail":      {"fmt": "webp", "mode": "quality", "quality": 70, "max_dim": 400},
    "Lossless PNG":   {"fmt": "png", "mode": "quality", "quality": 100, "max_dim": 0},
}


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@dataclass
class Config:
    fmt: str = "keep"          # keep | jpeg | webp | png | avif
    mode: str = "quality"      # quality | target
    quality: int = 80
    target_kb: int = 200
    max_dim: int = 0           # 0 = no limit
    out_dir: str = ""          # "" = next to original
    suffix: str = ".min"
    overwrite: bool = False
    keep_exif: bool = False
    dry_run: bool = False
    workers: int = max(1, min(4, os.cpu_count() or 2))
    recursive: bool = True


CONFIG_PATH = (Path(os.environ.get("APPDATA", Path.home() / ".config"))
               / "imgshrink" / "config.json")


def load_config() -> Config:
    cfg = Config()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        valid = {f.name for f in fields(Config)}
        for k, v in raw.items():
            if k in valid:
                setattr(cfg, k, v)
    except Exception:
        pass
    return cfg


def save_config(cfg: Config) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- imaging

def load_image(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    return ImageOps.exif_transpose(img)  # respect camera orientation


def fit(img: Image.Image, max_dim: int) -> Image.Image:
    if max_dim and max(img.size) > max_dim:
        img = img.copy()
        img.thumbnail((max_dim, max_dim), RESAMPLE)
    return img


def _to_rgb(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white and return an RGB image."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def encode(img: Image.Image, fmt: str, level: int, exif: bytes | None = None) -> bytes:
    """Encode. `level` = quality (JPEG/WebP/AVIF) or colour count (PNG)."""
    buf = io.BytesIO()
    extra = {"exif": exif} if exif else {}
    if fmt == "JPEG":
        im = img if img.mode == "RGB" else _to_rgb(img)
        im.save(buf, "JPEG", quality=int(level), optimize=True, progressive=True, **extra)
    elif fmt == "WEBP":
        im = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")
        im.save(buf, "WEBP", quality=int(level), method=6, **extra)
    elif fmt == "AVIF":
        im = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")
        im.save(buf, "AVIF", quality=int(level), **extra)
    elif fmt == "PNG":
        im = img
        if level < 256:
            try:
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA").quantize(colors=int(level), method=QUANT_FASTOCTREE)
                else:
                    im = im.convert("RGB").quantize(colors=int(level), method=QUANT_MEDIANCUT)
            except Exception:
                im = img
        im.save(buf, "PNG", optimize=True, compress_level=9)
    else:
        raise ValueError(f"unsupported output format: {fmt}")
    return buf.getvalue()


def _search(img, fmt, target, lo, hi, exif=None):
    """Binary-search the highest level that still fits in `target` bytes."""
    data = encode(img, fmt, lo, exif)
    if len(data) > target:
        return None
    best = (data, lo)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        data = encode(img, fmt, mid, exif)
        if len(data) <= target:
            best, lo = (data, mid), mid
        else:
            hi = mid - 1
    return best


def _resize(img: Image.Image, scale: float) -> Image.Image:
    dims = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(dims, RESAMPLE)


def _png_colours(quality: int) -> int:
    """PNG quality 100 = lossless recompress, lower = fewer palette colours."""
    return 256 if quality >= 100 else max(16, int(16 + 240 * quality / 100))


def shrink(img: Image.Image, fmt: str, cfg: Config):
    """Return (bytes, info). info = {'level', 'size', 'scale'}."""
    work = fit(img, cfg.max_dim)
    info = {"level": 0, "size": work.size, "scale": 1.0}
    exif = None
    if cfg.keep_exif and fmt in ("JPEG", "WEBP", "AVIF"):
        try:
            exif = img.getexif().tobytes() or None
        except Exception:
            exif = None

    lo_q, hi_q = (16, 256) if fmt == "PNG" else (20, 95)

    if cfg.mode == "quality":
        level = _png_colours(cfg.quality) if fmt == "PNG" else max(1, min(100, cfg.quality))
        data = encode(work, fmt, level, exif)
        info["level"] = level
        return data, info

    target = max(1, cfg.target_kb) * 1024

    best = _search(work, fmt, target, lo_q, hi_q, exif)          # phase 1: full size
    if best:
        info["level"] = best[1]
        return best[0], info

    probe_q = PROBE_Q[fmt]                                        # phase 2: scale search
    lo, hi, best_scale = 0.05, 1.0, None
    while hi - lo > 0.01:
        mid = (lo + hi) / 2
        if len(encode(_resize(work, mid), fmt, probe_q, exif)) <= target:
            best_scale, lo = mid, mid
        else:
            hi = mid
    scale = best_scale if best_scale is not None else 0.05
    scaled = _resize(work, scale)
    info["scale"] = scale

    res = _search(scaled, fmt, target, lo_q, hi_q, exif)          # phase 3: max quality
    if res:
        info["level"], info["size"] = res[1], scaled.size
        return res[0], info
    info["level"], info["size"] = lo_q, scaled.size
    return encode(scaled, fmt, lo_q, exif), info


# --------------------------------------------------------------- paths

def resolve_format(src: Path, cfg: Config) -> str:
    if cfg.fmt != "keep":
        return cfg.fmt.upper()
    src_fmt = SRC_FMT.get(src.suffix.lower())
    return src_fmt if src_fmt in KEEPABLE else "JPEG"


def destination(src: Path, cfg: Config, fmt: str) -> Path:
    ext = EXT_FOR[fmt]
    same_fmt = SRC_FMT.get(src.suffix.lower()) == fmt
    if cfg.out_dir:
        base = Path(cfg.out_dir).expanduser()
        dest = base / (src.stem + ext)
    elif cfg.overwrite and same_fmt:
        dest = src
    else:
        dest = src.with_name(src.stem + cfg.suffix + ext)
    if dest.exists() and dest.resolve() != src.resolve() and not cfg.overwrite:
        stem, i = dest.stem, 1
        while dest.exists():
            dest = dest.with_name(f"{stem}-{i}{dest.suffix}")
            i += 1
    return dest


def parse_paths(raw: str) -> list[Path]:
    """Parse pasted / drag-and-dropped paths: quoted, escaped spaces, or one per line."""
    out: list[Path] = []
    pat = re.compile(r'"([^"]+)"|\'([^\']+)\'|((?:\\ |[^\s])+)')
    for line in raw.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        if Path(line.strip("\"'")).expanduser().exists():       # whole line is one path
            out.append(Path(line.strip("\"'")).expanduser())
            continue
        for m in pat.finditer(line):
            tok = m.group(1) or m.group(2) or m.group(3)
            if os.name != "nt":
                tok = tok.replace("\\ ", " ")
            out.append(Path(tok).expanduser())
    return out


def collect_images(paths: list[Path], recursive: bool, suffix: str) -> list[Path]:
    seen, files = set(), []
    for p in paths:
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            cand = (q for q in it if q.is_file() and q.suffix.lower() in IMAGE_EXTS
                    and not (suffix and q.stem.endswith(suffix)))
        elif p.is_file():
            cand = [p]
        else:
            continue
        for q in sorted(cand):
            key = q.resolve()
            if key not in seen:
                seen.add(key)
                files.append(q)
    return files


@dataclass
class Result:
    src: Path
    status: str = "queued"      # queued | done | skipped | error | estimated
    before: int = 0
    after: int = 0
    dest: Path | None = None
    note: str = ""
    elapsed: float = 0.0
    out_px: tuple[int, int] | None = None
    in_px: tuple[int, int] | None = None
    reached: bool = True


def process_file(src: Path, cfg: Config) -> Result:
    t0 = time.perf_counter()
    res = Result(src=src, before=src.stat().st_size)
    try:
        img = load_image(src)
    except Exception as exc:
        res.status, res.note = "error", f"cannot open: {exc}"
        return res
    try:
        fmt = resolve_format(src, cfg)
        res.in_px = img.size
        data, info = shrink(img, fmt, cfg)
        dest = destination(src, cfg, fmt)
        same_fmt = SRC_FMT.get(src.suffix.lower()) == fmt
        res.after, res.dest, res.out_px = len(data), dest, info["size"]

        bits = []
        lvl = info["level"]
        if fmt == "PNG" and 0 < lvl < 256:
            bits.append(f"{lvl} colours")
        elif fmt != "PNG" and lvl:
            bits.append(f"q{lvl}")
        if info["size"] != img.size:
            bits.append(f"{info['size'][0]}×{info['size'][1]}px")
        res.note = ", ".join(bits)

        if cfg.mode == "target" and res.after > cfg.target_kb * 1024:
            res.reached = False
            res.note += " ⚠ target not reached"

        if len(data) >= res.before and same_fmt and dest.resolve() != src.resolve():
            res.status, res.note = "skipped", "already optimal"
        elif cfg.dry_run:
            res.status = "estimated"
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            res.status = "done"
    except Exception as exc:
        res.status, res.note = "error", str(exc)
    res.elapsed = time.perf_counter() - t0
    return res


def save_report(results: list[Result], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "output", "status", "before_bytes", "after_bytes",
                    "saved_pct", "note"])
        for r in results:
            pct = f"{100 * (1 - r.after / r.before):.1f}" if r.before and r.after else ""
            w.writerow([r.src, r.dest or "", r.status, r.before, r.after, pct, r.note])


def open_in_file_manager(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


# ====================================================================== CLI

def run_cli(args: argparse.Namespace, cfg: Config) -> int:
    files = collect_images([Path(p).expanduser() for p in args.paths],
                           cfg.recursive, cfg.suffix)
    if not files:
        print("No images found.")
        return 1
    ok = tot_b = tot_a = 0
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        futs = {pool.submit(process_file, f, cfg): f for f in files}
        for fut in as_completed(futs):
            r = fut.result()
            mark = {"done": "✔", "estimated": "≈", "skipped": "•", "error": "✖"}[r.status]
            if r.status in ("done", "estimated"):
                ok += 1
                tot_b += r.before
                tot_a += r.after
                print(f"{mark} {r.src.name}: {human(r.before)} → {human(r.after)} "
                      f"({100 * (1 - r.after / r.before):.0f}%) {r.note}")
            else:
                print(f"{mark} {r.src.name}: {r.note}")
    if ok:
        print(f"\nTotal: {ok} file(s)  {human(tot_b)} → {human(tot_a)}  "
              f"saved {human(max(0, tot_b - tot_a))}")
    return 0


# ====================================================================== TUI

def build_app():
    from rich.text import Text
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import (Button, DataTable, DirectoryTree, Footer, Header,
                                 Input, Label, ProgressBar, RichLog, Select, Static,
                                 Switch)

    class ImagePreview(Static):
        """Renders an image in the terminal using half-block characters."""

        def show(self, path: Path | None) -> None:
            self._path = path
            self.refresh_preview()

        def on_resize(self) -> None:
            self.refresh_preview()

        def refresh_preview(self) -> None:
            path = getattr(self, "_path", None)
            w, h = self.size.width, self.size.height
            if not path or w < 4 or h < 2:
                self.update(Text("no preview", style="dim"))
                return
            try:
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im)
                    im = im.convert("RGBA")
                    im.thumbnail((w, h * 2), RESAMPLE)
                    bg = Image.new("RGBA", im.size, (24, 24, 32, 255))
                    im = Image.alpha_composite(bg, im).convert("RGB")
            except Exception:
                self.update(Text("cannot preview", style="dim"))
                return
            if im.height % 2:
                im = im.crop((0, 0, im.width, im.height - 1))
            px = im.load()
            text = Text(no_wrap=True)
            for y in range(0, im.height, 2):
                for x in range(im.width):
                    r1, g1, b1 = px[x, y]
                    r2, g2, b2 = px[x, y + 1]
                    text.append("▀", style=f"rgb({r1},{g1},{b1}) on rgb({r2},{g2},{b2})")
                text.append("\n")
            self.update(text)

    class BrowseScreen(ModalScreen[list]):
        BINDINGS = [Binding("escape", "dismiss_none", "Close")]

        def __init__(self, start: Path) -> None:
            super().__init__()
            self.start = start
            self.picked: Path | None = None

        def compose(self) -> ComposeResult:
            with Vertical(id="browse-box"):
                yield Label("Browse — select a file or folder, then press Add", id="browse-title")
                yield DirectoryTree(str(self.start), id="tree")
                yield Label("nothing selected", id="browse-sel")
                with Horizontal(id="browse-btns"):
                    yield Button("Add", variant="primary", id="browse-add")
                    yield Button("Cancel", id="browse-cancel")

        def _set(self, p: Path) -> None:
            self.picked = p
            self.query_one("#browse-sel", Label).update(f"→ {p}")

        @on(DirectoryTree.FileSelected)
        def _file(self, e: DirectoryTree.FileSelected) -> None:
            self._set(Path(e.path))

        @on(DirectoryTree.DirectorySelected)
        def _dir(self, e: DirectoryTree.DirectorySelected) -> None:
            self._set(Path(e.path))

        @on(Button.Pressed, "#browse-add")
        def _add(self) -> None:
            self.dismiss([self.picked] if self.picked else [])

        @on(Button.Pressed, "#browse-cancel")
        def _cancel(self) -> None:
            self.dismiss([])

        def action_dismiss_none(self) -> None:
            self.dismiss([])

    class ImgShrink(App):
        TITLE = "imgshrink"
        SUB_TITLE = "shrink images, keep the look"
        CSS = """
        Screen { background: #0f1117; }
        Header { background: #161a23; color: #7dd3fc; }
        Footer { background: #161a23; }
        #body { height: 1fr; }
        #side { width: 40; border: round #2a3142; padding: 0 1; background: #131722; }
        #main { width: 1fr; }
        .section { color: #7dd3fc; text-style: bold; margin-top: 1; }
        .field { color: #94a3b8; margin-top: 1; }
        .row { height: 3; }
        .row Label { width: 1fr; padding-top: 1; color: #cbd5e1; }
        #addbar { height: 3; }
        #addbar Input { width: 1fr; }
        #addbar Button { margin-left: 1; min-width: 12; }
        #files { height: 1fr; border: round #2a3142; background: #131722; }
        #lower { height: 14; }
        #preview-box { width: 40; border: round #2a3142; background: #0b0d12; padding: 0 1; }
        #preview { width: 100%; height: 1fr; }
        #info { height: 3; color: #94a3b8; }
        #log-box { width: 1fr; border: round #2a3142; background: #131722; }
        #progress { margin: 0 1; height: 1; }
        #stats { height: 1; padding: 0 1; color: #a7f3d0; }
        BrowseScreen { align: center middle; }
        #browse-box { width: 80%; height: 80%; border: round #7dd3fc; background: #131722; padding: 1; }
        #browse-title { color: #7dd3fc; text-style: bold; }
        #tree { height: 1fr; }
        #browse-btns { height: 3; }
        #browse-btns Button { margin-right: 1; }
        Select { margin-bottom: 0; }
        Input.-invalid { border: tall red; }
        """

        BINDINGS = [
            Binding("ctrl+o", "browse", "Browse"),
            Binding("f5", "run", "Compress"),
            Binding("f6", "estimate", "Estimate"),
            Binding("f7", "report", "CSV report"),
            Binding("f8", "remove_row", "Remove"),
            Binding("f9", "clear", "Clear"),
            Binding("f4", "open_out", "Open folder"),
            Binding("ctrl+q", "quit", "Quit"),
        ]

        def __init__(self, cfg: Config, preload: list[Path]) -> None:
            super().__init__()
            self.cfg = cfg
            self.preload = preload
            self.rows: dict[str, Result] = {}
            self.running = False
            self._suppress = False

        # ------------------------------------------------------------- layout
        def compose(self) -> ComposeResult:
            c = self.cfg
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                with VerticalScroll(id="side"):
                    yield Label("PRESET", classes="section")
                    yield Select([(k, k) for k in PRESETS], value="Custom",
                                 allow_blank=False, id="preset")
                    yield Label("OUTPUT", classes="section")
                    yield Label("Format", classes="field")
                    yield Select([(f, f) for f in FORMATS], value=c.fmt,
                                 allow_blank=False, id="fmt")
                    yield Label("Mode", classes="field")
                    yield Select([("quality — fixed quality", "quality"),
                                  ("target — hit a max size", "target")],
                                 value=c.mode, allow_blank=False, id="mode")
                    yield Label("Quality (1-100)", classes="field")
                    yield Input(str(c.quality), type="integer", id="quality")
                    yield Label("Target size (KB)", classes="field")
                    yield Input(str(c.target_kb), type="integer", id="target_kb")
                    yield Label("Max dimension px (0 = none)", classes="field")
                    yield Input(str(c.max_dim), type="integer", id="max_dim")
                    yield Label("Output folder (blank = same folder)", classes="field")
                    yield Input(c.out_dir, placeholder="same folder", id="out_dir")
                    yield Label("Suffix", classes="field")
                    yield Input(c.suffix, id="suffix")
                    yield Label("OPTIONS", classes="section")
                    with Horizontal(classes="row"):
                        yield Label("Overwrite existing")
                        yield Switch(c.overwrite, id="overwrite")
                    with Horizontal(classes="row"):
                        yield Label("Keep EXIF metadata")
                        yield Switch(c.keep_exif, id="keep_exif")
                    with Horizontal(classes="row"):
                        yield Label("Include subfolders")
                        yield Switch(c.recursive, id="recursive")
                    with Horizontal(classes="row"):
                        yield Label("Dry run (don't write)")
                        yield Switch(c.dry_run, id="dry_run")
                    yield Label("Parallel workers", classes="field")
                    yield Input(str(c.workers), type="integer", id="workers")
                with Vertical(id="main"):
                    with Horizontal(id="addbar"):
                        yield Input(placeholder="Paste or drop file / folder paths, press Enter",
                                    id="addpath")
                        yield Button("Browse", id="btn-browse")
                        yield Button("Compress", variant="success", id="btn-run")
                    yield DataTable(id="files", cursor_type="row", zebra_stripes=True)
                    yield ProgressBar(total=100, show_eta=False, id="progress")
                    yield Static("Queue is empty — add some images.", id="stats")
                    with Horizontal(id="lower"):
                        with Vertical(id="preview-box"):
                            yield ImagePreview(id="preview")
                            yield Static("", id="info")
                        yield RichLog(id="log-box", wrap=True, markup=True)
            yield Footer()

        def on_mount(self) -> None:
            t = self.query_one("#files", DataTable)
            t.add_column("File", key="name", width=26)
            t.add_column("Before", key="before", width=10)
            t.add_column("After", key="after", width=10)
            t.add_column("Saved", key="saved", width=8)
            t.add_column("Status", key="status", width=10)
            t.add_column("Details", key="note")
            self.query_one("#progress", ProgressBar).update(total=100, progress=0)
            self.log_msg("[b #7dd3fc]imgshrink[/] ready. Paste paths above, "
                         "or press [b]Ctrl+O[/] to browse.")
            if not HAS_AVIF:
                self.log_msg("[dim]AVIF output unavailable (Pillow built without AVIF).[/]")
            if self.preload:
                self.add_paths(self.preload)
            self.query_one("#addpath", Input).focus()

        # -------------------------------------------------------------- helpers
        def log_msg(self, msg: str) -> None:
            self.query_one("#log-box", RichLog).write(msg)

        def _int(self, wid: str, lo: int, hi: int, default: int) -> int:
            try:
                return max(lo, min(hi, int(self.query_one(f"#{wid}", Input).value)))
            except ValueError:
                return default

        def sync_config(self) -> Config:
            c = self.cfg
            q = lambda i: self.query_one(f"#{i}")
            c.fmt = q("fmt").value
            c.mode = q("mode").value
            c.quality = self._int("quality", 1, 100, c.quality)
            c.target_kb = self._int("target_kb", 1, 100_000, c.target_kb)
            c.max_dim = self._int("max_dim", 0, 100_000, c.max_dim)
            c.out_dir = q("out_dir").value.strip().strip("\"'")
            c.suffix = q("suffix").value or ".min"
            c.overwrite = q("overwrite").value
            c.keep_exif = q("keep_exif").value
            c.recursive = q("recursive").value
            c.dry_run = q("dry_run").value
            c.workers = self._int("workers", 1, 32, c.workers)
            return c

        def push_config_to_widgets(self) -> None:
            self._suppress = True
            c = self.cfg
            q = lambda i: self.query_one(f"#{i}")
            q("fmt").value = c.fmt
            q("mode").value = c.mode
            q("quality").value = str(c.quality)
            q("target_kb").value = str(c.target_kb)
            q("max_dim").value = str(c.max_dim)
            self.call_after_refresh(setattr, self, "_suppress", False)

        def add_paths(self, paths: list[Path]) -> None:
            files = collect_images(paths, self.cfg.recursive, self.cfg.suffix or ".min")
            if not files:
                self.log_msg("[yellow]No images found in that path.[/]")
                return
            t = self.query_one("#files", DataTable)
            added = 0
            for f in files:
                key = str(f.resolve())
                if key in self.rows:
                    continue
                r = Result(src=f, before=f.stat().st_size)
                self.rows[key] = r
                t.add_row(f.name, human(r.before), "—", "—", "queued", "", key=key)
                added += 1
            self.log_msg(f"Added [b]{added}[/] image(s).")
            self.update_stats()

        def update_row(self, key: str, r: Result) -> None:
            t = self.query_one("#files", DataTable)
            color = {"done": "green", "estimated": "cyan", "skipped": "yellow",
                     "error": "red"}.get(r.status, "white")
            saved = (f"{100 * (1 - r.after / r.before):.0f}%"
                     if r.after and r.before else "—")
            t.update_cell(key, "after", human(r.after) if r.after else "—")
            t.update_cell(key, "saved", Text(saved, style=color))
            t.update_cell(key, "status", Text(r.status, style=color))
            t.update_cell(key, "note", r.note, update_width=True)

        def update_stats(self) -> None:
            rs = list(self.rows.values())
            done = [r for r in rs if r.status in ("done", "estimated")]
            before = sum(r.before for r in done)
            after = sum(r.after for r in done)
            if not rs:
                msg = "Queue is empty — add some images."
            elif not done:
                msg = f"{len(rs)} image(s) queued · {human(sum(r.before for r in rs))} total"
            else:
                pct = 100 * (1 - after / before) if before else 0
                msg = (f"{len(done)}/{len(rs)} processed · {human(before)} → {human(after)} · "
                       f"saved {human(max(0, before - after))} ({pct:.0f}%)")
            self.query_one("#stats", Static).update(msg)

        # --------------------------------------------------------------- events
        @on(Input.Submitted, "#addpath")
        def _submit_path(self, e: Input.Submitted) -> None:
            if e.value.strip():
                self.sync_config()
                self.add_paths(parse_paths(e.value))
                e.input.value = ""

        @on(Button.Pressed, "#btn-browse")
        def _btn_browse(self) -> None:
            self.action_browse()

        @on(Button.Pressed, "#btn-run")
        def _btn_run(self) -> None:
            self.action_run()

        @on(Select.Changed, "#preset")
        def _preset(self, e: Select.Changed) -> None:
            vals = PRESETS.get(str(e.value), {})
            if not vals:
                return
            for k, v in vals.items():
                setattr(self.cfg, k, v)
            self.push_config_to_widgets()
            self.log_msg(f"Preset applied: [b]{e.value}[/]")

        @on(Select.Changed, "#fmt, #mode")
        def _manual(self) -> None:
            pass

        @on(DataTable.RowHighlighted, "#files")
        def _highlight(self, e: DataTable.RowHighlighted) -> None:
            key = e.row_key.value if e.row_key else None
            r = self.rows.get(key) if key else None
            prev = self.query_one("#preview", ImagePreview)
            info = self.query_one("#info", Static)
            if not r:
                prev.show(None)
                info.update("")
                return
            prev.show(r.src)
            try:
                with Image.open(r.src) as im:
                    info.update(f"{r.src.name}\n{im.format} · {im.width}×{im.height} · "
                                f"{human(r.before)}")
            except Exception:
                info.update(r.src.name)

        # -------------------------------------------------------------- actions
        def action_browse(self) -> None:
            def done(paths: list | None) -> None:
                if paths:
                    self.sync_config()
                    self.add_paths(paths)
            self.push_screen(BrowseScreen(Path.home()), done)

        def action_remove_row(self) -> None:
            t = self.query_one("#files", DataTable)
            if not self.rows or self.running:
                return
            try:
                key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            except Exception:
                return
            self.rows.pop(key, None)
            t.remove_row(key)
            self.update_stats()

        def action_clear(self) -> None:
            if self.running:
                return
            self.rows.clear()
            self.query_one("#files", DataTable).clear()
            self.query_one("#progress", ProgressBar).update(total=100, progress=0)
            self.update_stats()

        def action_estimate(self) -> None:
            self.start(dry=True)

        def action_run(self) -> None:
            self.start(dry=False)

        def start(self, dry: bool) -> None:
            if self.running:
                return
            if not self.rows:
                self.log_msg("[yellow]Nothing to do — the queue is empty.[/]")
                return
            cfg = self.sync_config()
            if dry:
                cfg.dry_run = True
            save_config(cfg)
            self.running = True
            for k, r in self.rows.items():
                r.status, r.after, r.note = "queued", 0, ""
                self.update_row(k, r)
            self.query_one("#progress", ProgressBar).update(total=len(self.rows), progress=0)
            label = "Estimating" if cfg.dry_run else "Compressing"
            self.log_msg(f"[b]{label}[/] {len(self.rows)} image(s) with {cfg.workers} worker(s)…")
            self.run_batch(Config(**asdict(cfg)))

        @work(thread=True, exclusive=True)
        def run_batch(self, cfg: Config) -> None:
            t0 = time.perf_counter()
            keys = list(self.rows)
            with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
                futs = {pool.submit(process_file, self.rows[k].src, cfg): k for k in keys}
                for fut in as_completed(futs):
                    k = futs[fut]
                    self.call_from_thread(self._finish_one, k, fut.result())
            self.call_from_thread(self._finish_all, time.perf_counter() - t0, cfg)

        def _finish_one(self, key: str, r: Result) -> None:
            if key not in self.rows:
                return
            self.rows[key] = r
            self.update_row(key, r)
            self.query_one("#progress", ProgressBar).advance(1)
            self.update_stats()
            if r.status == "error":
                self.log_msg(f"[red]✖ {r.src.name}[/]: {r.note}")
            elif not r.reached:
                self.log_msg(f"[yellow]⚠ {r.src.name}: couldn't reach the target size[/]")

        def _finish_all(self, secs: float, cfg: Config) -> None:
            self.running = False
            n = sum(1 for r in self.rows.values() if r.status in ("done", "estimated"))
            verb = "Estimated" if cfg.dry_run else "Finished"
            self.log_msg(f"[b green]{verb}[/] {n} image(s) in {secs:.1f}s. "
                         f"[dim]F7 = CSV report, F4 = open output folder.[/]")
            self.update_stats()
            if cfg.dry_run:
                self.cfg.dry_run = False

        def action_report(self) -> None:
            rs = [r for r in self.rows.values() if r.status != "queued"]
            if not rs:
                self.log_msg("[yellow]No results yet — run Compress first.[/]")
                return
            base = Path(self.cfg.out_dir).expanduser() if self.cfg.out_dir else Path.cwd()
            base.mkdir(parents=True, exist_ok=True)
            path = base / f"imgshrink-report-{time.strftime('%Y%m%d-%H%M%S')}.csv"
            save_report(rs, path)
            self.log_msg(f"Report saved → [b]{path}[/]")

        def action_open_out(self) -> None:
            if self.cfg.out_dir:
                open_in_file_manager(Path(self.cfg.out_dir).expanduser())
                return
            for r in self.rows.values():
                if r.dest:
                    open_in_file_manager(r.dest.parent)
                    return
            self.log_msg("[yellow]Nothing written yet.[/]")

        def on_unmount(self) -> None:
            try:
                save_config(self.sync_config())
            except Exception:
                pass

    return ImgShrink


# ====================================================================== main

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="imgshrink",
                                description="Reduce image file sizes (TUI by default).")
    p.add_argument("paths", nargs="*", help="files or folders to add")
    p.add_argument("--cli", action="store_true", help="run headless, no TUI")
    p.add_argument("--format", choices=FORMATS, dest="fmt")
    p.add_argument("--quality", type=int)
    p.add_argument("--target", type=int, dest="target_kb", help="max size in KB (target mode)")
    p.add_argument("--max-dim", type=int, dest="max_dim")
    p.add_argument("--out", dest="out_dir")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--keep-exif", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-recursive", action="store_true")
    p.add_argument("--workers", type=int)
    p.add_argument("--preset", choices=[k for k in PRESETS if k != "Custom"],
                   help="apply a preset first, other flags override it")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()
    if args.preset:
        for k, v in PRESETS[args.preset].items():
            setattr(cfg, k, v)
    for k in ("fmt", "quality", "target_kb", "max_dim", "out_dir", "workers"):
        v = getattr(args, k)
        if v is not None:
            setattr(cfg, k, v)
    if args.target_kb is not None:
        cfg.mode = "target"
    elif args.quality is not None:
        cfg.mode = "quality"
    cfg.overwrite |= args.overwrite
    cfg.keep_exif |= args.keep_exif
    cfg.dry_run |= args.dry_run
    if args.no_recursive:
        cfg.recursive = False

    if args.cli:
        if not args.paths:
            sys.exit("--cli needs at least one file or folder.")
        sys.exit(run_cli(args, cfg))

    App = build_app()
    App(cfg, [Path(p).expanduser() for p in args.paths]).run()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
