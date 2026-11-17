"""Default paths for icon index DB and conversion cache."""

from __future__ import annotations

from pathlib import Path

# Package dir is src/phofilesystemiconhelper/; repo root is its parents[1]
_PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = _PACKAGE_DIR.parents[1]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "icon_index.sqlite"
DEFAULT_CACHE_DIR = DATA_DIR / "icon_cache"


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
