"""Load .ico / .icns files into Pillow images for GUI previews."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image


def load_icon_image(path: Path | str, size: int = 128) -> Image.Image | None:
    """Return a RGBA Pillow image resized to *size*, or None on failure."""
    src = Path(path)
    if not src.is_file():
        return None
    try:
        with Image.open(src) as im:
            im.load()
            # Prefer the largest frame in multi-size ICO/ICNS
            best = im
            if getattr(im, "n_frames", 1) > 1:
                frames: list[Image.Image] = []
                for i in range(im.n_frames):
                    im.seek(i)
                    frames.append(im.copy())
                best = max(frames, key=lambda f: f.size[0] * f.size[1])
            rgba = best.convert("RGBA")
            rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
            return rgba
    except OSError:
        return None


def icon_to_png_bytes(path: Path | str, size: int = 128) -> bytes | None:
    """Encode a preview PNG for Qt QPixmap.loadFromData."""
    img = load_icon_image(path, size=size)
    if img is None:
        return None
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
