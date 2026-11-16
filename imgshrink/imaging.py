"""Image decoding, resizing and encoding.

Nothing in this module knows about file paths, the CLI or the TUI: it takes
Pillow images in and returns encoded bytes out. That keeps it easy to test and
safe for contributors to change.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from .config import Config
from .constants import (
    PROBE_Q,
    QUANT_FASTOCTREE,
    QUANT_MEDIANCUT,
    RESAMPLE,
)


def load_image(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    return ImageOps.exif_transpose(img)  # respect camera orientation


def fit(img: Image.Image, max_dim: int) -> Image.Image:
    if max_dim and max(img.size) > max_dim:
        img = img.copy()
        img.thumbnail((max_dim, max_dim), RESAMPLE)
    return img


def _to_rgb(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white and return an RGB image."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def encode(img: Image.Image, fmt: str, level: int, exif: bytes | None = None) -> bytes:
    """Encode. `level` = quality (JPEG/WebP/AVIF) or colour count (PNG)."""
    buf = io.BytesIO()
    extra = {"exif": exif} if exif else {}
    if fmt == "JPEG":
        im = img if img.mode == "RGB" else _to_rgb(img)
        im.save(buf, "JPEG", quality=int(level), optimize=True, progressive=True, **extra)
    elif fmt == "WEBP":
        im = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")
        im.save(buf, "WEBP", quality=int(level), method=6, **extra)
    elif fmt == "AVIF":
        im = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA")
        im.save(buf, "AVIF", quality=int(level), **extra)
    elif fmt == "PNG":
        im = img
        if level < 256:
            try:
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA").quantize(colors=int(level), method=QUANT_FASTOCTREE)
                else:
                    im = im.convert("RGB").quantize(colors=int(level), method=QUANT_MEDIANCUT)
            except Exception:
                im = img
        im.save(buf, "PNG", optimize=True, compress_level=9)
    else:
        raise ValueError(f"unsupported output format: {fmt}")
    return buf.getvalue()


def _search(
    img: Image.Image,
    fmt: str,
    target: int,
    lo: int,
    hi: int,
    exif: bytes | None = None,
) -> tuple[bytes, int] | None:
    """Binary-search the highest level that still fits in `target` bytes."""
    data = encode(img, fmt, lo, exif)
    if len(data) > target:
        return None
    best = (data, lo)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        data = encode(img, fmt, mid, exif)
        if len(data) <= target:
            best, lo = (data, mid), mid
        else:
            hi = mid - 1
    return best


def _resize(img: Image.Image, scale: float) -> Image.Image:
    dims = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(dims, RESAMPLE)


def _png_colours(quality: int) -> int:
    """PNG quality 100 = lossless recompress, lower = fewer palette colours."""
    return 256 if quality >= 100 else max(16, int(16 + 240 * quality / 100))


def shrink(img: Image.Image, fmt: str, cfg: Config):
    """Return (bytes, info). info = {'level', 'size', 'scale'}."""
    work = fit(img, cfg.max_dim)
    info = {"level": 0, "size": work.size, "scale": 1.0}
    exif = None
    mode = cfg.exif_mode if getattr(cfg, "exif_mode", "none") != "none" else ("all" if cfg.keep_exif else "none")
    if mode != "none" and fmt in ("JPEG", "WEBP", "AVIF"):
        try:
            exif_obj = img.getexif()
            if mode == "safe":
                # Drop GPS and other personal tags; keep orientation + colour info.
                try:
                    if 34853 in exif_obj:  # GPSInfo IFD
                        del exif_obj[34853]
                except Exception:
                    pass
                for tag in (0x0132, 0x9003, 0x9004):  # DateTime strings often leak
                    pass
            exif = exif_obj.tobytes() or None
        except Exception:
            exif = None

    lo_q, hi_q = (16, 256) if fmt == "PNG" else (20, 95)

    if cfg.mode == "quality":
        level = _png_colours(cfg.quality) if fmt == "PNG" else max(1, min(100, cfg.quality))
        data = encode(work, fmt, level, exif)
        info["level"] = level
        return data, info

    target = max(1, cfg.target_kb) * 1024

    best = _search(work, fmt, target, lo_q, hi_q, exif)          # phase 1: full size
    if best:
        info["level"] = best[1]
        return best[0], info

    probe_q = PROBE_Q[fmt]                                        # phase 2: scale search
    lo, hi, best_scale = 0.05, 1.0, None
    while hi - lo > 0.01:
        mid = (lo + hi) / 2
        if len(encode(_resize(work, mid), fmt, probe_q, exif)) <= target:
            best_scale, lo = mid, mid
        else:
            hi = mid
    scale = best_scale if best_scale is not None else 0.05
    scaled = _resize(work, scale)
    info["scale"] = scale

    res = _search(scaled, fmt, target, lo_q, hi_q, exif)          # phase 3: max quality
    if res:
        info["level"], info["size"] = res[1], scaled.size
        return res[0], info
    info["level"], info["size"] = lo_q, scaled.size
    return encode(scaled, fmt, lo_q, exif), info
