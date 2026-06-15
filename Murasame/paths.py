from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_NAME = "MurasamePet"


def resource_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def user_data_dir() -> Path:
    override = os.environ.get("MURASAMEPET_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform.startswith("win"):
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_data_path(*parts: str) -> Path:
    return user_data_dir().joinpath(*parts)


def resolve_user_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return user_data_path(str(path))


def copy_seed_file(filename: str) -> Path:
    target = user_data_path(filename)
    if not target.exists():
        source = resource_path(filename)
        if source.exists():
            shutil.copy2(source, target)
    return target


def seed_character_cards() -> Path:
    target_dir = user_data_path("character_cards")
    target_dir.mkdir(parents=True, exist_ok=True)
    if any(target_dir.glob("*.json")):
        return target_dir

    source_dir = resource_path("character_cards")
    if not source_dir.exists():
        return target_dir

    for source in source_dir.glob("*.json"):
        shutil.copy2(source, target_dir / source.name)
    return target_dir
