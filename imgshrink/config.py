"""User settings and the presets offered by the TUI."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PRESETS: dict[str, dict] = {
    "Custom": {},
    "Web (WebP)": {"fmt": "webp", "mode": "quality", "quality": 80, "max_dim": 2048},
    "Email (≤500 KB)": {"fmt": "jpeg", "mode": "target", "target_kb": 500, "max_dim": 1600},
    "Social (1080)": {"fmt": "jpeg", "mode": "quality", "quality": 85, "max_dim": 1080},
    "Thumbnail": {"fmt": "webp", "mode": "quality", "quality": 70, "max_dim": 400},
    "Lossless PNG": {"fmt": "png", "mode": "quality", "quality": 100, "max_dim": 0},
}


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
    exif_mode: str = "none"   # none | safe | all  (overrides keep_exif when set)
    formats: list[str] = field(default_factory=list)  # multi-format output; empty = use fmt
    dry_run: bool = False
    workers: int = max(1, min(4, os.cpu_count() or 2))
    recursive: bool = True


CONFIG_PATH = (
    Path(os.environ.get("APPDATA", Path.home() / ".config"))
    / "imgshrink"
    / "config.json"
)


def load_config() -> Config:
    """Load settings, falling back to defaults for missing or invalid fields."""
    cfg = Config()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        valid = {f.name for f in fields(Config)}
        for key, value in raw.items():
            if key in valid:
                setattr(cfg, key, value)
    except Exception:
        pass
    return cfg


def save_config(cfg: Config) -> None:
    """Persist settings; failures must never break a compression run."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    except Exception:
        pass
