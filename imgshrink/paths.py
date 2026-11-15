"""Turning user input (pasted text, dropped folders) into image paths."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .constants import IMAGE_EXTS


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
    """Expand files and folders into a de-duplicated, sorted list of images."""
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


def open_in_file_manager(path: Path) -> None:
    """Open a folder in the OS file manager; silently ignore failures."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass
