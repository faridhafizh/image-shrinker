"""The main Textual application: queue, preview, progress and actions."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from PIL import Image
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Static,
)

from ..config import Config, save_config
from ..constants import HAS_AVIF, human
from ..paths import collect_images, open_in_file_manager, parse_paths
from ..pipeline import Result, process_file, save_report
from .screens import BrowseScreen
from .settings import PresetApplied, SettingsPanel
from .widgets import ImagePreview

CSS_FILE = Path(__file__).with_name("app.tcss")


class ImgShrink(App):
    TITLE = "imgshrink"
    SUB_TITLE = "shrink images, keep the look"
    CSS_PATH = CSS_FILE

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

    # ------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield SettingsPanel(self.cfg)
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
    @property
    def panel(self) -> SettingsPanel:
        return self.query_one(SettingsPanel)

    def log_msg(self, msg: str) -> None:
        self.query_one("#log-box", RichLog).write(msg)

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
            self.panel.sync_config()
            self.add_paths(parse_paths(e.value))
            e.input.value = ""

    @on(Button.Pressed, "#btn-browse")
    def _btn_browse(self) -> None:
        self.action_browse()

    @on(Button.Pressed, "#btn-run")
    def _btn_run(self) -> None:
        self.action_run()

    @on(PresetApplied)
    def _preset_applied(self, e: PresetApplied) -> None:
        self.log_msg(f"Preset applied: [b]{e.name}[/]")

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
                self.panel.sync_config()
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
        cfg = self.panel.sync_config()
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
            save_config(self.panel.sync_config())
        except Exception:
            pass
