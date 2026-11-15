"""One file in, one shrunken file out — plus the bookkeeping around it."""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import Config
from .constants import EXT_FOR, KEEPABLE, SRC_FMT
from .imaging import load_image, shrink

Status = Literal["queued", "done", "skipped", "error", "estimated"]


@dataclass
class Result:
    src: Path
    status: Status = "queued"
    before: int = 0
    after: int = 0
    dest: Path | None = None
    note: str = ""
    elapsed: float = 0.0
    out_px: tuple[int, int] | None = None
    in_px: tuple[int, int] | None = None
    reached: bool = True


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


def process_file(src: Path, cfg: Config) -> Result:
    """Shrink a single image. Never raises: errors are reported on the Result."""
    t0 = time.perf_counter()
    res = Result(src=src)
    try:
        res.before = src.stat().st_size
    except OSError as exc:
        res.status, res.note = "error", f"cannot read: {exc}"
        return res
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
