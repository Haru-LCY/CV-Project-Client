from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BASE64_IMAGE_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")
TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass
class MemoryConfig:
    enabled: bool = True
    provider: str = "mem0_local"
    user_id: str = "local-user"
    top_k: int = 5
    store_screenshots: bool = False
    desktop_summary_enabled: bool = True
    storage_path: str = ".memory/local_memory.jsonl"
    mem0: dict[str, Any] = field(default_factory=dict)


class MemoryStore:
    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self._fallback = LocalJsonMemory(config.storage_path)
        self._mem0 = self._create_mem0() if config.enabled and config.provider == "mem0_local" else None

    @classmethod
    def from_config(cls, app_config: dict[str, Any]) -> "MemoryStore":
        client_config = app_config.get("client", {})
        data = app_config.get("memory", {})
        configured_user_id = data.get("user_id")
        client_user_id = client_config.get("session_id") or "local-user"
        config = MemoryConfig(
            enabled=bool(data.get("enabled", True)),
            provider=str(data.get("provider") or "mem0_local"),
            user_id=str(configured_user_id or client_user_id),
            top_k=max(1, int(data.get("top_k", 5))),
            store_screenshots=bool(data.get("store_screenshots", False)),
            desktop_summary_enabled=bool(data.get("desktop_summary_enabled", True)),
            storage_path=str(data.get("storage_path") or ".memory/local_memory.jsonl"),
            mem0=dict(data.get("mem0") or {}),
        )
        return cls(config)

    def search(self, query: str, user_id: str | None = None, top_k: int | None = None) -> list[str]:
        if not self.config.enabled or not query.strip():
            return []
        resolved_user_id = user_id or self.config.user_id
        resolved_top_k = top_k or self.config.top_k
        if self._mem0 is not None:
            try:
                results = self._mem0.search(
                    query=query,
                    filters={"user_id": resolved_user_id},
                    top_k=resolved_top_k,
                )
                memories = self._extract_mem0_memories(results)
                if memories:
                    return memories[:resolved_top_k]
            except Exception as exc:
                print(f"Mem0 search failed, using local fallback: {type(exc).__name__}: {exc}")
        return self._fallback.search(query, resolved_user_id, resolved_top_k)

    def add_turn(self, user_text: str, assistant_text: str, metadata: dict[str, Any] | None = None) -> None:
        if not self.config.enabled:
            return
        cleaned_user_text = sanitize_memory_text(user_text)
        cleaned_assistant_text = sanitize_memory_text(assistant_text)
        if not cleaned_user_text and not cleaned_assistant_text:
            return
        user_id = self._metadata_user_id(metadata)
        payload = [
            {"role": "user", "content": cleaned_user_text},
            {"role": "assistant", "content": cleaned_assistant_text},
        ]
        self._add_mem0(payload, user_id)
        self._fallback.add(
            user_id=user_id,
            kind="conversation",
            text=f"用户：{cleaned_user_text}\n角色：{cleaned_assistant_text}",
            metadata=metadata,
        )

    def add_desktop_observation(
        self,
        summary: str,
        assistant_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.config.enabled or not self.config.desktop_summary_enabled:
            return
        cleaned_summary = sanitize_memory_text(summary)
        cleaned_assistant_text = sanitize_memory_text(assistant_text)
        if not cleaned_summary and not cleaned_assistant_text:
            return
        user_id = self._metadata_user_id(metadata)
        memory_text = f"桌面观察：{cleaned_summary}\n角色回应：{cleaned_assistant_text}"
        self._add_mem0([{"role": "user", "content": memory_text}], user_id)
        self._fallback.add(user_id=user_id, kind="desktop", text=memory_text, metadata=metadata)

    def clear_user(self, user_id: str | None = None) -> None:
        resolved_user_id = user_id or self.config.user_id
        if self._mem0 is not None:
            for method_name in ("delete_all", "reset"):
                method = getattr(self._mem0, method_name, None)
                if not callable(method):
                    continue
                try:
                    if method_name == "delete_all":
                        method(user_id=resolved_user_id)
                    else:
                        method()
                    break
                except Exception as exc:
                    print(f"Mem0 {method_name} failed: {type(exc).__name__}: {exc}")
        self._fallback.clear_user(resolved_user_id)

    def _add_mem0(self, messages: list[dict[str, str]], user_id: str) -> None:
        if self._mem0 is None:
            return
        try:
            self._mem0.add(messages, user_id=user_id)
        except Exception as exc:
            print(f"Mem0 add failed, local fallback retained memory: {type(exc).__name__}: {exc}")

    def _metadata_user_id(self, metadata: dict[str, Any] | None) -> str:
        if metadata and metadata.get("user_id"):
            return str(metadata["user_id"])
        return self.config.user_id

    def _create_mem0(self) -> Any | None:
        try:
            from mem0 import Memory

            mem0_config = self._mem0_config()
            if mem0_config:
                return Memory.from_config(mem0_config)
            return Memory()
        except Exception as exc:
            print(f"Mem0 unavailable, using local fallback: {type(exc).__name__}: {exc}")
            return None

    def _mem0_config(self) -> dict[str, Any]:
        data = self.config.mem0
        memory_dir = Path(self.config.storage_path).parent
        history_db_path = str(data.get("history_db_path") or memory_dir / "mem0_history.db")
        vector_path = str(data.get("vector_path") or memory_dir / "qdrant")
        config: dict[str, Any] = {
            "history_db_path": history_db_path,
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": vector_path,
                },
            },
        }
        if data.get("llm"):
            config["llm"] = data["llm"]
        if data.get("embedder"):
            config["embedder"] = data["embedder"]
        return config

    def _extract_mem0_memories(self, data: Any) -> list[str]:
        if isinstance(data, dict):
            data = data.get("results") or data.get("memories") or []
        if not isinstance(data, list):
            return []
        memories: list[str] = []
        for item in data:
            if isinstance(item, str):
                value = item
            elif isinstance(item, dict):
                value = item.get("memory") or item.get("text") or item.get("content") or ""
            else:
                value = ""
            value = sanitize_memory_text(str(value)).strip()
            if value:
                memories.append(value)
        return memories


class LocalJsonMemory:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def add(self, user_id: str, kind: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        cleaned = sanitize_memory_text(text)
        if not cleaned:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "user_id": user_id,
            "kind": kind,
            "text": cleaned,
            "metadata": _safe_metadata(metadata),
            "created_at": int(time.time()),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def search(self, query: str, user_id: str, top_k: int) -> list[str]:
        query_tokens = _tokens(query)
        if not query_tokens or not self.path.exists():
            return []
        query_counter = Counter(query_tokens)
        scored: list[tuple[float, int, str]] = []
        for index, record in enumerate(self._records()):
            if record.get("user_id") != user_id:
                continue
            text = str(record.get("text") or "")
            score = _similarity(query_counter, Counter(_tokens(text)))
            if score > 0:
                scored.append((score, int(record.get("created_at") or index), text))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [text for _, _, text in scored[:top_k]]

    def clear_user(self, user_id: str) -> None:
        if not self.path.exists():
            return
        remaining = [record for record in self._records() if record.get("user_id") != user_id]
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as f:
            for record in remaining:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp_path, self.path)

    def _records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
        return records


def sanitize_memory_text(text: str) -> str:
    without_images = BASE64_IMAGE_PATTERN.sub("[image omitted]", text or "")
    return re.sub(r"\s+", " ", without_images).strip()


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_PATTERN.findall(text):
        normalized = token.lower()
        tokens.append(normalized)
        cjk_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
        if len(cjk_chars) >= 2:
            tokens.extend(cjk_chars)
            tokens.extend("".join(cjk_chars[index : index + 2]) for index in range(len(cjk_chars) - 1))
    return tokens


def _similarity(left: Counter[str], right: Counter[str]) -> float:
    overlap = set(left) & set(right)
    if not overlap:
        return 0.0
    dot = sum(left[token] * right[token] for token in overlap)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
