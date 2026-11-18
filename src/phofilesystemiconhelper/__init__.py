"""Helps set and manage custom filesystem and volume icons on Windows and macOS."""

from phofilesystemiconhelper.apply_volume_icon import (
    ApplyResult,
    VolumeIconState,
    apply_icon_path,
    apply_match,
    apply_matches,
    get_volume_icon_state,
    is_windows_admin,
    revert_volume_icon,
)
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
    "ApplyResult",
    "DiskIdentity",
    "IcnsConversionError",
    "IconRecord",
    "MatchResult",
    "VolumeIconState",
    "apply_icon_path",
    "apply_match",
    "apply_matches",
    "batch_icns_to_ico",
    "ensure_format",
    "get_volume_icon_state",
    "icns_to_ico",
    "ico_to_icns",
    "index_icons",
    "is_windows_admin",
    "list_disks",
    "load_icons",
    "match_all_disks",
    "match_disk",
    "revert_volume_icon",
]
