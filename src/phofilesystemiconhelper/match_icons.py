"""Score icon DB entries against probed disks and pick winners."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from phofilesystemiconhelper.disk_probe import DiskIdentity, list_disks
from phofilesystemiconhelper.icon_db import (
    IconRecord,
    connect,
    default_db_path,
    list_icons,
    parse_icon_filename,
)
from phofilesystemiconhelper.icns_to_ico import ensure_format
from phofilesystemiconhelper.paths import DEFAULT_CACHE_DIR, ensure_data_dirs

GENERIC_STEMS = frozenset(
    {
        "ssd",
        "hdd",
        "nvme",
        "nvmedrive",
        "usb",
        "usb_drive",
        "external",
        "external_drive",
        "external_drive_zion",
        "removable",
        "removable_drive",
        "cd_drive",
        "optical",
        "drive-harddisk",
        "drive-removable-media-usb",
    }
)


@dataclass
class MatchResult:
    disk: DiskIdentity
    icon: IconRecord | None
    score: int
    reasons: list[str] = field(default_factory=list)
    resolved_path: Path | None = None  # platform-native path after conversion


def _disk_tokens(disk: DiskIdentity) -> set[str]:
    text = f"{disk.model} {disk.name} {disk.vendor or ''}"
    parsed = parse_icon_filename(Path(text.replace("/", " ") + ".ico"))
    tokens = set(parsed["tokens"])
    if disk.vendor:
        tokens.add(disk.vendor.lower())
    return {t for t in tokens if len(t) > 1}


def _capacity_close(a: int | None, b: int | None, pct: float = 0.15) -> bool:
    if not a or not b:
        return False
    lo, hi = min(a, b), max(a, b)
    if lo <= 0:
        return False
    return (hi - lo) / hi <= pct


def _is_generic(icon: IconRecord) -> bool:
    stem_key = icon.stem.lower().replace(" ", "_")
    return stem_key in GENERIC_STEMS or icon.stem.lower() in GENERIC_STEMS


def score_icon(disk: DiskIdentity, icon: IconRecord, *, platform: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    disk_tokens = _disk_tokens(disk)

    disk_media = disk.media
    icon_media = icon.media
    media_conflict = (
        disk_media in {"ssd", "nvme", "hdd"}
        and icon_media in {"ssd", "nvme", "hdd"}
        and not (
            disk_media == icon_media
            or (disk_media == "nvme" and icon_media == "ssd")
            or (disk_media == "ssd" and icon_media == "nvme")
        )
    )

    if icon.vendor and disk.vendor and icon.vendor == disk.vendor:
        if media_conflict:
            reasons.append(f"vendor-skipped-media-conflict:{icon.vendor}")
        else:
            score += 40
            reasons.append(f"vendor:{icon.vendor}")

    overlap = sorted(set(icon.tokens) & disk_tokens)
    # Avoid double-counting pure vendor token
    overlap = [t for t in overlap if t != (disk.vendor or "")]
    if overlap and not media_conflict:
        points = min(60, 12 * len(overlap))
        score += points
        reasons.append(f"tokens:{','.join(overlap[:8])}+{points}")

    if disk_media == "nvme" and icon_media in {"nvme", "ssd"}:
        score += 25
        reasons.append("media:nvme/ssd")
    elif disk_media != "unknown" and icon_media == disk_media:
        score += 25
        reasons.append(f"media:{disk_media}")
    elif media_conflict:
        score -= 20
        reasons.append("media-conflict")
    elif icon_media == "unknown" and disk_media in {"ssd", "nvme", "hdd"}:
        score -= 8
        reasons.append("icon-media-unknown")

    if _capacity_close(disk.capacity_bytes, icon.capacity_bytes):
        score += 15
        reasons.append("capacity")

    if disk.bus != "unknown" and icon.bus != "unknown":
        if disk.bus == icon.bus or (
            disk.bus in {"usb", "external"} and icon.bus in {"usb", "external"}
        ):
            score += 15
            reasons.append(f"bus:{icon.bus}")

    native = "ico" if platform == "win32" else "icns"
    if icon.format == native:
        score += 10
        reasons.append(f"format:{native}")

    rel = icon.relative_path.lower().replace("\\", "/")
    if "driveicons" in rel or "new drive icons" in rel:
        score += 8
        reasons.append("drive-pack")

    if _is_generic(icon):
        media_ok = icon_media == disk_media or (
            disk_media == "nvme" and icon_media == "ssd"
        )
        # Generics are only a media-type fallback. Prefer drive-pack generics
        # over random theme icons, but keep them below real model matches.
        if disk_media != "unknown" and media_ok:
            if "media:" in ",".join(reasons) or "media:nvme/ssd" in reasons:
                # Already got media points; small pack bonus only.
                if "drive-pack" in reasons:
                    score += 5
                    reasons.append("generic-pack")
                score = min(score, 70)
            elif score < 40:
                score += 20
                reasons.append("generic-fallback")
                score = min(score, 55)
            else:
                score = min(score, 35)
                reasons.append("generic-cap")
        else:
            score = min(score, 30)
            reasons.append("generic-cap")

    return score, reasons


def match_disk(
    disk: DiskIdentity,
    icons: list[IconRecord],
    *,
    platform: str | None = None,
) -> MatchResult:
    platform = platform or sys.platform
    best: IconRecord | None = None
    best_score = -1
    best_reasons: list[str] = []

    for icon in icons:
        score, reasons = score_icon(disk, icon, platform=platform)
        if score > best_score:
            best, best_score, best_reasons = icon, score, reasons
            continue
        if score == best_score and best is not None:
            # Tie-break: prefer native format, then shorter relative path
            native = "ico" if platform == "win32" else "icns"
            best_native = 1 if best.format == native else 0
            cur_native = 1 if icon.format == native else 0
            if cur_native > best_native or (
                cur_native == best_native
                and len(icon.relative_path) < len(best.relative_path)
            ):
                best, best_score, best_reasons = icon, score, reasons

    # Require a minimum useful score unless only generics exist
    if best is not None and best_score < 20:
        best, best_score, best_reasons = None, 0, ["no-confident-match"]

    return MatchResult(
        disk=disk,
        icon=best,
        score=max(best_score, 0),
        reasons=best_reasons,
    )


def match_all_disks(
    *,
    db_path: Path | str | None = None,
    disks: list[DiskIdentity] | None = None,
    include_system: bool = False,
    resolve_native: bool = True,
    cache_dir: Path | str | None = None,
) -> list[MatchResult]:
    ensure_data_dirs()
    conn = connect(db_path or default_db_path())
    try:
        icons = list_icons(conn)
    finally:
        conn.close()

    if disks is None:
        disks = list_disks()

    platform = sys.platform
    want = "ico" if platform == "win32" else "icns"
    cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR

    results: list[MatchResult] = []
    for disk in disks:
        if disk.is_system and not include_system:
            results.append(
                MatchResult(
                    disk=disk,
                    icon=None,
                    score=0,
                    reasons=["skipped-system-volume"],
                )
            )
            continue
        result = match_disk(disk, icons, platform=platform)
        if resolve_native and result.icon is not None:
            try:
                result.resolved_path = ensure_format(
                    result.icon.path, want=want, cache_dir=cache
                )
            except Exception as exc:
                result.reasons.append(f"convert-failed:{exc}")
                result.resolved_path = result.icon.path
        results.append(result)
    return results
