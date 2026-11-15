"""Tests for argument parsing and the headless entry point."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from imgshrink import cli
from imgshrink.config import Config


def test_parse_args_defaults() -> None:
    args = cli.parse_args([])
    assert args.paths == []
    assert args.cli is False
    assert args.fmt is None


def test_target_flag_switches_to_target_mode(monkeypatch, tmp_path: Path) -> None:
    captured: list[Config] = []

    monkeypatch.setattr(cli, "load_config", lambda: Config())
    monkeypatch.setattr(cli, "run_cli", lambda args, cfg: captured.append(cfg) or 0)

    with pytest.raises(SystemExit):
        cli.main(["--cli", str(tmp_path), "--target", "500"])

    assert captured[0].mode == "target"
    assert captured[0].target_kb == 500


def test_preset_is_applied_before_flags(monkeypatch, tmp_path: Path) -> None:
    captured: list[Config] = []

    monkeypatch.setattr(cli, "load_config", lambda: Config())
    monkeypatch.setattr(cli, "run_cli", lambda args, cfg: captured.append(cfg) or 0)

    with pytest.raises(SystemExit):
        cli.main(["--cli", str(tmp_path), "--preset", "Email (≤500 KB)"])

    cfg = captured[0]
    assert cfg.fmt == "jpeg"
    assert cfg.mode == "target"
    assert cfg.target_kb == 500


def test_cli_end_to_end(monkeypatch, tmp_path: Path, capsys) -> None:
    src = tmp_path / "in.png"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(src)
    out = tmp_path / "out"

    monkeypatch.setattr(cli, "load_config", lambda: Config())

    with pytest.raises(SystemExit) as exc:
        cli.main(["--cli", str(src), "--format", "webp", "--quality", "60", "--out", str(out)])

    assert exc.value.code == 0
    assert (out / "in.webp").exists()
    assert "Total:" in capsys.readouterr().out


def test_cli_without_paths_exits_with_message(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_config", lambda: Config())

    with pytest.raises(SystemExit) as exc:
        cli.main(["--cli"])

    assert "needs at least one" in str(exc.value.code)
