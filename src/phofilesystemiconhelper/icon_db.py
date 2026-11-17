"""Recursive .icns/.ico indexer backed by SQLite."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from phofilesystemiconhelper.paths import DEFAULT_DB_PATH, ensure_data_dirs

ICON_SUFFIXES = {".icns", ".ico"}

KNOWN_VENDORS: tuple[tuple[str, str], ...] = (
    ("otherworldcomputing", "owc"),
    ("western digital", "wd"),
    ("sandisk", "sandisk"),
    ("samsung", "samsung"),
    ("seagate", "seagate"),
    ("crucial", "crucial"),
    ("transcend", "transcend"),
    ("toshiba", "toshiba"),
    ("hitachi", "hitachi"),
    ("micron", "micron"),
    ("kingston", "kingston"),
    ("intel", "intel"),
    ("lacie", "lacie"),
    ("adata", "adata"),
    ("corsair", "corsair"),
    ("sabrent", "sabrent"),
    ("verbatim", "verbatim"),
    ("realtek", "realtek"),
    ("owc", "owc"),
    ("ocz", "ocz"),
    ("wdc", "wd"),
    ("wd", "wd"),
    ("hgst", "hgst"),
    ("plextor", "plextor"),
    ("skhynix", "skhynix"),
    ("hynix", "hynix"),
    ("teamgroup", "teamgroup"),
    ("siliconpower", "siliconpower"),
)

NOISE_TOKENS = frozenset(
    {
        "icon",
        "icons",
        "macos",
        "mac",
        "windows",
        "win",
        "drive",
        "drives",
        "premium",
        "the",
        "and",
        "for",
        "pc",
        "new",
        "custom",
        "filesystem",
        "folder",
        "folders",
        "device",
        "devices",
        "storage",
        "black",
        "white",
        "red",
        "blue",
        "green",
        "yellow",
        "grey",
        "gray",
        "color",
        "colour",
    }
)

_CAPACITY_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>tb|gb|mb)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS icons (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL,
    stem TEXT NOT NULL,
    mtime REAL NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    vendor TEXT,
    media TEXT NOT NULL,
    bus TEXT NOT NULL,
    capacity_bytes INTEGER,
    tokens TEXT NOT NULL,
    platform_hint TEXT NOT NULL,
    relative_path TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_icons_vendor ON icons(vendor);
CREATE INDEX IF NOT EXISTS idx_icons_media ON icons(media);
CREATE INDEX IF NOT EXISTS idx_icons_format ON icons(format);
"""


@dataclass(frozen=True)
class IconRecord:
    path: Path
    format: str
    stem: str
    mtime: float
    size_bytes: int
    sha256: str
    vendor: str | None
    media: str
    bus: str
    capacity_bytes: int | None
    tokens: tuple[str, ...]
    platform_hint: str
    relative_path: str


def default_db_path() -> Path:
    return DEFAULT_DB_PATH


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    ensure_data_dirs()
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _capacity_bytes(text: str) -> int | None:
    match = _CAPACITY_RE.search(text.replace("_", " "))
    if not match:
        return None
    num = float(match.group("num"))
    unit = match.group("unit").lower()
    mult = {"mb": 1000**2, "gb": 1000**3, "tb": 1000**4}[unit]
    return int(num * mult)


def _detect_vendor(text_lower: str) -> str | None:
    tokens = set(_TOKEN_RE.findall(text_lower))
    # Prefer whole-token matches so short needles like "wd" do not hit
    # inside "newdriveicons".
    for needle, canon in KNOWN_VENDORS:
        parts = needle.split()
        if len(parts) == 1 and parts[0] in tokens:
            return canon
        if len(parts) > 1 and all(p in tokens for p in parts):
            return canon
    for needle, canon in KNOWN_VENDORS:
        compact = needle.replace(" ", "")
        if len(compact) < 3:
            continue
        if needle in text_lower or compact in text_lower.replace(" ", ""):
            return canon
    return None


def _detect_media(text_lower: str, tokens: set[str]) -> str:
    joined = " ".join(tokens)
    if (
        "nvme" in tokens
        or "nvmedrive" in tokens
        or "m2" in tokens
        or "m.2" in text_lower
        or "nvme" in text_lower
    ):
        return "nvme"
    if "ssd" in tokens or "ssd" in text_lower or "ssd" in joined or "solidstate" in text_lower:
        return "ssd"
    if (
        "hdd" in tokens
        or "hdd" in text_lower
        or "harddisk" in text_lower
        or "barracuda" in tokens
    ):
        return "hdd"
    # Classic WD color desktop drives (Black/Blue/Red/…) are HDDs unless
    # the name also says SSD/NVMe.
    if (
        "wd" in tokens
        and "ssd" not in text_lower
        and "nvme" not in text_lower
        and any(
            c in text_lower
            for c in ("black", "blue", "red", "green", "purple", "white", "gold")
        )
    ):
        return "hdd"
    if "optical" in tokens or "cd" in tokens or "dvd" in tokens or "bluray" in tokens:
        return "optical"
    return "unknown"


def _detect_bus(text_lower: str, tokens: set[str]) -> str:
    if "usb" in tokens or "removable" in tokens:
        return "usb"
    if "external" in tokens or "portable" in tokens:
        return "external"
    if "internal" in tokens:
        return "internal"
    if "thunderbolt" in tokens or "tbt" in tokens:
        return "external"
    return "unknown"


def _detect_platform_hint(path: Path, text_lower: str) -> str:
    parts = {p.lower() for p in path.parts}
    joined = "/".join(parts)
    if "macos" in text_lower or " mac " in f" {text_lower} " or "/mac/" in f"/{joined}/":
        if "windows" in text_lower or "/windows/" in f"/{joined}/" or "/win/" in f"/{joined}/":
            return "any"
        return "mac"
    if "windows" in text_lower or "/windows/" in f"/{joined}/" or "/win/" in f"/{joined}/" or "pc-" in text_lower:
        return "win"
    if path.suffix.lower() == ".icns":
        return "mac"
    if path.suffix.lower() == ".ico":
        return "win"
    return "any"


def parse_icon_filename(path: Path, root: Path | None = None) -> dict:
    stem = path.stem.strip()
    stem_lower = stem.lower()
    # Prefer the filename for media/capacity; use parent path only for vendor/tokens.
    parent_text = " ".join(path.parts[-4:-1]).lower()
    text_lower = f"{stem_lower} {parent_text}"
    raw_tokens = [t.lower() for t in _TOKEN_RE.findall(text_lower)]
    tokens = tuple(
        t
        for t in raw_tokens
        if t not in NOISE_TOKENS and len(t) > 1 and not t.isdigit()
    )
    stem_tokens = set(_TOKEN_RE.findall(stem_lower))
    token_set = set(tokens)
    # Stem media wins over folder names like SSD_HDD_Icons.
    media = _detect_media(stem_lower, stem_tokens)
    if media == "unknown":
        media = _detect_media(text_lower, token_set)
    bus = _detect_bus(stem_lower, stem_tokens)
    if bus == "unknown":
        bus = _detect_bus(text_lower, token_set)
    # Vendor from filename; only fall back to the immediate parent folder name
    # (not the whole path) so packs like "WD Icons" do not tag every child.
    vendor = _detect_vendor(stem_lower)
    if vendor is None and path.parent.name:
        vendor = _detect_vendor(path.parent.name.lower())
    rel = str(path.relative_to(root)) if root is not None else path.name
    return {
        "stem": stem,
        "vendor": vendor,
        "media": media,
        "bus": bus,
        "capacity_bytes": _capacity_bytes(stem_lower) or _capacity_bytes(text_lower),
        "tokens": tokens,
        "platform_hint": _detect_platform_hint(path, text_lower),
        "relative_path": rel.replace("\\", "/"),
    }


def iter_icon_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in ICON_SUFFIXES:
            yield path


def _row_to_record(row: sqlite3.Row) -> IconRecord:
    return IconRecord(
        path=Path(row["path"]),
        format=row["format"],
        stem=row["stem"],
        mtime=row["mtime"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        vendor=row["vendor"],
        media=row["media"],
        bus=row["bus"],
        capacity_bytes=row["capacity_bytes"],
        tokens=tuple(json.loads(row["tokens"])),
        platform_hint=row["platform_hint"],
        relative_path=row["relative_path"],
    )


def list_icons(conn: sqlite3.Connection) -> list[IconRecord]:
    rows = conn.execute("SELECT * FROM icons ORDER BY path").fetchall()
    return [_row_to_record(r) for r in rows]


def icon_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM icons").fetchone()
    return int(row["n"])


def index_icons(
    root: Path | str,
    db_path: Path | str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Index all .icns/.ico under ``root``. Returns number of upserted rows."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Icon root not found: {root_path}")

    own_conn = conn is None
    if conn is None:
        conn = connect(db_path)

    upserted = 0
    seen_paths: set[str] = set()

    for path in iter_icon_files(root_path):
        abs_path = str(path.resolve())
        seen_paths.add(abs_path)
        try:
            st = path.stat()
            digest = _sha256_file(path)
            parsed = parse_icon_filename(path, root_path)
            fmt = path.suffix.lower().lstrip(".")
            conn.execute(
                """
                INSERT INTO icons (
                    path, format, stem, mtime, size_bytes, sha256,
                    vendor, media, bus, capacity_bytes, tokens,
                    platform_hint, relative_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    format=excluded.format,
                    stem=excluded.stem,
                    mtime=excluded.mtime,
                    size_bytes=excluded.size_bytes,
                    sha256=excluded.sha256,
                    vendor=excluded.vendor,
                    media=excluded.media,
                    bus=excluded.bus,
                    capacity_bytes=excluded.capacity_bytes,
                    tokens=excluded.tokens,
                    platform_hint=excluded.platform_hint,
                    relative_path=excluded.relative_path
                """,
                (
                    abs_path,
                    fmt,
                    parsed["stem"],
                    st.st_mtime,
                    st.st_size,
                    digest,
                    parsed["vendor"],
                    parsed["media"],
                    parsed["bus"],
                    parsed["capacity_bytes"],
                    json.dumps(list(parsed["tokens"])),
                    parsed["platform_hint"],
                    parsed["relative_path"],
                ),
            )
            upserted += 1
        except OSError as exc:
            warnings.warn(f"Skipping unreadable icon {path}: {exc}", stacklevel=2)

    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("indexed_root", str(root_path)),
    )
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("indexed_count", str(upserted)),
    )
    conn.commit()
    if own_conn:
        conn.close()
    return upserted


def load_icons(db_path: Path | str | None = None) -> list[IconRecord]:
    conn = connect(db_path)
    try:
        return list_icons(conn)
    finally:
        conn.close()
