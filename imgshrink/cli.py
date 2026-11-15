"""Command-line entry point and headless batch runner."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import PRESETS, Config, load_config
from .constants import FORMATS, human
from .paths import collect_images
from .pipeline import Result, process_file

STATUS_MARK = {"done": "✔", "estimated": "≈", "skipped": "•", "error": "✖"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    return p.parse_args(argv)


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
            r: Result = fut.result()
            mark = STATUS_MARK[r.status]
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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
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

    # Textual is only needed for the TUI: importing it here keeps --cli light.
    from .tui.app import ImgShrink

    ImgShrink(cfg, [Path(p).expanduser() for p in args.paths]).run()


def run() -> None:
    """Console-script wrapper that turns Ctrl+C into a clean exit."""
    # Windows consoles/redirects default to cp1252, which cannot encode ✔/→/≤.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
