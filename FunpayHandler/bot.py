from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import math
import requests
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from FunPayAPI import Account, Runner, events, types
from FunPayAPI.common import exceptions as fp_exceptions

from backend.config import (
    AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE,
    DOTA_MATCH_DELAY_EXPIRE,
    DOTA_MATCH_GRACE_MINUTES,
    HOURS_FOR_REVIEW,
    RENTAL_CHECK_INTERVAL,
    STEAM_BRIDGE_URL,
)
from DatabaseHandler.databaseSetup import MySQLDB
from backend.logger import logger
from backend.notifications import send_message_to_admin
from backend.realtime import publish_chat_message
from FunPayAPI.common.utils import RegularExpressions
from SteamHandler.SteamGuard import get_steam_guard_code
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence_bot import get_presence_bot

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
STOCK_LIST_LIMIT = 8
LP_EXCHANGE_WINDOW_MINUTES = 10
RUNNER_REQUEST_DELAY_SECONDS = 1.5
ACCOUNT_LABEL_NOISE_RE = re.compile(r"\b(?:\u0430\u0440\u0435\u043d\u0434\u0430|rent(?:al)?)\b", re.IGNORECASE)
COMMANDS_HELP = (
    "\u041a\u043e\u043c\u0430\u043d\u0434\u044b:\n"
    "!acc / !\u0430\u043a\u043a \u2014 \u0434\u0430\u043d\u043d\u044b\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430\n"
    "!code / !\u043a\u043e\u0434 \u2014 \u043a\u043e\u0434 Steam Guard\n"
    "!stock / !\u0441\u0442\u043e\u043a \u2014 \u043d\u0430\u043b\u0438\u0447\u0438\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u043e\u0432\n"
    "!extend / !\u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c <\u0447\u0430\u0441\u044b> <ID_\u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430> \u2014 \u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c \u0430\u0440\u0435\u043d\u0434\u0443\n"
    "!admin / !\u0430\u0434\u043c\u0438\u043d \u2014 \u0432\u044b\u0437\u0432\u0430\u0442\u044c \u043f\u0440\u043e\u0434\u0430\u0432\u0446\u0430\n"
    "!lpexchange / !\u043b\u043f\u0437\u0430\u043c\u0435\u043d\u0430 <ID> \u2014 \u0437\u0430\u043c\u0435\u043d\u0430 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 (10 \u043c\u0438\u043d\u0443\u0442 \u043f\u043e\u0441\u043b\u0435 !\u043a\u043e\u0434)\n"
    "!cancel / !\u043e\u0442\u043c\u0435\u043d\u0430 <ID> \u2014 \u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c \u0430\u0440\u0435\u043d\u0434\u0443"
)
COMMANDS_INLINE = (
    "\u041a\u043e\u043c\u0430\u043d\u0434\u044b: !acc/!\u0430\u043a\u043a, !code/!\u043a\u043e\u0434, !stock/!\u0441\u0442\u043e\u043a, !extend/!\u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c, "
    "!admin/!\u0430\u0434\u043c\u0438\u043d, !lpexchange/!\u043b\u043f\u0437\u0430\u043c\u0435\u043d\u0430, !cancel/!\u043e\u0442\u043c\u0435\u043d\u0430"
)
MESSAGE_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")


def _normalize_time_label(time_text: str) -> str:
    parts = time_text.split(":")
    if len(parts) not in (2, 3):
        return time_text
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return time_text
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _extract_message_time_from_text(text: str | None) -> Optional[str]:
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    match = MESSAGE_TIME_RE.search(cleaned)
    if not match:
        return None
    return _normalize_time_label(match.group(1))


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
        key_id: Optional[int] = None,
        proxy: Optional[dict] = None,
        on_refresh: Optional[callable] = None,
    ) -> None:
        self._token = token
        self._db = db or MySQLDB()
        self._user_id = user_id
        self._key_id = key_id
        self._proxy = proxy
        self._on_refresh = on_refresh

        self._acc: Optional[Account] = None
        self._runner: Optional[Runner] = None
        self._pending_account_choice: Dict[str, List[Dict]] = {}
        self._pending_lot_extend: Dict[str, PendingLotExtend] = {}
        self._processed_order_ids: set[str] = set()
        self._processed_order_statuses: set[tuple[str, str]] = set()
        self._processed_message_ids: set[str] = set()
        self._recent_message_signatures: Dict[tuple[int, str, str], float] = {}
        self._recent_message_cleanup_ts = 0.0

        self._last_refresh_ts = 0.0
        self._token_lock = threading.Lock()
        self._refresh_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._expire_delay_since: Dict[int, datetime] = {}
        self._expire_delay_next_check: Dict[int, datetime] = {}
        self._expire_delay_notified: set[int] = set()
        self._expire_warning_sent: Dict[int, set[int]] = {}
        self._expire_warning_start: Dict[int, str] = {}
        # Pending order confirmations; auto-ticket after deadline
        self._confirm_tasks: Dict[str, dict] = {}
        self._confirm_lock = threading.Lock()
        self._auto_ticket_cache: tuple[bool, float] = (True, 0.0)
        self._auto_raise_cache: tuple[bool, float] = (True, 0.0)

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

    def _add_confirm_task(
        self,
        order_id: str,
        buyer: str,
        lot_number: int | None,
        rental_minutes: int | None,
    ) -> None:
        if not self._auto_tickets_enabled():
            return
        if not order_id:
            return
        minutes = rental_minutes if rental_minutes and rental_minutes > 0 else 60
        due = datetime.utcnow() + timedelta(minutes=minutes) + timedelta(hours=24)
        payload = {
            "buyer": buyer,
            "lot_number": lot_number,
            "due_at": due,
            "rental_minutes": minutes,
            "submitted": False,
        }
        with self._confirm_lock:
            self._confirm_tasks[order_id] = payload

    def _clear_confirm_task(self, order_id: str) -> None:
        if not order_id:
            return
        with self._confirm_lock:
            self._confirm_tasks.pop(order_id, None)

    def _auto_tickets_enabled(self) -> bool:
        now = time.time()
        cached_val, ts = self._auto_ticket_cache
        if now - ts < 60:
            return cached_val
        enabled = self._db.get_setting_bool("auto_ticket_enabled", True)
        self._auto_ticket_cache = (enabled, now)
        return enabled

    def _auto_raise_enabled(self) -> bool:
        now = time.time()
        cached_val, ts = self._auto_raise_cache
        if now - ts < 60:
            return cached_val
        enabled = self._db.get_setting_bool("auto_raise_enabled", True)
        self._auto_raise_cache = (enabled, now)
        return enabled

    def _auto_raise_loop(self) -> None:
        while not self._stop_requested.is_set():
            if not self._auto_raise_enabled():
                time.sleep(60)
                continue
            if not self._acc:
                time.sleep(15)
                continue
            if not self._proxy:
                logger.info("Auto-raise skipped: proxy not configured.")
                time.sleep(300)
                continue
            min_wait = 7200
            try:
                cats_attr = getattr(self._acc, "categories", None)
                if callable(cats_attr):
                    categories = cats_attr() or []
                else:
                    categories = cats_attr or []
                if not categories and hasattr(self._acc, "get_sorted_categories"):
                    categories = list(self._acc.get_sorted_categories().values())
                allowed_ids_raw = self._db.get_setting("auto_raise_categories", None)
                allowed_ids = None
                if allowed_ids_raw:
                    try:
                        allowed_ids = {int(x) for x in str(allowed_ids_raw).replace(" ", "").split(",") if x}
                    except Exception:
                        allowed_ids = None
                if allowed_ids is not None:
                    categories = [c for c in categories if getattr(c, "id", None) in allowed_ids]
                if not categories:
                    time.sleep(300)
                    continue
                for cat in categories:
                    try:
                        self._acc.raise_lots(cat.id)
                        min_wait = min(min_wait, 7200)
                        logger.info(f"Raised lots for category {getattr(cat, 'name', cat.id)} (user={self._user_id} key={self._key_id})")
                    except fp_exceptions.RaiseError as exc:
                        wait = exc.wait_time or 7200
                        min_wait = min(min_wait, wait + 5)
                        logger.info(f"Raise deferred for category {getattr(exc.category, 'name', 'unknown')}: wait {wait}s")
                    except Exception as exc:
                        logger.warning(f"Raise failed for category {getattr(cat, 'name', cat.id)}: {exc}")
                time.sleep(max(120, min_wait))
            except Exception as exc:
                logger.warning(f"Auto-raise loop error: {exc}")
                time.sleep(300)

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
            int(target_mmr), MMR_RANGE_DEFAULT, self._user_id, key_id=self._key_id
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
            int(target_mmr), MMR_RANGE_DEFAULT, self._user_id, key_id=self._key_id
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
            if self._on_refresh:
                try:
                    self._on_refresh(False, "Golden key missing")
                except Exception:
                    pass
            return
        try:
            self._acc = Account(token, proxy=self._proxy).get()
            self._runner = Runner(self._acc)
            logger.info(
                "FunPay session refreshed successfully (user=%s key=%s proxy=%s)",
                self._user_id,
                self._key_id,
                self._proxy.get("http") if isinstance(self._proxy, dict) else None,
            )
            if self._on_refresh:
                try:
                    self._on_refresh(True, None)
                except Exception:
                    pass
        except Exception as exc:
            logger.error(f"FunPay session refresh failed (user={self._user_id} key={self._key_id}): {exc}")
            if self._on_refresh:
                try:
                    self._on_refresh(False, str(exc))
                except Exception:
                    pass

    def request_token_update(self, token: str) -> None:
        if not token:
            return
        with self._token_lock:
            self._token = token
        self._refresh_requested.set()

    def update_proxy(self, proxy: Optional[dict]) -> None:
        self._proxy = proxy
        self._refresh_requested.set()

    def request_stop(self) -> None:
        self._stop_requested.set()
        runner = self._runner
        for method_name in ("stop", "close", "shutdown"):
            handler = getattr(runner, method_name, None)
            if callable(handler):
                try:
                    handler()
                except Exception:
                    pass
                break

    def start(self) -> None:
        logger.info(f"Starting FunPay bot (user={self._user_id} key={self._key_id})...")
        if self._stop_requested.is_set():
            return
        if not self._token:
            logger.error("FunPay golden key is missing. FunPay automation stopped.")
            return

        self.refresh_session()
        self._last_refresh_ts = time.time()

        thread = threading.Thread(target=self._check_rental_expiration_loop, daemon=True)
        thread.start()
        logger.info("Rental expiration checker started.")

        confirm_thread = threading.Thread(target=self._confirm_check_loop, daemon=True)
        confirm_thread.start()
        logger.info("Order confirmation watcher started.")

        raise_thread = threading.Thread(target=self._auto_raise_loop, daemon=True)
        raise_thread.start()
        logger.info("Auto raise loop started.")

        if self._runner is None:
            raise RuntimeError("Runner not initialized")

        for event in self._runner.listen(requests_delay=RUNNER_REQUEST_DELAY_SECONDS):
            if self._stop_requested.is_set():
                logger.info(f"Stopping FunPay bot (user={self._user_id} key={self._key_id})...")
                break
            try:
                self._tick_refresh_if_needed()

                if event.type is events.EventTypes.NEW_ORDER:
                    self._handle_new_order(event)

                if event.type is events.EventTypes.NEW_MESSAGE:
                    self._handle_new_message(event)

            except Exception:
                logger.exception(
                    f"An error occurred while processing event: {getattr(event, 'type', None)}"
                )

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

    def _get_active_accounts_for_owner(self, owner: str) -> list[dict]:
        return self._db.get_user_active_accounts(owner, self._user_id, key_id=self._key_id) or []

    def _get_available_lots(self) -> list[dict]:
        lots = self._db.get_available_lot_accounts(self._user_id, key_id=None) or []
        filtered = []
        for item in lots:
            if item.get("lot_number") is None:
                continue
            filtered.append(item)
        return filtered

    def _confirm_order(self, acc: Account, order_id: str | int | None) -> None:
        if not order_id:
            return
        for method_name in ("confirm", "confirm_order", "confirm_order_by_id"):
            handler = getattr(acc, method_name, None)
            if callable(handler):
                try:
                    handler(order_id)
                except Exception as exc:
                    logger.warning(f"Order confirm failed via {method_name}: {exc}")
                return

    def _clean_account_label(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        cleaned = cleaned.translate(
            str.maketrans({"\u3010": " ", "\u3011": " ", "[": " ", "]": " ", "(": " ", ")": " "})
        )
        cleaned = ACCOUNT_LABEL_NOISE_RE.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        cleaned = cleaned.strip(" -\u2014")
        return cleaned

    def _display_account_name(self, name: Optional[str]) -> str:
        cleaned = self._clean_account_label(name or "")
        return cleaned or "\u0430\u043a\u043a\u0430\u0443\u043d\u0442"

    def _format_rental_status(self, account: dict, current_time: datetime) -> tuple[str | None, str]:
        rental_start = account.get("rental_start")
        if not rental_start:
            return None, "\u043d\u0435 \u043d\u0430\u0447\u0430\u0442\u043e (\u043e\u0436\u0438\u0434\u0430\u0435\u043c !\u043a\u043e\u0434)"
        _, expiry_str, remaining_str = get_remaining_time(account, current_time)
        return expiry_str, remaining_str

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
        # also clear confirm task if any
        self._clear_confirm_task(str(order_id))

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
            key_id=self._key_id,
        )
        if action in ("closed", "order_confirmed", "order_confirmed_by_admin"):
            self._clear_confirm_task(order_id)

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

        if self._db.is_blacklisted(buyer, self._user_id, key_id=self._key_id):
            # If buyer pays enough units while blacklisted, auto-unblacklist after reaching the compensation threshold.
            description = str(getattr(order, "description", "") or "")
            lot_number = parse_lot_number(description)
            amount = int(getattr(order, "amount", 1) or 1)
            COMP_THRESHOLD = 5
            # Log this payment toward compensation
            self._db.log_order_event(
                order_id=order_id,
                owner_id=buyer,
                action="blacklist_comp",
                account_name=description,
                lot_number=lot_number,
                amount=amount,
                price=getattr(order, "price", None),
                user_id=self._user_id,
                key_id=self._key_id,
            )
            self._db.log_blacklist_event(
                buyer,
                "compensation_payment",
                details=f"order={order_id}; lot={lot_number}; amount={amount}",
                user_id=self._user_id,
                key_id=self._key_id,
            )
            paid_total = self._db.get_blacklist_compensation_total(buyer, self._user_id, key_id=self._key_id)
            if paid_total >= COMP_THRESHOLD:
                self._db.remove_from_blacklist(buyer, self._user_id, key_id=self._key_id)
                self._db.log_blacklist_event(
                    buyer,
                    "auto_unblacklist",
                    details=f"total={paid_total}/{COMP_THRESHOLD}; order={order_id}; lot={lot_number}; amount={amount}",
                    user_id=self._user_id,
                    key_id=self._key_id,
                )
                acc.send_message(
                    chat_id,
                    f"Оплата компенсации получена ({paid_total} шт). Доступ разблокирован."
                )
                send_message_to_admin(
                    "BLACKLIST AUTO-REMOVED\n\n"
                    f"Buyer: {buyer}\nOrder: {order_id}\nLot: {lot_number}\nAmount: {amount}\n"
                    f"Total paid: {paid_total}/{COMP_THRESHOLD}"
                )
                self._mark_order_processed(event)
                return

            remaining = max(COMP_THRESHOLD - paid_total, 0)
            lot_link = None
            if lot_number is not None:
                mapping = self._db.get_lot_mapping(lot_number, self._user_id, key_id=self._key_id)
                lot_link = (mapping or {}).get("lot_url")
            acc.send_message(
                chat_id,
                "Вы в черном списке. Чтобы разблокировать команды, оплатите компенсацию: "
                f"нужно 5 шт этого лота. Сейчас оплачено: {paid_total}. "
                f"Осталось: {remaining} шт."
                + (f"\nОплатите по ссылке: {lot_link}" if lot_link else "")
            )
            self._db.log_blacklist_event(
                buyer,
                "blocked_order",
                details=f"order={order_id}; lot={lot_number}; amount={amount}; paid={paid_total}; remaining={remaining}",
                user_id=self._user_id,
                key_id=self._key_id,
            )
            send_message_to_admin(
                "BLACKLISTED ORDER\n\n"
                f"Buyer: {buyer}\n"
                f"Order: {order_id}\n"
                f"Description: {getattr(order, 'description', '')}\n"
                f"Amount: {getattr(order, 'amount', '')}\n"
                f"Price: {getattr(order, 'price', '')}"
            )
            self._db.log_order_event(
                order_id=order_id,
                owner_id=buyer,
                action="blacklisted",
                account_name=str(getattr(order, "description", "") or ""),
                lot_number=parse_lot_number(str(getattr(order, "description", "") or "")),
                amount=getattr(order, "amount", None),
                price=getattr(order, "price", None),
                user_id=self._user_id,
                key_id=self._key_id,
            )
            self._mark_order_processed(event)
            return

        description = str(getattr(order, "description", "") or "")
        amount = int(getattr(order, "amount", 1) or 1)

        lot_number = parse_lot_number(description)
        if lot_number is not None:
            self._process_lot_order(acc, chat_id, event, buyer, lot_number, amount)
            return

        self._process_named_order(acc, chat_id, event, buyer, description, amount)

    # --- Pending confirmation tracking -------------------------------------------------

    def _confirm_check_loop(self) -> None:
        while not self._stop_requested.is_set():
            if not self._auto_tickets_enabled():
                time.sleep(60)
                continue
            now = datetime.utcnow()
            to_submit: list[tuple[str, dict]] = []
            with self._confirm_lock:
                for oid, data in list(self._confirm_tasks.items()):
                    due_at: datetime = data.get("due_at") or now
                    if data.get("submitted"):
                        continue
                    if now >= due_at:
                        to_submit.append((oid, data))
            for order_id, data in to_submit:
                try:
                    self._submit_missing_confirmation_ticket(order_id, data)
                except Exception as exc:
                    logger.error(f"Failed to auto-submit ticket for order {order_id}: {exc}")
                finally:
                    self._clear_confirm_task(order_id)
            time.sleep(60)

    def _classify_ticket_dispute(self, buyer: str) -> bool:
        """
        Use AI to judge if the buyer chat contains a dispute/complaint after delivery.
        Returns True if ambiguous/dispute, False if clear or inconclusive.
        """
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or not self._acc:
            return False
        try:
            chat = self._acc.get_chat_by_name(buyer, True)
            if not chat:
                return False
            history = self._acc.get_chat_history(chat.id) or []
            texts = [msg.text for msg in history if getattr(msg, "text", None)]
            if not texts:
                return False
            last_msgs = texts[-50:]
            payload = {
                "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты модератор FunPay. Определи, есть ли спор/претензия покупателя по заказу. "
                            "Ответь только 'dispute' если есть жалоба/неудовлетворенность/возврат/не работает/бан, "
                            "иначе 'clear'. Запросы Steam Guard и коды не считаются спором."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Сообщения (последние):\n" + "\n".join(last_msgs),
                    },
                ],
                "max_tokens": 4,
                "temperature": 0,
            }
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=8,
            )
            resp.raise_for_status()
            content = (
                resp.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .lower()
            )
            return "dispute" in content
        except Exception as exc:
            logger.warning(f"AI dispute check failed for buyer {buyer}: {exc}")
            return False

    def _generate_ticket_comment(self, order_id: str, buyer: str, lot_number: int | None, ambiguous: bool) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        # Follow FunPay admin guidance: two lists, clear that service is rendered and buyer just forgot confirmation.
        list1 = (
            f"заказ {order_id}, покупатель {buyer}" + (f", лот №{lot_number}" if lot_number else "")
            if not ambiguous
            else "нет"
        )
        list2 = (
            f"заказ {order_id}, покупатель {buyer}" + (f", лот №{lot_number}" if lot_number else "")
            if ambiguous
            else "нет"
        )
        prompt = (
            "Составь обращение в поддержку FunPay (адресат — сотрудник поддержки). "
            "Формат должен быть строгим:\n"
            "1) В начале фраза: \"Я предоставил услугу, покупатель забыл подтвердить\".\n"
            "2) Далее два списка, как просит саппорт:\n"
            "   Список 1 — однозначно оказанные услуги (покупатель лишь не нажал подтвердить).\n"
            "   Список 2 — неоднозначные случаи (если нет, напиши \"нет\").\n"
            f"Список 1: {list1}. Список 2: {list2}. "
            "Не обращайся к покупателю. Кратко и без воды."
        )
        fallback = (
            "Я предоставил услугу, покупатель забыл подтвердить.\n"
            f"Список 1 (однозначно оказанные): {list1}.\n"
            f"Список 2 (неоднозначные): {list2}.\n"
            "Просьба подтвердить заказ. Спасибо!"
        )
        if not api_key:
            return fallback
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "Ты вежливый саппорт FunPay."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 160,
                    "temperature": 0.3,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            return content.strip() if content else fallback
        except Exception as exc:
            logger.warning(f"GROQ generation failed, using fallback: {exc}")
            return fallback

    def _submit_missing_confirmation_ticket(self, order_id: str, data: dict) -> None:
        if not self._token:
            return
        buyer = data.get("buyer") or ""
        ambiguous = self._classify_ticket_dispute(buyer)
        comment = self._generate_ticket_comment(order_id, buyer, data.get("lot_number"), ambiguous)
        session = requests.Session()
        if self._proxy:
            session.proxies.update(self._proxy)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )
        session.cookies.set("golden_key", self._token, domain=".funpay.com")
        session.cookies.set("golden_key", self._token, domain="support.funpay.com")

        form_resp = session.get("https://support.funpay.com/tickets/new/1", timeout=20, allow_redirects=True)
        form_resp.raise_for_status()
        soup = BeautifulSoup(form_resp.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise RuntimeError("Support form not found")
        action = urljoin(form_resp.url, form.get("action") or "")
        payload = {inp.get("name"): inp.get("value") or "" for inp in form.find_all("input") if inp.get("name")}
        payload["ticket[comment][body_html]"] = comment
        payload["ticket[fields][2]"] = order_id
        # role seller -> value 2, topic 201 (buyer forgot to confirm)
        payload["ticket[fields][3]"] = "2"
        payload["ticket[fields][4]"] = ""  # buyer topics
        payload["ticket[fields][5]"] = "201"

        post_resp = session.post(action, data=payload, timeout=20, allow_redirects=False)
        ok = post_resp.status_code < 400
        ticket_url = None
        try:
            payload_json = post_resp.json()
            ticket_url = payload_json.get("action", {}).get("url")
        except Exception:
            ticket_url = post_resp.headers.get("Location")

        self._db.insert_support_ticket(
            self._user_id,
            self._key_id,
            "problem_order",
            "seller",
            order_id,
            comment,
            ticket_url,
            "ok" if ok else f"fail:{post_resp.status_code}",
            source="auto",
        )
        self._db.log_order_event(
            order_id=order_id,
            owner_id=data.get("buyer") or "",
            action="ticket_auto",
            account_name=None,
            lot_number=data.get("lot_number"),
            amount=None,
            price=None,
            user_id=self._user_id,
            key_id=self._key_id,
        )
        send_message_to_admin(
            "AUTO SUPPORT TICKET\n\n"
            f"Order: {order_id}\n"
            f"Buyer: {data.get('buyer')}\n"
            f"Due passed: {data.get('due_at')}\n"
            f"Status: {'ok' if ok else f'fail:{post_resp.status_code}'}\n"
            f"URL: {ticket_url or 'n/a'}"
        )

    def _process_lot_order(
        self,
        acc: Account,
        chat_id: int,
        event: Any,
        buyer: str,
        lot_number: int,
        amount: int,
    ) -> None:
        mapping = self._db.get_lot_mapping(lot_number, self._user_id, key_id=self._key_id)
        if not mapping:
            acc.send_message(chat_id, "Лот не привязан к аккаунту. Вызовите администратора командой !админ.")
            send_message_to_admin(
                "ЛОТ БЕЗ ПРИВЯЗКИ\n\n"
                f"Покупатель: {buyer}\n"
                f"Лот: №{lot_number}\n"
                f"Заказ: {event.order.id}"
            )
            return

        account = self._db.get_account_by_lot_number(lot_number, self._user_id, key_id=self._key_id)
        if not account:
            acc.send_message(chat_id, "Ошибка: лот привязан к аккаунту, но аккаунт не найден. Напишите !админ.")
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

            refreshed = self._db.get_account_by_id(account["id"], self._user_id, key_id=self._key_id)
            current_time = datetime.now(tz=MOSCOW_TZ)
            expiry_str, remaining_str = self._format_rental_status(refreshed, current_time)
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
                + (f"Истекает: {expiry_str} МСК | " if expiry_str else "")
                + f"Осталось: {remaining_str}{note}",
            )
            rental_minutes = unit_minutes * amount
            steam_id = self._resolve_account_steamid(account)
            self._db.log_order_event(
                order_id=str(event.order.id),
                owner_id=buyer,
                action="extended",
                account_name=account.get("account_name"),
                account_id=account.get("id"),
                lot_number=lot_number,
                amount=amount,
                price=getattr(event.order, "price", None),
                rental_minutes=rental_minutes,
                steam_id=steam_id,
                user_id=self._user_id,
                key_id=self._key_id,
            )
            self._confirm_order(acc, event.order.id)
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
        all_accounts = self._db.get_all_account_names(self._user_id, key_id=self._key_id)
        matched_account = match_account_name(order_name, all_accounts)
        if matched_account is None:
            logger.warning(f"No matching account found for order: {order_name}")
            return

        account_name = matched_account
        display_name = self._display_account_name(account_name)
        if account_name not in all_accounts:
            logger.info(f"Item '{account_name}' not found in rentals; skipping.")
            return

        specific_account = self._db.get_account_by_name(
            account_name, user_id=self._user_id, key_id=self._key_id
        )
        if not specific_account:
            logger.error(f"Account with name '{account_name}' not found in database")
            acc.send_message(
                chat_id,
                f"Ошибка: аккаунт '{display_name}' не найден.\n"
                "Возврат оформлен. Если нужна помощь — напишите !админ.",
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
                "Если нужен другой вариант — напишите !админ.",
            )

        existing_rentals = self._db.get_user_accounts_by_name(
            buyer, account_name, user_id=self._user_id, key_id=self._key_id
        )
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

        account = self._db.get_account_by_id(rental["id"], self._user_id, key_id=self._key_id)
        if account:
            current_time = datetime.now(tz=MOSCOW_TZ)
            expiry_str, remaining_str = self._format_rental_status(account, current_time)
            lines = [
                f"ID: {rental['id']}",
                f"Логин: {rental['login']}",
                f"Пароль: {rental['password']}",
            ]
            if expiry_str:
                lines.append(f"Истекает: {expiry_str} МСК")
            lines.append(f"Осталось: {remaining_str}")
            lines.append(f"{COMMANDS_INLINE}")
            acc.send_message(chat_id, "\n".join(lines))

        send_message_to_admin(
            "RENTAL EXTENDED\n\n"
            f"User: {event.order.buyer_username}\n"
            f"Account type: {order_name}\n"
            f"Extension: +{duration_label}\n"
            f"Price: {event.order.price} RUB\n"
            f"Account ID: {rental['id']}\n"
            "Note: user already had an active rental",
        )

        rental_minutes = unit_minutes * units
        steam_id = self._resolve_account_steamid(rental)
        self._db.log_order_event(
            order_id=str(event.order.id),
            owner_id=event.order.buyer_username,
            action="extended",
            account_name=order_name,
            account_id=rental.get("id"),
            lot_number=None,
            amount=units,
            price=getattr(event.order, "price", None),
            rental_minutes=rental_minutes,
            steam_id=steam_id,
            user_id=self._user_id,
            key_id=self._key_id,
        )
        self._confirm_order(acc, event.order.id)

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
        order_id = getattr(event.order, "id", None)
        self._db.set_account_owner(
            account["id"],
            event.order.buyer_username,
            self._user_id,
            start_rental=False,
            key_id=self._key_id,
            order_id=str(event.order.id),
        )
        unit_minutes = self._get_unit_minutes(account)
        duration_label = format_duration_minutes(unit_minutes * units)
        self._set_rental_duration_for_order(account["id"], units, unit_minutes)
        display_name = self._display_account_name(account.get("account_name"))
        total_minutes = unit_minutes * units
        if order_id:
            self._add_confirm_task(str(order_id), event.order.buyer_username, lot_number, total_minutes)

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
            "\u0412\u0430\u0448 \u0430\u043a\u043a\u0430\u0443\u043d\u0442:\n"
            f"ID: {account['id']}\n"
            f"\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435: {display_name}\n"
            f"\u041b\u043e\u0433\u0438\u043d: {account['login']}\n"
            f"\u041f\u0430\u0440\u043e\u043b\u044c: {account['password']}\n"
            f"\u0410\u0440\u0435\u043d\u0434\u0430: {duration_label}\n\n"
            "\u23f1\ufe0f \u041e\u0442\u0441\u0447\u0435\u0442 \u0430\u0440\u0435\u043d\u0434\u044b \u043d\u0430\u0447\u043d\u0435\u0442\u0441\u044f \u043f\u043e\u0441\u043b\u0435 \u043f\u0435\u0440\u0432\u043e\u0433\u043e \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0438\u044f \u043a\u043e\u0434\u0430 (!code / !\u043a\u043e\u0434).\n\n"
            f"{COMMANDS_HELP}\n\n"
            "\u0415\u0441\u043b\u0438 \u043d\u0443\u0436\u043d\u0430 \u043f\u043e\u043c\u043e\u0449\u044c \u2014 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 !\u0430\u0434\u043c\u0438\u043d."
        )
        if note:
            message = f"{note}\n\n{message}"
        acc.send_message(chat_id, message)

        rental_minutes = unit_minutes * units
        steam_id = self._resolve_account_steamid(account)
        self._db.log_order_event(
            order_id=str(event.order.id),
            owner_id=event.order.buyer_username,
            action="issued",
            account_name=account.get("account_name"),
            account_id=account.get("id"),
            lot_number=lot_number,
            amount=units,
            price=getattr(event.order, "price", None),
            rental_minutes=rental_minutes,
            steam_id=steam_id,
            user_id=self._user_id,
            key_id=self._key_id,
        )
        self._confirm_order(acc, event.order.id)

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
            return

        message_id = (
            getattr(event.message, "id", None)
            or getattr(event.message, "message_id", None)
            or getattr(event.message, "msg_id", None)
        )
        if message_id is not None:
            message_key = str(message_id)
            if message_key in self._processed_message_ids:
                return
            self._processed_message_ids.add(message_key)
            if len(self._processed_message_ids) > 5000:
                self._processed_message_ids.clear()

        raw_text = (event.message.text or "").strip()
        signature = (int(chat_id), str(event.message.author), raw_text.lower())
        now_ts = time.time()
        last_seen = self._recent_message_signatures.get(signature)
        if last_seen and now_ts - last_seen < 2.0:
            return
        self._recent_message_signatures[signature] = now_ts
        if now_ts - self._recent_message_cleanup_ts > 30:
            self._recent_message_cleanup_ts = now_ts
            cutoff = now_ts - 60
            self._recent_message_signatures = {
                key: ts for key, ts in self._recent_message_signatures.items() if ts >= cutoff
            }

        owner = event.message.author
        if self._user_id is not None:
            sent_time = _extract_message_time_from_text(getattr(event.message, "html", None))
            if not sent_time:
                sent_time = _extract_message_time_from_text(event.message.text or "")
            item = {
                "id": event.message.id,
                "text": event.message.text,
                "author": event.message.author,
                "author_id": event.message.author_id,
                "chat_id": event.message.chat_id,
                "chat_name": event.message.chat_name,
                "image_link": event.message.image_link,
                "by_bot": event.message.by_bot,
                "type": event.message.type.name if event.message.type else None,
                "sent_time": sent_time,
            }
            publish_chat_message(self._user_id, self._key_id, chat_id, item)
            try:
                role = "bot" if event.message.by_bot else "user"
                self._db.log_chat_message(owner, role, event.message.text or "", self._user_id, self._key_id)
            except Exception as exc:
                logger.warning(f"Failed to log chat message for {owner}: {exc}")

        if event.message.type in (
            types.MessageTypes.NEW_FEEDBACK,
            types.MessageTypes.FEEDBACK_CHANGED,
        ):
            self._handle_feedback_event(acc, event, chat_id)
            return
        if event.message.type == types.MessageTypes.FEEDBACK_DELETED:
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
        if event.message.type == types.MessageTypes.ORDER_PURCHASED:
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

        logger.info(
            f"[bot u={self._user_id} key={self._key_id} chat={chat_id}] "
            f"{event.message.author} : {event.message.text}"
        )
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

        if message_text.startswith("!lpexchange") or message_text.startswith("!лпзамена"):
            self._handle_lp_exchange(acc, chat_id, event.message.author, raw_text)
            return

        if message_text in ("!stock", "!сток"):
            self._handle_stock(acc, chat_id)
            return

        if message_text in ("!admin", "!админ"):
            self._handle_admin_call(acc, chat_id, event.message.author)
            return

        if message_text.startswith("!отмена"):
            self._handle_cancel(acc, chat_id, event.message.author, raw_text)
            return

        if not raw_text:
            return

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

    def _handle_feedback_event(
        self, acc: Account, event: Any, chat_id: int | None = None
    ) -> None:
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
            if event.message.type == types.MessageTypes.FEEDBACK_CHANGED:
                self._handle_feedback_deleted(acc, event, chat_id)
            return
        owner = review.author or getattr(order, "buyer_username", None) or event.message.author
        if not owner:
            return
        rating = int(review.stars)
        review_text = review.text or ""
        self._db.upsert_feedback_reward(order_id, owner, rating, review_text, self._user_id)
        if rating < 5:
            return
        reward = self._db.get_feedback_reward(order_id, self._user_id)
        if reward and reward.get("claimed_at"):
            return
        if reward and reward.get("revoked_at"):
            return
        accounts = self._db.get_user_active_accounts(owner, self._user_id, key_id=self._key_id)
        if not accounts:
            send_message_to_admin(
                "BONUS SKIPPED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {owner}\n"
                "Reason: no active rental to extend.",
            )
            return

        target = accounts[0]
        account_id = target["id"]
        if not self._db.extend_rental_duration_for_owner(
            account_id, owner, HOURS_FOR_REVIEW, 0, key_id=self._key_id
        ):
            send_message_to_admin(
                "BONUS APPLY FAILED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {owner}\n"
                f"Account ID: {account_id}",
            )
            return

        if not self._db.mark_feedback_reward_claimed(order_id, account_id, self._user_id):
            logger.warning(f"Failed to mark feedback reward claimed for order {order_id}.")

        updated = self._db.get_account_by_id(account_id, self._user_id, key_id=self._key_id)
        total_minutes = get_duration_minutes(updated or {})
        if total_minutes <= 0:
            total_minutes = get_duration_minutes(target) + HOURS_FOR_REVIEW * 60
        total_label = format_duration_minutes(total_minutes)
        chat = acc.get_chat_by_name(owner, True)
        chat_id = getattr(chat, "id", None) or getattr(event.message, "chat_id", None)
        if chat_id:
            acc.send_message(
                chat_id,
                f"\u041e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d \u043e\u0442\u0437\u044b\u0432 5 \u0437\u0432\u0435\u0437\u0434 \u2014 \u043c\u044b \u0434\u043e\u0431\u0430\u0432\u0438\u043b\u0438 {HOURS_FOR_REVIEW} \u0447\u0430\u0441 \u0430\u0440\u0435\u043d\u0434\u044b.\n"
                f"\u041e\u0431\u0449\u0435\u0435 \u0432\u0440\u0435\u043c\u044f \u0430\u0440\u0435\u043d\u0434\u044b: {total_label}.",
            )

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

        reward = self._db.get_feedback_reward(order_id, self._user_id)
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
            candidate = self._db.get_account_by_id(
                int(claimed_account_id), self._user_id, key_id=self._key_id
            )
            if candidate and candidate.get("owner") == reward_owner:
                target_account = candidate
        if target_account is None:
            accounts = self._db.get_user_active_accounts(
                reward_owner, self._user_id, key_id=self._key_id
            )
            if accounts:
                target_account = accounts[0]

        if target_account is None:
            send_message_to_admin(
                "BONUS REVOKE SKIPPED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {reward_owner}\n"
                "Reason: no active rental to deduct.",
            )
            self._db.mark_feedback_reward_revoked(order_id, self._user_id)
            return

        if not self._db.reduce_rental_duration_for_owner(
            target_account["id"], reward_owner, HOURS_FOR_REVIEW, 0, key_id=self._key_id
        ):
            send_message_to_admin(
                "BONUS REVOKE FAILED\n\n"
                f"Order: {order_id}\n"
                f"Owner: {reward_owner}\n"
                f"Account ID: {target_account['id']}",
            )
            return

        self._db.mark_feedback_reward_revoked(order_id, self._user_id)
        updated = self._db.get_account_by_id(
            target_account["id"], self._user_id, key_id=self._key_id
        )
        total_minutes = get_duration_minutes(updated or {})
        if total_minutes <= 0:
            total_minutes = get_duration_minutes(target_account) - HOURS_FOR_REVIEW * 60
        total_label = format_duration_minutes(max(total_minutes, 0))
        message = (
            "\u041c\u044b \u043e\u0431\u043d\u0430\u0440\u0443\u0436\u0438\u043b\u0438 \u0447\u0442\u043e \u0432\u044b \u0443\u0434\u0430\u043b\u0438\u043b\u0438 \u043e\u0442\u0437\u044b\u0432 \u2014 "
            f"\u0443\u043c\u0435\u043d\u044c\u0448\u0438\u043c \u0432\u0430\u0448\u0443 \u0430\u0440\u0435\u043d\u0434\u0443 \u043d\u0430 {HOURS_FOR_REVIEW} \u0447\u0430\u0441.\n"
            f"\u041e\u0431\u0449\u0435\u0435 \u0432\u0440\u0435\u043c\u044f \u0430\u0440\u0435\u043d\u0434\u044b: {total_label}."
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
            f"Removed: {HOURS_FOR_REVIEW}h\n"
            f"Total after: {total_label}",
        )

    def _try_handle_pending_choice(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> bool:
        if owner in self._pending_account_choice:
            accounts = self._pending_account_choice[owner]
            choice = match_account_choice(raw_text, accounts)
            if choice:
                current_time = datetime.now(tz=MOSCOW_TZ)
                expiry_str, remaining_str = self._format_rental_status(choice, current_time)
                display_name = self._display_account_name(choice.get("account_name"))
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {choice['id']}\n"
                    + f"Аккаунт: {display_name}\n"
                    + f"Логин: {choice['login']}\n"
                    + f"Пароль: {choice['password']}\n"
                    + (f"Истекает: {expiry_str} МСК | " if expiry_str else "")
                    + f"Осталось: {remaining_str}",
                )
                self._pending_account_choice.pop(owner, None)
            else:
                acc.send_message(chat_id, USER.choice_not_understood)
            return True

        return False

    def _handle_code(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            started = self._db.start_rental_for_owner(owner, self._user_id, key_id=self._key_id)
            owner_data = self._db.get_owner_mafile(owner, self._user_id, key_id=self._key_id)
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
                if started:
                    lines.append("")
                    lines.append("⏱️ Аренда началась сейчас (с момента получения кода).")
                acc.send_message(chat_id, "\n".join(lines))
            else:
                if self._db.owner_has_frozen_rental(owner, self._user_id, key_id=self._key_id):
                    acc.send_message(
                        chat_id,
                        "Администратор заморозил вашу аренду. Коды временно недоступны. Если нужна помощь — !админ.",
                    )
                else:
                    acc.send_message(chat_id, USER.active_rentals_empty)
        except Exception as exc:
            acc.send_message(chat_id, f"Ошибка при получении кода: {exc}")

    def _handle_acc(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner, self._user_id, key_id=self._key_id)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            current_time = datetime.now(tz=MOSCOW_TZ)
            if len(accounts) == 1:
                account = accounts[0]
                expiry_str, remaining_str = self._format_rental_status(account, current_time)
                display_name = self._display_account_name(account.get("account_name"))
                acc.send_message(
                    chat_id,
                    USER.account_details_header
                    + f"ID: {account['id']}\n"
                    + f"Аккаунт: {display_name}\n"
                    + f"Логин: {account['login']}\n"
                    + f"Пароль: {account['password']}\n"
                    + (f"Истекает: {expiry_str} МСК | " if expiry_str else "")
                    + f"Осталось: {remaining_str}",
                )
                return

            lines = [USER.choose_account_prompt]
            for account in accounts:
                expiry_str, remaining_str = self._format_rental_status(account, current_time)
                display_name = self._display_account_name(account.get("account_name"))
                if expiry_str:
                    lines.append(f"{account['id']}) {display_name} ({account['login']}) — осталось {remaining_str}")
                else:
                    lines.append(f"{account['id']}) {display_name} ({account['login']}) — не начато (ожидаем !код)")
            self._pending_account_choice[owner] = accounts
            acc.send_message(chat_id, "\n".join(lines))
        except Exception as exc:
            logger.error(f"Failed to send account details to {owner}: {exc}")
            acc.send_message(chat_id, USER.acc_failed)

    def _handle_extend(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            parts = raw_text.split()
            accounts = self._db.get_user_active_lot_accounts(
                owner, self._user_id, key_id=self._key_id
            )
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            def build_extend_help(prefix: str | None = None) -> str:
                current_time = datetime.now(tz=MOSCOW_TZ)
                lines: list[str] = []
                if prefix:
                    lines.append(prefix)
                lines.extend(
                    [
                        "Чтобы продлить аренду, напишите:",
                        "!продлить <часы> <ID аккаунта>",
                        "",
                        "Ваши активные аренды:",
                    ]
                )
                for account in accounts:
                    expiry_str, remaining_str = self._format_rental_status(account, current_time)
                    login = account.get("login") or self._display_account_name(account.get("account_name"))
                    account_id = account.get("id")
                    if expiry_str:
                        lines.append(f"{login} (ID {account_id}) — закончится через {remaining_str}")
                    else:
                        lines.append(f"{login} (ID {account_id}) — не начато (ожидаем !код)")
                return "\n".join(lines)

            if len(parts) == 1:
                acc.send_message(chat_id, build_extend_help())
                return

            if len(parts) < 2 or not parts[1].isdigit():
                acc.send_message(chat_id, build_extend_help("Использование: !продлить <часы> <ID аккаунта>"))
                return

            hours = int(parts[1])
            if hours <= 0:
                acc.send_message(chat_id, USER.extend_hours_positive)
                return

            target_account = None
            if len(parts) >= 3 and parts[2].isdigit():
                account_id = int(parts[2])
                target_account = next(
                    (item for item in accounts if str(item.get("id")) == str(account_id)),
                    None,
                )
                if target_account is None:
                    acc.send_message(
                        chat_id,
                        build_extend_help("Аккаунт с таким ID не найден в ваших активных арендах."),
                    )
                    return
            elif len(accounts) == 1:
                target_account = accounts[0]
            else:
                acc.send_message(chat_id, build_extend_help("Укажите ID аккаунта для продления."))
                return

            account_id = target_account.get("id")
            login = target_account.get("login") or self._display_account_name(target_account.get("account_name"))
            lot_number = target_account.get("lot_number")
            if not lot_number:
                acc.send_message(
                    chat_id,
                    f"Аккаунт {login} (ID {account_id}) не привязан к лоту. Напишите !админ.",
                )
                return

            lot_url = target_account.get("lot_url")
            link_line = f"\nСсылка: {lot_url}" if lot_url else ""
            acc.send_message(
                chat_id,
                f"Чтобы продлить аренду аккаунта {login} (ID {account_id}) на {hours} ч, "
                f"оплатите лот №{lot_number} в количестве {hours} шт."
                f"{link_line}\n\nПосле оплаты бот автоматически продлит аренду.",
            )
            self._pending_lot_extend[owner] = PendingLotExtend(
                hours=hours, lot_number=int(lot_number), created_ts=time.time()
            )
        except Exception as exc:
            logger.error(f"Failed to extend rental for {owner}: {exc}")
            acc.send_message(chat_id, USER.extend_failed)

    def _handle_stock(self, acc: Account, chat_id: int) -> None:
        try:
            available_lots = self._get_available_lots()
            if available_lots:
                batches: list[list[str]] = []
                current: list[str] = []
                for index, account in enumerate(available_lots, start=1):
                    display_name = self._display_account_name(account.get("account_name"))
                    lot_number = account.get("lot_number")
                    if display_name == "\u0430\u043a\u043a\u0430\u0443\u043d\u0442" and lot_number:
                        display_name = f"\u0410\u043a\u043a\u0430\u0443\u043d\u0442 \u2116{lot_number}"
                    lot_url = account.get("lot_url")
                    line = f"{display_name} - {lot_url}" if lot_url else f"{display_name}"
                    current.append(line)
                    if len(current) >= STOCK_LIST_LIMIT:
                        batches.append(current)
                        current = []
                if len(current) > 0:
                    batches.append(current)
                if not batches:
                    acc.send_message(chat_id, self._build_stock_message())
                    return
                header_sent = False
                for batch in batches:
                    message_lines = batch
                    if not header_sent:
                        message_lines = [USER.stock_title, *batch]
                        header_sent = True
                    acc.send_message(chat_id, "\n".join(message_lines))
                return
            acc.send_message(chat_id, self._build_stock_message())
        except Exception as exc:
            logger.error(f"Failed to load stock: {exc}")
            acc.send_message(chat_id, USER.stock_failed)

    def _handle_admin_call(self, acc: Account, chat_id: int, owner: str) -> None:
        try:
            self._db.log_admin_call(owner, chat_id, self._user_id, key_id=self._key_id)
            acc.send_message(
                chat_id,
                "Админ вызван. Мы ответим как можно скорее. "
                "Если вопрос срочный — кратко опишите проблему одним сообщением.",
            )
            chat_link = f"https://funpay.com/chat/?node={chat_id}"
            send_message_to_admin(
                "ADMIN CALL\n\n"
                f"Owner: {owner}\n"
                f"Chat ID: {chat_id}\n"
                f"Chat: {chat_link}"
            )
        except Exception as exc:
            logger.error(f"Failed to handle admin call for {owner}: {exc}")
            acc.send_message(chat_id, "Не удалось вызвать администратора. Попробуйте позже.")

    def _handle_lp_exchange(self, acc: Account, chat_id: int, owner: str, raw_text: str) -> None:
        try:
            accounts = self._db.get_user_active_accounts(owner, self._user_id, key_id=self._key_id)
            if not accounts:
                acc.send_message(chat_id, USER.active_rentals_empty)
                return

            parts = raw_text.split()
            target_account = None
            if len(parts) >= 2 and parts[1].isdigit():
                account_id = int(parts[1])
                target_account = next((item for item in accounts if item.get("id") == account_id), None)
                if not target_account:
                    acc.send_message(chat_id, "Аккаунт с таким ID не найден в ваших активных арендах.")
                    return
            elif len(accounts) == 1:
                target_account = accounts[0]
            else:
                current_time = datetime.now(tz=MOSCOW_TZ)
                lines = [
                    "Укажите ID аренды для замены.",
                    "Команда: !лпзамена <ID>",
                    "",
                    "Ваши активные аренды:",
                ]
                for account in accounts:
                    expiry_str, remaining_str = self._format_rental_status(account, current_time)
                    display_name = self._display_account_name(account.get("account_name"))
                    if expiry_str:
                        lines.append(f"ID {account['id']}: {display_name} — осталось {remaining_str}")
                    else:
                        lines.append(f"ID {account['id']}: {display_name} — не начато (ожидаем !код)")
                acc.send_message(chat_id, "\n".join(lines))
                return

            full_target = self._db.get_account_by_id(
                int(target_account.get("id")), self._user_id, key_id=self._key_id
            )
            if full_target:
                target_account = full_target

            rental_start = target_account.get("rental_start")
            if not rental_start:
                acc.send_message(
                    chat_id,
                    "Обмен доступен только после получения кода. "
                    "Сначала используйте !code / !код. "
                    f"После этого есть {LP_EXCHANGE_WINDOW_MINUTES} минут на замену.",
                )
                return

            if isinstance(rental_start, datetime):
                start_dt = rental_start
            else:
                try:
                    start_dt = datetime.strptime(str(rental_start), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    acc.send_message(chat_id, "Не удалось определить время начала аренды. Напишите !админ.")
                    return
            if start_dt.tzinfo is None:
                start_dt = MOSCOW_TZ.localize(start_dt)

            now = datetime.now(tz=MOSCOW_TZ)
            elapsed_seconds = max(0.0, (now - start_dt).total_seconds())
            if elapsed_seconds > LP_EXCHANGE_WINDOW_MINUTES * 60:
                elapsed_minutes = int(elapsed_seconds // 60)
                acc.send_message(
                    chat_id,
                    f"Срок замены истёк. Команда доступна только первые {LP_EXCHANGE_WINDOW_MINUTES} минут "
                    f"после получения кода. Прошло {elapsed_minutes} мин.",
                )
                return

            replacement = self._select_replacement_account(target_account)
            if not replacement:
                acc.send_message(chat_id, self._build_replacement_message(target_account))
                return

            if not self._db.set_account_owner(
                replacement["id"],
                owner,
                self._user_id,
                start_rental=False,
                key_id=self._key_id,
            ):
                acc.send_message(chat_id, "Свободных замен нет. Попробуйте чуть позже.")
                return

            duration_units = target_account.get("rental_duration")
            duration_minutes = target_account.get("rental_duration_minutes")
            if duration_minutes is None:
                duration_minutes = get_duration_minutes(target_account)
            if not duration_minutes:
                duration_minutes = 60
            if duration_units is None:
                duration_units = max(1, int((duration_minutes + 59) // 60))

            conn, cursor = self._db.open_connection()
            try:
                if self._user_id in (None, 0):
                    cursor.execute(
                        """
                        UPDATE accounts
                        SET rental_start = ?, rental_duration = ?, rental_duration_minutes = ?
                        WHERE ID = ?
                        """,
                        (start_dt.strftime("%Y-%m-%d %H:%M:%S"), int(duration_units), int(duration_minutes), replacement["id"]),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE accounts
                        SET rental_start = ?, rental_duration = ?, rental_duration_minutes = ?
                        WHERE ID = ? AND user_id = ?
                        """,
                        (
                            start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            int(duration_units),
                            int(duration_minutes),
                            replacement["id"],
                            int(self._user_id),
                        ),
                    )
                conn.commit()
            finally:
                cursor.close()
                conn.close()

            self._db.release_account(int(target_account["id"]), self._user_id, key_id=self._key_id)
            self._db.update_account(
                int(target_account["id"]),
                {"rental_duration": 1, "rental_duration_minutes": 60},
                self._user_id,
                key_id=self._key_id,
            )

            refreshed = (
                self._db.get_account_by_id(int(replacement["id"]), self._user_id, key_id=self._key_id)
                or replacement
            )
            expiry_str, remaining_str = self._format_rental_status(refreshed, now)
            display_name = self._display_account_name(refreshed.get("account_name"))

            acc.send_message(
                chat_id,
                "✅ Замена выполнена. Ваш новый аккаунт:\n"
                f"ID: {refreshed.get('id')}\n"
                f"Аккаунт: {display_name}\n"
                f"Логин: {refreshed.get('login')}\n"
                f"Пароль: {refreshed.get('password')}\n"
                + (f"Истекает: {expiry_str} МСК | " if expiry_str else "")
                + f"Осталось: {remaining_str}\n\n"
                "⏱ Время аренды сохраняется, оно не продлевается.",
            )

            send_message_to_admin(
                "LP EXCHANGE\n\n"
                f"Owner: {owner}\n"
                f"Old account ID: {target_account.get('id')}\n"
                f"New account ID: {replacement.get('id')}\n"
                f"Window: {LP_EXCHANGE_WINDOW_MINUTES} min\n"
                f"Elapsed: {int(elapsed_seconds // 60)} min",
            )
        except Exception as exc:
            logger.error(f"Failed to exchange account for {owner}: {exc}")
            acc.send_message(chat_id, "Не удалось выполнить замену. Попробуйте позже.")

    def _build_stock_message(self) -> str:
        all_lots = self._db.get_all_lot_accounts(self._user_id, key_id=None)
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
            accounts = self._db.get_user_active_accounts(owner, self._user_id, key_id=self._key_id)
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

            self._db.release_account(account_id, self._user_id, key_id=self._key_id)
            self._db.update_account(
                account_id,
                {"rental_duration": 1, "rental_duration_minutes": 60},
                self._user_id,
                key_id=self._key_id,
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
            query = """
                SELECT 
                    a.ID,
                    a.owner,
                    a.rental_start,
                    a.rental_duration,
                    a.rental_duration_minutes,
                    a.path_to_maFile,
                    a.mafile_json,
                    a.password,
                    a.login,
                    a.account_name,
                    a.rental_order_id
                FROM accounts a
                WHERE a.owner IS NOT NULL
                AND a.rental_start IS NOT NULL
                AND (a.rental_frozen = 0 OR a.rental_frozen IS NULL)
            """
            params: tuple[int, ...] = ()
            # When running multiple bots (one per dashboard user), do NOT leak expiration
            # notifications across users. Older versions queried all rows.
            if self._user_id not in (None, 0):
                query += " AND a.user_id = ?"
                params = (int(self._user_id),)

            cursor.execute(query, params)
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
                rental_order_id,
            ) = row
            # Raw DB values keep sensitive fields encrypted; decrypt before using them.
            try:
                password = self._db._decrypt_value(password)
            except Exception:
                password = None
            try:
                mafile_json = self._db._decrypt_value(mafile_json)
            except Exception:
                mafile_json = None
            if not owner or owner == "OTHER_ACCOUNT":
                continue

            if isinstance(start_time, datetime):
                start_datetime = start_time
            else:
                start_datetime = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            if start_datetime.tzinfo is None:
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
            floor_minutes = math.floor(minutes_remaining)
            if floor_minutes == 10 and 10 not in sent:
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
                    order_id=rental_order_id,
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

    def _resolve_account_steamid(self, account: Optional[dict]) -> Optional[str]:
        if not account:
            return None
        mafile_json = account.get("mafile_json")
        if not mafile_json:
            account_id = account.get("id")
            if account_id is not None:
                try:
                    account_id = int(account_id)
                except (TypeError, ValueError):
                    account_id = None
                full = (
                    self._db.get_account_by_id(account_id, self._user_id, key_id=self._key_id)
                    if account_id is not None
                    else None
                )
                if full:
                    mafile_json = full.get("mafile_json")
        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return None
        return str(steamid64)

    def _fetch_bridge_presence(self, steamid64: int) -> Optional[dict]:
        if not STEAM_BRIDGE_URL:
            return None
        url = f"{STEAM_BRIDGE_URL.rstrip('/')}/presence/{steamid64}"
        try:
            resp = requests.get(url, timeout=4)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data:
                return data
        except Exception:
            return None
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

        steamid64 = self._steamid64_from_mafile(mafile_json)
        if steamid64 is None:
            return False

        next_check = self._expire_delay_next_check.get(account_id)
        if next_check and current_time < next_check:
            return True

        bridge_presence = self._fetch_bridge_presence(steamid64)
        in_match = bool(bridge_presence.get("in_match")) if bridge_presence else False
        steam_display = None
        if bridge_presence:
            steam_display = bridge_presence.get("match_time") or bridge_presence.get("hero_name")
        else:
            bot = get_presence_bot()
            if bot is not None:
                snapshot = bot.get_cached(steamid64)
                if snapshot is None:
                    try:
                        snapshot = asyncio.run(bot.fetch_presence(steamid64))
                    except Exception:
                        snapshot = None
                if snapshot and snapshot.in_match:
                    in_match = True
                    steam_display = snapshot.rich_presence.get("steam_display") if snapshot.rich_presence else None

        if not in_match:
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_next_check.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        since = self._expire_delay_since.get(account_id)
        if since is None:
            self._expire_delay_since[account_id] = current_time
            since = current_time

        if current_time - since >= timedelta(minutes=DOTA_MATCH_GRACE_MINUTES):
            self._expire_delay_since.pop(account_id, None)
            self._expire_delay_next_check.pop(account_id, None)
            self._expire_delay_notified.discard(account_id)
            return False

        self._expire_delay_next_check[account_id] = current_time + timedelta(minutes=1)

        if account_id not in self._expire_delay_notified:
            extra = f"\nСтатус: {steam_display}\n" if steam_display else ""
            try:
                self.send_message_by_owner(
                    owner,
                    "Ваша аренда закончилась, но мы видим, что вы в игре.\n"
                    "У вас есть время, чтобы закончить матч. Через 1 минуту я проверю снова.\n"
                    "Доступ будет закрыт автоматически, если матч уже закончится.\n"
                    "Если хотите продлить — используйте команду:\n"
                    f"!продлить <часы> <ID аккаунта>\n"
                    f"{extra}",
                )
            except Exception:
                pass
            try:
                send_message_to_admin(
                    "EXPIRE DELAYED (IN MATCH)\n\n"
                    f"Account ID: {account_id}\n"
                    f"Owner: {owner}\n"
                    f"Status: {steam_display}\n"
                    "Recheck: 1 minute\n"
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
                f"Осталось: {math.floor(minutes_remaining)} мин\n"
                "Если нужно продление — используйте команду:\n"
                "!продлить <часы> <ID аккаунта>\n\n"
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
        order_id: str | None = None,
    ) -> None:
        logger.info(f"Account {account_id} rental expired.")
        self._expire_warning_sent.pop(account_id, None)
        self._expire_warning_start.pop(account_id, None)
        deauth_ok = False
        deauth_error: str | None = None
        try:
            if AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE:
                if not mafile_json or not password:
                    deauth_error = "mafile_json/password missing (decrypt failed?)"
                else:
                    try:
                        deauth_ok = asyncio.run(
                            logout_all_steam_sessions(
                                steam_login=steam_login,
                                steam_password=password,
                                mafile_json=mafile_json,
                            )
                        )
                    except Exception as exc:
                        deauth_error = str(exc)
                        logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")

            if AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE:
                deauth_status = "ok" if deauth_ok else "failed"
            else:
                deauth_status = "skipped"

            admin_message = (
                "RENTAL EXPIRED\n\n"
                f"Account ID: {account_id}\n"
                f"Owner: {owner}\n"
                f"Deauthorize: {deauth_status}\n"
                f"Expired at: {expiry_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if deauth_error:
                admin_message += f"\nDeauth error: {deauth_error}"
            send_message_to_admin(admin_message)

            try:
                order_link = f"https://funpay.com/orders/{order_id}" if order_id else None
                message = (
                    "\u0412\u0430\u0448\u0430 \u0430\u0440\u0435\u043d\u0434\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430.\n\n"
                    f"ID \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430: {account_id}\n"
                    "\u0417\u0430\u043a\u0430\u0437 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d. \u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0437\u0430\u0439\u0434\u0438\u0442\u0435 \u0432 \u0440\u0430\u0437\u0434\u0435\u043b \u00ab\u041f\u043e\u043a\u0443\u043f\u043a\u0438\u00bb, \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0437\u0430\u043a\u0430\u0437 \u0438 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u0437\u0430\u043a\u0430\u0437\u0430\u00bb.\n"
                    "\u0415\u0441\u043b\u0438 \u0445\u043e\u0442\u0438\u0442\u0435 \u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c, \u043a\u0443\u043f\u0438\u0442\u0435 \u043d\u043e\u0432\u044b\u0439 \u043b\u043e\u0442.\n"
                    "\u0415\u0441\u043b\u0438 \u043d\u0443\u0436\u043d\u0430 \u043f\u043e\u043c\u043e\u0449\u044c, \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 \u0447\u0430\u0442."
                )
                if order_link:
                    message += f"\n\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0442\u0443\u0442 -> {order_link}"
                self.send_message_by_owner(owner, message)
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

        if not self._db.update_account(account_id, update_fields, self._user_id, key_id=self._key_id):
            logger.error(f"Failed to update expired account state for account {account_id}")
            invalid_accs.append(account_id)
        if not self._db.release_account(account_id, self._user_id, key_id=self._key_id):
            logger.error(f"Failed to release expired account {account_id}")
            invalid_accs.append(account_id)
