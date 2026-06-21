from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class AppPaths:
    root: Path
    data_dir: Path
    reports_dir: Path
    backup_dir: Path
    error_log: Path
    settings_file: Path
    database_file: Path


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        # Portable builds keep user data next to the executable.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ensure_app_paths() -> AppPaths:
    root = get_app_root()
    data_dir = root / "data"
    reports_dir = root / "reports"
    backup_dir = data_dir / "backup"
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return AppPaths(
        root=root,
        data_dir=data_dir,
        reports_dir=reports_dir,
        backup_dir=backup_dir,
        error_log=root / "error.log",
        settings_file=data_dir / "settings.json",
        database_file=data_dir / "tournaments.db",
    )
