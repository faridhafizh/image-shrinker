"""Tests for the pure imaging layer."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from imgshrink.config import Config
from imgshrink.constants import HAS_AVIF, human
from imgshrink.imaging import _png_colours, _search, encode, fit, shrink

ENCODABLE = ["JPEG", "WEBP", "PNG"] + (["AVIF"] if HAS_AVIF else [])


def test_human_readable_sizes() -> None:
    assert human(0) == "0 B"
    assert human(1023) == "1023 B"
    assert human(1024) == "1.0 KB"
    assert human(1536) == "1.5 KB"
    assert human(1024**2) == "1.0 MB"
    assert human(1024**3 * 2) == "2.0 GB"


@pytest.mark.parametrize("fmt", ENCODABLE)
def test_encode_roundtrip(sample_png, fmt: str) -> None:
    with Image.open(sample_png) as im:
        im.load()
        data = encode(im, fmt, 256 if fmt == "PNG" else 80)
    assert data
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == fmt
        assert out.size == (96, 64)


def test_encode_rejects_unknown_format(sample_png) -> None:
    with Image.open(sample_png) as im:
        with pytest.raises(ValueError):
            encode(im, "GIF", 80)


def test_png_colours_mapping() -> None:
    assert _png_colours(100) == 256
    assert _png_colours(0) == 16
    assert _png_colours(50) == 136


def test_fit_caps_the_longest_side(sample_png) -> None:
    with Image.open(sample_png) as im:
        assert fit(im, 0).size == im.size
        assert max(fit(im, 32).size) <= 32
        assert fit(im, 1000).size == im.size


def test_search_never_exceeds_target(sample_png) -> None:
    with Image.open(sample_png) as im:
        target = len(encode(im, "JPEG", 80))
        best = _search(im, "JPEG", target, 20, 95)
    assert best is not None
    data, level = best
    assert len(data) <= target
    assert level >= 20


def test_shrink_quality_mode_uses_quality_as_level(sample_png) -> None:
    with Image.open(sample_png) as im:
        data, info = shrink(im, "JPEG", Config(fmt="jpeg", quality=70, max_dim=32))
    assert info["level"] == 70
    assert max(info["size"]) <= 32
    assert Image.open(io.BytesIO(data)).format == "JPEG"


def test_shrink_target_mode_keeps_full_size_when_it_fits(sample_png) -> None:
    with Image.open(sample_png) as im:
        data, info = shrink(im, "WEBP", Config(fmt="webp", mode="target", target_kb=200))
    assert info["scale"] == 1.0
    assert len(data) <= 200 * 1024


def test_shrink_target_mode_downscales_when_needed() -> None:
    noisy = Image.effect_noise((512, 512), 64).convert("RGB")
    data, info = shrink(noisy, "JPEG", Config(fmt="jpeg", mode="target", target_kb=2))
    assert info["scale"] < 1.0
    assert max(info["size"]) < 512
    assert Image.open(io.BytesIO(data)).format == "JPEG"
