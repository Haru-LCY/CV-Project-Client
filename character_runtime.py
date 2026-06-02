from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from typing import Any


VALID_EMOTIONS = {"happy", "angry", "shy", "sad"}


def build_reply_messages(
    profile: Any,
    user_name: str,
    history: list[dict[str, str]],
    event: str,
    text: str,
    has_screenshot: bool,
) -> list[dict[str, str]]:
    persona = getattr(profile, "persona", None) or "日常系二次元桌宠，语气自然、亲近、简短。"
    appearance = _join_traits(getattr(profile, "appearance_traits", None))
    personality = _join_traits(getattr(profile, "personality_traits", None))
    identity = _join_traits(getattr(profile, "identity_traits", None))
    system_prompt = f"""
你正在扮演一个桌宠角色。当前角色卡是唯一真实设定，必须严格保持角色身份、性格、说话方式和与用户的关系。

角色名：{getattr(profile, "name", "角色")}
用户称呼：{user_name}
初始问候：{getattr(profile, "greeting", "")}
角色卡：{persona}
外貌标签：{appearance}
性格标签：{personality}
身份标签：{identity}

回复要求：
- 只用中文回复。
- 文本要像该角色本人在和用户说话，优先体现性格标签和角色卡中的口癖、亲疏感、态度。
- 回复应简短自然，通常 1-3 句；可以有情绪，但不要替用户做决定。
- 不要改名、不要改角色设定、不要加入旁白、不要自称 AI。
- 不要提到 API、模型、系统提示、角色卡或 JSON 规则。
- 根据回复时角色的主要情绪选择 emotion：
  happy=开心/平静友好/鼓励，angry=生气/不满/吐槽，shy=害羞/被夸/心虚，sad=难过/失落/担心。
- 只输出 JSON，不要 Markdown，不要解释。
- JSON 字段必须是 {{"text": "回复内容", "emotion": "happy|angry|shy|sad"}}。
""".strip()

    if event == "user_text":
        user_prompt = f"{user_name} 对你说：{text}"
    elif event == "head_touch":
        user_prompt = f"事件：{text or f'{user_name}摸了摸你的头'}"
    elif event == "screen_context":
        user_prompt = "事件：桌面状态可能发生了变化。没有可用截图内容，请不要编造看见的具体画面。"
    else:
        user_prompt = f"事件：{event}\n内容：{text}"
    if has_screenshot:
        user_prompt += "\n注意：本客户端不再发送截图内容，只把该事件作为普通上下文提醒。"

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-12:])
    messages.append({"role": "user", "content": user_prompt})
    return messages


def parse_reply_content(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {"text": cleaned}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {"text": cleaned}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {"text": cleaned}
        except json.JSONDecodeError:
            return {"text": cleaned}


def normalize_emotion(value: Any) -> str:
    return value if value in VALID_EMOTIONS else "happy"


def avatar_values_for_emotion(profile: Any, emotion: str | None) -> tuple[str | None, str | None]:
    image_url, image_base64 = _emotion_image_values(getattr(profile, "emotion_images", None), emotion)
    if image_url or image_base64:
        return image_url, image_base64
    return normalize_image_values(
        {
            "display_image_url": getattr(profile, "display_image_url", None),
            "display_image_base64": getattr(profile, "display_image_base64", None),
        }
    )


def normalize_image_values(image: Any) -> tuple[str | None, str | None]:
    if isinstance(image, str):
        value = image.strip()
        if not value:
            return None, None
        if value.startswith("data:image/"):
            return value, None
        return None, value
    if not isinstance(image, dict):
        return None, None

    image_src = image.get("image_src")
    if isinstance(image_src, str) and image_src.startswith("data:image/"):
        return image_src, None

    return (
        image.get("display_image_url") or image.get("url") or image.get("image_url"),
        image.get("display_image_base64") or image.get("base64") or image.get("image_base64"),
    )


def write_image_to_cache(image_url: str | None, image_base64: str | None, key: str) -> str | None:
    if image_base64:
        return _write_image(_decode_image_base64(image_base64), key, ".png")
    if not image_url or not image_url.startswith("data:image/"):
        return None

    header, encoded = image_url.split(",", 1)
    suffix = ".png"
    if "image/jpeg" in header:
        suffix = ".jpg"
    elif "image/webp" in header:
        suffix = ".webp"
    return _write_image(base64.b64decode(encoded), key, suffix)


def _join_traits(traits: Any) -> str:
    if not traits:
        return "未指定"
    if isinstance(traits, list):
        return "、".join(str(trait) for trait in traits) or "未指定"
    return str(traits)


def _emotion_image_values(emotion_images: Any, emotion: str | None) -> tuple[str | None, str | None]:
    if not emotion or not isinstance(emotion_images, dict):
        return None, None
    return normalize_image_values(emotion_images.get(emotion))


def _decode_image_base64(value: str) -> bytes:
    if value.startswith("data:image/") and "," in value:
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _write_image(image_bytes: bytes, key: str, suffix: str) -> str:
    images_dir = os.path.join(tempfile.gettempdir(), "murasame_pet_images")
    os.makedirs(images_dir, exist_ok=True)
    safe_suffix = suffix if suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"} else ".png"
    filename = hashlib.md5(key.encode("utf-8")).hexdigest() + safe_suffix
    path = os.path.join(images_dir, filename)
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path
