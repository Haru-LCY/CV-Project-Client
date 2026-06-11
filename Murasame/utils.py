import json
import os


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
    with open("./config.json", "r", encoding="utf-8") as f:
        return _merge_defaults(DEFAULT_CONFIG, json.load(f))


def save_config(config: dict) -> None:
    path = "./config.json"
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
        f.write("\n")
    os.replace(tmp_path, path)
