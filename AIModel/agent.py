import json
import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend import config as app_config
from backend.logger import logger

from .groq_client import GroqClient


_ALLOWED_ACTIONS = {
    "none",
    "send_account",
    "send_code",
    "handoff",
    "stock",
    "extend",
    "cancel",
}

_SYSTEM_PROMPT = (
    "You are a support assistant for a FunPay account rental bot. "
    "Respond in Russian with a casual, friendly tone. "
    "Never provide account credentials, logins, passwords, or Steam codes. "
    "Before purchase, only describe available lots (lot number, account type, lot_url). "
    "If active_rental_count is 0, guide the user to buy a lot on FunPay; "
    "the bot will send details automatically after payment. "
    "Do not ask the user to confirm payment manually. "
    "When the user asks about availability or how to rent, set action to stock and use available_lots. "
    "If the user asks for a Steam Guard code, set action to send_code. "
    "If the user asks to cancel, set action to cancel and request account_id if missing. "
    "Do not mention MMR values; treat them as private. "
    "If user reports account not working or login issues and active_rental_count > 0, "
    "reply that you will check and set action to send_code. "
    "If there is no active rental, explain how to buy a lot and show available_lots; "
    "do not speculate about why something does not work. "
    "Use history_summary, recent_messages, memory_facts, and last_message_time to keep context across turns. "
    "recent_messages items may include time; use it when helpful. "
    "If the user asks what you remember, reply with memory_facts. "
    "Keep replies short (1-4 sentences). "
    "Output JSON only with keys: reply, action, args. "
    "Action must be one of: none, send_account, send_code, handoff, stock, extend, cancel. "
    "Use args for parameters: extend needs hours and lot_number; cancel needs account_id. "
    "If required details are missing, set action to none and ask for them."
)

_SUMMARY_PROMPT = (
    "Summarize the conversation for future context. "
    "Keep the summary under {max_chars} characters. "
    "Include: user requests, lots discussed, order status, preferences, issues. "
    "If timestamps are provided, note when key events happened. "
    "Exclude credentials or sensitive data. "
    "Return plain text only."
)


@dataclass
class AIResponse:
    reply: str
    action: str
    args: Dict[str, Any]


class AIResponder:
    def __init__(self) -> None:
        provider = (app_config.AI_PROVIDER or "none").strip().lower()
        self.enabled = bool(app_config.AI_ENABLED) and provider != "none"
        self._provider = provider
        self._model = app_config.AI_MODEL
        self._timeout = app_config.AI_TIMEOUT_SECONDS
        self._temperature = app_config.AI_TEMPERATURE
        self._max_tokens = app_config.AI_MAX_TOKENS
        self._base_url = app_config.AI_BASE_URL
        self._system_prompt = app_config.AI_SYSTEM_PROMPT or _SYSTEM_PROMPT
        self._prompt_variants = _parse_prompt_variants(app_config.AI_SYSTEM_PROMPT_VARIANTS)
        self._fallback_reply = app_config.AI_FALLBACK_REPLY or ""
        self._payment_required_reply = app_config.AI_PAYMENT_REQUIRED_REPLY or ""
        self._queue_timeout = max(0, int(app_config.AI_QUEUE_TIMEOUT_SECONDS))
        self._semaphore = threading.BoundedSemaphore(max(1, int(app_config.AI_MAX_CONCURRENT)))
        self._last_error = threading.local()
        self._api_key = app_config.AI_API_KEY
        self._client: Optional[GroqClient] = None

        if self.enabled and self._provider == "groq":
            if not self._api_key:
                logger.warning("AI provider is set to groq, but AI_API_KEY is missing.")
                self.enabled = False
                return
            self._client = GroqClient(
                self._base_url,
                self._api_key,
                self._model,
                self._timeout,
                self._temperature,
                self._max_tokens,
            )
        elif self.enabled:
            logger.warning(
                "AI provider '%s' is not supported; disabling AI.",
                self._provider,
            )
            self.enabled = False

    def select_prompt_variant(self, key: Optional[str]) -> tuple[str, Optional[str]]:
        if not self._prompt_variants:
            return self._system_prompt, None
        if key:
            bucket = _stable_bucket(key, len(self._prompt_variants))
        else:
            bucket = 0
        prompt = self._prompt_variants[bucket]
        return prompt, f"variant_{bucket}"

    @property
    def payment_required_reply(self) -> str:
        return self._payment_required_reply

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def respond(
        self,
        user_message: str,
        context: Dict[str, Any],
        system_prompt_override: Optional[str] = None,
    ) -> Optional[AIResponse]:
        if not self.enabled:
            return None
        if not user_message:
            return None
        if not self._client:
            return None

        if not self._acquire_slot():
            self._set_last_error("queue_timeout")
            if self._fallback_reply:
                return AIResponse(reply=self._fallback_reply, action="none", args={})
            return None

        messages = self._build_messages(user_message, context, system_prompt_override)
        try:
            content = self._client.chat(messages)
        except Exception as exc:
            logger.warning("AI provider error: %s", exc)
            self._set_last_error("provider_error")
            if self._fallback_reply:
                return AIResponse(reply=self._fallback_reply, action="none", args={})
            return None
        finally:
            self._release_slot()

        data = _extract_json(content)
        if isinstance(data, dict):
            reply = (data.get("reply") or "").strip()
            action = (data.get("action") or "none").strip().lower()
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
        else:
            reply = (content or "").strip()
            action = "none"
            args = {}

        if action not in _ALLOWED_ACTIONS:
            action = "none"

        if not reply and action == "none":
            return None

        self._set_last_error(None)

        return AIResponse(reply=reply, action=action, args=args)

    def summarize(
        self,
        existing_summary: str,
        messages: list[dict],
        max_chars: int,
    ) -> Optional[str]:
        if not self.enabled or not self._client:
            return None
        if not messages:
            return existing_summary
        if not self._acquire_slot():
            self._set_last_error("queue_timeout")
            return existing_summary
        prompt = _SUMMARY_PROMPT.format(max_chars=int(max_chars))
        payload = {"summary": existing_summary, "messages": messages}
        try:
            content = self._client.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=app_config.AI_SUMMARY_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning("AI summary error: %s", exc)
            self._set_last_error("provider_error")
            return None
        finally:
            self._release_slot()
        summary = (content or "").strip()
        if not summary:
            return None
        self._set_last_error(None)
        if len(summary) > int(max_chars):
            summary = summary[: int(max_chars)].rstrip()
        return summary

    def _build_messages(
        self,
        user_message: str,
        context: Dict[str, Any],
        system_prompt_override: Optional[str] = None,
    ) -> list[dict]:
        payload = {"message": user_message, "context": context}
        system_prompt = system_prompt_override or self._system_prompt
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def _acquire_slot(self) -> bool:
        return self._semaphore.acquire(timeout=self._queue_timeout)

    def _release_slot(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            return

    def _set_last_error(self, reason: Optional[str]) -> None:
        try:
            self._last_error.reason = reason
        except Exception:
            pass

    def last_error_reason(self) -> Optional[str]:
        return getattr(self._last_error, "reason", None)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except Exception:
        return None


def _parse_prompt_variants(raw: str) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except Exception:
            return []
        return [str(item) for item in data if isinstance(item, str) and item.strip()]
    parts = [item.strip() for item in raw.split("|||")]
    return [item for item in parts if item]


def _stable_bucket(key: str, buckets: int) -> int:
    if buckets <= 1:
        return 0
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:4], "little", signed=False)
    return int(value % buckets)


_ai_instance: Optional[AIResponder] = None


def get_ai_responder() -> AIResponder:
    global _ai_instance
    if _ai_instance is None:
        _ai_instance = AIResponder()
    return _ai_instance
