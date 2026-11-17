"""Convert macOS .icns icons to multi-size Windows .ico files (works on Windows)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

DEFAULT_ICO_SIZES: tuple[tuple[int, int], ...] = (
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)

_MAX_ICO_SIDE = 256


class IcnsConversionError(Exception):
    """Raised when an .icns file cannot be converted to .ico."""


def _pixel_side(width: int, height: int, scale: int) -> int:
    return max(width, height) * scale


def _normalize_size_entry(entry: tuple) -> tuple[int, int, int] | None:
    if len(entry) == 3:
        w, h, scale = entry
    elif len(entry) == 2:
        w, h = entry
        scale = 1
    else:
        return None
    return int(w), int(h), int(scale)


def _load_icns_frames(im: Image.Image) -> list[Image.Image]:
    """Load RGBA frames from an open ICNS image, largest first, capped at 256px."""
    raw_sizes = im.info.get("sizes") or []
    # Prefer larger native pixels; dedupe by resulting pixel size.
    candidates: list[tuple[int, tuple[int, int, int]]] = []
    seen: set[int] = set()
    for entry in raw_sizes:
        normalized = _normalize_size_entry(tuple(entry))
        if normalized is None:
            continue
        w, h, scale = normalized
        side = _pixel_side(w, h, scale)
        if side <= 0 or side in seen:
            continue
        seen.add(side)
        candidates.append((side, (w, h, scale)))
    candidates.sort(key=lambda t: t[0], reverse=True)

    frames: list[Image.Image] = []
    icns = getattr(im, "icns", None)
    for side, best_size in candidates:
        if side > _MAX_ICO_SIDE:
            continue
        try:
            if icns is not None:
                frame = icns.getimage(best_size)
            else:
                frame = im.copy()
                frame.size = best_size[:2]
                frame.load(scale=best_size[2])
            frames.append(frame.convert("RGBA"))
        except Exception:
            continue

    if frames:
        return frames

    # Fallback: largest image Pillow selected on open.
    try:
        base = im.convert("RGBA")
    except Exception as exc:
        raise IcnsConversionError(f"Failed to decode ICNS image: {exc}") from exc

    if max(base.size) > _MAX_ICO_SIDE:
        base = base.resize((_MAX_ICO_SIDE, _MAX_ICO_SIDE), Image.Resampling.LANCZOS)
    return [base]


def _frames_for_ico(
    frames: Sequence[Image.Image],
    sizes: Sequence[tuple[int, int]],
) -> tuple[Image.Image, list[Image.Image]]:
    """Pick primary + append_images matching requested ICO sizes."""
    by_side: dict[int, Image.Image] = {}
    for frame in frames:
        side = max(frame.size)
        if side > _MAX_ICO_SIDE:
            continue
        # Keep first (largest-first list) for each exact side.
        by_side.setdefault(side, frame)

    if not by_side:
        raise IcnsConversionError("No usable icon frames at or below 256x256")

    largest = by_side[max(by_side)]
    requested = [
        (w, h)
        for w, h in sizes
        if 0 < w <= _MAX_ICO_SIDE and 0 < h <= _MAX_ICO_SIDE and w == h
    ]
    if not requested:
        requested = list(DEFAULT_ICO_SIZES)

    # Primary image should be the largest requested size we can serve.
    max_req = max(w for w, _ in requested)
    if max_req in by_side:
        primary = by_side[max_req]
    elif max(largest.size) >= max_req:
        primary = largest.resize((max_req, max_req), Image.Resampling.LANCZOS)
    else:
        primary = largest

    append: list[Image.Image] = []
    for w, h in requested:
        if (w, h) == primary.size:
            continue
        if w in by_side:
            append.append(by_side[w])
        else:
            src = largest if max(largest.size) >= w else largest
            append.append(src.resize((w, h), Image.Resampling.LANCZOS))
    return primary, append


def icns_to_ico(
    src: Path | str,
    dest: Path | str | None = None,
    *,
    sizes: Iterable[tuple[int, int]] = DEFAULT_ICO_SIZES,
) -> Path:
    """Convert a single .icns file to a multi-size .ico.

    Parameters
    ----------
    src:
        Path to the source .icns file.
    dest:
        Output .ico path. Defaults to ``<src_stem>.ico`` beside the source.
    sizes:
        Square ICO entry sizes to include (max 256).

    Returns
    -------
    Path
        Path to the written .ico file.
    """
    src_path = Path(src)
    if not src_path.is_file():
        raise IcnsConversionError(f"Source not found: {src_path}")

    dest_path = Path(dest) if dest is not None else src_path.with_suffix(".ico")
    if dest_path.suffix.lower() != ".ico":
        dest_path = dest_path.with_suffix(".ico")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    size_list = tuple(sizes) or DEFAULT_ICO_SIZES

    try:
        with Image.open(src_path) as im:
            if getattr(im, "format", None) not in (None, "ICNS") and src_path.suffix.lower() != ".icns":
                raise IcnsConversionError(
                    f"Expected an ICNS file, got format={im.format!r}: {src_path}"
                )
            frames = _load_icns_frames(im)
            primary, append = _frames_for_ico(frames, size_list)
            save_kwargs: dict = {
                "format": "ICO",
                "sizes": list(size_list),
            }
            if append:
                save_kwargs["append_images"] = append
            primary.save(dest_path, **save_kwargs)
    except IcnsConversionError:
        raise
    except Exception as exc:
        raise IcnsConversionError(f"Failed to convert {src_path}: {exc}") from exc

    return dest_path


def batch_icns_to_ico(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    recursive: bool = False,
    sizes: Iterable[tuple[int, int]] = DEFAULT_ICO_SIZES,
) -> list[Path]:
    """Convert all .icns files under ``input_dir`` into ``output_dir``.

    Relative paths are preserved when ``recursive`` is True.
    """
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)
    if not in_dir.is_dir():
        raise IcnsConversionError(f"Input directory not found: {in_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = "**/*.icns" if recursive else "*.icns"
    written: list[Path] = []
    errors: list[str] = []

    for src in sorted(in_dir.glob(pattern)):
        if not src.is_file():
            continue
        rel = src.relative_to(in_dir) if recursive else Path(src.name)
        dest = out_dir / rel.with_suffix(".ico")
        try:
            written.append(icns_to_ico(src, dest, sizes=sizes))
        except IcnsConversionError as exc:
            errors.append(str(exc))

    if not written and errors:
        raise IcnsConversionError(
            "No icons converted. First error: " + errors[0]
        )
    return written


DEFAULT_ICNS_SIZES: tuple[tuple[int, int, int], ...] = (
    (16, 16, 1),
    (16, 16, 2),
    (32, 32, 1),
    (32, 32, 2),
    (128, 128, 1),
    (128, 128, 2),
    (256, 256, 1),
    (256, 256, 2),
    (512, 512, 1),
    (512, 512, 2),
)


def ico_to_icns(
    src: Path | str,
    dest: Path | str | None = None,
) -> Path:
    """Convert a Windows .ico to a macOS .icns (works cross-platform via Pillow)."""
    src_path = Path(src)
    if not src_path.is_file():
        raise IcnsConversionError(f"Source not found: {src_path}")

    dest_path = Path(dest) if dest is not None else src_path.with_suffix(".icns")
    if dest_path.suffix.lower() != ".icns":
        dest_path = dest_path.with_suffix(".icns")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(src_path) as im:
            base = im.convert("RGBA")
            # Use largest available ICO frame when present.
            sizes = sorted(im.info.get("sizes") or [base.size], reverse=True)
            if sizes:
                try:
                    im.size = sizes[0]
                    im.load()
                    base = im.convert("RGBA")
                except Exception:
                    pass

            append: list[Image.Image] = []
            for w, h, scale in DEFAULT_ICNS_SIZES:
                px = w * scale
                if px > max(base.size):
                    continue
                if (px, px) == base.size:
                    continue
                append.append(base.resize((px, px), Image.Resampling.LANCZOS))

            save_kwargs: dict = {"format": "ICNS"}
            if append:
                save_kwargs["append_images"] = append
            # Pillow ICNS writer wants a reasonably large master.
            master = base
            if max(master.size) < 256:
                master = master.resize((256, 256), Image.Resampling.LANCZOS)
            master.save(dest_path, **save_kwargs)
    except IcnsConversionError:
        raise
    except Exception as exc:
        raise IcnsConversionError(f"Failed to convert {src_path}: {exc}") from exc

    return dest_path


def ensure_format(
    src: Path | str,
    *,
    want: str,
    cache_dir: Path | str,
) -> Path:
    """Return a path to ``src`` in ``want`` format (``ico`` or ``icns``), converting into cache if needed."""
    src_path = Path(src)
    want = want.lower().lstrip(".")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    suffix = src_path.suffix.lower().lstrip(".")
    if suffix == want:
        return src_path

    dest = cache / f"{src_path.stem}.{want}"
    if dest.is_file() and dest.stat().st_mtime >= src_path.stat().st_mtime:
        return dest

    if want == "ico" and suffix == "icns":
        return icns_to_ico(src_path, dest)
    if want == "icns" and suffix == "ico":
        return ico_to_icns(src_path, dest)
    raise IcnsConversionError(f"Cannot convert .{suffix} to .{want}: {src_path}")
