from __future__ import annotations

import base64
import json
import os
import re
import traceback
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image, ImageFilter, ImageOps
from PyQt5.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QDialog, QMessageBox, QVBoxLayout

from Murasame.paths import resource_path, seed_character_cards, user_data_path


API_BASE_URL = "https://maas-openapi.wanjiedata.com"
DESCRIPTION_MODEL = "deepseek-v4-flash"
IMAGE_MODEL = "gemini-3.1-flash-image-preview"
EMOTION_SPECS = {
    "happy": "开心，明亮笑容，眼神轻快，像刚刚收到用户夸奖",
    "angry": "生气，轻微鼓脸或皱眉，克制可爱，不要激烈攻击姿态",
    "shy": "害羞，脸红，视线稍微移开，动作内敛",
    "sad": "伤心，低落难过，眼神湿润但不要夸张哭喊",
}
REFERENCE_EMOTIONS = ("angry", "shy", "sad")


@dataclass
class GeneratedCharacterProfile:
    character_id: str | None
    name: str
    persona: str
    greeting: str
    display_image_url: str | None = None
    display_image_base64: str | None = None
    expression_layers: list[int] | None = None
    fgimage_target: str = "ムラサメb"
    emotion_images: dict | None = None
    appearance_traits: list[str] | None = None
    personality_traits: list[str] | None = None
    identity_traits: list[str] | None = None
    personality_dimensions: dict[str, int] | None = None
    appearance_style_dimensions: dict[str, int] | None = None
    style: str | None = None


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
        personality_dimensions = self._normalize_dimensions(personality_dimensions)
        appearance_style_dimensions = self._normalize_dimensions(appearance_style_dimensions)
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
        candidate_paths = [self.api_key_path]
        source_api_key_path = resource_path("apikey.md")
        if source_api_key_path.exists() and source_api_key_path not in candidate_paths:
            candidate_paths.append(source_api_key_path)

        api_key_path = next((path for path in candidate_paths if path.exists()), None)
        if api_key_path is None:
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
        personality_guidance = self._format_dimension_guidance(personality_dimensions, "性格")
        appearance_style_guidance = self._format_dimension_guidance(appearance_style_dimensions, "外貌风格")
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
        personality_guidance = self._format_dimension_guidance(personality_dimensions, "性格")
        appearance_style_guidance = self._format_dimension_guidance(appearance_style_dimensions, "外貌风格")
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
        happy_image = self._make_desktop_pet_standee(happy_source_image)
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

    def _normalize_dimensions(self, dimensions: Any) -> dict[str, int]:
        if not isinstance(dimensions, dict):
            return {}
        result: dict[str, int] = {}
        for trait, strength in dimensions.items():
            trait_text = str(trait).strip()
            if not trait_text:
                continue
            try:
                strength_value = int(strength)
            except (TypeError, ValueError):
                strength_value = 3
            result[trait_text] = min(5, max(1, strength_value))
        return result

    def _format_dimension_guidance(self, dimensions: dict[str, int] | None, label: str) -> str:
        if not dimensions:
            return ""
        buckets = {
            1: "只作为很轻的底色",
            2: "作为辅助倾向",
            3: "自然体现",
            4: "明显体现",
            5: "作为主要取向",
        }
        lines = [f"{label}创作取向："]
        for trait, strength in dimensions.items():
            lines.append(f"- {trait}：{buckets.get(strength, '自然体现')}")
        return "\n".join(lines)

    def _generate_image(self, image_prompt: str, reference_image_base64: str | None = None) -> str:
        return self._make_desktop_pet_standee(self._generate_source_image(image_prompt, reference_image_base64))

    def _generate_reference_standee(self, image_prompt: str, reference_image_base64: str) -> str:
        return self._make_desktop_pet_standee(self._generate_source_image(image_prompt, reference_image_base64))

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

    def _make_desktop_pet_standee(self, image_base64: str) -> str:
        image_bytes = base64.b64decode(image_base64)
        with Image.open(BytesIO(image_bytes)) as image:
            rgba = image.convert("RGBA")

        alpha = self._white_background_alpha(rgba)
        character = rgba.copy()
        character.putalpha(alpha)
        character = self._crop_to_alpha(character, padding=28)
        outlined = self._add_standee_outline(character)
        return self._encode_png_base64(outlined)

    def _white_background_alpha(self, image: Image.Image) -> Image.Image:
        rgb = image.convert("RGB")
        pixels = rgb.load()
        width, height = rgb.size
        background = Image.new("L", rgb.size, 0)
        background_pixels = background.load()
        visited: set[tuple[int, int]] = set()
        queue: deque[tuple[int, int]] = deque()

        for x in range(width):
            queue.append((x, 0))
            queue.append((x, height - 1))
        for y in range(height):
            queue.append((0, y))
            queue.append((width - 1, y))

        while queue:
            x, y = queue.popleft()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            if not self._is_background_white(pixels[x, y]):
                continue
            background_pixels[x, y] = 255
            if x > 0:
                queue.append((x - 1, y))
            if x + 1 < width:
                queue.append((x + 1, y))
            if y > 0:
                queue.append((x, y - 1))
            if y + 1 < height:
                queue.append((x, y + 1))

        background = background.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.0))
        return ImageOps.invert(background)

    def _is_background_white(self, color: tuple[int, int, int]) -> bool:
        r, g, b = color
        return min(r, g, b) >= 235 and max(r, g, b) - min(r, g, b) <= 42

    def _crop_to_alpha(self, image: Image.Image, padding: int) -> Image.Image:
        bbox = image.getchannel("A").getbbox()
        if not bbox:
            return image
        left = max(0, bbox[0] - padding)
        top = max(0, bbox[1] - padding)
        right = min(image.width, bbox[2] + padding)
        bottom = min(image.height, bbox[3] + padding)
        return image.crop((left, top, right, bottom))

    def _add_standee_outline(self, character: Image.Image) -> Image.Image:
        alpha = character.getchannel("A")
        outline_outer = alpha.filter(ImageFilter.MaxFilter(19)).filter(ImageFilter.GaussianBlur(1.6))
        outline_inner = alpha.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(0.8))

        padding = 18
        canvas_size = (character.width + padding * 2, character.height + padding * 2)
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        outer_layer = Image.new("RGBA", canvas_size, (255, 255, 255, 0))
        inner_layer = Image.new("RGBA", canvas_size, (255, 236, 246, 0))
        shadow_layer = Image.new("RGBA", canvas_size, (105, 78, 96, 0))

        outer_alpha = Image.new("L", canvas_size, 0)
        inner_alpha = Image.new("L", canvas_size, 0)
        shadow_alpha = Image.new("L", canvas_size, 0)
        outer_alpha.paste(outline_outer, (padding, padding))
        inner_alpha.paste(outline_inner, (padding, padding))
        shadow_alpha.paste(alpha.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(4.0)), (padding + 3, padding + 5))

        outer_layer.putalpha(outer_alpha.point(lambda value: min(255, int(value * 0.96))))
        inner_layer.putalpha(inner_alpha.point(lambda value: min(210, int(value * 0.72))))
        shadow_layer.putalpha(shadow_alpha.point(lambda value: min(80, int(value * 0.24))))

        canvas.alpha_composite(shadow_layer)
        canvas.alpha_composite(outer_layer)
        canvas.alpha_composite(inner_layer)
        canvas.alpha_composite(character, (padding, padding))
        return canvas

    def _encode_png_base64(self, image: Image.Image) -> str:
        output = BytesIO()
        image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("utf-8")

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


class CharacterGenerationWorker(QThread):
    finished = pyqtSignal(object, object)

    def __init__(
        self,
        api_client: Any,
        user_name: str,
        appearance_traits: list[str],
        personality_traits: list[str],
        identity_traits: list[str],
        style: str,
        personality_dimensions: dict[str, int] | None = None,
        appearance_style_dimensions: dict[str, int] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.user_name = user_name
        self.appearance_traits = appearance_traits
        self.personality_traits = personality_traits
        self.identity_traits = identity_traits
        self.style = style
        self.personality_dimensions = personality_dimensions or {}
        self.appearance_style_dimensions = appearance_style_dimensions or {}

    def run(self) -> None:
        try:
            profile = LocalCharacterGenerator().generate(
                user_name=self.user_name,
                appearance_traits=self.appearance_traits,
                personality_traits=self.personality_traits,
                identity_traits=self.identity_traits,
                style=self.style,
                personality_dimensions=self.personality_dimensions,
                appearance_style_dimensions=self.appearance_style_dimensions,
            )
            self.finished.emit(profile, None)
        except Exception as exc:
            traceback.print_exc()
            self.finished.emit(None, f"API 生成失败：{type(exc).__name__}: {exc}")


class CharacterWorkbenchBridge(QObject):
    generationStarted = pyqtSignal()
    generationFinished = pyqtSignal(str)
    generationFailed = pyqtSignal(str)
    previewStale = pyqtSignal()
    cardSaved = pyqtSignal(str)
    cardSaveFailed = pyqtSignal(str)

    def __init__(
        self,
        dialog: "CharacterCreatorDialog",
        options: dict,
        api_client: Any,
        default_options: dict,
        default_user_name: str,
    ) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.options = options
        self.api_client = api_client
        self.default_options = default_options
        self.default_user_name = default_user_name
        self.generation_worker: CharacterGenerationWorker | None = None

    @pyqtSlot(result=str)
    def getInitialState(self) -> str:
        defaults = self.options.get("defaults") or self.default_options.get("defaults", {})
        state = {
            "options": self.options,
            "defaults": defaults,
            "userName": self.api_client.user_name or self.default_user_name,
            "historyCards": self._history_card_summaries(),
        }
        return json.dumps(state, ensure_ascii=False)

    @pyqtSlot(result=str)
    def getHistoryCards(self) -> str:
        return json.dumps(self._history_card_summaries(), ensure_ascii=False)

    @pyqtSlot(str)
    def startGeneration(self, payload_json: str) -> None:
        if self.generation_worker is not None:
            return
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            self.generationFailed.emit(f"参数解析失败：{exc}")
            return

        self.dialog.preview_profile = None
        self.dialog.preview_is_current = False
        self.dialog.preview_user_name = payload.get("user_name") or self.default_user_name
        self.generationStarted.emit()
        raw_appearance_traits = payload.get("appearance_traits") or self.default_options["defaults"]["appearance_traits"]
        raw_personality_traits = (
            payload.get("personality_traits") or self.default_options["defaults"]["personality_traits"]
        )
        appearance_traits = self._clean_traits(raw_appearance_traits)
        personality_traits = self._clean_traits(raw_personality_traits)
        personality_dimensions = self._normalize_dimensions(payload.get("personality_dimensions"))
        if not personality_dimensions:
            personality_dimensions = self._dimensions_from_legacy_traits(raw_personality_traits)
        appearance_style_dimensions = self._normalize_dimensions(payload.get("appearance_style_dimensions"))

        self.generation_worker = CharacterGenerationWorker(
            api_client=self.api_client,
            user_name=self.dialog.preview_user_name,
            appearance_traits=appearance_traits,
            personality_traits=personality_traits,
            identity_traits=payload.get("identity_traits") or [],
            style=payload.get("style") or self.default_options["defaults"]["style"],
            personality_dimensions=personality_dimensions,
            appearance_style_dimensions=appearance_style_dimensions,
            parent=self,
        )
        self.generation_worker.finished.connect(self.on_generation_finished)
        self.generation_worker.start()

    def on_generation_finished(self, profile: Any, error: str | None) -> None:
        self.generation_worker = None
        if error or profile is None:
            self.dialog.preview_profile = None
            self.dialog.preview_is_current = False
            self.generationFailed.emit(error or "unknown error")
            return

        self.dialog.preview_profile = profile
        self.dialog.preview_is_current = True
        self.generationFinished.emit(json.dumps(self._profile_payload(profile), ensure_ascii=False))

    @pyqtSlot()
    def markStale(self) -> None:
        if self.dialog.preview_profile is None:
            return
        self.dialog.preview_is_current = False
        self.previewStale.emit()

    @pyqtSlot()
    def applyCharacter(self) -> None:
        if self.dialog.preview_profile is None or not self.dialog.preview_is_current:
            self.generationFailed.emit("请先生成预览，再应用角色。")
            return
        self.dialog.accept()

    @pyqtSlot()
    def saveCharacterCard(self) -> None:
        if self.dialog.preview_profile is None or not self.dialog.preview_is_current:
            self.cardSaveFailed.emit("请先生成预览，再保存角色卡。")
            return
        try:
            cards_dir = self._cards_dir()
            cards_dir.mkdir(parents=True, exist_ok=True)
            profile = self.dialog.preview_profile
            filename = self._safe_card_filename(getattr(profile, "name", None), getattr(profile, "character_id", None))
            path = cards_dir / filename
            with path.open("w", encoding="utf-8") as f:
                json.dump(self._character_card_payload(profile), f, ensure_ascii=False, indent=4)
                f.write("\n")
            self.cardSaved.emit(str(path))
        except Exception as exc:
            traceback.print_exc()
            self.cardSaveFailed.emit(f"{type(exc).__name__}: {exc}")

    @pyqtSlot(str)
    def loadHistoryCard(self, path: str) -> None:
        try:
            card_path = self._resolve_card_path(path)
            with card_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            profile = self._profile_from_card(data)
            self._upgrade_card_dimensions(card_path, profile)
            self.dialog.preview_profile = profile
            self.dialog.preview_is_current = True
            self.dialog.preview_user_name = self.api_client.user_name or self.default_user_name
            self.generationFinished.emit(json.dumps(self._profile_payload(profile), ensure_ascii=False))
        except Exception as exc:
            traceback.print_exc()
            self.generationFailed.emit(f"加载历史角色失败：{type(exc).__name__}: {exc}")

    @pyqtSlot()
    def cancel(self) -> None:
        self.dialog.reject()

    def _profile_payload(self, profile: Any) -> dict:
        return {
            "character_id": profile.character_id,
            "name": profile.name,
            "persona": profile.persona,
            "greeting": profile.greeting,
            "image_src": self._profile_image_src(profile),
            "emotion_images": self._emotion_images_payload(profile),
            "personality_dimensions": getattr(profile, "personality_dimensions", None) or {},
            "appearance_style_dimensions": getattr(profile, "appearance_style_dimensions", None) or {},
        }

    def _character_card_payload(self, profile: Any) -> dict:
        return {
            "schema_version": 2,
            "character_id": getattr(profile, "character_id", None),
            "name": getattr(profile, "name", ""),
            "persona": getattr(profile, "persona", ""),
            "greeting": getattr(profile, "greeting", ""),
            "fgimage_target": getattr(profile, "fgimage_target", "ムラサメb"),
            "appearance_traits": getattr(profile, "appearance_traits", None) or [],
            "personality_traits": getattr(profile, "personality_traits", None) or [],
            "identity_traits": getattr(profile, "identity_traits", None) or [],
            "personality_dimensions": getattr(profile, "personality_dimensions", None) or {},
            "appearance_style_dimensions": getattr(profile, "appearance_style_dimensions", None) or {},
            "trait_dimensions": {
                "personality": getattr(profile, "personality_dimensions", None) or {},
                "appearance_style": getattr(profile, "appearance_style_dimensions", None) or {},
            },
            "style": getattr(profile, "style", None),
            "display_image_base64": getattr(profile, "display_image_base64", None),
            "emotion_images": getattr(profile, "emotion_images", None) or {},
        }

    def _safe_card_filename(self, name: str | None, character_id: str | None) -> str:
        safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name or "character").strip("._")
        safe_id = re.sub(r"[^\w.-]+", "_", character_id or uuid.uuid4().hex[:12]).strip("._")
        return f"{safe_name or 'character'}_{safe_id or uuid.uuid4().hex[:12]}.json"

    def _cards_dir(self) -> Path:
        return seed_character_cards()

    def _history_card_summaries(self) -> list[dict]:
        cards_dir = self._cards_dir()
        if not cards_dir.exists():
            return []
        summaries = []
        for path in sorted(cards_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                summaries.append(
                    {
                        "path": str(path),
                        "filename": path.name,
                        "name": data.get("name") or path.stem,
                        "greeting": data.get("greeting") or "",
                    }
                )
            except Exception:
                traceback.print_exc()
        return summaries

    def _resolve_card_path(self, path: str) -> Path:
        cards_dir = self._cards_dir().resolve()
        card_path = Path(path)
        if not card_path.is_absolute():
            card_path = cards_dir / card_path
        card_path = card_path.resolve()
        if cards_dir not in card_path.parents or card_path.suffix.lower() != ".json":
            raise ValueError("角色卡路径不在 character_cards 目录中")
        return card_path

    def _upgrade_card_dimensions(self, path: Path, profile: GeneratedCharacterProfile) -> None:
        payload = self._character_card_payload(profile)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
            f.write("\n")

    def _profile_from_card(self, data: dict) -> GeneratedCharacterProfile:
        trait_dimensions = data.get("trait_dimensions") if isinstance(data.get("trait_dimensions"), dict) else {}
        raw_personality_traits = data.get("personality_traits") or []
        personality_dimensions = self._normalize_dimensions(
            data.get("personality_dimensions") or trait_dimensions.get("personality")
        )
        if not personality_dimensions:
            personality_dimensions = self._dimensions_from_legacy_traits(raw_personality_traits)
        return GeneratedCharacterProfile(
            character_id=data.get("character_id") or f"local-{uuid.uuid4().hex[:12]}",
            name=data.get("name") or "角色",
            persona=data.get("persona") or "",
            greeting=data.get("greeting") or "你好呀。",
            display_image_base64=data.get("display_image_base64"),
            expression_layers=data.get("expression_layers"),
            fgimage_target=data.get("fgimage_target") or "ムラサメb",
            emotion_images=data.get("emotion_images") or {},
            appearance_traits=self._clean_traits(data.get("appearance_traits") or []),
            personality_traits=self._clean_traits(raw_personality_traits),
            identity_traits=data.get("identity_traits") or [],
            personality_dimensions=personality_dimensions,
            appearance_style_dimensions=self._normalize_dimensions(
                data.get("appearance_style_dimensions") or trait_dimensions.get("appearance_style")
            ),
            style=data.get("style"),
        )

    def _clean_traits(self, traits: Any) -> list[str]:
        if not isinstance(traits, list):
            return []
        result = []
        for trait in traits:
            text = re.sub(r"\(强度[1-5]/5\)$", "", str(trait).strip())
            if text:
                result.append(text)
        return result

    def _dimensions_from_legacy_traits(self, traits: Any) -> dict[str, int]:
        if not isinstance(traits, list):
            return {}
        result: dict[str, int] = {}
        for trait in traits:
            text = str(trait).strip()
            match = re.search(r"^(.*)\(强度([1-5])/5\)$", text)
            if match:
                result[match.group(1).strip()] = int(match.group(2))
        return result

    def _normalize_dimensions(self, dimensions: Any) -> dict[str, int]:
        if not isinstance(dimensions, dict):
            return {}
        result: dict[str, int] = {}
        for trait, strength in dimensions.items():
            trait_text = str(trait).strip()
            if not trait_text:
                continue
            try:
                strength_value = int(strength)
            except (TypeError, ValueError):
                strength_value = 3
            result[trait_text] = min(5, max(1, strength_value))
        return result

    def _profile_image_src(self, profile: Any) -> str | None:
        return self._image_src_from_values(
            getattr(profile, "display_image_url", None),
            getattr(profile, "display_image_base64", None),
        )

    def _emotion_images_payload(self, profile: Any) -> dict:
        result = {}
        emotion_images = getattr(profile, "emotion_images", None) or {}
        for emotion in ("happy", "angry", "shy", "sad"):
            src = None
            image = emotion_images.get(emotion) if isinstance(emotion_images, dict) else None
            if isinstance(image, str):
                src = self._image_src_from_values(image, None)
            elif isinstance(image, dict):
                src = image.get("image_src") or self._image_src_from_values(
                    image.get("display_image_url") or image.get("url"),
                    image.get("display_image_base64") or image.get("base64"),
                )
            if src:
                result[emotion] = {"image_src": src}
        return result

    def _image_src_from_values(self, image_url: str | None, image_base64: str | None) -> str | None:
        if image_base64:
            return f"data:image/png;base64,{image_base64}"
        if image_url:
            if image_url.startswith("data:") or urlparse(image_url).scheme:
                return image_url
        return None


class CharacterCreatorDialog(QDialog):
    def __init__(
        self,
        options: dict,
        api_client: Any,
        default_options: dict,
        default_user_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("角色生成工作台")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowStaysOnTopHint
        )
        self.resize(1040, 720)
        self.preview_profile = None
        self.preview_is_current = False
        self.preview_user_name = api_client.user_name or default_user_name

        try:
            from PyQt5.QtWebChannel import QWebChannel
            from PyQt5.QtWebEngineWidgets import QWebEngineView
        except ModuleNotFoundError as exc:
            QMessageBox.critical(
                parent,
                "缺少依赖",
                "HTML 工作台需要安装 PyQtWebEngine。\n\n请运行：uv sync\n\n"
                f"当前错误：{type(exc).__name__}: {exc}",
            )
            raise

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        layout.addWidget(self.web_view)

        self.bridge = CharacterWorkbenchBridge(self, options, api_client, default_options, default_user_name)
        self.channel = QWebChannel(self.web_view.page())
        self.channel.registerObject("characterWorkbench", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        html_path = resource_path("ui", "character_workbench.html")
        self.web_view.load(QUrl.fromLocalFile(str(html_path)))
