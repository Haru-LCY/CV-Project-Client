from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from PIL import Image, ImageDraw, ImageOps


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"}
IGNORED_NAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}
ALLOWED_CATEGORY_FOLDERS = {
    "图片",
    "文档",
    "视频",
    "音频",
    "压缩包",
    "安装包",
    "代码",
    "数据表格",
    "快捷方式",
    "其他",
}


@dataclass(frozen=True)
class DesktopEntry:
    id: int
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


def desktop_root_from_config(config: dict[str, Any]) -> Path:
    tools_config = config.get("agent_tools", {}) if isinstance(config.get("agent_tools"), dict) else {}
    configured = tools_config.get("desktop_root")
    if isinstance(configured, str) and configured.strip():
        return Path(os.path.expanduser(configured)).resolve()
    return (Path.home() / "Desktop").resolve()


def list_desktop_files(desktop_root: Path, images_only: bool = False) -> list[DesktopEntry]:
    if not desktop_root.exists():
        return []
    entries: list[DesktopEntry] = []
    for path in sorted(desktop_root.iterdir(), key=lambda item: item.name.lower()):
        if not _is_allowed_direct_file(desktop_root, path):
            continue
        if images_only and path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        entries.append(DesktopEntry(id=len(entries) + 1, path=path))
    return entries


def build_image_contact_sheet(entries: list[DesktopEntry], max_thumb_size: int = 180, columns: int = 4) -> str | None:
    thumbs: list[tuple[DesktopEntry, Image.Image]] = []
    for entry in entries:
        try:
            with Image.open(entry.path) as image:
                thumb = ImageOps.exif_transpose(image).convert("RGB")
                thumb.thumbnail((max_thumb_size, max_thumb_size), Image.Resampling.LANCZOS)
                thumbs.append((entry, thumb.copy()))
        except Exception:
            continue
    if not thumbs:
        return None

    font_height = 26
    padding = 12
    cell_width = max_thumb_size + padding * 2
    cell_height = max_thumb_size + font_height + padding * 2
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (cell_width * columns, cell_height * rows), "white")
    draw = ImageDraw.Draw(sheet)

    for index, (entry, thumb) in enumerate(thumbs):
        row, col = divmod(index, columns)
        x = col * cell_width
        y = row * cell_height
        draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1), outline=(210, 210, 210))
        label = f"{entry.id}"
        draw.text((x + padding, y + padding), label, fill=(20, 20, 20))
        image_x = x + padding + (max_thumb_size - thumb.width) // 2
        image_y = y + padding + font_height + (max_thumb_size - thumb.height) // 2
        sheet.paste(thumb, (image_x, image_y))

    buffer = BytesIO()
    sheet.save(buffer, format="JPEG", quality=86, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def capture_desktop_data_uri(max_width: int = 1280, jpeg_quality: int = 75) -> str:
    try:
        from PIL import ImageGrab

        screenshot = ImageGrab.grab()
        if not isinstance(screenshot, Image.Image):
            return ""
        image = screenshot.convert("RGB")
        if image.width > max_width:
            target_height = max(1, int(image.height * max_width / image.width))
            image = image.resize((max_width, target_height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:
        print(f"Desktop screenshot capture failed: {type(exc).__name__}: {exc}")
        return ""


def metadata_for_entries(entries: list[DesktopEntry]) -> list[dict[str, Any]]:
    return [{"id": entry.id, "name": entry.name, "extension": entry.suffix or ""} for entry in entries]


def selected_entries(entries: list[DesktopEntry], ids: list[Any]) -> list[DesktopEntry]:
    id_set: set[int] = set()
    for value in ids:
        try:
            id_set.add(int(value))
        except (TypeError, ValueError):
            continue
    return [entry for entry in entries if entry.id in id_set]


def move_files(desktop_root: Path, moves: list[dict[str, Any]]) -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    for move in moves:
        source = _safe_direct_child(desktop_root, str(move.get("source") or ""))
        category = str(move.get("category") or "").strip()
        if category not in ALLOWED_CATEGORY_FOLDERS:
            continue
        if source is None or not source.exists() or not source.is_file():
            continue
        target_dir = desktop_root / category
        target_dir.mkdir(exist_ok=True)
        target = _dedupe_path(target_dir / source.name)
        shutil.move(str(source), str(target))
        moved.append((source, target))
    return moved


def trash_files(paths: list[str]) -> list[Path]:
    trashed: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        if not path.exists() or not path.is_file():
            continue
        _send_to_trash(path)
        trashed.append(path)
    return trashed


def google_search_url(query: str) -> str:
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("搜索内容不能为空。")
    return f"https://www.google.com/search?q={quote_plus(cleaned)}"


def open_google_search(query: str) -> str:
    url = google_search_url(query)
    if sys.platform == "win32":
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", f'Start-Process chrome "{url}"'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    elif sys.platform == "darwin":
        subprocess.run(["open", url], check=True)
    else:
        raise RuntimeError("当前平台暂不支持打开网页工具。")
    return url


def _is_allowed_direct_file(desktop_root: Path, path: Path) -> bool:
    if path.name.startswith(".") or path.name in IGNORED_NAMES:
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.parent == desktop_root and resolved.is_file()


def _safe_direct_child(desktop_root: Path, name: str) -> Path | None:
    if not name or "/" in name or "\\" in name:
        return None
    candidate = (desktop_root / name).resolve()
    if candidate.parent != desktop_root:
        return None
    return candidate


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为重名文件生成安全目标路径: {path.name}")


def _send_to_trash(path: Path) -> None:
    try:
        from send2trash import send2trash

        send2trash(str(path))
        return
    except ImportError:
        pass

    if os.name == "posix":
        trash_dir = Path.home() / ".Trash"
        trash_dir.mkdir(exist_ok=True)
        shutil.move(str(path), str(_dedupe_path(trash_dir / path.name)))
        return
    raise RuntimeError("缺少 send2trash，且当前平台没有可用的废纸篓实现。")
