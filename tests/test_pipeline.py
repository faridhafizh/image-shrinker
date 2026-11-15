"""Tests for the per-file pipeline."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from imgshrink.config import Config
from imgshrink.pipeline import process_file


def test_process_file_writes_the_shrunken_image(sample_png: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = process_file(sample_png, Config(fmt="jpeg", quality=70, out_dir=str(out)))

    assert result.status == "done"
    assert result.dest == out / "sample.jpg"
    assert result.dest.exists()
    assert result.after == result.dest.stat().st_size
    assert result.in_px == (96, 64)


def test_process_file_dry_run_does_not_write(sample_png: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = process_file(sample_png, Config(fmt="jpeg", dry_run=True, out_dir=str(out)))

    assert result.status == "estimated"
    assert result.after > 0
    assert not result.dest.exists()


def test_process_file_reports_missing_files(tmp_path: Path) -> None:
    result = process_file(tmp_path / "nope.png", Config())

    assert result.status == "error"
    assert "cannot read" in result.note


def test_process_file_skips_files_that_would_grow(tmp_path: Path) -> None:
    src = tmp_path / "noisy.jpg"
    Image.effect_noise((128, 128), 80).convert("RGB").save(src, "JPEG", quality=5)
    out = tmp_path / "out"

    result = process_file(src, Config(fmt="keep", quality=95, out_dir=str(out)))

    assert result.status == "skipped"
    assert result.note == "already optimal"
    assert not (out / "noisy.jpg").exists()


def test_process_file_flags_unreachable_targets(
    monkeypatch, sample_png: Path, tmp_path: Path
) -> None:
    from imgshrink import pipeline

    # Pretend the encoder always overshoots, so the flagging logic can be tested
    # without depending on how well a particular Pillow build compresses.
    monkeypatch.setattr(
        pipeline,
        "shrink",
        lambda img, fmt, cfg: (b"x" * 4096, {"level": 20, "size": img.size, "scale": 1.0}),
    )

    result = pipeline.process_file(
        sample_png,
        Config(fmt="jpeg", mode="target", target_kb=1, out_dir=str(tmp_path / "out")),
    )

    assert result.status == "done"
    assert result.reached is False
    assert "target not reached" in result.note
