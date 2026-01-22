import json
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
    "Before purchase, only describe available lots (lot number, account type, MMR, lot_url). "
    "If active_rental_count is 0, guide the user to buy a lot on FunPay; "
    "the bot will send details automatically after payment. "
    "Do not ask the user to confirm payment manually. "
    "When user asks about availability or how to rent, use available_lots from context. "
    "Include MMR in lot descriptions when present. "
    "Use history_summary and recent_messages to keep context across turns. "
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
        self._fallback_reply = app_config.AI_FALLBACK_REPLY or ""
        self._payment_required_reply = app_config.AI_PAYMENT_REQUIRED_REPLY or ""
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

    @property
    def payment_required_reply(self) -> str:
        return self._payment_required_reply

    def respond(self, user_message: str, context: Dict[str, Any]) -> Optional[AIResponse]:
        if not self.enabled:
            return None
        if not user_message:
            return None
        if not self._client:
            return None

        messages = self._build_messages(user_message, context)
        try:
            content = self._client.chat(messages)
        except Exception as exc:
            logger.warning("AI provider error: %s", exc)
            if self._fallback_reply:
                return AIResponse(reply=self._fallback_reply, action="none", args={})
            return None

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
            return None
        summary = (content or "").strip()
        if not summary:
            return None
        if len(summary) > int(max_chars):
            summary = summary[: int(max_chars)].rstrip()
        return summary

    def _build_messages(self, user_message: str, context: Dict[str, Any]) -> list[dict]:
        payload = {"message": user_message, "context": context}
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]


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


_ai_instance: Optional[AIResponder] = None


def get_ai_responder() -> AIResponder:
    global _ai_instance
    if _ai_instance is None:
        _ai_instance = AIResponder()
    return _ai_instance
