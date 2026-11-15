"""Tests for settings persistence."""

from __future__ import annotations

from pathlib import Path

from imgshrink import config
from imgshrink.config import Config


def test_load_config_returns_defaults_when_file_is_missing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.json")
    assert config.load_config() == Config()


def test_config_roundtrip(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    cfg = Config(fmt="webp", quality=55, out_dir=str(tmp_path / "out"))
    config.save_config(cfg)

    assert path.exists()
    assert config.load_config() == cfg


def test_load_config_ignores_unknown_keys(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"fmt": "png", "not_a_field": 123}', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    cfg = config.load_config()
    assert cfg.fmt == "png"
    assert not hasattr(cfg, "not_a_field")


def test_load_config_survives_corrupt_json(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    assert config.load_config() == Config()
