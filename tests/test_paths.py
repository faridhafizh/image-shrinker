"""Tests for path parsing and output naming."""

from __future__ import annotations

from pathlib import Path

from imgshrink.config import Config
from imgshrink.paths import collect_images, parse_paths
from imgshrink.pipeline import Result, destination, resolve_format, save_report


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_parse_paths_one_per_line(tmp_path: Path) -> None:
    a = _touch(tmp_path / "a.png")
    b = _touch(tmp_path / "b.jpg")
    assert parse_paths(f"{a}\n{b}") == [a, b]


def test_parse_paths_quoted_with_spaces(tmp_path: Path) -> None:
    f = _touch(tmp_path / "a b.png")
    assert parse_paths(f'"{f}"') == [f]


def test_parse_paths_ignores_blank_lines() -> None:
    assert parse_paths("\n  \n") == []


def test_collect_images_recursive_skips_output_suffix(tmp_path: Path) -> None:
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "a.min.jpg")
    _touch(tmp_path / "sub" / "c.png")

    names = sorted(f.name for f in collect_images([tmp_path], recursive=True, suffix=".min"))
    assert names == ["a.jpg", "c.png"]


def test_collect_images_non_recursive(tmp_path: Path) -> None:
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "sub" / "c.png")

    names = [f.name for f in collect_images([tmp_path], recursive=False, suffix=".min")]
    assert names == ["a.jpg"]


def test_collect_images_deduplicates(tmp_path: Path) -> None:
    f = _touch(tmp_path / "a.jpg")
    assert collect_images([f, f], recursive=True, suffix=".min") == [f]


def test_resolve_format_keeps_only_supported_formats(tmp_path: Path) -> None:
    assert resolve_format(tmp_path / "a.jpg", Config()) == "JPEG"
    assert resolve_format(tmp_path / "a.bmp", Config()) == "JPEG"
    assert resolve_format(tmp_path / "a.png", Config(fmt="webp")) == "WEBP"


def test_destination_defaults_to_suffix_next_to_source(tmp_path: Path) -> None:
    src = _touch(tmp_path / "photo.jpg")
    assert destination(src, Config(), "JPEG") == tmp_path / "photo.min.jpg"


def test_destination_avoids_overwriting_existing_files(tmp_path: Path) -> None:
    src = _touch(tmp_path / "photo.jpg")
    _touch(tmp_path / "photo.min.jpg")

    dest = destination(src, Config(), "JPEG")
    assert dest.name == "photo.min-1.jpg"


def test_destination_overwrites_only_when_asked(tmp_path: Path) -> None:
    src = _touch(tmp_path / "photo.jpg")
    assert destination(src, Config(overwrite=True), "JPEG") == src


def test_destination_honours_out_dir(tmp_path: Path) -> None:
    src = _touch(tmp_path / "src" / "photo.jpg")
    out = tmp_path / "out"

    dest = destination(src, Config(out_dir=str(out)), "WEBP")
    assert dest == out / "photo.webp"


def test_save_report_writes_a_row_per_result(tmp_path: Path) -> None:
    rows = [
        Result(src=tmp_path / "a.jpg", status="done", before=1000, after=400,
               dest=tmp_path / "a.min.jpg", note="q70"),
        Result(src=tmp_path / "b.jpg", status="error", note="boom"),
    ]
    report = tmp_path / "report.csv"
    save_report(rows, report)

    text = report.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("source,output,status")
    assert "a.min.jpg" in text
    assert "boom" in text
