"""Shared fixtures for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """A small gradient image, so encoders have something realistic to work on."""
    img = Image.new("RGB", (96, 64))
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            px[x, y] = (x * 2 % 256, y * 3 % 256, (x + y) % 256)
    path = tmp_path / "sample.png"
    img.save(path)
    return path
