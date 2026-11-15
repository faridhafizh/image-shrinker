"""Shared constants and small formatting helpers.

This is the only module that touches Pillow at import time, so the friendly
"install Pillow" message also covers the rest of the package.
"""

from __future__ import annotations

try:
    from PIL import Image, features
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise SystemExit(
        "This tool needs Pillow.\nInstall it with:  pip install pillow"
    ) from exc

RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
QUANT_FASTOCTREE = getattr(getattr(Image, "Quantize", Image), "FASTOCTREE", 2)
QUANT_MEDIANCUT = getattr(getattr(Image, "Quantize", Image), "MEDIANCUT", 0)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
SRC_FMT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".avif": "AVIF",
}
HAS_AVIF = features.check("avif")
KEEPABLE = {"JPEG", "PNG", "WEBP"} | ({"AVIF"} if HAS_AVIF else set())
EXT_FOR = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png", "AVIF": ".avif"}
FORMATS = ["keep", "jpeg", "webp", "png"] + (["avif"] if HAS_AVIF else [])

# Mid-range probe quality used to drive the scale search in target mode.
PROBE_Q = {"JPEG": 80, "WEBP": 80, "AVIF": 60, "PNG": 200}  # PNG = colour count


def human(n: float) -> str:
    """Format a byte count as a short human-readable string."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
