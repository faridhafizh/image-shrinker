"""Reusable widgets that know nothing about the queue or the settings."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps
from rich.text import Text
from textual.widgets import Static

from ..constants import RESAMPLE


class ImagePreview(Static):
    """Renders an image in the terminal using half-block characters."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._path: Path | None = None

    def show(self, path: Path | None) -> None:
        self._path = path
        self.refresh_preview()

    def on_resize(self) -> None:
        self.refresh_preview()

    def refresh_preview(self) -> None:
        path = self._path
        w, h = self.size.width, self.size.height
        if not path or w < 4 or h < 2:
            self.update(Text("no preview", style="dim"))
            return
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im = im.convert("RGBA")
                im.thumbnail((w, h * 2), RESAMPLE)
                bg = Image.new("RGBA", im.size, (24, 24, 32, 255))
                im = Image.alpha_composite(bg, im).convert("RGB")
        except Exception:
            self.update(Text("cannot preview", style="dim"))
            return
        if im.height % 2:
            im = im.crop((0, 0, im.width, im.height - 1))
        px = im.load()
        text = Text(no_wrap=True)
        for y in range(0, im.height, 2):
            for x in range(im.width):
                r1, g1, b1 = px[x, y]
                r2, g2, b2 = px[x, y + 1]
                text.append("▀", style=f"rgb({r1},{g1},{b1}) on rgb({r2},{g2},{b2})")
            text.append("\n")
        self.update(text)
