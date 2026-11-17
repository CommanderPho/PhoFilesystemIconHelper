"""Probe local physical disks (Windows CIM / macOS diskutil)."""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from phofilesystemiconhelper.icon_db import KNOWN_VENDORS

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


@dataclass
class DiskIdentity:
    id: str
    name: str
    model: str
    vendor: str | None
    serial: str | None
    media: str  # ssd | hdd | nvme | optical | unknown
    bus: str  # internal | external | usb | unknown
    capacity_bytes: int | None
    mounts: list[str] = field(default_factory=list)
    is_system: bool = False
    platform: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vendor_from_model(model: str) -> str | None:
    text = (model or "").lower()
    # Crucial often uses CT#### product codes.
    if re.match(r"^ct\d", text.replace(" ", "")) or "crucial" in text:
        return "crucial"
    if text.startswith("wd_") or "wd_black" in text or "wd black" in text:
        return "wd"
    for needle, canon in KNOWN_VENDORS:
        if needle in text or needle.replace(" ", "") in text.replace(" ", ""):
            return canon
    tokens = set(_TOKEN_RE.findall(text))
    for needle, canon in KNOWN_VENDORS:
        parts = needle.split()
        if len(parts) == 1 and parts[0] in tokens:
            return canon
    return None


def _normalize_media(
    *,
    media_type: str | None = None,
    solid_state: bool | None = None,
    bus_type: str | None = None,
    model: str = "",
) -> str:
    mt = (media_type or "").lower()
    bus = (bus_type or "").lower()
    model_l = model.lower()
    if "nvme" in mt or "nvme" in bus or "nvme" in model_l:
        return "nvme"
    if solid_state is True or "ssd" in mt or mt in {"4", "solidstate"}:
        return "ssd"
    if "hdd" in mt or "hdd" in model_l or mt in {"3", "hdd"}:
        return "hdd"
    if "optical" in mt or "cd" in mt or "dvd" in mt:
        return "optical"
    if solid_state is False:
        return "hdd"
    return "unknown"


def _normalize_bus(
    *,
    bus_type: str | None = None,
    removable: bool | None = None,
    interface: str | None = None,
) -> str:
    bits = " ".join(
        x.lower() for x in (bus_type or "", interface or "") if x
    )
    if removable is True or "usb" in bits:
        return "usb" if "usb" in bits else "external"
    if any(x in bits for x in ("thunderbolt", "firewire", "1394", "external")):
        return "external"
    if any(x in bits for x in ("sata", "nvme", "scsi", "raid", "ide", "sas")):
        return "internal"
    if removable is False:
        return "internal"
    return "unknown"


def list_disks() -> list[DiskIdentity]:
    if sys.platform == "win32":
        return _list_disks_windows()
    if sys.platform == "darwin":
        return _list_disks_macos()
    raise NotImplementedError(f"Disk probe not supported on {sys.platform}")


def _run_powershell(script: str) -> Any:
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PowerShell disk probe failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    text = result.stdout.strip()
    if not text:
        return []
    return json.loads(text)


def _list_disks_windows() -> list[DiskIdentity]:
    # One script: physical disks + media type + logical mounts.
    script = r"""
$ErrorActionPreference = 'Stop'
$physMedia = @{}
try {
  Get-CimInstance -Namespace root/Microsoft/Windows/Storage -ClassName MSFT_PhysicalDisk -ErrorAction SilentlyContinue |
    ForEach-Object {
      $physMedia[[string]$_.DeviceId] = @{
        MediaType = [string]$_.MediaType
        BusType = [string]$_.BusType
        FriendlyName = [string]$_.FriendlyName
      }
    }
} catch {}

$drives = Get-CimInstance Win32_DiskDrive
$out = @()
foreach ($d in $drives) {
  $index = [string]$d.Index
  $mediaInfo = $physMedia[$index]
  $mediaType = if ($mediaInfo) { $mediaInfo.MediaType } else { '' }
  $busType = if ($mediaInfo -and $mediaInfo.BusType) { $mediaInfo.BusType } else { [string]$d.InterfaceType }

  $mounts = New-Object System.Collections.Generic.List[string]
  $partitions = Get-CimAssociatedInstance -InputObject $d -ResultClassName Win32_DiskPartition -ErrorAction SilentlyContinue
  foreach ($p in @($partitions)) {
    $logicals = Get-CimAssociatedInstance -InputObject $p -ResultClassName Win32_LogicalDisk -ErrorAction SilentlyContinue
    foreach ($l in @($logicals)) {
      if ($l.DeviceID) { [void]$mounts.Add([string]$l.DeviceID) }
    }
  }

  $out += [pscustomobject]@{
    Id = [string]$d.DeviceID
    Index = $index
    Model = [string]$d.Model
    Serial = [string]$d.SerialNumber
    Size = [int64]$d.Size
    InterfaceType = [string]$d.InterfaceType
    MediaType = $mediaType
    BusType = $busType
    PNPDeviceID = [string]$d.PNPDeviceID
    Mounts = @($mounts)
  }
}
$out | ConvertTo-Json -Compress -Depth 5
"""
    raw = _run_powershell(script)
    if isinstance(raw, dict):
        raw = [raw]
    disks: list[DiskIdentity] = []
    for item in raw or []:
        model = (item.get("Model") or "").strip()
        mounts = [m for m in (item.get("Mounts") or []) if m]
        # Normalize drive letters to "C:" form
        mounts = [m.upper().rstrip("\\/") for m in mounts]
        media = _normalize_media(
            media_type=str(item.get("MediaType") or ""),
            bus_type=str(item.get("BusType") or item.get("InterfaceType") or ""),
            model=model,
        )
        # MSFT MediaType: 3=HDD, 4=SSD, 5=SCM
        mt_raw = str(item.get("MediaType") or "")
        if mt_raw == "4":
            media = "ssd"
        elif mt_raw == "3":
            media = "hdd"
        model_l = model.lower()
        if media == "unknown":
            if any(x in model_l for x in ("ssd", "nvme", "rocket", "evo", "mx500")):
                media = "ssd"
            elif re.search(r"\bwd\d{2}\b", model_l) or "hdd" in model_l:
                media = "hdd"
        pnp = str(item.get("PNPDeviceID") or "").upper()
        iface = str(item.get("InterfaceType") or "").upper()
        # USB NVMe bridge chips (e.g. Realtek RTL9210) are external enclosures.
        usbish = (
            "USB" in iface
            or "USB" in pnp
            or "RTL9210" in model.upper()
            or "USBSTOR" in pnp
        )
        bus = _normalize_bus(
            bus_type=str(item.get("BusType") or ""),
            interface=str(item.get("InterfaceType") or ""),
            removable=usbish,
        )
        is_system = any(m.upper().startswith("C:") for m in mounts)
        disks.append(
            DiskIdentity(
                id=str(item.get("Id") or item.get("Index") or model),
                name=model or str(item.get("Id") or "disk"),
                model=model,
                vendor=_vendor_from_model(model),
                serial=(item.get("Serial") or None),
                media=media,
                bus=bus,
                capacity_bytes=int(item["Size"]) if item.get("Size") else None,
                mounts=mounts,
                is_system=is_system,
                platform="win32",
            )
        )
    return disks


def _plist_run(args: list[str]) -> Any:
    result = subprocess.run(
        args,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Command failed ({args[0]}): {err}")
    return plistlib.loads(result.stdout)


def _list_disks_macos() -> list[DiskIdentity]:
    listing = _plist_run(["diskutil", "list", "-plist"])
    disks: list[DiskIdentity] = []
    for entry in listing.get("AllDisksAndPartitions", []):
        device = entry.get("DeviceIdentifier")
        if not device:
            continue
        # Skip synthesized APFS containers' leaf weirdness: probe whole disks only
        if re.match(r"^disk\d+s\d+", device):
            continue
        try:
            info = _plist_run(["diskutil", "info", "-plist", device])
        except RuntimeError:
            continue

        if info.get("VirtualOrPhysical") == "Virtual":
            continue
        content = (info.get("Content") or "").lower()
        if "disk image" in content:
            continue

        model = (
            info.get("MediaName")
            or info.get("DeviceModel")
            or info.get("IORegistryEntryName")
            or device
        )
        model = str(model).strip()
        solid = info.get("SolidState")
        protocol = str(info.get("BusProtocol") or info.get("Protocol") or "")
        removable = bool(info.get("Removable") or info.get("RemovableMedia"))
        size = info.get("TotalSize") or info.get("Size")
        mounts: list[str] = []
        mp = info.get("MountPoint")
        if mp:
            mounts.append(str(mp))
        # Collect partition mounts from list entry
        for part in entry.get("Partitions", []) or []:
            pmp = part.get("MountPoint")
            if pmp:
                mounts.append(str(pmp))
        for container in entry.get("APFSVolumes", []) or []:
            pmp = container.get("MountPoint")
            if pmp:
                mounts.append(str(pmp))
        # Unique preserve order
        seen: set[str] = set()
        uniq_mounts: list[str] = []
        for m in mounts:
            if m not in seen:
                seen.add(m)
                uniq_mounts.append(m)

        media = _normalize_media(
            solid_state=bool(solid) if solid is not None else None,
            bus_type=protocol,
            model=model,
        )
        bus = _normalize_bus(
            bus_type=protocol,
            removable=removable,
            interface=protocol,
        )
        is_system = "/" in uniq_mounts
        disks.append(
            DiskIdentity(
                id=str(device),
                name=model or device,
                model=model,
                vendor=_vendor_from_model(model),
                serial=(info.get("IORegistryEntrySerialNumber") or info.get("SerialNumberNumber") or None),
                media=media,
                bus=bus,
                capacity_bytes=int(size) if size else None,
                mounts=uniq_mounts,
                is_system=is_system,
                platform="darwin",
            )
        )
    return disks
