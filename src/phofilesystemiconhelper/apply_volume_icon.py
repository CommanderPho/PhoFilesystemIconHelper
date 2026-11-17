"""Apply matched icons as OS volume icons (Windows DriveIcons / macOS .VolumeIcon.icns)."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from phofilesystemiconhelper.icns_to_ico import ensure_format
from phofilesystemiconhelper.match_icons import MatchResult, match_all_disks
from phofilesystemiconhelper.paths import DEFAULT_CACHE_DIR, ensure_data_dirs


@dataclass
class ApplyResult:
    mount: str
    icon_path: Path | None
    ok: bool
    message: str
    dry_run: bool


def is_windows_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _notify_shell_windows() -> None:
    # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def _set_driveicons_registry(letter: str, ico_path: Path) -> None:
    import winreg

    letter = letter.rstrip(":\\/").upper()
    key_path = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons"
        rf"\{letter}\DefaultIcon"
    )
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(ico_path.resolve()))


def _write_autorun(mount_root: Path, ico_name: str) -> None:
    autorun = mount_root / "autorun.inf"
    content = f"[autorun]\r\nicon={ico_name}\r\n"
    autorun.write_text(content, encoding="ascii", errors="replace")
    try:
        # Hide autorun.inf a bit (optional)
        ctypes.windll.kernel32.SetFileAttributesW(str(autorun), 0x2)  # HIDDEN
    except Exception:
        pass


def apply_windows_mount(
    mount: str,
    ico_path: Path,
    *,
    removable: bool,
    dry_run: bool,
) -> ApplyResult:
    letter = mount.rstrip("\\/").upper()
    if not letter.endswith(":"):
        letter = letter + ":" if len(letter) == 1 else letter
    root = Path(letter + "\\")
    ico_path = ico_path.resolve()

    if dry_run:
        actions = [f"HKLM DriveIcons\\{letter[0]}\\DefaultIcon = {ico_path}"]
        if removable and root.exists():
            actions.append(f"copy ico + autorun.inf on {root}")
        return ApplyResult(
            mount=letter,
            icon_path=ico_path,
            ok=True,
            message="; ".join(actions),
            dry_run=True,
        )

    if not is_windows_admin():
        return ApplyResult(
            mount=letter,
            icon_path=ico_path,
            ok=False,
            message="Administrator privileges required for HKLM DriveIcons; re-run elevated",
            dry_run=False,
        )

    try:
        _set_driveicons_registry(letter[0], ico_path)
        msg = f"set DriveIcons\\{letter[0]}"
        if removable and root.exists():
            dest_ico = root / ico_path.name
            shutil.copy2(ico_path, dest_ico)
            _write_autorun(root, dest_ico.name)
            msg += f"; wrote {dest_ico.name} + autorun.inf"
        _notify_shell_windows()
        return ApplyResult(
            mount=letter,
            icon_path=ico_path,
            ok=True,
            message=msg,
            dry_run=False,
        )
    except PermissionError as exc:
        return ApplyResult(
            mount=letter,
            icon_path=ico_path,
            ok=False,
            message=f"permission denied: {exc}",
            dry_run=False,
        )
    except OSError as exc:
        return ApplyResult(
            mount=letter,
            icon_path=ico_path,
            ok=False,
            message=str(exc),
            dry_run=False,
        )


def _set_macos_custom_icon_flag(mount: Path) -> None:
    # Prefer SetFile if present (Xcode CLT); fall back to xattr/FinderInfo no-op attempt.
    setfile = shutil.which("SetFile")
    if setfile:
        subprocess.run(
            [setfile, "-a", "C", str(mount)],
            check=False,
            capture_output=True,
        )
        return
    # Touch .VolumeIcon.icns is usually enough for Finder after restart/remount.
    # Also try hiding the file.
    vol_icon = mount / ".VolumeIcon.icns"
    if vol_icon.exists():
        subprocess.run(
            ["chflags", "hidden", str(vol_icon)],
            check=False,
            capture_output=True,
        )


def apply_macos_mount(
    mount: str,
    icns_path: Path,
    *,
    dry_run: bool,
) -> ApplyResult:
    root = Path(mount)
    icns_path = icns_path.resolve()
    dest = root / ".VolumeIcon.icns"

    if dry_run:
        return ApplyResult(
            mount=mount,
            icon_path=icns_path,
            ok=True,
            message=f"copy {icns_path} -> {dest}; set custom-icon flag",
            dry_run=True,
        )

    if not root.is_dir():
        return ApplyResult(
            mount=mount,
            icon_path=icns_path,
            ok=False,
            message=f"mount not found: {mount}",
            dry_run=False,
        )

    try:
        shutil.copy2(icns_path, dest)
        _set_macos_custom_icon_flag(root)
        return ApplyResult(
            mount=mount,
            icon_path=icns_path,
            ok=True,
            message=f"wrote {dest}",
            dry_run=False,
        )
    except OSError as exc:
        return ApplyResult(
            mount=mount,
            icon_path=icns_path,
            ok=False,
            message=str(exc),
            dry_run=False,
        )


def apply_match(
    result: MatchResult,
    *,
    dry_run: bool = True,
    cache_dir: Path | str | None = None,
) -> list[ApplyResult]:
    ensure_data_dirs()
    if result.icon is None:
        return [
            ApplyResult(
                mount=",".join(result.disk.mounts) or result.disk.id,
                icon_path=None,
                ok=False,
                message="no icon matched",
                dry_run=dry_run,
            )
        ]
    if not result.disk.mounts:
        return [
            ApplyResult(
                mount=result.disk.id,
                icon_path=result.icon.path,
                ok=False,
                message="disk has no mount points",
                dry_run=dry_run,
            )
        ]

    cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    want = "ico" if sys.platform == "win32" else "icns"
    try:
        native = result.resolved_path or ensure_format(
            result.icon.path, want=want, cache_dir=cache
        )
    except Exception as exc:
        return [
            ApplyResult(
                mount=",".join(result.disk.mounts),
                icon_path=result.icon.path,
                ok=False,
                message=f"convert failed: {exc}",
                dry_run=dry_run,
            )
        ]

    removable = result.disk.bus in {"usb", "external"}
    applied: list[ApplyResult] = []
    for mount in result.disk.mounts:
        if sys.platform == "win32":
            # Only drive-letter mounts
            if len(mount) >= 2 and mount[1] == ":":
                applied.append(
                    apply_windows_mount(
                        mount, native, removable=removable, dry_run=dry_run
                    )
                )
            else:
                applied.append(
                    ApplyResult(
                        mount=mount,
                        icon_path=native,
                        ok=False,
                        message="not a drive-letter mount",
                        dry_run=dry_run,
                    )
                )
        elif sys.platform == "darwin":
            if mount == "/" and result.disk.is_system:
                applied.append(
                    ApplyResult(
                        mount=mount,
                        icon_path=native,
                        ok=False,
                        message="refusing system volume (pass include_system upstream)",
                        dry_run=dry_run,
                    )
                )
            else:
                applied.append(
                    apply_macos_mount(mount, native, dry_run=dry_run)
                )
        else:
            applied.append(
                ApplyResult(
                    mount=mount,
                    icon_path=native,
                    ok=False,
                    message=f"unsupported platform {sys.platform}",
                    dry_run=dry_run,
                )
            )
    return applied


def apply_matches(
    *,
    db_path: Path | str | None = None,
    include_system: bool = False,
    dry_run: bool = True,
) -> tuple[list[MatchResult], list[ApplyResult]]:
    matches = match_all_disks(
        db_path=db_path,
        include_system=include_system,
    )
    applied: list[ApplyResult] = []
    for match in matches:
        if match.icon is None:
            continue
        if match.disk.is_system and not include_system:
            continue
        applied.extend(apply_match(match, dry_run=dry_run))
    return matches, applied
