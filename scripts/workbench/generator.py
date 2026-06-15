from __future__ import annotations

import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from Murasame.paths import copy_seed_file, user_data_path
from scripts.character_traits import format_dimension_guidance, normalize_dimensions
from scripts.profile import CharacterProfile as GeneratedCharacterProfile
from scripts.workbench.constants import API_BASE_URL, DESCRIPTION_MODEL, EMOTION_SPECS, IMAGE_MODEL, REFERENCE_EMOTIONS
from scripts.workbench.image_processing import make_desktop_pet_standee


class ApiKeyNotFoundError(RuntimeError):
    pass


class LocalCharacterGenerator:
    def __init__(self, api_key_path: Path | None = None, timeout: int = 180) -> None:
        self.api_key_path = api_key_path or user_data_path("apikey.md")
        self.timeout = timeout
        self.api_key = self._load_api_key()

    def generate(
        self,
        user_name: str,
        appearance_traits: list[str],
        personality_traits: list[str],
        identity_traits: list[str],
        style: str,
        personality_dimensions: dict[str, int] | None = None,
        appearance_style_dimensions: dict[str, int] | None = None,
    ) -> GeneratedCharacterProfile:
        personality_dimensions = normalize_dimensions(personality_dimensions)
        appearance_style_dimensions = normalize_dimensions(appearance_style_dimensions)
        profile_json = self._generate_description(
            user_name=user_name,
            appearance_traits=appearance_traits,
            personality_traits=personality_traits,
            identity_traits=identity_traits,
            personality_dimensions=personality_dimensions,
            appearance_style_dimensions=appearance_style_dimensions,
        )
        emotion_images = self._generate_emotion_images(
            profile_json,
            appearance_traits,
            personality_traits,
            identity_traits,
            style,
            personality_dimensions,
            appearance_style_dimensions,
        )
        display_image_base64 = emotion_images["happy"]["display_image_base64"]
        return GeneratedCharacterProfile(
            character_id=f"local-{uuid.uuid4().hex[:12]}",
            name=profile_json.get("name") or "小雨",
            persona=profile_json.get("persona") or "",
            greeting=profile_json.get("greeting") or f"{user_name}，今天也一起努力吧。",
            display_image_base64=display_image_base64,
            emotion_images=emotion_images,
            appearance_traits=appearance_traits,
            personality_traits=personality_traits,
            identity_traits=identity_traits,
            personality_dimensions=personality_dimensions,
            appearance_style_dimensions=appearance_style_dimensions,
            style=style,
        )

    def _load_api_key(self) -> str:
        env_key = os.environ.get("API_KEY")
        if env_key:
            return env_key.strip().strip('"')
        api_key_path = self.api_key_path if self.api_key_path.exists() else copy_seed_file("apikey.md")
        if not api_key_path.exists():
            raise ApiKeyNotFoundError(f"找不到 API key 文件，请创建 {self.api_key_path}")
        for line in api_key_path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value:
                continue
            if value.startswith("export API_KEY="):
                match = re.search(r'API_KEY=["\']?([^"\']+)["\']?', value)
                if match and "<" not in match.group(1):
                    return match.group(1).strip()
                continue
            if value.startswith(("curl ", "--", "{", "}", '"', "#", "export ")):
                continue
            if len(value) > 24 and " " not in value:
                return value
        raise ApiKeyNotFoundError(f"{api_key_path} 中没有找到可用 API_KEY")

    def _generate_description(
        self,
        user_name: str,
        appearance_traits: list[str],
        personality_traits: list[str],
        identity_traits: list[str],
        personality_dimensions: dict[str, int] | None = None,
        appearance_style_dimensions: dict[str, int] | None = None,
    ) -> dict:
        personality_guidance = format_dimension_guidance(personality_dimensions, "性格")
        appearance_style_guidance = format_dimension_guidance(appearance_style_dimensions, "外貌风格")
        identity_line = f"身份设定：{'、'.join(identity_traits)}" if identity_traits else ""
        prompt = f"""
请根据下面选项生成一个日常系二次元桌宠角色设定。不要使用奇幻、战斗、恐怖、病娇或成人向设定。

用户称呼：{user_name}
外貌设定：{"、".join(appearance_traits)}
性格设定：{"、".join(personality_traits)}
{identity_line}
{appearance_style_guidance}
{personality_guidance}

上面的创作取向只用于决定哪些特质更突出。生成的 name、persona、greeting 中禁止提到任何控制信息，不要出现“权重、强度、等级、维度、数值、分数、几分、五分”等表述，也不要写“带着几分某性格”。

请只输出 JSON，不要 Markdown，不要解释。JSON 字段：
{{
  "name": "2-4 个中文字符的角色名",
  "persona": "120-180 字中文人设，包含外貌、性格、与用户的相处方式",
  "greeting": "一句自然可爱的中文初始问候"
}}
""".strip()
        response = requests.post(
            f"{API_BASE_URL}/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DESCRIPTION_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": 0.9,
                "top_p": 1,
                "presence_penalty": 0,
                "frequency_penalty": 0,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return self._parse_json_object(content)

    def _parse_json_object(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if not match:
                raise
            return json.loads(match.group(0))

    def _build_image_prompt(
        self,
        profile_json: dict,
        appearance_traits: list[str],
        personality_traits: list[str],
        identity_traits: list[str],
        style: str,
        emotion_label: str,
        emotion_prompt: str,
        personality_dimensions: dict[str, int] | None = None,
        appearance_style_dimensions: dict[str, int] | None = None,
    ) -> str:
        personality_guidance = format_dimension_guidance(personality_dimensions, "性格")
        appearance_style_guidance = format_dimension_guidance(appearance_style_dimensions, "外貌风格")
        identity_line = f"身份：{'、'.join(identity_traits)}" if identity_traits else ""
        return f"""
生成一张日常系二次元桌宠角色立绘，纯白色背景，单人，全身或膝上构图，干净线稿，柔和上色，适合桌面宠物窗口展示。

角色名：{profile_json.get("name", "角色")}
人设：{profile_json.get("persona", "")}
外貌：{"、".join(appearance_traits)}
性格：{"、".join(personality_traits)}
{identity_line}
画风：{style}
{appearance_style_guidance}
{personality_guidance}
当前情感：{emotion_label}。表情要求：{emotion_prompt}。

要求：可爱、清爽、日常服装。创作取向只用于画面取舍，不要在画面中加入文字、数字、标签或维度图。背景必须是干净纯白色，不要透明背景、不要棋盘格、不要渐变背景、不要场景背景、不要阴影底板、不要文字、水印、边框，不要暴露或成人向内容。
""".strip()

    def _build_reference_emotion_prompt(self, emotion_label: str, emotion_prompt: str) -> str:
        return f"""
请严格参考输入图片生成同一个角色的纯白色背景桌宠立绘，只改变表情和非常轻微的姿势。背景必须保持干净纯白色，不要透明背景或棋盘格。

当前情感：{emotion_label}。表情要求：{emotion_prompt}。

必须保持完全一致：服装款式、服装颜色、发型、发色、瞳色、配饰、年龄感、体型、画风、线稿粗细、上色方式、整体比例。
优先复制参考图中的身体、服装、头发和配饰，只重绘脸部表情；如果需要动作变化，只允许非常轻微的头部角度、手部小动作或身体倾斜。
允许变化：眉眼、嘴型、脸红、眼泪、头部角度、手部小动作、身体轻微倾斜。
禁止变化：换衣服、增加或删除外套/领结/发饰/袜子/鞋子、改变发长、改变发色、改变角色年龄、改变构图比例、增加场景背景、增加棋盘格、增加文字、水印、阴影底板或边框。
""".strip()

    def _generate_emotion_images(
        self,
        profile_json: dict,
        appearance_traits: list[str],
        personality_traits: list[str],
        identity_traits: list[str],
        style: str,
        personality_dimensions: dict[str, int] | None = None,
        appearance_style_dimensions: dict[str, int] | None = None,
    ) -> dict:
        happy_prompt = self._build_image_prompt(
            profile_json,
            appearance_traits,
            personality_traits,
            identity_traits,
            style,
            "happy",
            EMOTION_SPECS["happy"],
            personality_dimensions,
            appearance_style_dimensions,
        )
        happy_source_image = self._generate_source_image(happy_prompt)
        happy_image = make_desktop_pet_standee(happy_source_image)
        result: dict[str, dict[str, str]] = {
            "happy": {"display_image_base64": happy_image},
        }

        with ThreadPoolExecutor(max_workers=len(REFERENCE_EMOTIONS)) as executor:
            futures = {
                executor.submit(
                    self._generate_reference_standee,
                    self._build_reference_emotion_prompt(
                        emotion,
                        emotion_prompt,
                    ),
                    happy_source_image,
                ): emotion
                for emotion, emotion_prompt in EMOTION_SPECS.items()
                if emotion in REFERENCE_EMOTIONS
            }
            for future in as_completed(futures):
                emotion = futures[future]
                try:
                    result[emotion] = {"display_image_base64": future.result()}
                except Exception as exc:
                    print(f"Emotion image generation failed for {emotion}; using happy image fallback: {exc}")
                    result[emotion] = {"display_image_base64": happy_image}
        return result

    def _generate_image(self, image_prompt: str, reference_image_base64: str | None = None) -> str:
        return make_desktop_pet_standee(self._generate_source_image(image_prompt, reference_image_base64))

    def _generate_reference_standee(self, image_prompt: str, reference_image_base64: str) -> str:
        return make_desktop_pet_standee(self._generate_source_image(image_prompt, reference_image_base64))

    def _generate_source_image(self, image_prompt: str, reference_image_base64: str | None = None) -> str:
        parts: list[dict] = [{"text": image_prompt}]
        if reference_image_base64:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": self._guess_image_mime_type(reference_image_base64),
                        "data": reference_image_base64,
                    }
                }
            )
        response = requests.post(
            f"{API_BASE_URL}/api/v1beta/models/{IMAGE_MODEL}:generateContent?alt=sse",
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "contents": [
                    {
                        "parts": parts
                    }
                ]
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        image_base64 = self._extract_image_base64_from_generate_content(response.text)
        if not image_base64:
            raise RuntimeError(f"图片接口没有返回 inline image data: {self._summarize_image_response(response.text)}")
        return image_base64

    def _summarize_image_response(self, text: str) -> str:
        snippets = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line == "[DONE]":
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                snippets.append(line[:300])
                continue
            summary = self._find_response_summary(obj)
            if summary:
                snippets.append(summary)
        return " | ".join(snippets[:3]) or text[:500] or "empty response"

    def _find_response_summary(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("finishReason", "finish_reason", "blockReason", "block_reason", "message", "text"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return f"{key}={item.strip()[:240]}"
            for child in value.values():
                found = self._find_response_summary(child)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_response_summary(item)
                if found:
                    return found
        return None

    def _guess_image_mime_type(self, image_base64: str) -> str:
        if image_base64.startswith("/9j/"):
            return "image/jpeg"
        if image_base64.startswith("iVBORw0KGgo"):
            return "image/png"
        if image_base64.startswith("UklGR"):
            return "image/webp"
        return "image/png"

    def _extract_image_base64_from_generate_content(self, text: str) -> str | None:
        json_objects: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                continue
            try:
                json_objects.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if not json_objects:
            try:
                json_objects.append(json.loads(text))
            except json.JSONDecodeError:
                return None

        for obj in json_objects:
            found = self._find_inline_image(obj)
            if found:
                return found
        return None

    def _find_inline_image(self, value: Any) -> str | None:
        if isinstance(value, dict):
            if "inlineData" in value and isinstance(value["inlineData"], dict):
                data = value["inlineData"].get("data")
                if data:
                    return data
            if "inline_data" in value and isinstance(value["inline_data"], dict):
                data = value["inline_data"].get("data")
                if data:
                    return data
            for child in value.values():
                found = self._find_inline_image(child)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_inline_image(item)
                if found:
                    return found
        return None

    def _normalize_dimensions(self, dimensions: Any) -> dict[str, int]:
        return normalize_dimensions(dimensions)

    def _format_dimension_guidance(self, dimensions: dict[str, int] | None, label: str) -> str:
        return format_dimension_guidance(dimensions, label)
