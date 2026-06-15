from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from Murasame import utils
from scripts.character_runtime import (
    avatar_values_for_emotion,
    build_reply_messages,
    normalize_emotion,
    parse_reply_content,
    write_image_to_cache,
)
from scripts.character_traits import clean_trait_list, dimensions_from_legacy_traits
from scripts.desktop_tools import (
    ALLOWED_CATEGORY_FOLDERS,
    build_image_contact_sheet,
    capture_desktop_data_uri,
    desktop_root_from_config,
    list_desktop_files,
    metadata_for_entries,
    move_files,
    open_google_search,
    selected_entries,
    trash_files,
)
from scripts.memory_runtime import MemoryStore, sanitize_memory_text
from scripts.pet_defaults import DEFAULT_CHARACTER_OPTIONS, DEFAULT_VL_MODEL
from scripts.profile import CharacterProfile, DEFAULT_CHARACTER_NAME, DEFAULT_FGIMAGE_TARGET, DEFAULT_USER_NAME, PetResponse
from scripts.workbench.constants import API_BASE_URL, DESCRIPTION_MODEL
from scripts.workbench.generator import LocalCharacterGenerator


class PetApiClient:
    def __init__(self) -> None:
        config = utils.get_config()
        client_config = config.get("client", {})
        vl_config = config.get("vl", {})
        character_config = config.get("character", {})
        self.session_id = client_config.get("session_id", "local-user")
        self.timeout = float(client_config.get("timeout_seconds", 120))
        self.vl_model = vl_config.get("model") or DEFAULT_VL_MODEL
        self.agent_tools_config = config.get("agent_tools", {})
        self.desktop_root = desktop_root_from_config(config)
        self.character_id = character_config.get("character_id")
        self.user_name = character_config.get("user_name") or DEFAULT_USER_NAME
        self.character_profile = self._character_from_config(character_config)
        self.memory = MemoryStore.from_config(config)
        self.api_key: str | None = None
        self.history: list[dict[str, str]] = []

    def get_character_options(self) -> dict:
        options = json.loads(json.dumps(DEFAULT_CHARACTER_OPTIONS, ensure_ascii=False))
        defaults = options.setdefault("defaults", {})
        profile = self.character_profile
        if profile.appearance_traits:
            defaults["appearance_traits"] = profile.appearance_traits
        if profile.personality_traits:
            defaults["personality_traits"] = profile.personality_traits
        if profile.personality_dimensions:
            defaults["personality_dimensions"] = profile.personality_dimensions
        if profile.appearance_style_dimensions:
            defaults["appearance_style_dimensions"] = profile.appearance_style_dimensions
        if profile.style:
            defaults["style"] = profile.style
        return options

    def respond(self, event: str, text: str, screenshot_base64: str | None = None) -> PetResponse:
        memory_query = self._memory_query(event, text)
        retrieved_memories = self.memory.search(memory_query, self.memory.config.user_id, self.memory.config.top_k)
        messages = build_reply_messages(
            self.character_profile,
            self.user_name,
            self.history,
            event,
            text,
            bool(screenshot_base64),
            retrieved_memories,
        )
        model = DESCRIPTION_MODEL
        tools = self._native_tools_for_event(event) if self._agent_tools_enabled() else []
        tool_choice = self._tool_choice_for_event(event, bool(screenshot_base64))
        if event == "screen_context" and screenshot_base64 and not tools:
            model = self.vl_model
            user_text = messages[-1]["content"]
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": screenshot_base64}},
                    {"type": "text", "text": user_text},
                ],
            }

        response = self._post_chat(
            model,
            messages,
            temperature=0.85,
            tools=tools,
            tool_choice=tool_choice,
        )
        message = response.json()["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            return self._respond_with_native_tools(event, text, messages, message, tool_calls, screenshot_base64)
        return self._pet_response_from_message(event, text, message)

    def _pet_response_from_message(
        self,
        event: str,
        text: str,
        message: dict[str, Any],
        pending_action: dict | None = None,
        desktop_summary_fallback: str = "",
    ) -> PetResponse:
        content_value = message.get("content") or ""
        content = content_value if isinstance(content_value, str) else json.dumps(content_value, ensure_ascii=False)
        data = parse_reply_content(content)
        reply_text = data.get("text") or content.strip()
        emotion = normalize_emotion(data.get("emotion"))
        desktop_summary = str(data.get("desktop_summary") or desktop_summary_fallback).strip()
        self._remember_turn(event, text, reply_text, desktop_summary)
        return PetResponse(
            text=reply_text,
            emotion=emotion,
            session_id=self.session_id,
            tool_action=pending_action,
        )

    def download_image(self, image_url: str | None, image_base64: str | None, key: str) -> str | None:
        return write_image_to_cache(image_url, image_base64, key)

    def confirm_tool_action(self, action: dict[str, Any]) -> PetResponse:
        action_type = action.get("type")
        if action_type != "trash_files":
            return PetResponse(text="这个工具动作不认识，我没有执行。", emotion="sad", session_id=self.session_id)
        files = action.get("files")
        if not isinstance(files, list):
            return PetResponse(text="删除列表格式不对，我没有执行。", emotion="sad", session_id=self.session_id)
        safe_paths: list[str] = []
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            path = Path(str(file_info.get("path") or "")).resolve()
            if path.parent == self.desktop_root and path.exists() and path.is_file():
                safe_paths.append(str(path))
        trashed = trash_files(safe_paths)
        if not trashed:
            reply = "没有文件被移到废纸篓。"
            emotion = "sad"
        else:
            reply = f"已把 {len(trashed)} 个文件移到废纸篓。"
            emotion = "happy"
        self._remember_turn("desktop_tool", "confirm_trash", reply)
        return PetResponse(text=reply, emotion=emotion, session_id=self.session_id)

    def _get_api_key(self) -> str:
        if not self.api_key:
            self.api_key = LocalCharacterGenerator(timeout=int(self.timeout)).api_key
        return self.api_key

    def _post_chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> requests.Response:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "top_p": 1,
            "presence_penalty": 0,
            "frequency_penalty": 0,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        response = requests.post(
            f"{API_BASE_URL}/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._get_api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def _agent_tools_enabled(self) -> bool:
        if not isinstance(self.agent_tools_config, dict):
            return True
        return bool(self.agent_tools_config.get("enabled", True))

    def _native_tools_for_event(self, event: str) -> list[dict[str, Any]]:
        read_screen_tool = {
            "type": "function",
            "function": {
                "name": "read_screen",
                "description": "读取当前桌面截图并返回可见内容摘要。定时桌面观察事件应调用此工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "focus": {
                            "type": "string",
                            "description": "可选。希望重点观察的内容，例如当前任务、窗口、文档或用户提到的目标。",
                        }
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }
        if event == "screen_context":
            return [read_screen_tool]
        if event != "user_text":
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "open_google_search",
                    "description": "当用户明确要求搜索、查询或打开网页搜索时，用浏览器打开 Google 搜索结果页。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "要搜索的关键词或问题，不包含额外寒暄。",
                            }
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "organize_desktop",
                    "description": "按用户要求整理桌面直接文件，把文件移动到固定白名单分类文件夹。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "instruction": {
                                "type": "string",
                                "description": "用户的整理要求。工具会自行读取桌面直接文件并生成安全移动计划。",
                            }
                        },
                        "required": ["instruction"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_desktop_images_for_trash",
                    "description": "查找桌面上符合描述的图片文件，返回待用户确认的移入废纸篓计划；工具不会直接删除。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "要查找并准备移入废纸篓的图片内容描述。",
                            }
                        },
                        "required": ["description"],
                        "additionalProperties": False,
                    },
                },
            },
            read_screen_tool,
        ]

    def _tool_choice_for_event(self, event: str, has_screenshot: bool) -> str | dict[str, Any] | None:
        if event == "screen_context" and has_screenshot:
            return {"type": "function", "function": {"name": "read_screen"}}
        return "auto"

    def _respond_with_native_tools(
        self,
        event: str,
        text: str,
        messages: list[dict],
        message: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        screenshot_base64: str | None,
    ) -> PetResponse:
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        pending_action: dict | None = None
        desktop_summary_fallback = ""
        for tool_call in tool_calls:
            name = self._tool_call_name(tool_call)
            arguments = self._tool_call_arguments(tool_call)
            result, action = self._execute_native_tool(name, arguments, screenshot_base64)
            if action:
                pending_action = action
            if name == "read_screen":
                desktop_summary_fallback = str(result.get("desktop_summary") or result.get("observation") or "").strip()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call.get("id") or name),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        response = self._post_chat(DESCRIPTION_MODEL, messages, temperature=0.85)
        final_message = response.json()["choices"][0]["message"]
        return self._pet_response_from_message(
            event,
            text,
            final_message,
            pending_action=pending_action,
            desktop_summary_fallback=desktop_summary_fallback,
        )

    def _tool_call_name(self, tool_call: dict[str, Any]) -> str:
        function = tool_call.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(tool_call.get("name") or "")

    def _tool_call_arguments(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function")
        raw_arguments = function.get("arguments") if isinstance(function, dict) else tool_call.get("arguments")
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str) or not raw_arguments.strip():
            return {}
        try:
            data = json.loads(raw_arguments)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _execute_native_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        screenshot_base64: str | None,
    ) -> tuple[dict[str, Any], dict | None]:
        try:
            if name == "open_google_search":
                return self._open_google_search_tool(str(arguments.get("query") or "")), None
            if name == "organize_desktop":
                return self._organize_desktop_tool(str(arguments.get("instruction") or "")), None
            if name == "find_desktop_images_for_trash":
                return self._plan_desktop_image_trash_tool(str(arguments.get("description") or ""))
            if name == "read_screen":
                return self._read_screen_tool(str(arguments.get("focus") or ""), screenshot_base64), None
        except Exception as exc:
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}, None
        return {"status": "error", "message": f"未知工具：{name}"}, None

    def _open_google_search_tool(self, query: str) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"status": "error", "message": "搜索内容不能为空。"}
        url = open_google_search(query)
        return {"status": "success", "message": f"已打开网页搜索：{query}", "query": query, "url": url}

    def _plan_desktop_image_trash_tool(self, description: str) -> tuple[dict[str, Any], dict | None]:
        image_entries = list_desktop_files(self.desktop_root, images_only=True)
        if not image_entries:
            return {"status": "empty", "message": "桌面上没有可识别的图片文件。"}, None
        sheet = build_image_contact_sheet(image_entries)
        if not sheet:
            return {"status": "error", "message": "桌面图片缩略图生成失败，没有删除任何东西。"}, None

        query = description.strip() or "用户要求删除的图片"
        prompt = f"""
你需要从一张桌面图片缩略图索引表中，找出符合用户描述的图片编号。
用户描述：{query}
候选文件：
{json.dumps(metadata_for_entries(image_entries), ensure_ascii=False)}

只输出 JSON，不要 Markdown。格式：
{{"matches": [{{"id": 1, "confidence": 0.0, "reason": "简短理由"}}]}}
规则：
- 只有图片内容明显符合描述时才加入 matches。
- confidence 取 0 到 1。
- 不确定时返回空 matches。
""".strip()
        response = self._post_chat(
            self.vl_model,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": sheet}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0.1,
        )
        content = response.json()["choices"][0]["message"].get("content") or ""
        data = parse_reply_content(content)
        matches = data.get("matches") if isinstance(data, dict) else []
        ids: list[int] = []
        if isinstance(matches, list):
            for match in matches:
                if not isinstance(match, dict):
                    continue
                try:
                    confidence = float(match.get("confidence", 0))
                    match_id = int(match.get("id"))
                except (TypeError, ValueError):
                    continue
                if confidence >= 0.65:
                    ids.append(match_id)
        selected = selected_entries(image_entries, ids)
        if not selected:
            return {
                "status": "no_match",
                "message": "没找到足够确定符合描述的图片，没有删除任何东西。",
                "description": query,
            }, None

        files = [{"name": entry.name, "path": str(entry.path)} for entry in selected]
        action = {"type": "trash_files", "files": files}
        return {
            "status": "requires_confirmation",
            "message": f"找到了 {len(files)} 个可能符合描述的图片，需要用户确认后才会移到废纸篓。",
            "description": query,
            "files": [{"name": file_info["name"]} for file_info in files],
        }, action

    def _organize_desktop_tool(self, instruction: str) -> dict[str, Any]:
        entries = list_desktop_files(self.desktop_root, images_only=False)
        if not entries:
            return {"status": "empty", "message": "桌面上没有需要整理的直接文件。"}
        prompt = f"""
你是桌面文件整理器。请根据用户要求、文件名和扩展名，把桌面文件移动到固定分类文件夹。
用户要求：{instruction}
允许的分类文件夹：{sorted(ALLOWED_CATEGORY_FOLDERS)}
文件列表：
{json.dumps(metadata_for_entries(entries), ensure_ascii=False)}

只输出 JSON，不要 Markdown。格式：
{{"moves": [{{"source": "原文件名.ext", "category": "图片"}}]}}
规则：
- source 必须完全等于文件列表中的 name。
- category 必须来自允许的分类文件夹。
- 不要移动不确定的文件。
- 不要创建允许列表外的文件夹。
""".strip()
        response = self._post_chat(
            DESCRIPTION_MODEL,
            [{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = response.json()["choices"][0]["message"].get("content") or ""
        data = parse_reply_content(content)
        moves = data.get("moves") if isinstance(data, dict) else []
        if not isinstance(moves, list):
            moves = []
        moved = move_files(self.desktop_root, moves)
        if not moved:
            return {"status": "no_moves", "message": "没有生成安全可执行的整理计划，所以没有移动文件。"}
        categories = sorted({target.parent.name for _, target in moved})
        return {
            "status": "success",
            "message": f"已整理 {len(moved)} 个文件，放进了 {len(categories)} 个分类文件夹：{'、'.join(categories)}。",
            "moved_count": len(moved),
            "categories": categories,
            "files": [{"source": source.name, "target": str(target)} for source, target in moved],
        }

    def _read_screen_tool(self, focus: str, screenshot_base64: str | None) -> dict[str, Any]:
        config = utils.get_config().get("vl", {})
        screenshot = screenshot_base64 or capture_desktop_data_uri(
            max(320, int(config.get("max_width", 1280))),
            max(35, min(95, int(config.get("jpeg_quality", 75)))),
        )
        if not screenshot:
            return {"status": "error", "message": "没有可用截图。", "observation": "", "desktop_summary": ""}
        prompt = f"""
你正在作为桌宠的屏幕读取工具读取当前桌面截图。
观察重点：{focus.strip() or "当前任务、应用窗口、文档和用户活动"}

只输出 JSON，不要 Markdown。格式：
{{"observation": "给角色看的简短可见内容摘要", "desktop_summary": "值得长期记住的一句话，没有则为空字符串"}}
规则：
- 只描述截图中明确可见的内容。
- 不要转录大段文字，不要输出密码、密钥、身份证号等敏感内容。
- 不要猜测截图外的信息。
""".strip()
        response = self._post_chat(
            self.vl_model,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": screenshot}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0.1,
        )
        content = response.json()["choices"][0]["message"].get("content") or ""
        data = parse_reply_content(content)
        observation = str(data.get("observation") or data.get("text") or content).strip()
        desktop_summary = str(data.get("desktop_summary") or "").strip()
        return {
            "status": "success",
            "observation": observation,
            "desktop_summary": desktop_summary,
        }

    def _remember_turn(self, event: str, user_text: str, reply_text: str, desktop_summary: str = "") -> None:
        short_term_user_text = user_text or event
        self.history.extend(
            [
                {"role": "user", "content": short_term_user_text},
                {"role": "assistant", "content": json.dumps({"text": reply_text}, ensure_ascii=False)},
            ]
        )
        self.history = self.history[-12:]
        metadata = {
            "event": event,
            "session_id": self.session_id,
            "user_id": self.memory.config.user_id,
        }
        if event == "screen_context":
            summary = desktop_summary or reply_text
            self.memory.add_desktop_observation(summary, reply_text, metadata)
            return
        self.memory.add_turn(user_text or event, reply_text, metadata)

    def _memory_query(self, event: str, text: str) -> str:
        if event == "screen_context":
            return "桌面观察 当前任务 应用 文档"
        if text.strip():
            return sanitize_memory_text(text)
        return event

    def _character_from_config(self, data: dict) -> CharacterProfile:
        return CharacterProfile(
            character_id=data.get("character_id") or data.get("id") or self.character_id,
            name=data.get("name") or data.get("character_name") or DEFAULT_CHARACTER_NAME,
            persona=data.get("persona") or "",
            greeting=data.get("greeting") or "主人，你好呀！",
            display_image_url=data.get("display_image_url"),
            display_image_base64=data.get("display_image_base64"),
            expression_layers=data.get("expression_layers"),
            fgimage_target=data.get("fgimage_target") or DEFAULT_FGIMAGE_TARGET,
            emotion_images=data.get("emotion_images"),
            appearance_traits=clean_trait_list(data.get("appearance_traits")),
            personality_traits=clean_trait_list(data.get("personality_traits")),
            identity_traits=data.get("identity_traits"),
            personality_dimensions=data.get("personality_dimensions")
            or (data.get("trait_dimensions") or {}).get("personality")
            or dimensions_from_legacy_traits(data.get("personality_traits")),
            appearance_style_dimensions=data.get("appearance_style_dimensions")
            or (data.get("trait_dimensions") or {}).get("appearance_style"),
            style=data.get("style"),
        )

    def remember_character(self, profile: CharacterProfile, user_name: str) -> None:
        config = utils.get_config()
        character_config = config.setdefault("character", {})
        character_config["character_id"] = profile.character_id
        character_config["name"] = profile.name
        character_config["persona"] = profile.persona
        character_config["greeting"] = profile.greeting
        character_config["display_image_url"] = profile.display_image_url
        character_config["display_image_base64"] = profile.display_image_base64
        character_config["expression_layers"] = profile.expression_layers
        character_config["fgimage_target"] = profile.fgimage_target
        character_config["emotion_images"] = profile.emotion_images
        character_config["appearance_traits"] = profile.appearance_traits
        character_config["personality_traits"] = profile.personality_traits
        character_config["identity_traits"] = profile.identity_traits
        character_config["personality_dimensions"] = profile.personality_dimensions
        character_config["appearance_style_dimensions"] = profile.appearance_style_dimensions
        character_config["trait_dimensions"] = {
            "personality": profile.personality_dimensions or {},
            "appearance_style": profile.appearance_style_dimensions or {},
        }
        character_config["style"] = profile.style
        character_config["user_name"] = user_name or DEFAULT_USER_NAME
        utils.save_config(config)
        self.character_id = profile.character_id
        self.user_name = user_name or DEFAULT_USER_NAME
        self.character_profile = profile
        self.history.clear()
