"""The settings sidebar: all output options in one place."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Input, Label, Select, Switch

from ..config import PRESETS, Config
from ..constants import FORMATS


class PresetApplied(Message):
    """Posted after a preset has been written into the form."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


class SettingsPanel(VerticalScroll):
    """Form widget that reads/writes a `Config` instance."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(id="side")
        self.cfg = cfg

    def compose(self) -> ComposeResult:
        c = self.cfg
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
        yield Label("EXIF mode", classes="field")
        yield Select([("none — strip all", "none"),
                      ("safe — drop GPS/personal", "safe"),
                      ("all — keep everything", "all")],
                     value=c.exif_mode, allow_blank=False, id="exif_mode")
        yield Label("Multi-formats (comma, blank = single)", classes="field")
        yield Input(",".join(c.formats), placeholder="jpeg,webp,avif", id="formats")
        with Horizontal(classes="row"):
            yield Label("Include subfolders")
            yield Switch(c.recursive, id="recursive")
        with Horizontal(classes="row"):
            yield Label("Dry run (don't write)")
            yield Switch(c.dry_run, id="dry_run")
        yield Label("Parallel workers", classes="field")
        yield Input(str(c.workers), type="integer", id="workers")

    # ------------------------------------------------------------------ data
    def _int(self, wid: str, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(self.query_one(f"#{wid}", Input).value)))
        except ValueError:
            return default

    def sync_config(self) -> Config:
        """Copy every widget value into the shared Config object."""
        c = self.cfg
        c.fmt = str(self.query_one("#fmt", Select).value)
        c.mode = str(self.query_one("#mode", Select).value)
        c.quality = self._int("quality", 1, 100, c.quality)
        c.target_kb = self._int("target_kb", 1, 100_000, c.target_kb)
        c.max_dim = self._int("max_dim", 0, 100_000, c.max_dim)
        c.out_dir = self.query_one("#out_dir", Input).value.strip().strip("\"'")
        c.suffix = self.query_one("#suffix", Input).value or ".min"
        c.overwrite = self.query_one("#overwrite", Switch).value
        c.keep_exif = self.query_one("#keep_exif", Switch).value
        c.exif_mode = str(self.query_one("#exif_mode", Select).value)
        raw_fmts = self.query_one("#formats", Input).value.strip()
        c.formats = [f.strip().lower() for f in raw_fmts.split(",") if f.strip()]
        c.recursive = self.query_one("#recursive", Switch).value
        c.dry_run = self.query_one("#dry_run", Switch).value
        c.workers = self._int("workers", 1, 32, c.workers)
        return c

    def push_config_to_widgets(self) -> None:
        """Write Config values back into the form (used when a preset is applied)."""
        c = self.cfg
        self.query_one("#fmt", Select).value = c.fmt
        self.query_one("#mode", Select).value = c.mode
        self.query_one("#quality", Input).value = str(c.quality)
        self.query_one("#target_kb", Input).value = str(c.target_kb)
        self.query_one("#max_dim", Input).value = str(c.max_dim)

    # ---------------------------------------------------------------- events
    @on(Select.Changed, "#preset")
    def _preset(self, e: Select.Changed) -> None:
        vals = PRESETS.get(str(e.value), {})
        if not vals:
            return
        for k, v in vals.items():
            setattr(self.cfg, k, v)
        self.push_config_to_widgets()
        self.post_message(PresetApplied(str(e.value)))
