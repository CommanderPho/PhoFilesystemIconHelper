"""Helps set and manage custom filesystem and volume icons on Windows and macOS."""

from phofilesystemiconhelper.apply_volume_icon import apply_match, apply_matches
from phofilesystemiconhelper.disk_probe import DiskIdentity, list_disks
from phofilesystemiconhelper.icns_to_ico import (
    DEFAULT_ICO_SIZES,
    IcnsConversionError,
    batch_icns_to_ico,
    ensure_format,
    icns_to_ico,
    ico_to_icns,
)
from phofilesystemiconhelper.icon_db import IconRecord, index_icons, load_icons
from phofilesystemiconhelper.match_icons import MatchResult, match_all_disks, match_disk

__all__ = [
    "DEFAULT_ICO_SIZES",
    "DiskIdentity",
    "IcnsConversionError",
    "IconRecord",
    "MatchResult",
    "apply_match",
    "apply_matches",
    "batch_icns_to_ico",
    "ensure_format",
    "icns_to_ico",
    "ico_to_icns",
    "index_icons",
    "list_disks",
    "load_icons",
    "match_all_disks",
    "match_disk",
]
