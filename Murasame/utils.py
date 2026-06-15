import json
import os

from Murasame.paths import copy_seed_file, resolve_user_path, user_data_path


DEFAULT_CONFIG = {
    "enable_vl": True,
    "client": {
        "session_id": "local-user",
        "timeout_seconds": 120,
    },
    "vl": {
        "model": "qwen3-vl-flash",
        "interval_seconds": 30,
        "max_width": 1280,
        "jpeg_quality": 75,
    },
    "display": {
        "preset": "balanced",
        "custom": {
            "visible_ratio": 0.4,
            "text_x_offset": 140,
            "text_y_offset": 20,
        },
    },
    "memory": {
        "enabled": True,
        "provider": "mem0_local",
        "user_id": None,
        "top_k": 5,
        "store_screenshots": False,
        "desktop_summary_enabled": True,
        "storage_path": ".memory/local_memory.jsonl",
        "mem0": {
            "history_db_path": ".memory/mem0_history.db",
            "vector_path": ".memory/qdrant",
            "llm": None,
            "embedder": None,
        },
    },
    "character": {
        "character_id": None,
        "name": "丛雨",
        "persona": "",
        "greeting": "主人，你好呀！",
        "display_image_url": None,
        "display_image_base64": None,
        "expression_layers": [1717, 1475, 1261],
        "fgimage_target": "ムラサメb",
        "emotion_images": None,
        "appearance_traits": None,
        "personality_traits": None,
        "identity_traits": None,
        "style": None,
        "user_name": "用户",
        "auto_open_creator": True,
    },
}


def _merge_defaults(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_defaults(result[key], value)
        else:
            result[key] = value
    return result


def get_config() -> dict:
    path = copy_seed_file("config.json")
    if not path.exists():
        save_config(DEFAULT_CONFIG)
        path = user_data_path("config.json")
    with path.open("r", encoding="utf-8") as f:
        config = _merge_defaults(DEFAULT_CONFIG, json.load(f))
    return _resolve_config_paths(config)


def save_config(config: dict) -> None:
    path = user_data_path("config.json")
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp_path, path)


def _resolve_config_paths(config: dict) -> dict:
    memory = config.setdefault("memory", {})
    storage_path = memory.get("storage_path") or DEFAULT_CONFIG["memory"]["storage_path"]
    memory["storage_path"] = str(resolve_user_path(storage_path))

    mem0 = memory.setdefault("mem0", {})
    for key in ("history_db_path", "vector_path"):
        value = mem0.get(key)
        if value:
            mem0[key] = str(resolve_user_path(value))
    return config
