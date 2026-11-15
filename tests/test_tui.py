"""Smoke tests for the Textual app (headless, no TTY required)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("textual")

from imgshrink.config import Config  # noqa: E402
from imgshrink.tui import app as tui_app  # noqa: E402


def _make_app(tmp_path: Path, monkeypatch) -> tui_app.ImgShrink:
    src = tmp_path / "in.png"
    Image.new("RGB", (32, 32), (10, 120, 200)).save(src)

    # Settings must never be written to the real user config during tests.
    monkeypatch.setattr(tui_app, "save_config", lambda cfg: None)

    return tui_app.ImgShrink(Config(out_dir=str(tmp_path / "out")), [src])


def test_queue_is_populated_and_compress_runs(tmp_path: Path, monkeypatch) -> None:
    app = _make_app(tmp_path, monkeypatch)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            assert len(app.rows) == 1

            app.action_run()
            for _ in range(200):
                if not app.running:
                    break
                await pilot.pause(0.05)

            assert not app.running
            row = next(iter(app.rows.values()))
            assert row.status == "done", row.note
            assert row.dest is not None and row.dest.exists()

    asyncio.run(scenario())


def test_preset_updates_config_and_widgets(tmp_path: Path, monkeypatch) -> None:
    from textual.widgets import Input, Select

    app = _make_app(tmp_path, monkeypatch)
    logged: list[str] = []

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.log_msg = logged.append  # type: ignore[method-assign]
            app.panel.query_one("#preset", Select).value = "Thumbnail"
            await pilot.pause()

            assert app.cfg.fmt == "webp"
            assert app.cfg.max_dim == 400
            assert app.panel.query_one("#quality", Input).value == "70"
            assert any("Preset applied" in msg for msg in logged)

    asyncio.run(scenario())
