from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend import config as app_config
from backend.logger import logger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryEntry:
    owner: str
    user_id: int
    summary: str = ""
    facts: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    last_summary_id: int = 0
    next_message_id: int = 1
    last_seen_at: Optional[str] = None


class LocalMemoryStore:
    def __init__(self, base_dir: str, max_messages: int = 200, max_facts: int = 20) -> None:
        self._base_dir = Path(base_dir)
        self._max_messages = max(1, int(max_messages))
        self._max_facts = max(1, int(max_facts))
        self._lock = threading.Lock()
        self._entries: Dict[Tuple[int, str], MemoryEntry] = {}
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, owner: str, user_id: int | None) -> Tuple[int, str]:
        return int(user_id or 0), str(owner)

    def _owner_hash(self, owner: str) -> str:
        return hashlib.sha1(owner.encode("utf-8")).hexdigest()

    def _entry_path(self, owner: str, user_id: int) -> Path:
        user_dir = self._base_dir / f"user_{int(user_id)}"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"{self._owner_hash(owner)}.json"

    def _load_entry(self, owner: str, user_id: int | None) -> MemoryEntry:
        key = self._key(owner, user_id)
        cached = self._entries.get(key)
        if cached:
            return cached

        owner_value = key[1]
        user_value = key[0]
        path = self._entry_path(owner_value, user_value)
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load memory for %s: %s", owner_value, exc)
                data = {}

        entry = MemoryEntry(
            owner=owner_value,
            user_id=user_value,
            summary=str(data.get("summary") or ""),
            facts=list(data.get("facts") or []),
            messages=list(data.get("messages") or []),
            last_summary_id=int(data.get("last_summary_id") or 0),
            next_message_id=int(data.get("next_message_id") or 1),
            last_seen_at=data.get("last_seen_at"),
        )

        entry.facts = [item for item in entry.facts if isinstance(item, dict)]
        entry.messages = [item for item in entry.messages if isinstance(item, dict)]

        if len(entry.messages) > self._max_messages:
            entry.messages = entry.messages[-self._max_messages:]
        if len(entry.facts) > self._max_facts:
            entry.facts = entry.facts[-self._max_facts:]

        max_id = 0
        for item in entry.messages:
            try:
                msg_id = int(item.get("id") or 0)
            except Exception:
                msg_id = 0
            if msg_id > max_id:
                max_id = msg_id
        if entry.next_message_id <= max_id:
            entry.next_message_id = max_id + 1

        if not entry.last_seen_at and entry.messages:
            last_time = entry.messages[-1].get("created_at")
            if last_time:
                entry.last_seen_at = str(last_time)

        self._entries[key] = entry
        return entry

    def _save_entry(self, entry: MemoryEntry) -> None:
        path = self._entry_path(entry.owner, entry.user_id)
        payload = {
            "owner": entry.owner,
            "user_id": entry.user_id,
            "summary": entry.summary,
            "facts": entry.facts,
            "messages": entry.messages,
            "last_summary_id": entry.last_summary_id,
            "next_message_id": entry.next_message_id,
            "last_seen_at": entry.last_seen_at,
            "updated_at": _now_iso(),
        }
        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            tmp_path.replace(path)
        except Exception as exc:
            logger.warning("Failed to save memory for %s: %s", entry.owner, exc)

    def log_message(
        self,
        owner: str,
        role: str,
        message: str,
        user_id: int | None = None,
        created_at: Optional[str] = None,
    ) -> None:
        if not owner or not role or not message:
            return
        created_at = created_at or _now_iso()
        with self._lock:
            entry = self._load_entry(owner, user_id)
            entry.messages.append(
                {
                    "id": entry.next_message_id,
                    "role": role,
                    "text": message,
                    "created_at": created_at,
                }
            )
            entry.next_message_id += 1
            if len(entry.messages) > self._max_messages:
                entry.messages = entry.messages[-self._max_messages:]
            entry.last_seen_at = created_at
            self._save_entry(entry)

    def add_fact(
        self,
        owner: str,
        fact: str,
        user_id: int | None = None,
        created_at: Optional[str] = None,
    ) -> bool:
        if not owner or not fact:
            return False
        created_at = created_at or _now_iso()
        with self._lock:
            entry = self._load_entry(owner, user_id)
            entry.facts.append({"text": fact, "created_at": created_at})
            if len(entry.facts) > self._max_facts:
                entry.facts = entry.facts[-self._max_facts:]
            self._save_entry(entry)
        return True

    def get_facts(self, owner: str, user_id: int | None = None) -> List[Dict[str, Any]]:
        if not owner:
            return []
        with self._lock:
            entry = self._load_entry(owner, user_id)
            return [dict(item) for item in entry.facts]

    def get_summary_state(self, owner: str, user_id: int | None = None) -> Dict[str, Any]:
        if not owner:
            return {"summary": "", "last_summary_id": 0, "last_seen_at": None}
        with self._lock:
            entry = self._load_entry(owner, user_id)
            return {
                "summary": entry.summary,
                "last_summary_id": entry.last_summary_id,
                "last_seen_at": entry.last_seen_at,
            }

    def set_summary(
        self,
        owner: str,
        summary: str,
        last_summary_id: int,
        user_id: int | None = None,
    ) -> None:
        if not owner:
            return
        with self._lock:
            entry = self._load_entry(owner, user_id)
            entry.summary = summary
            entry.last_summary_id = int(last_summary_id or 0)
            self._save_entry(entry)

    def get_messages_after(
        self,
        owner: str,
        last_message_id: int,
        user_id: int | None = None,
    ) -> List[Dict[str, Any]]:
        if not owner:
            return []
        try:
            threshold = int(last_message_id or 0)
        except Exception:
            threshold = 0
        with self._lock:
            entry = self._load_entry(owner, user_id)
            return [dict(item) for item in entry.messages if int(item.get("id") or 0) > threshold]

    def get_recent_messages(
        self,
        owner: str,
        limit: int = 20,
        user_id: int | None = None,
    ) -> List[Dict[str, Any]]:
        if not owner:
            return []
        try:
            limit_value = int(limit or 0)
        except Exception:
            limit_value = 0
        with self._lock:
            entry = self._load_entry(owner, user_id)
            items = entry.messages[-limit_value:] if limit_value else list(entry.messages)
            return [dict(item) for item in items]

    def get_last_seen_at(self, owner: str, user_id: int | None = None) -> Optional[str]:
        if not owner:
            return None
        with self._lock:
            entry = self._load_entry(owner, user_id)
            return entry.last_seen_at


_memory_store: Optional[LocalMemoryStore] = None


def get_memory_store() -> LocalMemoryStore:
    global _memory_store
    if _memory_store is None:
        base_dir = app_config.AI_MEMORY_DIR or "data/chat_memory"
        _memory_store = LocalMemoryStore(
            base_dir=base_dir,
            max_messages=app_config.AI_MEMORY_MAX_MESSAGES,
            max_facts=app_config.AI_MEMORY_MAX_FACTS,
        )
    return _memory_store


__all__ = ["LocalMemoryStore", "get_memory_store"]
