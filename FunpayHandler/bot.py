from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from FunPayAPI import Account, Runner, events, types

from backend.config import (
    AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE,
    DOTA_MATCH_DELAY_EXPIRE,
    DOTA_MATCH_GRACE_MINUTES,
    HOURS_FOR_REVIEW,
    AI_CONTEXT_MESSAGES,
    AI_MESSAGE_MAX_CHARS,
    AI_ORDER_HISTORY_LIMIT,
    AI_RENTAL_HISTORY_LIMIT,
    AI_SUMMARY_ENABLED,
    AI_SUMMARY_MAX_CHARS,
    AI_SUMMARY_TRIGGER,
    RENTAL_CHECK_INTERVAL,
)
from DatabaseHandler.databaseSetup import MySQLDB
from backend.logger import logger
from backend.notifications import send_message_to_admin
from FunPayAPI.common.utils import RegularExpressions
from SteamHandler.SteamGuard import get_steam_guard_code
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence_bot import get_presence_bot
from AIModel.agent import get_ai_responder

from .messages import USER
from .utils import (
    MOSCOW_TZ,
    format_duration_minutes,
    get_duration_minutes,
    get_remaining_time,
    match_account_choice,
    match_account_name,
    parse_lot_number,
)


REFRESH_INTERVAL_SECONDS = 1300  # 30 minutes
PENDING_EXTEND_TTL_SECONDS = 6 * 60 * 60
MMR_RANGE_DEFAULT = 1000
AI_STOCK_LIMIT = 10
MMR_REDACTION_REGEX = re.compile(
    r"(?:\b(?:mmr|\u043c\u043c\u0440)\s*\d+(?:\s*-\s*\d+)?\b|\b\d+(?:\s*-\s*\d+)?\s*(?:mmr|\u043c\u043c\u0440)\b)",
    re.IGNORECASE,
)
SENSITIVE_KEYWORDS = (
    "password",
    "пароль",
    "login",
    "логин",
    "steam guard",
    "guard code",
    "steamguard",
    "код steam",
)
ISSUE_KEYWORDS = (
    "не работает",
    "нерабоч",
    "не рабоч",
    "не могу войти",
    "не могу зайти",
    "не входит",
    "не пускает",
    "ошибка",
    "invalid password",
    "wrong password",
    "incorrect password",
    "login failed",
    "not working",
    "doesn't work",
    "steam guard",
    "guard code",
    "steamguard",
    "code",
    "код",
)
ISSUE_REPLY = (
    "\u041f\u043e\u043d\u044f\u043b, \u0441\u0435\u0439\u0447\u0430\u0441 "
    "\u043f\u0440\u043e\u0432\u0435\u0440\u044e. \u041f\u0440\u0438\u0448\u043b\u044e "
    "\u0441\u0432\u0435\u0436\u0438\u0439 Steam Guard \u043a\u043e\u0434 \u2014 "
    "\u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0432\u043e\u0439\u0442\u0438 "
    "\u0435\u0449\u0435 \u0440\u0430\u0437. \u0415\u0441\u043b\u0438 \u043d\u0435 "
    "\u043f\u043e\u043c\u043e\u0436\u0435\u0442, \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435, "
    "\u0447\u0442\u043e \u0438\u043c\u0435\u043d\u043d\u043e \u043f\u0438\u0448\u0435\u0442 \u043f\u0440\u0438 \u0432\u0445\u043e\u0434\u0435."
)
ISSUE_NO_RENTAL_REPLY = (
    "\u0421\u0435\u0439\u0447\u0430\u0441 \u043d\u0435 \u0432\u0438\u0436\u0443 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0439 "
    "\u0430\u0440\u0435\u043d\u0434\u044b. \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 "
    "\u043b\u043e\u0442 \u043d\u0430 FunPay \u2014 \u043f\u043e\u0441\u043b\u0435 "
    "\u043e\u043f\u043b\u0430\u0442\u044b \u0431\u043e\u0442 \u0441\u0430\u043c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442 "
    "\u0434\u0430\u043d\u043d\u044b\u0435."
)
COMMANDS_HELP = (
    "Команды:\n"
    "!acc / !акк — данные аккаунта\n"
    "!code / !код — код Steam Guard\n"
    "!stock / !сток — наличие аккаунтов\n"
    "!extend / !продлить <часы> <номер_лота> — продлить аренду\n"
    "!cancel / !отмена <ID> — отменить аренду\n"
    "!bonus / !бонус — бонус за отзыв (5★)"
)
COMMANDS_INLINE = (
    "Команды: !acc/!акк, !code/!код, !stock/!сток, !extend/!продлить, "
    "!cancel/!отмена, !bonus/!бонус"
)


@dataclass(frozen=True)
class PendingLotExtend:
    hours: int
    lot_number: int
    created_ts: float


class FunpayBot:
    def __init__(
        self,
        token: Optional[str] = None,
        db: Optional[MySQLDB] = None,
        user_id: Optional[int] = None,
    ) -> None:
        self._token = token
        self._db = db or MySQLDB()
        self._user_id = user_id

        self._acc: Optional[Account] = None
        self._runner: Optional[Runner] = None
        self._ai = get_ai_responder()

        self._pending_account_choice: Dict[str, List[Dict]] = {}
        self._pending_lot_extend: Dict[str, PendingLotExtend] = {}
        self._processed_order_ids: set[str] = set()
        self._processed_order_statuses: set[tuple[str, str]] = set()

        self._last_refresh_ts = 0.0
        self._token_lock = threading.Lock()
        self._refresh_requested = threading.Event()
        self._expire_delay_since: Dict[int, datetime] = {}
        self._expire_delay_notified: set[int] = set()
        self._expire_warning_sent: Dict[int, set[int]] = {}
        self._expire_warning_start: Dict[int, str] = {}

    def _get_unit_minutes(self, account: dict) -> int:
        base_minutes = get_duration_minutes(account)
        if base_minutes <= 0:
            return 0
        if account.get("owner"):
            units = int(account.get("rental_duration") or 0)
            if units > 0 and base_minutes % units == 0:
                per_unit = base_minutes // units
                return max(per_unit, 1)
        return max(base_minutes, 1)

    def _set_rental_duration_for_order(self, account_id: int, units: int, unit_minutes: int) -> None:
        total_minutes = int(units) * int(unit_minutes)
        conn, cursor = self._db.open_connection()
        try:
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration = ?, rental_duration_minutes = ?
                WHERE ID = ?
                """,
                (int(units), total_minutes, account_id),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def _build_replacement_message(self, account: dict, lot_number: int | None = None) -> str:
        subject = "\u043b\u043e\u0442" if lot_number is not None else "\u0430\u043a\u043a\u0430\u0443\u043d\u0442"
        now = datetime.now(tz=MOSCOW_TZ)
        _, expiry_str, remaining_str = get_remaining_time(account, now)
        release_line = None
        if expiry_str and remaining_str:
            release_line = (
                f"\u0422\u0435\u043a\u0443\u0449\u0438\u0439 {subject} \u043e\u0441\u0432\u043e\u0431\u043e\u0434\u0438\u0442\u0441\u044f \u0432 {expiry_str} "
                f"(\u043e\u0441\u0442\u0430\u043b\u043e\u0441\u044c {remaining_str})."
            )

        try:
            target_mmr = int(account.get("mmr"))
        except Exception:
            target_mmr = None
        if target_mmr is None:
            lines = [
                f"\u041a \u0441\u043e\u0436\u0430\u043b\u0435\u043d\u0438\u044e, {subject} \u0443\u0436\u0435 \u0437\u0430\u043d\u044f\u0442.",
                "\u041f\u043e\u0434\u043e\u0431\u0440\u0430\u0442\u044c \u0437\u0430\u043c\u0435\u043d\u0443 \u0441\u0435\u0439\u0447\u0430\u0441 \u043d\u0435 \u0443\u0434\u0430\u0451\u0442\u0441\u044f.",
            ]
            if release_line:
                lines.append(release_line)
            lines.append(
                "\u0415\u0441\u043b\u0438 \u0445\u043e\u0442\u0438\u0442\u0435 \u0437\u0430\u043c\u0435\u043d\u0443 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443, \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u043c\u043d\u0435."
            )
            return "\n".join(lines)

        candidates = self._db.get_lot_accounts_by_mmr_range(
            int(target_mmr), MMR_RANGE_DEFAULT, self._user_id
        )
        candidates = [item for item in candidates if item.get("id") != account.get("id")]
        available = [item for item in candidates if not item.get("owner")]
        available_lines = []
        for item in available:
            display_name = self._display_account_name(item.get("account_name"))
            lot_label = (
                f"\u2116{item.get('lot_number')}" if item.get("lot_number") else "\u0431\u0435\u0437 \u043b\u043e\u0442\u0430"
            )
            if item.get("lot_url"):
                available_lines.append(
                    f"{lot_label} \u2014 {display_name} \u2014 {item.get('lot_url')}"
                )
            else:
                available_lines.append(f"{lot_label} \u2014 {display_name}")

        if available_lines:
            lines = [
                f"\u041a \u0441\u043e\u0436\u0430\u043b\u0435\u043d\u0438\u044e, {subject} \u0443\u0436\u0435 \u0437\u0430\u043d\u044f\u0442.",
                "\u0412\u043e\u0442 \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0435 \u0437\u0430\u043c\u0435\u043d\u044b \u0438\u0437 \u043f\u043e\u0445\u043e\u0436\u0438\u0445 \u043b\u043e\u0442\u043e\u0432:",
                "",
                *available_lines,
            ]
            if release_line:
                lines.extend(["", release_line])
            return "\n".join(lines)

        upcoming = []
        for item in candidates:
            if not item.get("owner"):
                continue
            expiry_time, expiry_label, remaining_label = get_remaining_time(item, now)
            if not expiry_time:
                continue
            upcoming.append((expiry_time, item, expiry_label, remaining_label))
        upcoming.sort(key=lambda entry: entry[0])

        lines = [
            f"\u041a \u0441\u043e\u0436\u0430\u043b\u0435\u043d\u0438\u044e, {subject} \u0443\u0436\u0435 \u0437\u0430\u043d\u044f\u0442.",
            "\u0421\u0435\u0439\u0447\u0430\u0441 \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0445 \u0437\u0430\u043c\u0435\u043d \u043d\u0435\u0442.",
        ]
        if upcoming:
            lines.append("\u0411\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0435 \u043e\u0441\u0432\u043e\u0431\u043e\u0436\u0434\u0435\u043d\u0438\u044f:")
            for _, item, expiry_label, remaining_label in upcoming[:5]:
                display_name = self._display_account_name(item.get("account_name"))
                lot_label = (
                    f"\u2116{item.get('lot_number')}" if item.get("lot_number") else "\u0431\u0435\u0437 \u043b\u043e\u0442\u0430"
                )
                lines.append(
                    f"{lot_label} \u2014 {display_name} \u2014 {expiry_label} (\u043e\u0441\u0442\u0430\u043b\u043e\u0441\u044c {remaining_label})"
                )
        if release_line:
            lines.append(release_line)
        lines.append(
            "\u0415\u0441\u043b\u0438 \u0445\u043e\u0442\u0438\u0442\u0435 \u0437\u0430\u043c\u0435\u043d\u0443 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443, \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u043c\u043d\u0435."
        )
        return "\n".join(lines)

    def _select_replacement_account(self, account: dict) -> dict | None:
        try:
            target_mmr = int(account.get("mmr"))
        except Exception:
            return None

        candidates = self._db.get_lot_accounts_by_mmr_range(
            int(target_mmr), MMR_RANGE_DEFAULT, self._user_id
        )
        available: list[dict] = []
        for item in candidates:
            if item.get("owner"):
                continue
            if item.get("id") == account.get("id"):
                continue
            if item.get("mmr") is None:
                continue
            available.append(item)
        if not available:
            return None

        def sort_key(item: dict) -> tuple[int, int, int]:
            try:
                diff = abs(int(item.get("mmr")) - target_mmr)
            except Exception:
                diff = 999999
            lot_number = item.get("lot_number")
            lot_sort = int(lot_number) if isinstance(lot_number, int) else 999999
            account_id = int(item.get("id") or 0)
            return (diff, lot_sort, account_id)

        available.sort(key=sort_key)
        return available[0]

    def _try_auto_replacement(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        account: dict,
        amount: int,
        original_lot: int | None = None,
    ) -> bool:
        replacement = self._select_replacement_account(account)
        if not replacement:
            return False

        display_name = self._display_account_name(replacement.get("account_name"))
        lot_number = replacement.get("lot_number")
        mmr_label = (
            f"{replacement.get('mmr')} MMR"
            if replacement.get("mmr") is not None
            else "MMR"
        )
        lot_label = f"\u2116{lot_number}" if lot_number else "\u043b\u043e\u0442"
        lot_url = replacement.get("lot_url")
        note = (
            "\u0410\u043a\u043a\u0430\u0443\u043d\u0442 \u0443\u0436\u0435 \u0432 \u0430\u0440\u0435\u043d\u0434\u0435. "
            f"\u0412\u044b\u0434\u0430\u043b\u0438 \u0437\u0430\u043c\u0435\u043d\u0443: {lot_label} \u2014 {display_name} ({mmr_label})."
        )
        if lot_url:
            note = f"{note}\n\u0421\u0441\u044b\u043b\u043a\u0430: {lot_url}"
        self._issue_new_account(acc, chat_id, event, replacement, amount, lot_number, note=note)
        self._mark_order_processed(event)

        target_mmr = account.get("mmr")
        send_message_to_admin(
            "AUTO REPLACEMENT ISSUED\n\n"
            f"Buyer: {event.order.buyer_username}\n"
            f"Original lot: {original_lot}\n"
            f"Original account: {account.get('account_name')} (ID {account.get('id')})\n"
            f"Replacement: {replacement.get('account_name')} (ID {replacement.get('id')}, lot {lot_number})\n"
            f"MMR target: {target_mmr} \u00b1 {MMR_RANGE_DEFAULT}",
        )
        return True

    def _extend_rental_for_order(self, account_id: int, owner: str, units: int, unit_minutes: int) -> bool:
        total_minutes = int(units) * int(unit_minutes)
        if total_minutes <= 0:
            return False
        conn, cursor = self._db.open_connection()
        try:
            cursor.execute(
                """
                UPDATE accounts
                SET rental_duration_minutes = COALESCE(rental_duration_minutes, rental_duration * 60) + ?,
                    rental_duration = COALESCE(rental_duration, 0) + ?
                WHERE ID = ? AND owner = ?
                """,
                (total_minutes, int(units), account_id, owner),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            conn.close()

    @property
    def account(self) -> Optional[Account]:
        return self._acc

    def refresh_session(self) -> None:
        logger.info("Refreshing FunPay session...")
        with self._token_lock:
            token = self._token
        if not token:
            logger.error("FunPay golden key is missing. FunPay automation stopped.")
            return
        self._acc = Account(token).get()
        self._runner = Runner(self._acc)
        logger.info("FunPay session refreshed successfully.")

    def request_token_update(self, token: str) -> None:
        if not token:
            return
        with self._token_lock:
            self._token = token
        self._refresh_requested.set()

    def start(self) -> None:
        logger.info("Starting FunPay bot...")
        if not self._token:
            logger.error("FunPay golden key is missing. FunPay automation stopped.")
            return

        self.refresh_session()
        self._last_refresh_ts = time.time()

        thread = threading.Thread(target=self._check_rental_expiration_loop, daemon=True)
        thread.start()
        logger.info("Rental expiration checker started.")

        if self._runner is None:
            raise RuntimeError("Runner not initialized")

        for event in self._runner.listen(requests_delay=8):
            try:
                self._tick_refresh_if_needed()

                if event.type is events.EventTypes.NEW_ORDER:
                    self._handle_new_order(event)

                if event.type is events.EventTypes.NEW_MESSAGE:
                    self._handle_new_message(event)

            except Exception as exc:
                logger.error(f"An error occurred while processing event: {exc}")

    def send_message_by_owner(self, owner: str, message: str) -> None:
        if self._acc is None:
            logger.error("FunPay session not initialized; cannot send message.")
            return
        chat = self._acc.get_chat_by_name(owner, True)
        if not chat or not getattr(chat, "id", None):
            logger.warning(f"FunPay chat not found for {owner}; cannot send message.")
            return
        self._acc.send_message(chat.id, message)

    def _tick_refresh_if_needed(self) -> None:
        now = time.time()
        if self._refresh_requested.is_set():
            self._refresh_requested.clear()
            logger.info("Refreshing session due to updated token...")
            self.refresh_session()
            self._last_refresh_ts = now
            return
        if now - self._last_refresh_ts < REFRESH_INTERVAL_SECONDS:
            return
        logger.info("Refreshing session due to interval timeout...")
        self.refresh_session()
        self._last_refresh_ts = now

    def _normalize_message_text(self, message: Any) -> str:
        if message is None:
            return ""
        text = (getattr(message, "text", None) or "").strip()
        if text:
            return text
        if getattr(message, "image_link", None):
            return "[image]"
        return ""

    def _log_chat_message(self, owner: str, role: str, message: str) -> None:
        if not owner or not message:
            return
        self._db.log_chat_message(owner, role, message, self._user_id)

    def _is_sensitive_message(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)

    def _is_issue_message(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in ISSUE_KEYWORDS)

    def _redact_mmr_label(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = MMR_REDACTION_REGEX.sub("", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned.strip(" -\u2014")

    def _display_account_name(self, name: Optional[str]) -> str:
        cleaned = self._redact_mmr_label(name or "")
        return cleaned or "\u0430\u043a\u043a\u0430\u0443\u043d\u0442"

    def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        sanitized: List[Dict[str, str]] = []
        for item in messages:
            text = (item.get("message") or "").strip()
            if not text:
                continue
            if self._is_sensitive_message(text):
                continue
            if len(text) > AI_MESSAGE_MAX_CHARS:
                text = text[:AI_MESSAGE_MAX_CHARS].rstrip() + "..."
            role = (item.get("role") or "user").strip().lower()
            if role not in ("user", "bot"):
                role = "user"
            sanitized.append({"role": role, "text": text})
        return sanitized

    def _format_datetime(self, value: Any) -> Optional[str]:
        if isinstance(value, datetime):
            return value.isoformat()
        if value is None:
            return None
        return str(value)

    def _refresh_chat_summary(self, owner: str) -> str:
        summary_entry = self._db.get_chat_summary(owner, self._user_id)
        summary_text = summary_entry["summary"] if summary_entry else ""
        last_message_id = summary_entry["last_message_id"] if summary_entry else 0

        if not AI_SUMMARY_ENABLED or not self._ai or not self._ai.enabled:
            return summary_text

        pending = self._db.get_chat_messages_after(owner, last_message_id, self._user_id)
        if len(pending) < AI_SUMMARY_TRIGGER:
            return summary_text

        chunk = pending[:AI_SUMMARY_TRIGGER]
        sanitized = self._sanitize_messages(chunk)
        if not sanitized:
            return summary_text

        updated = self._ai.summarize(summary_text, sanitized, AI_SUMMARY_MAX_CHARS)
        if not updated:
            return summary_text

        self._db.upsert_chat_summary(owner, updated, chunk[-1]["id"], self._user_id)
        return updated

    def _build_ai_context(self, owner: str) -> Dict[str, Any]:
        active_accounts = self._db.get_user_active_accounts(owner, self._user_id)
        available_lots = self._db.get_available_lot_accounts(self._user_id)
        summary_text = self._refresh_chat_summary(owner)
        recent_messages = self._db.get_chat_messages(owner, AI_CONTEXT_MESSAGES, self._user_id)
        recent_messages = self._sanitize_messages(recent_messages)

        safe_lots: List[Dict[str, Any]] = []
        for item in available_lots[:AI_STOCK_LIMIT]:
            safe_lots.append(
                {
                    "lot_number": item.get("lot_number"),
                    "account_name": self._redact_mmr_label(item.get("account_name")),
                    "lot_url": item.get("lot_url"),
                }
            )

        rental_history = self._db.get_user_rental_history(owner)
        safe_rentals: List[Dict[str, Any]] = []
        for item in rental_history[:AI_RENTAL_HISTORY_LIMIT]:
            safe_rentals.append(
                {
                    "account_name": self._redact_mmr_label(item.get("account_name")),
                    "rental_start": self._format_datetime(item.get("rental_start")),
                    "rental_duration_minutes": item.get("rental_duration_minutes"),
                }
            )

        order_history = self._db.get_order_history(
            owner, AI_ORDER_HISTORY_LIMIT, self._user_id
        )
        safe_orders: List[Dict[str, Any]] = []
        for item in order_history:
            safe_orders.append(
                {
                    "order_id": item.get("order_id"),
                    "account_name": self._redact_mmr_label(item.get("account_name")),
                    "lot_number": item.get("lot_number"),
                    "amount": item.get("amount"),
                    "price": item.get("price"),
                    "action": item.get("action"),
                    "created_at": self._format_datetime(item.get("created_at")),
                }
            )

        active_account_names: List[str] = []
        for item in active_accounts:
            name = self._redact_mmr_label(item.get("account_name"))
            if name:
                active_account_names.append(name)

        return {
            "active_rental_count": len(active_accounts),
            "active_account_ids": [
                item.get("id")
                for item in active_accounts
                if item.get("id") is not None
            ],
            "active_account_names": active_account_names,
            "available_lot_count": len(available_lots),
            "available_lots": safe_lots,
            "recent_messages": recent_messages,
            "history_summary": summary_text,
            "rental_history": safe_rentals,
            "order_history": safe_orders,
        }

    def _handle_new_order(self, event: Any) -> None:
        self._process_order(event, source="NEW_ORDER")

    def _handle_order_paid(self, event: Any) -> None:
        order = getattr(event, "order", None)
        if order is not None:
            self._log_order_status(order, "paid", "ORDER_PAID")
        self._process_order(event, source="ORDER_PAID")

    def _mark_order_processed(self, event: Any) -> None:
        order = getattr(event, "order", None)
        if not order:
            return
        order_id = getattr(order, "id", None)
        if order_id is None:
            return
        self._processed_order_ids.add(str(order_id))

    def _log_order_status(self, order: Any, action: str, source: str) -> None:
        order_id = getattr(order, "id", None)
        if not order_id or not action:
            return
        order_id = str(order_id)
        status_key = (order_id, action)
        if status_key in self._processed_order_statuses:
            return
        self._processed_order_statuses.add(status_key)

        buyer = str(getattr(order, "buyer_username", "") or "unknown")
        description = str(getattr(order, "description", "") or "")
        amount = getattr(order, "amount", None)
        price = getattr(order, "price", None)
        lot_number = parse_lot_number(description)

        self._db.log_order_event(
            order_id=order_id,
            owner_id=buyer,
            action=action,
            account_name=description or None,
            lot_number=lot_number,
            amount=amount,
            price=price,
            user_id=self._user_id,
        )

        send_message_to_admin(
            f"ORDER {action.upper()}\n\n"
            f"Order: {order_id}\n"
            f"Buyer: {buyer}\n"
            f"Description: {description}\n"
            f"Amount: {amount}\n"
            f"Price: {price}\n"
            f"Source: {source}"
        )

    def _process_order(self, event: Any, source: str) -> None:
        if self._acc is None:
            self.refresh_session()
        acc = self._acc
        if acc is None:
            return

        order = getattr(event, "order", None)
        if order is None:
            return

        order_id = getattr(order, "id", None)
        if not order_id:
            logger.warning(f"Skipping order with invalid id from {source}: {order_id}")
            return
        order_id = str(order_id)

        if order_id in self._processed_order_ids:
            return

        buyer = str(order.buyer_username)
        chat = acc.get_chat_by_name(buyer, True)
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            chat_id = getattr(order, "chat_id", None)
        if chat_id is None:
            logger.warning(f"Skipping order {order_id}: chat id not found")
            return

        description = str(getattr(order, "description", "") or "")
        amount = int(getattr(order, "amount", 1) or 1)

        lot_number = parse_lot_number(description)
        if lot_number is not None:
            self._process_lot_order(acc, chat_id, event, buyer, lot_number, amount)
            return

        self._process_named_order(acc, chat_id, event, buyer, description, amount)

    def _process_lot_order(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        buyer: str,
        lot_number: int,
        amount: int,
    ) -> None:
        mapping = self._db.get_lot_mapping(lot_number, self._user_id)
        if not mapping:
            acc.send_message(chat_id, "Лот не привязан к аккаунту. Дождитесь ответа администратора.")
            send_message_to_admin(
                "ЛОТ БЕЗ ПРИВЯЗКИ\n\n"
                f"Покупатель: {buyer}\n"
                f"Лот: №{lot_number}\n"
                f"Заказ: {event.order.id}"
            )
            return

        account = self._db.get_account_by_lot_number(lot_number, self._user_id)
        if not account:
            acc.send_message(chat_id, "Ошибка: лот привязан к аккаунту, но аккаунт не найден. Напишите администратору.")
            send_message_to_admin(
                "ОШИБКА ПРИ ВЫДАЧЕ\n\n"
                f"Покупатель: {buyer}\n"
                f"Лот: №{lot_number}\n"
                f"Заказ: {event.order.id}\n"
                "Причина: аккаунт по лоту не найден в БД"
            )
            return

        pending = self._pending_lot_extend.get(buyer)
        if pending is not None and (time.time() - pending.created_ts) > PENDING_EXTEND_TTL_SECONDS:
            self._pending_lot_extend.pop(buyer, None)
            pending = None

        is_requested_extend = pending is not None and pending.lot_number == lot_number
        if is_requested_extend:
            self._pending_lot_extend.pop(buyer, None)

        if account.get("owner") is None:
            self._issue_new_account(acc, chat_id, event, account, amount, lot_number)
            self._mark_order_processed(event)
            return

        if account.get("owner") == buyer:
            unit_minutes = self._get_unit_minutes(account)
            success = self._extend_rental_for_order(account["id"], buyer, amount, unit_minutes)
            if not success:
                acc.send_message(chat_id, USER.extend_failed)
                return

            refreshed = self._db.get_account_by_id(account["id"])
            current_time = datetime.now(tz=MOSCOW_TZ)
            _, expiry_str, remaining_str = get_remaining_time(refreshed, current_time)
            duration_label = format_duration_minutes(unit_minutes * amount)
            display_name = self._display_account_name(account.get("account_name"))

            note = ""
            if is_requested_extend and pending and pending.hours != amount:
                pending_label = format_duration_minutes(unit_minutes * pending.hours)
                note = (
                    f"\n\nПримечание: вы запросили {pending_label}, "
                    f"но оплатили {duration_label} (будет продлено на {amount} шт)."
                )

            acc.send_message(
                chat_id,
                f"Продлено на {duration_label}.\n"
                f"Лот: №{lot_number}\n"
                f"ID: {account['id']}\n"
                f"Аккаунт: {display_name}\n"
                f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}{note}",
            )
            self._db.log_order_event(
                order_id=str(event.order.id),
                owner_id=buyer,
                action="extended",
                account_name=account.get("account_name"),
                lot_number=lot_number,
                amount=amount,
                price=getattr(event.order, "price", None),
                user_id=self._user_id,
            )
            acc.confirm(event.order.id)
            self._mark_order_processed(event)
            return

        if self._try_auto_replacement(acc, chat_id, event, account, amount, original_lot=lot_number):
            return
        acc.send_message(chat_id, self._build_replacement_message(account, lot_number))
        send_message_to_admin(
            "КОНФЛИКТ ПО ЛОТУ\n\n"
            f"Покупатель: {buyer}\n"
            f"Лот: №{lot_number}\n"
            f"Заказ: {event.order.id}\n"
            f"Текущий владелец: {account.get('owner')}"
        )

    def _process_named_order(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        buyer: str,
        order_name: str,
        amount: int,
    ) -> None:
        all_accounts = self._db.get_all_account_names()
        matched_account = match_account_name(order_name, all_accounts)
        if matched_account is None:
            logger.warning(f"No matching account found for order: {order_name}")
            return

        account_name = matched_account
        display_name = self._display_account_name(account_name)
        if account_name not in all_accounts:
            logger.info(f"Item '{account_name}' not found in rentals; skipping.")
            return

        specific_account = self._db.get_account_by_name(account_name)
        if not specific_account:
            logger.error(f"Account with name '{account_name}' not found in database")
            acc.send_message(
                chat_id,
                f"Ошибка: аккаунт '{display_name}' не найден.\n"
                "Возврат оформлен. Напишите, поможем.",
            )
            return

        if specific_account.get("owner") is not None:
            logger.warning(f"Account '{account_name}' is already rented by {specific_account['owner']}")
            if self._try_auto_replacement(acc, chat_id, event, specific_account, amount):
                return
            acc.send_message(chat_id, self._build_replacement_message(specific_account))
            return

        if amount > 1:
            unit_minutes = self._get_unit_minutes(specific_account)
            unit_label = format_duration_minutes(unit_minutes)
            total_label = format_duration_minutes(unit_minutes * amount)
            acc.send_message(
                chat_id,
                f"Вы оплатили {amount} шт. '{display_name}'.\n"
                f"Продление будет на {total_label} (1 шт = {unit_label}).\n\n"
                "Если нужен другой вариант — напишите в чат.",
            )

        existing_rentals = self._db.get_user_accounts_by_name(buyer, account_name)
        if existing_rentals:
            self._extend_existing_rental(acc, chat_id, event, existing_rentals[0], account_name, amount)
            self._mark_order_processed(event)
            return

        self._issue_new_account(acc, chat_id, event, specific_account, amount)
        self._mark_order_processed(event)

    def _extend_existing_rental(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        rental: dict,
        order_name: str,
        units: int,
    ) -> None:
        unit_minutes = self._get_unit_minutes(rental)
        duration_label = format_duration_minutes(unit_minutes * units)
        display_name = self._display_account_name(order_name)
        logger.info(
            f"User {event.order.buyer_username} already has active rental for {order_name}, extending by {duration_label}..."
        )
        success = self._extend_rental_for_order(
            rental["id"],
            event.order.buyer_username,
            units,
            unit_minutes,
        )
        if not success:
            acc.send_message(chat_id, USER.extend_failed)
            return

        acc.send_message(
            chat_id,
            "Аренда продлена!\n\n"
            f"Тип аккаунта: {display_name}\n"
            f"Продление: +{duration_label}\n"
            f"ID: {rental['id']}\n\n"
            "Данные аккаунта ниже.",
        )

        account = self._db.get_account_by_id(rental["id"])
        if account:
            rental_start = account["rental_start"]
            if isinstance(rental_start, datetime):
                start_dt = rental_start
            else:
                start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
            duration_minutes = get_duration_minutes(account)
            expiry_time = start_dt + timedelta(minutes=duration_minutes)
            acc.send_message(
                chat_id,
                f"ID: {rental['id']}\n"
                f"Логин: {rental['login']}\n"
                f"Пароль: {rental['password']}\n"
                f"Истекает: {expiry_time.strftime('%H:%M:%S')} МСК\n"
                f"{COMMANDS_INLINE}",
            )

        send_message_to_admin(
            "RENTAL EXTENDED\n\n"
            f"User: {event.order.buyer_username}\n"
            f"Account type: {order_name}\n"
            f"Extension: +{duration_label}\n"
            f"Price: {event.order.price} RUB\n"
            f"Account ID: {rental['id']}\n"
            "Note: user already had an active rental",
        )

        self._db.log_order_event(
            order_id=str(event.order.id),
            owner_id=event.order.buyer_username,
            action="extended",
            account_name=order_name,
            lot_number=None,
            amount=units,
            price=getattr(event.order, "price", None),
            user_id=self._user_id,
        )
        acc.confirm(event.order.id)

    def _issue_new_account(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        account: dict,
        units: int,
        lot_number: int | None = None,
        note: str | None = None,
    ) -> None:
        logger.info(f"Assigning specific account '{account['account_name']}' to user {event.order.buyer_username}")
        self._db.set_account_owner(account["id"], event.order.buyer_username, self._user_id)
        unit_minutes = self._get_unit_minutes(account)
        duration_label = format_duration_minutes(unit_minutes * units)
        self._set_rental_duration_for_order(account["id"], units, unit_minutes)
        display_name = self._display_account_name(account.get("account_name"))

        send_message_to_admin(
            "NEW ACCOUNT ISSUED\n\n"
            f"Buyer: {event.order.buyer_username}\n"
            f"ID: {account['id']}\n"
            f"Account name: {account['account_name']}\n"
            f"Login: {account['login']}\n"
            f"Password: {account['password']}\n"
            f"Price: {event.order.price} RUB\n"
            f"Ordered: {units} pcs.\n"
            f"Rental time: {duration_label}\n"
            f"Note: specific account '{account['account_name']}' issued for {duration_label}",
        )

        message = (
            "Ваш аккаунт:\n"
            f"ID: {account['id']}\n"
            f"Название: {display_name}\n"
            f"Логин: {account['login']}\n"
            f"Пароль: {account['password']}\n"
            f"Аренда: {duration_label}\n\n"
            f"{COMMANDS_HELP}\n\n"
            "Если нужна помощь — напишите в чат.",
        )
        if note:
            message = f"{note}\n\n{message}"
        acc.send_message(chat_id, message)

        self._db.log_order_event(
            order_id=str(event.order.id),
            owner_id=event.order.buyer_username,
            action="issued",
            account_name=account.get("account_name"),
            lot_number=lot_number,
            amount=units,
            price=getattr(event.order, "price", None),
            user_id=self._user_id,
        )
        acc.confirm(event.order.id)

    def _handle_new_message(self, event: Any) -> None:
        if self._acc is None:
            return
        acc = self._acc
        chat = acc.get_chat_by_name(event.message.author, True)
        chat_id = getattr(chat, "id", None) or getattr(event.message, "chat_id", None)
        if chat_id is None:
            logger.warning(f"Chat id not found for message from {event.message.author}")
            return

        if event.message.author_id == acc.id:
            target = getattr(event.message, "chat_name", None) or event.message.author
            text = self._normalize_message_text(event.message)
            if target and text:
                self._log_chat_message(target, "bot", text)
            return

        owner = event.message.author
        text = self._normalize_message_text(event.message)
        if owner and text:
            self._log_chat_message(owner, "user", text)

        if event.message.type in (
            types.MessageTypes.NEW_FEEDBACK,
            types.MessageTypes.FEEDBACK_CHANGED,
        ):
            self._handle_feedback_event(acc, event)
            return
        if event.message.type is types.MessageTypes.FEEDBACK_DELETED:
            self._handle_feedback_deleted(acc, event, chat_id)
            return
        if event.message.type in (
            types.MessageTypes.ORDER_CONFIRMED,
            types.MessageTypes.ORDER_CONFIRMED_BY_ADMIN,
        ):
            self._handle_order_status_message(
                acc, event, "closed", "ORDER_CONFIRMED_MESSAGE"
            )
            return
        if event.message.type in (
            types.MessageTypes.REFUND,
            types.MessageTypes.PARTIAL_REFUND,
            types.MessageTypes.REFUND_BY_ADMIN,
        ):
            self._handle_order_status_message(acc, event, "refunded", "REFUND_MESSAGE")
            return
        if event.message.type is types.MessageTypes.ORDER_PURCHASED:
            order_id = self._extract_order_id(event.message.text or "")
            if order_id:
                try:
                    order = acc.get_order(order_id)
                    self._log_order_status(order, "paid", "ORDER_PURCHASED_MESSAGE")
                    self._process_order(
                        SimpleNamespace(order=order),
                        source="ORDER_PURCHASED_MESSAGE",
                    )
                except Exception as exc:
                    logger.warning(f"Failed to process paid order {order_id}: {exc}")
            return

        logger.info(f"{event.message.author} : {event.message.text}")
        raw_text = (event.message.text or "").strip()
        message_text = raw_text.lower()

        if message_text and not message_text.startswith("!"):
            if self._try_handle_pending_choice(acc, chat_id, event.message.author, raw_text):
                return

        if message_text in ("!code", "!код"):
            self._handle_code(acc, chat_id, event.message.author)
            return

        if message_text in ("!acc", "!акк"):
            self._handle_acc(acc, chat_id, event.message.author)
            return

        if message_text.startswith("!extend") or message_text.startswith("!продлить"):
            self._handle_extend(acc, chat_id, event.message.author, raw_text)
            return

        if message_text in ("!stock", "!сток"):
            self._handle_stock(acc, chat_id)
            return

        if message_text.startswith("!отмена"):
            self._handle_cancel(acc, chat_id, event.message.author, raw_text)
            return

        if message_text in ("!bonus", "!бонус"):
            self._handle_bonus(acc, chat_id, event.message.author)
            return

        if not raw_text:
            return

        if not self._ai or not self._ai.enabled:
            return

        context = self._build_ai_context(event.message.author)
        if self._is_issue_message(raw_text):
            if context.get("active_rental_count"):
                acc.send_message(chat_id, ISSUE_REPLY)
                self._handle_code(acc, chat_id, event.message.author)
            else:
                stock_message = self._build_stock_message()
                acc.send_message(chat_id, f"{ISSUE_NO_RENTAL_REPLY}\n\n{stock_message}")
            return
        response = self._ai.respond(raw_text, context)
        if not response:
            return
        has_active_rental = bool(context.get("active_rental_count"))
        no_rental_reply = self._ai.payment_required_reply or ISSUE_NO_RENTAL_REPLY

        if response.action == "send_code":
            if has_active_rental:
                self._handle_code(acc, chat_id, event.message.author)
            else:
                stock_message = self._build_stock_message()
                acc.send_message(chat_id, f"{no_rental_reply}\n\n{stock_message}")
            return

        if response.action == "send_account":
            if has_active_rental:
                self._handle_acc(acc, chat_id, event.message.author)
            else:
                stock_message = self._build_stock_message()
                acc.send_message(chat_id, f"{no_rental_reply}\n\n{stock_message}")
            return

        if response.action == "handoff":
            if response.reply:
                acc.send_message(chat_id, response.reply)
            send_message_to_admin(
                f"AI handoff requested for {event.message.author}: {raw_text}"
            )
            return

        if response.action == "stock":
            stock_message = self._build_stock_message()
            if has_active_rental:
                if response.reply:
                    acc.send_message(chat_id, f"{response.reply}\n\n{stock_message}")
                else:
                    acc.send_message(chat_id, stock_message)
            else:
                acc.send_message(chat_id, f"{no_rental_reply}\n\n{stock_message}")
            return

        if response.action == "extend":
            hours = response.args.get("hours")
            lot_number = response.args.get("lot_number")
            try:
                hours = int(hours)
                lot_number = int(lot_number)
            except (TypeError, ValueError):
                hours = None
                lot_number = None

            if hours and lot_number:
                self._handle_extend(
                    acc,
                    chat_id,
                    event.message.author,
                    f"extend {hours} {lot_number}",
                )
            elif response.reply:
                acc.send_message(chat_id, response.reply)
            else:
                self._handle_extend(acc, chat_id, event.message.author, raw_text)
            return

        if response.action == "cancel":
            account_id = response.args.get("account_id")
            try:
                account_id = int(account_id)
            except (TypeError, ValueError):
                account_id = None

            if account_id:
                self._handle_cancel(
                    acc,
                    chat_id,
                    event.message.author,
                    f"cancel {account_id}",
                )
            elif response.reply:
                acc.send_message(chat_id, response.reply)
            else:
                self._handle_cancel(acc, chat_id, event.message.author, raw_text)
            return

        if response.action == "none" and not has_active_rental:
            stock_message = self._build_stock_message()
            acc.send_message(chat_id, f"{no_rental_reply}\n\n{stock_message}")
            return

        if response.reply:
            acc.send_message(chat_id, response.reply)

    def _extract_order_id(self, text: str) -> Optional[str]:
        match = RegularExpressions().ORDER_ID.search(text or "")
        if not match:
            return None
        return match.group(0).lstrip("#")

    def _handle_order_status_message(
        self,
        acc: Account,
        event: Any,
        action: str,
        source: str,
    ) -> None:
        order_id = self._extract_order_id(event.message.text or "")
        if not order_id:
            return
        try:
            order = acc.get_order(order_id)
        except Exception as exc:
            logger.warning(f"Failed to fetch order {order_id} for {action}: {exc}")
            send_message_to_admin(
                f"ORDER {action.upper()}\n\n"
                f"Order: {order_id}\n"
                f"Source: {source}\n"
                f"Error: {exc}"
            )
            return
        self._log_order_status(order, action, source)

    def _handle_feedback_event(self, acc: Account, event: Any) -> None:
        order_id = self._extract_order_id(event.message.text or "")
        if not order_id:
            return
        try:
            order = acc.get_order(order_id)
        except Exception as exc:
            logger.warning(f"Failed to fetch order {order_id} for feedback: {exc}")
            return
        review = getattr(order, "review", None)
        if not review or review.stars is None:
            return
        owner = review.author or getattr(order, "buyer_username", None) or event.message.author
        if not owner:
            return
        review_text = review.text or ""
        self._db.upsert_feedback_reward(order_id, owner, int(review.stars), review_text)

    def _handle_feedback_deleted(self, acc: Account, event: Any, chat_id: int | None = None) -> None:
        order_id = self._extract_order_id(event.message.text or "")
        if not order_id:
            return
        try:
            order = acc.get_order(order_id)
        except Exception as exc:
            logger.warning(f"Failed to fetch order {order_id} for feedback delete: {exc}")
            return
        owner = getattr(order, "buyer_username", None) or event.message.author
        if not owner:
            return

        reward = self._db.get_feedback_reward(order_id)
        if not reward:
            return
        if reward.get("revoked_at"):
            return
        if not reward.get("claimed_at"):
            return

        reward_owner = reward.get("owner") or owner
        target_account = None
        claimed_account_id = reward.get("account_id")
        if claimed_account_id:
            candidate = self._db.get_account_by_id(int(claimed_account_id), self._user_id)
            if candidate and candidate.get("owner") == reward_owner:
                target_account = candidate
        if target_account is None:
            accounts = self._db.get_user_active_accounts(reward_owner, self._user_id)
            if accounts:
                target_account = accounts[0]

        if target_account is None:
            send_message_to_admin(
                "BONUS REVOKE SKIPPED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {reward_owner}\n"
                "Reason: no active rental to deduct.",
            )
            self._db.mark_feedback_reward_revoked(order_id)
            return

        if not self._db.reduce_rental_duration_for_owner(
            target_account["id"], reward_owner, HOURS_FOR_REVIEW, 0
        ):
            send_message_to_admin(
                "BONUS REVOKE FAILED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {reward_owner}\n"
                f"Account ID: {target_account['id']}",
            )
            return

        self._db.mark_feedback_reward_revoked(order_id)
        duration_label = format_duration_minutes(HOURS_FOR_REVIEW * 60)
        message = (
            f"\u041e\u0442\u043d\u044f\u043b\u0438 {duration_label} \u043e\u0442 "
            f"\u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u0430\u0440\u0435\u043d\u0434\u044b, "
            f"\u0442\u0430\u043a \u043a\u0430\u043a \u0437\u0430\u043c\u0435\u0442\u0438\u043b\u0438, "
            f"\u0447\u0442\u043e \u0432\u044b \u0443\u0434\u0430\u043b\u0438\u043b\u0438 "
            f"\u043e\u0442\u0437\u044b\u0432 \u043a \u0437\u0430\u043a\u0430\u0437\u0443 #{order_id}."
        )
        if chat_id is None:
            chat = acc.get_chat_by_name(reward_owner, True)
            chat_id = getattr(chat, "id", None)
        if chat_id:
            acc.send_message(chat_id, message)
        send_message_to_admin(
            "BONUS REVOKED\n\n"
            f"Order: {order_id}\n"
            f"Owner: {reward_owner}\n"
            f"Account ID: {target_account['id']}\n"
            f"Removed: {duration_label}",
        )

    def _handle_bonus(self, acc: Account, chat_id: int, owner: str) -> None:
        reward = self._db.get_unclaimed_feedback_reward(owner, min_rating=5)
        if not reward:
            acc.send_message(chat_id, "Не найдено 5★ отзыва без бонуса.")
            return

        order_id = reward["order_id"]
        try:
            order = acc.get_order(order_id)
        except Exception as exc:
            logger.warning(f"Failed to fetch order {order_id} for bonus: {exc}")
            acc.send_message(chat_id, "Не удалось проверить отзыв. Попробуйте позже.")
            return

        review = getattr(order, "review", None)
        if not review or review.stars is None or int(review.stars) < 5:
            acc.send_message(chat_id, "Отзыв не соответствует требованию 5★.")
            return

        accounts = self._db.get_user_active_accounts(owner)
        if not accounts:
            acc.send_message(chat_id, "Нет активных аренд для начисления бонуса.")
            return

        target = accounts[0]
        account_id = target["id"]
        if not self._db.extend_rental_duration_for_owner(account_id, owner, HOURS_FOR_REVIEW, 0):
            acc.send_message(chat_id, "Не удалось начислить бонус. Попробуйте позже.")
            return

        self._db.mark_feedback_reward_claimed(order_id, account_id)
        updated = self._db.get_account_by_id(account_id, self._user_id)
        total_minutes = get_duration_minutes(updated or {})
        if total_minutes <= 0:
            total_minutes = get_duration_minutes(target) + HOURS_FOR_REVIEW * 60
        total_label = format_duration_minutes(total_minutes)
        acc.send_message(
            chat_id,
            f"\u0411\u043e\u043d\u0443\u0441 \u043d\u0430\u0447\u0438\u0441\u043b\u0435\u043d: +{HOURS_FOR_REVIEW} \u0447. \u0437\u0430 \u043e\u0442\u0437\u044b\u0432 5\u2605. \u0417\u0430\u043a\u0430\u0437 #{order_id}.\n"
            f"\u041e\u0431\u0449\u0435\u0435 \u0432\u0440\u0435\u043c\u044f \u0430\u0440\u0435\u043d\u0434\u044b: {total_label}.",
        )

    def _try_handle_pending_choice(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> bool:
        if owner in self._pending_account_choice:
            accounts = self._pending_account_choice[owner]
            choice = match_account_choice(raw_text, accounts)
            if choice:
                current_time = datetime.now(tz=MOSCOW_TZ)
                _, expiry_str, remaining_str = get_remaining_time(choice, current_time)
                display_name = self._display_account_name(choice.get("account_name"))
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {choice['id']}\n"
                    + f"Аккаунт: {display_name}\n"
                    + f"Логин: {choice['login']}\n"
                    + f"Пароль: {choice['password']}\n"
                    + f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                )
                self._pending_account_choice.pop(owner, None)
            else:
                acc.send_message(chat_id, USER.choice_not_understood)
            return True

        return False

    def _handle_code(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            owner_data = self._db.get_owner_mafile(owner)
            if owner_data:
                lines = ["Коды Steam Guard:"]
                for account in owner_data:
                    (
                        _account_id,
                        account_name,
                        mafile_path,
                        mafile_json,
                        login,
                        _rental_duration,
                    ) = account
                    display_name = self._display_account_name(account_name)
                    guard_code = get_steam_guard_code(
                        mafile_path=mafile_path,
                        mafile_json=mafile_json,
                    )
                    lines.append(f"{display_name} ({login}): {guard_code}")
                acc.send_message(chat_id, "\n".join(lines))
            else:
                acc.send_message(chat_id, USER.active_rentals_empty)
        except Exception as exc:
            acc.send_message(chat_id, f"Ошибка при получении кода: {exc}")

    def _handle_acc(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            current_time = datetime.now(tz=MOSCOW_TZ)
            if len(accounts) == 1:
                account = accounts[0]
                _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                display_name = self._display_account_name(account.get("account_name"))
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {account['id']}\n"
                    + f"Аккаунт: {display_name}\n"
                    + f"Логин: {account['login']}\n"
                    + f"Пароль: {account['password']}\n"
                    + f"Истекает: {expiry_str} МСК | Осталось: {remaining_str}",
                )
                return

            lines = [USER.choose_account_prompt]
            for account in accounts:
                _, _, remaining_str = get_remaining_time(account, current_time)
                display_name = self._display_account_name(account.get("account_name"))
                lines.append(f"{account['id']}) {display_name} ({account['login']}) — осталось {remaining_str}")
            self._pending_account_choice[owner] = accounts
            acc.send_message(chat_id, "\n".join(lines))
        except Exception as exc:
            logger.error(f"Failed to send account details to {owner}: {exc}")
            acc.send_message(chat_id, USER.acc_failed)

    def _handle_extend(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            parts = raw_text.split()
            if len(parts) == 1:
                accounts = self._db.get_user_active_lot_accounts(owner)
                if not accounts:
                    acc.send_message(chat_id, USER.active_rentals_empty)
                    return

                current_time = datetime.now(tz=MOSCOW_TZ)
                lines = [
                    "Чтобы продлить аренду, оплатите нужный лот и укажите количество часов.",
                    "Команда: !продлить <часы> <номер_лота>",
                    "",
                    "Ваши активные аренды:",
                ]
                for account in accounts:
                    _, expiry_str, remaining_str = get_remaining_time(account, current_time)
                    lot_number = account.get("lot_number")
                    lot_url = account.get("lot_url")
                    display_name = self._display_account_name(account.get("account_name"))
                    if lot_number:
                        line = f"Лот №{lot_number}: {display_name} — истекает {expiry_str} МСК (осталось {remaining_str})"
                        if lot_url:
                            line += f" — {lot_url}"
                        lines.append(line)
                    else:
                        lines.append(
                            f"ID {account['id']}: {display_name} — лот не настроен (напишите администратору)."
                        )
                acc.send_message(chat_id, "\n".join(lines))
                return

            if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
                acc.send_message(chat_id, "Использование: !продлить <часы> <номер_лота>")
                return

            hours = int(parts[1])
            lot_number = int(parts[2])
            if hours <= 0:
                acc.send_message(chat_id, USER.extend_hours_positive)
                return
            if lot_number <= 0:
                acc.send_message(chat_id, "Номер лота должен быть больше 0.")
                return

            mapping = self._db.get_lot_mapping(lot_number, self._user_id)
            if not mapping:
                acc.send_message(chat_id, f"Лот №{lot_number} не привязан к аккаунту. Напишите администратору.")
                return

            lot_url = mapping.get("lot_url")
            link_line = f"\nСсылка: {lot_url}" if lot_url else ""
            acc.send_message(
                chat_id,
                f"Оплатите лот №{lot_number} в количестве {hours} шт, чтобы продлить аренду на {hours} ч."
                f"{link_line}\n\nПосле оплаты бот автоматически продлит аренду.",
            )
            self._pending_lot_extend[owner] = PendingLotExtend(
                hours=hours, lot_number=lot_number, created_ts=time.time()
            )
        except Exception as exc:
            logger.error(f"Failed to extend rental for {owner}: {exc}")
            acc.send_message(chat_id, USER.extend_failed)

    def _handle_stock(self, acc: Account, chat_id: int) -> None:
        try:
            acc.send_message(chat_id, self._build_stock_message())
        except Exception as exc:
            logger.error(f"Failed to load stock: {exc}")
            acc.send_message(chat_id, USER.stock_failed)

    def _build_stock_message(self) -> str:
        available_lots = self._db.get_available_lot_accounts(self._user_id)
        if available_lots:
            lines = [USER.stock_title]
            for account in available_lots:
                lot_label = f"№{account['lot_number']}"
                display_name = self._display_account_name(account.get("account_name"))
                lot_url = account.get("lot_url")
                if lot_url:
                    lines.append(f"{display_name} - {lot_label} - {lot_url}")
                else:
                    lines.append(f"{display_name} - {lot_label}")
            return "\n".join(lines)

        all_lots = self._db.get_all_lot_accounts(self._user_id)
        if not all_lots:
            return USER.stock_no_lots_configured

        current_time = datetime.now(tz=MOSCOW_TZ)
        next_expiry = self._find_next_expiry(all_lots)
        if not next_expiry:
            return "Свободных лотов нет. Не удалось определить время освобождения."

        remaining = next_expiry - current_time
        if remaining.total_seconds() < 0:
            remaining = timedelta(0)
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return (
            "Свободных лотов нет. Ближайший освободится через "
            f"{hours} ч {minutes} мин (в {next_expiry.strftime('%H:%M:%S')} МСК)."
        )

    def _handle_cancel(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            parts = raw_text.split()
            if len(parts) < 2:
                lines = [
                    "Выберите аренду для отмены.",
                    "Команда: !отмена <ID>",
                    "",
                    "Активные аренды:",
                ]
                current_time = datetime.now(tz=MOSCOW_TZ)
                for account in accounts:
                    _, _, remaining_str = get_remaining_time(account, current_time)
                    display_name = self._display_account_name(account.get("account_name"))
                    lines.append(f"ID {account['id']}: {display_name} — осталось {remaining_str}")
                acc.send_message(chat_id, "\n".join(lines))
                return

            if not parts[1].isdigit():
                acc.send_message(chat_id, "Использование: !отмена <ID>")
                return

            account_id = int(parts[1])
            account = next((item for item in accounts if item["id"] == account_id), None)
            if not account:
                acc.send_message(chat_id, "Аккаунт с таким ID не найден в ваших активных арендах.")
                return

            acc.send_message(chat_id, "Отмена аренды... Это может занять некоторое время.")
            deauth_ok = False
            try:
                deauth_ok = asyncio.run(
                    logout_all_steam_sessions(
                        steam_login=account.get("login") or account.get("account_name") or "",
                        steam_password=account.get("password") or "",
                        mafile_json=account.get("mafile_json") or "",
                    )
                )
            except Exception as exc:
                logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")

            self._db.release_account(account_id)
            self._db.update_account(
                account_id,
                {"rental_duration": 1, "rental_duration_minutes": 60},
            )

            send_message_to_admin(
                "RENTAL CANCELLED\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Deauthorize: {'ok' if deauth_ok else 'failed'}\n"
            )
            acc.send_message(chat_id, "Аренда отменена. Доступ закрыт.")
        except Exception as exc:
            logger.error(f"Failed to cancel rental for {owner}: {exc}")
            acc.send_message(chat_id, USER.extend_failed)

    def _find_next_expiry(self, all_lots: List[Dict]) -> Optional[datetime]:
        current_time = datetime.now(tz=MOSCOW_TZ)
        next_expiry = None
        for account in all_lots:
            if account.get("owner") is None:
                continue
            rental_start = account.get("rental_start")
            duration_minutes = get_duration_minutes(account)
            if not rental_start or duration_minutes <= 0:
                continue

            if isinstance(rental_start, datetime):
                start_dt = rental_start
            else:
                try:
                    start_dt = datetime.strptime(rental_start, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

            if start_dt.tzinfo is None:
                start_dt = MOSCOW_TZ.localize(start_dt)

            expiry_time = start_dt + timedelta(minutes=duration_minutes)
            if next_expiry is None or expiry_time < next_expiry:
                next_expiry = expiry_time

        if next_expiry and next_expiry < current_time:
            return current_time
        return next_expiry

    def _check_rental_expiration_loop(self) -> None:
        logger.info("Starting rental expiration checker...")
        invalid_accs: list[int] = []
        while True:
            try:
                self._check_rental_expiration_once(invalid_accs)
            except Exception as exc:
                logger.error(f"Error in rental expiration checker: {exc}")
            time.sleep(RENTAL_CHECK_INTERVAL)

    def _check_rental_expiration_once(self, invalid_accs: list[int]) -> None:
        conn, cursor = self._db.open_connection()
        try:
            cursor.execute(
                """
                SELECT a.ID, a.owner, a.rental_start, a.rental_duration, a.rental_duration_minutes, a.path_to_maFile, a.mafile_json, a.password, a.login, a.account_name
                FROM accounts a
                WHERE a.owner IS NOT NULL
                AND a.rental_start IS NOT NULL
                """
            )
            accounts_data = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        current_time = datetime.now(tz=MOSCOW_TZ)
        for row in accounts_data:
            (
                account_id,
                owner,
                start_time,
                duration,
                duration_minutes,
                mafile_path,
                mafile_json,
                password,
                login,
                account_name,
            ) = row
            if not owner:
                continue

            if isinstance(start_time, datetime):
                start_datetime = start_time
            else:
                start_datetime = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            start_datetime = MOSCOW_TZ.localize(start_datetime)
            try:
                total_minutes = int(duration_minutes) if duration_minutes is not None else int(duration) * 60
            except Exception:
                total_minutes = 0
            if total_minutes <= 0:
                continue
            expiry_time = start_datetime + timedelta(minutes=total_minutes)

            time_remaining = expiry_time - current_time
            minutes_remaining = time_remaining.total_seconds() / 60
            start_key = f"{start_datetime.isoformat()}|{total_minutes}"
            if self._expire_warning_start.get(account_id) != start_key:
                self._expire_warning_start[account_id] = start_key
                self._expire_warning_sent.pop(account_id, None)

            sent = self._expire_warning_sent.setdefault(account_id, set())
            if 0 < minutes_remaining <= 10 and 10 not in sent:
                self._send_expiration_warning(owner, account_id, minutes_remaining, expiry_time, 10)
                sent.add(10)

            if current_time >= expiry_time and account_id not in invalid_accs:
                steam_login = login or account_name
                if self._should_delay_expire_due_to_dota_match(
                    account_id=account_id,
                    owner=owner,
                    current_time=current_time,
                    mafile_json=mafile_json,
                ):
                    continue
                self._expire_rental(
                    invalid_accs=invalid_accs,
                    owner=owner,
                    account_id=account_id,
                    mafile_path=mafile_path,
                    mafile_json=mafile_json,
                    password=password,
                    steam_login=steam_login,
                    expiry_time=expiry_time,
                )

    def _steamid64_from_mafile(self, mafile_json: Optional[str]) -> Optional[int]:
        if not mafile_json:
            return None
        try:
            data = json.loads(mafile_json) if isinstance(mafile_json, str) else mafile_json
            value = (data or {}).get("Session", {}).get("SteamID")
            if value is None:
                value = (data or {}).get("steamid") or (data or {}).get("SteamID")
            if value is None:
                return None
            steamid64 = int(value)
            if steamid64 < 70_000_000_000_000_000:
                return None
            return steamid64
        except Exception:
            return None

    def _should_delay_expire_due_to_dota_match(
        self,
        *,
        account_id: int,
        owner: str,
        current_time: datetime,
        mafile_json: Optional[str],
    ) -> bool:
        if not DOTA_MATCH_DELAY_EXPIRE:
            return False
        bot = get_presence_bot()
        if bot is None:
            return False

        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return False

        snapshot = bot.get_cached(steamid64)
        if snapshot is None:
            try:
                snapshot = asyncio.run(bot.fetch_presence(steamid64))
            except Exception:
                snapshot = None

        if not snapshot or not snapshot.in_match:
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        since = self._expire_delay_since.get(account_id)
        if since is None:
            self._expire_delay_since[account_id] = current_time
            since = current_time

        if current_time - since >= timedelta(minutes=DOTA_MATCH_GRACE_MINUTES):
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        if account_id not in self._expire_delay_notified:
            steam_display = snapshot.rich_presence.get("steam_display") if snapshot.rich_presence else None
            extra = f"\nСтатус: {steam_display}\n" if steam_display else ""
            try:
                self.send_message_by_owner(
                    owner,
                    "Ваша аренда уже закончилась, но вы сейчас в матче Dota 2.\n"
                    f"Я подожду до {DOTA_MATCH_GRACE_MINUTES} минут и затем автоматически закрою доступ.\n"
                    f"{extra}",
                )
            except Exception:
                pass
            try:
                send_message_to_admin(
                    "EXPIRE DELAYED (DOTA MATCH)\n\n"
                    f"Account ID: {account_id}\n"
                    f"Owner: {owner}\n"
                    f"steam_display: {steam_display}\n"
                    f"Grace: {DOTA_MATCH_GRACE_MINUTES} minutes\n",
                )
            except Exception:
                pass
            self._expire_delay_notified.add(account_id)

        return True

    def _should_delay_expire_due_to_in_game(self, mafile_json: Optional[str]) -> bool:
        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return False
        try:
            presence = fetch_web_presence(steamid64)
            return bool(presence.get("in_game"))
        except Exception:
            return False

    def _send_expiration_warning(
        self,
        owner: str,
        account_id: int,
        minutes_remaining: float,
        expiry_time: datetime,
        reminder_minutes: int,
    ) -> None:
        try:
            remaining_minutes = max(int(minutes_remaining), 0)
            send_message_to_admin(
                "EXPIRATION WARNING!\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Time left: ~{remaining_minutes} minutes\n"
                f"Reminder: {reminder_minutes} minutes\n"
                "Tip: user will lose access soon!",
            )
            self.send_message_by_owner(
                owner,
                f"Внимание! Ваша аренда скоро закончится через {reminder_minutes} минут.\n\n"
                f"ID аккаунта: {account_id}\n"
                f"Осталось: ~{remaining_minutes} мин\n"
                "Если нужно продление — используйте команду:\n"
                "!продлить <часы> <номер_лота>\n\n"
                "Команды:\n"
                "!акк — данные аккаунта\n"
                "!код — код Steam Guard\n"
                "!сток — наличие\n"
                "!продлить <часы> <номер_лота> — продлить аренду\n"
                "!отмена <ID> — отменить аренду\n!бонус — бонус за отзыв\n\n"
                f"Окончание: {expiry_time.strftime('%H:%M:%S')} МСК",
            )
        except Exception as exc:
            logger.error(f"Failed to send warning notification: {exc}")

    def _expire_rental(
        self,
        invalid_accs: list[int],
        owner: str,
        account_id: int,
        mafile_path: str,
        mafile_json: str,
        password: str,
        steam_login: str,
        expiry_time: datetime,
    ) -> None:
        logger.info(f"Account {account_id} rental expired.")
        self._expire_warning_sent.pop(account_id, None)
        self._expire_warning_start.pop(account_id, None)
        deauth_ok = False
        try:
            if AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE:
                try:
                    deauth_ok = asyncio.run(
                        logout_all_steam_sessions(
                            steam_login=steam_login,
                            steam_password=password,
                            mafile_json=mafile_json,
                        )
                    )
                except Exception as exc:
                    logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")

            send_message_to_admin(
                "RENTAL EXPIRED\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Deauthorize: {'ok' if deauth_ok else 'failed'}\n"
                f"Expired at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}",
            )

            try:
                self.send_message_by_owner(
                    owner,
                    "\u0412\u0430\u0448\u0430 \u0430\u0440\u0435\u043d\u0434\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430.\n\n"
                    f"ID \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430: {account_id}\n"
                    "\u0415\u0441\u043b\u0438 \u0445\u043e\u0442\u0438\u0442\u0435 \u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c, \u043a\u0443\u043f\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u043b\u043e\u0442.\n"
                    "\u0415\u0441\u043b\u0438 \u043d\u0443\u0436\u043d\u0430 \u043f\u043e\u043c\u043e\u0449\u044c, \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 \u0447\u0430\u0442.",
                )
            except Exception as exc:
                logger.error(f"Failed to send expiration notification: {exc}")
        except Exception as exc:
            logger.error(f"Failed to expire account {account_id}: {exc}")
            try:
                send_message_to_admin(
                    "RENTAL EXPIRED (PARTIAL)\n\n"
                    f"Account ID: {account_id}\n"
                    f"Owner: {owner}\n"
                    "Result: deauthorize failed; owner cleared anyway\n"
                    f"Error: {exc}\n",
                )
            except Exception:
                pass

        update_fields = {"rental_duration": 1, "rental_duration_minutes": 60}

        if not self._db.update_account(account_id, update_fields):
            logger.error(f"Failed to update expired account state for account {account_id}")
            invalid_accs.append(account_id)
        if not self._db.release_account(account_id):
            logger.error(f"Failed to release expired account {account_id}")
            invalid_accs.append(account_id)
