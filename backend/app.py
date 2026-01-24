import html as html_module
import json
import hashlib
import asyncio
import os
import random
import re
import subprocess
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Thread
from threading import Lock
from typing import Any, Optional
from urllib.parse import quote
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup

from backend.config import (
    DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE,
    STEAM_BRIDGE_URL,
    STEAM_PRESENCE_ENABLED,
    STEAM_PRESENCE_IDENTITY_SECRET,
    STEAM_PRESENCE_LOGIN,
    STEAM_PRESENCE_PASSWORD,
    STEAM_PRESENCE_REFRESH_TOKEN,
    STEAM_PRESENCE_SHARED_SECRET,
)
from DatabaseHandler.databaseSetup import MySQLDB
from FunPayAPI import Account as FPAccount
from FunPayAPI.common import enums as fp_enums
from backend.logger import logger
from backend.notifications import list_notifications
from backend.realtime import manager as realtime_manager
from backend.realtime import (
    publish_chat_message,
    set_chat_cache,
    set_event_loop,
    broadcast_to_user,
    broadcast_to_user_chat,
)
from SteamHandler.changePassword import changeSteamPassword
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence_bot import get_presence_bot, init_presence_bot
from SteamHandler.steampassword.exceptions import ErrorSteamPasswordChange
import requests
from FunpayHandler.bot import FunpayBot


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR.parent / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"

app = FastAPI(title="FunpaySeller")

_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")
_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_MONTH_RE = re.compile(r"\b(\d{1,2})\s+([a-zа-я.]+)\b", re.IGNORECASE)
_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "сент": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

SESSION_COOKIE_NAME = "sessionId"
SESSION_TTL_DAYS = 7
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
SESSION_REFRESH_WINDOW_SECONDS = 24 * 60 * 60

# Simple in-memory rate limits (per-IP) for auth endpoints
RATE_LIMIT_RULES = {
    "login": {"limit": 10, "window": 60},       # 10 attempts per minute
    "register": {"limit": 5, "window": 300},    # 5 attempts per 5 minutes
}
_rate_buckets: dict[tuple[str, str], deque] = defaultdict(deque)
_rate_lock = Lock()


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


def build_proxy_config(
    proxy_url: Optional[str],
    proxy_username: Optional[str] = None,
    proxy_password: Optional[str] = None,
) -> Optional[dict]:
    """
    Normalize proxy inputs into a requests-compatible dict.
    Accepts formats:
      - socks5://host:port
      - socks5://user:pass@host:port
      - socks5://host:port:user:pass (legacy)
      - host:port[:user[:pass]] (scheme defaults to socks5)
    """
    if not proxy_url:
        return None
    raw = str(proxy_url).strip()
    if not raw:
        return None

    scheme = "socks5"
    rest = raw
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        scheme = scheme or "socks5"

    user = proxy_username.strip() if proxy_username else None
    password = proxy_password.strip() if proxy_password else None

    # credentials@host:port
    if "@" in rest:
        creds, rest = rest.split("@", 1)
        if ":" in creds:
            parts = creds.split(":", 1)
            if not user:
                user = parts[0]
            if len(parts) > 1 and not password:
                password = parts[1]
        elif creds and not user:
            user = creds

    parts = rest.split(":")
    if len(parts) < 2:
        raise ValueError("Invalid proxy format, expected host:port")
    host = parts[0]
    port = parts[1]
    if len(parts) >= 3 and not user:
        user = parts[2]
    if len(parts) >= 4 and not password:
        password = parts[3]

    if not host or not port:
        raise ValueError("Invalid proxy format, missing host or port")

    auth = ""
    if user:
        auth = quote(user)
        if password:
            auth += f":{quote(password)}"
        auth += "@"

    proxy_uri = f"{scheme}://{auth}{host}:{port}"
    return {"http": proxy_uri, "https": proxy_uri}

def _format_epoch_time(raw_value: str) -> str | None:
    if not raw_value or not raw_value.isdigit():
        return None
    try:
        stamp = int(raw_value)
    except ValueError:
        return None
    if stamp > 1_000_000_000_000:
        stamp = stamp // 1000
    if stamp < 946684800:
        return None
    dt = datetime.fromtimestamp(stamp)
    label = _normalize_time_label(dt.strftime("%H:%M:%S"))
    today = datetime.now().date()
    if dt.date() != today:
        return f"{label} {dt:%d.%m}"
    return label


def _extract_message_time_from_text(text: str) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    if not text:
        return None
    time_match = _TIME_RE.search(text)
    if not time_match:
        return None
    time_label = _normalize_time_label(time_match.group(1))
    lower = text.lower()
    today = datetime.now().date()
    date_value = None
    if "сегодня" in lower or "today" in lower:
        date_value = today
    elif "вчера" in lower or "yesterday" in lower:
        date_value = today - timedelta(days=1)
    else:
        date_match = _DATE_RE.search(text)
        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))
            year = int(date_match.group(3)) if date_match.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                date_value = datetime(year, month, day).date()
            except ValueError:
                date_value = None
        else:
            month_match = _MONTH_RE.search(lower)
            if month_match:
                day = int(month_match.group(1))
                raw_month = re.sub(r"[^a-zа-я]", "", month_match.group(2))
                month_key = raw_month[:3]
                month = _MONTHS.get(raw_month) or _MONTHS.get(month_key)
                if month:
                    try:
                        date_value = datetime(today.year, month, day).date()
                    except ValueError:
                        date_value = None
    if date_value and date_value != today:
        return f"{time_label} {date_value:%d.%m}"
    return time_label


def _extract_message_time(html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    date_el = (
        soup.select_one(".chat-msg-date")
        or soup.select_one(".message-date")
        or soup.select_one(".msg-date")
        or soup.select_one(".chat-message-date")
        or soup.select_one(".chat-msg-time")
        or soup.select_one(".time")
        or soup.select_one("time")
        or soup.select_one("[class*='date']")
        or soup.select_one("[class*='time']")
    )
    candidate = None
    if date_el:
        candidate = (
            date_el.get("datetime")
            or date_el.get("title")
            or date_el.get("data-time")
            or date_el.get("data-date")
            or date_el.get_text(strip=True)
        )
    if candidate:
        epoch_label = _format_epoch_time(candidate)
        if epoch_label:
            return epoch_label
        parsed = _extract_message_time_from_text(candidate)
        if parsed:
            return parsed
    text = html_module.unescape(soup.get_text(" ", strip=True))
    return _extract_message_time_from_text(text)


def _extract_avatar_url(html: str | None) -> str | None:
    if not html:
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return None
    avatar = soup.select_one(".avatar-photo") or soup.select_one(".avatar") or soup.select_one(".chat-avatar")
    if avatar:
        style = avatar.get("style") or ""
        match = re.search(r"url\\(([^)]+)\\)", style)
        if match:
            url = match.group(1).strip(" '\"")
            if url.startswith("//"):
                url = f"https:{url}"
            if url.startswith("/"):
                url = f"https://funpay.com{url}"
            return url
        img = avatar.find("img")
        if img and img.get("src"):
            url = img.get("src")
            if url.startswith("//"):
                url = f"https:{url}"
            if url.startswith("/"):
                url = f"https://funpay.com{url}"
            return url
    img = soup.find("img")
    if img and img.get("src"):
        url = img.get("src")
        if url.startswith("//"):
            url = f"https:{url}"
        if url.startswith("/"):
            url = f"https://funpay.com{url}"
        return url
    return None
db = MySQLDB()
CHAT_LIST_TTL = 30.0
CHAT_HISTORY_TTL = 10.0
CHAT_HISTORY_MAX = 200
PRESENCE_TTL = 10.0
PRESENCE_OFFLINE_GRACE = 45.0
BALANCE_REFRESH_SECONDS = 15 * 60
BALANCE_SERIES_DAYS = 30
STATS_SERIES_DAYS = 370
_normalized_users: set[int] = set()


def _ensure_user_key_normalized(user_id: int | None) -> None:
    if user_id is None:
        return
    if user_id in _normalized_users:
        return
    try:
        default_key = db.get_default_key(user_id)
        if default_key and default_key.get("id"):
            db.normalize_legacy_key_data(user_id, int(default_key["id"]))
            db.normalize_orphan_keys(user_id)
        db.purge_orphan_key_data(user_id)
    except Exception as exc:
        logger.error(f"Failed to normalize legacy keys for user {user_id}: {exc}")
    finally:
        _normalized_users.add(user_id)


def _start_bot_for_user(user: dict | None) -> None:
    if not user:
        return
    user_id = user.get("id")
    if user_id is None:
        return
    default_key = db.get_default_key(user_id)
    if default_key and default_key.get("golden_key"):
        if not default_key.get("proxy_url"):
            logger.error("Proxy is required for default workspace but missing; skip starting bot.")
            return
        bot_manager.start_for_user_key(
            user_id,
            default_key["id"],
            default_key["golden_key"],
            proxy_url=default_key.get("proxy_url"),
            proxy_username=default_key.get("proxy_username"),
            proxy_password=default_key.get("proxy_password"),
        )
        return
    token = user.get("golden_key")
    if token:
        logger.error("Add a workspace with a proxy to start FunPay bot; inline golden key is not supported without proxy.")


class BotManager:
    def __init__(self):
        self._bots: dict[tuple[int, int | None], dict] = {}
        self._token_index: dict[tuple[int, str], tuple[int | None]] = {}
        self._global_tokens: dict[str, tuple[int, int | None]] = {}
        self._lock = Lock()

    def start_for_user_key(
        self,
        user_id: int,
        key_id: int | None,
        golden_key: str,
        *,
        proxy_url: str | None = None,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> None:
        if not golden_key:
            return
        proxy = None
        try:
            proxy = build_proxy_config(proxy_url, proxy_username, proxy_password)
        except Exception as exc:
            logger.error(f"Invalid proxy for user {user_id} key {key_id}: {exc}")
            return
        with self._lock:
            global_owner = self._global_tokens.get(golden_key)
            if global_owner and global_owner[0] != user_id:
                logger.warning(
                    "FunPay token already active for user %s key %s; skipping start for user %s key %s",
                    global_owner[0],
                    global_owner[1],
                    user_id,
                    key_id,
                )
                return
            existing = self._bots.get((user_id, key_id))
            if existing and existing.get("thread") and existing["thread"].is_alive():
                if existing.get("key") == golden_key and existing.get("proxy") == proxy:
                    return
                bot = existing.get("bot")
                if bot is not None:
                    if existing.get("key") != golden_key:
                        bot.request_token_update(golden_key)
                    if existing.get("proxy") != proxy:
                        bot.update_proxy(proxy)
                if existing.get("key") and self._global_tokens.get(existing.get("key")) == (user_id, key_id):
                    self._global_tokens.pop(existing.get("key"), None)
                existing["key"] = golden_key
                existing["proxy"] = proxy
                self._token_index[(user_id, golden_key)] = key_id
                self._global_tokens[golden_key] = (user_id, key_id)
                return
            token_key = (user_id, golden_key)
            if token_key in self._token_index:
                    canonical = self._token_index.get(token_key)
                    canonical_entry = self._bots.get((user_id, canonical))
                    if canonical_entry:
                        self._bots[(user_id, key_id)] = canonical_entry
                        self._global_tokens.setdefault(golden_key, (user_id, canonical))
                    logger.info(
                        f"FunPay bot reused for user {user_id} key {key_id} (shared token)."
                    )
                    return
            try:
                bot = FunpayBot(token=golden_key, db=db, user_id=user_id, key_id=key_id, proxy=proxy)
                thread = Thread(target=bot.start, daemon=True)
                thread.start()
                self._bots[(user_id, key_id)] = {
                    "bot": bot,
                    "key": golden_key,
                    "thread": thread,
                    "proxy": proxy,
                }
                self._token_index[token_key] = key_id
                self._global_tokens[golden_key] = (user_id, key_id)
                logger.info(f"FunPay bot started for user {user_id} key {key_id}")
            except Exception as exc:
                logger.error(f"Failed to start FunPay bot for user {user_id} key {key_id}: {exc}")

    def start_all(self) -> None:
        for user in db.list_users_with_keys():
            try:
                self.start_for_user_key(
                    user["id"],
                    user.get("key_id"),
                    user["golden_key"],
                    proxy_url=user.get("proxy_url"),
                    proxy_username=user.get("proxy_username"),
                    proxy_password=user.get("proxy_password"),
                )
            except Exception as exc:
                logger.error(f"Failed to start bot for user {user.get('id')}: {exc}")

    def stop_for_user_key(self, user_id: int, key_id: int | None) -> None:
        with self._lock:
            entry = self._bots.pop((user_id, key_id), None)
            if not entry:
                return
            bot = entry.get("bot")
            token = entry.get("key")
            shared = False
            if token:
                token_key = (user_id, token)
                if self._token_index.get(token_key) == key_id:
                    # Keep the token mapping if another key shares the same bot.
                    for (uid, kid), other in self._bots.items():
                        if uid != user_id:
                            continue
                        if other.get("bot") is bot:
                            self._token_index[token_key] = kid
                            self._global_tokens[token] = (user_id, kid)
                            shared = True
                            break
                    if not shared:
                        self._token_index.pop(token_key, None)
                        if self._global_tokens.get(token) == (user_id, key_id):
                            self._global_tokens.pop(token, None)
            if not shared and bot is not None:
                try:
                    bot.request_stop()
                except Exception:
                    pass

    def send_message(self, user_id: int, owner: str, message: str, key_id: int | None = None) -> bool:
        if not owner or not message:
            return False
        with self._lock:
            entry = None
            if key_id is not None:
                entry = self._bots.get((user_id, key_id))
            if entry is None:
                for (uid, _kid), bot in self._bots.items():
                    if uid == user_id:
                        entry = bot
                        break
            bot = entry.get("bot") if entry else None
        if not bot:
            return False
        try:
            bot.send_message_by_owner(owner, message)
            return True
        except Exception as exc:
            logger.error(f"Failed to send message to {owner}: {exc}")
            return False


bot_manager = BotManager()


class ChatCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._chats: dict[tuple[int, int | None], dict[str, Any]] = {}
        self._histories: dict[tuple[int, int | None], dict[int, dict[str, Any]]] = {}
        self._refreshing_chats: set[tuple[int, int | None]] = set()
        self._refreshing_histories: set[tuple[int, int, int | None]] = set()

    def get_cached_chats(self, user_id: int, key_id: int | None) -> tuple[list[dict] | None, float | None]:
        cache_key = (user_id, key_id)
        with self._lock:
            entry = self._chats.get(cache_key)
            if not entry:
                return None, None
            return list(entry["items"]), entry["ts"]

    def get_cached_history(self, user_id: int, key_id: int | None, chat_id: int) -> tuple[list[dict] | None, float | None]:
        cache_key = (user_id, key_id)
        with self._lock:
            user_hist = self._histories.get(cache_key)
            if not user_hist:
                return None, None
            entry = user_hist.get(chat_id)
            if not entry:
                return None, None
            return list(entry["items"]), entry["ts"]

    def get_chat_summary(self, user_id: int, key_id: int | None, chat_id: int) -> dict | None:
        cache_key = (user_id, key_id)
        with self._lock:
            entry = self._chats.get(cache_key)
            if not entry:
                return None
            for chat in entry["items"]:
                if chat.get("id") == chat_id:
                    return dict(chat)
        return None

    def get_chat_id_by_name(self, user_id: int, key_id: int | None, name: str) -> int | None:
        if not name:
            return None
        cache_key = (user_id, key_id)
        with self._lock:
            entry = self._chats.get(cache_key)
            if not entry:
                return None
            for chat in entry["items"]:
                if chat.get("name") == name:
                    return chat.get("id")
        return None

    def set_chats(self, user_id: int, key_id: int | None, items: list[dict]) -> None:
        self._set_chats(user_id, key_id, items)

    def _set_chats(self, user_id: int, key_id: int | None, items: list[dict]) -> None:
        cache_key = (user_id, key_id)
        with self._lock:
            existing = self._chats.get(cache_key, {}).get("items") if self._chats.get(cache_key) else []
            avatar_map = {
                chat.get("id"): chat.get("avatar_url")
                for chat in (existing or [])
                if chat.get("id") is not None and chat.get("avatar_url")
            }
            merged = []
            for item in items:
                if not item.get("avatar_url") and item.get("id") in avatar_map:
                    item["avatar_url"] = avatar_map.get(item.get("id"))
                merged.append(item)
            self._chats[cache_key] = {"items": merged, "ts": time.time()}

    def _set_history(self, user_id: int, key_id: int | None, chat_id: int, items: list[dict]) -> None:
        cache_key = (user_id, key_id)
        with self._lock:
            user_hist = self._histories.setdefault(cache_key, {})
            trimmed = list(items)[-CHAT_HISTORY_MAX:]
            user_hist[chat_id] = {"items": trimmed, "ts": time.time()}

    def append_message(self, user_id: int, key_id: int | None, chat_id: int, item: dict, max_items: int = CHAT_HISTORY_MAX) -> None:
        now = time.time()
        cache_key = (user_id, key_id)
        with self._lock:
            user_hist = self._histories.setdefault(cache_key, {})
            entry = user_hist.get(chat_id)
            if not entry:
                entry = {"items": [], "ts": now}
                user_hist[chat_id] = entry
            items = entry["items"]
            items.append(item)
            if len(items) > max_items:
                del items[:-max_items]
            entry["ts"] = now

            chats_entry = self._chats.get(cache_key)
            if chats_entry:
                for chat in chats_entry["items"]:
                    if chat.get("id") == chat_id:
                        chat["last_message_text"] = item.get("text") or ""
                        if item.get("sent_time"):
                            chat["last_message_time"] = item.get("sent_time")
                        chat["unread"] = False
                        break
                chats_entry["ts"] = now

    def _fetch_chats(self, token: str, proxy: Optional[dict] = None) -> list[dict]:
        account = FPAccount(token, proxy=proxy).get()
        chats_map = account.get_chats(update=True)
        items = []
        for chat in chats_map.values():
            last_message_time = _extract_message_time(getattr(chat, "html", None))
            avatar_url = _extract_avatar_url(getattr(chat, "html", None))
            items.append(
                {
                    "id": chat.id,
                    "name": chat.name,
                    "last_message_text": chat.last_message_text,
                    "last_message_time": last_message_time,
                    "unread": chat.unread,
                    "node_msg_id": chat.node_msg_id,
                    "user_msg_id": chat.user_msg_id,
                    "avatar_url": avatar_url,
                }
            )
        return items

    def _fetch_history(self, token: str, chat_id: int, proxy: Optional[dict] = None) -> list[dict]:
        account = FPAccount(token, proxy=proxy).get()
        messages = account.get_chat_history(chat_id) or []
        items = []
        for message in messages:
            items.append(
                {
                    "id": message.id,
                    "text": message.text,
                    "author": message.author,
                    "author_id": message.author_id,
                    "chat_id": message.chat_id,
                    "chat_name": message.chat_name,
                    "image_link": message.image_link,
                    "by_bot": message.by_bot,
                    "type": message.type.name if message.type else None,
                    "sent_time": _extract_message_time(message.html),
                }
            )
        return items

    def refresh_chats_sync(self, user_id: int, key_id: int | None, token: str, proxy: Optional[dict] = None) -> list[dict]:
        items = self._fetch_chats(token, proxy=proxy)
        self._set_chats(user_id, key_id, items)
        return items

    def refresh_history_sync(self, user_id: int, key_id: int | None, chat_id: int, token: str, proxy: Optional[dict] = None) -> list[dict]:
        items = self._fetch_history(token, chat_id, proxy=proxy)
        self._set_history(user_id, key_id, chat_id, items)
        return items

    def refresh_chats_async(self, user_id: int, key_id: int | None, token: str, proxy: Optional[dict] = None, on_done=None) -> None:
        cache_key = (user_id, key_id)
        with self._lock:
            if cache_key in self._refreshing_chats:
                return
            self._refreshing_chats.add(cache_key)

        def runner() -> None:
            try:
                items = self._fetch_chats(token, proxy=proxy)
                self._set_chats(user_id, key_id, items)
                if on_done:
                    try:
                        on_done(items)
                    except Exception as exc:
                        logger.warning(f"chats_async on_done failed for user {user_id} key {key_id}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed to refresh chats cache for user {user_id} key {key_id}: {exc}")
            finally:
                with self._lock:
                    self._refreshing_chats.discard(cache_key)

        Thread(target=runner, daemon=True).start()

    def refresh_history_async(self, user_id: int, key_id: int | None, chat_id: int, token: str, proxy: Optional[dict] = None, on_done=None) -> None:
        key = (user_id, chat_id, key_id)
        with self._lock:
            if key in self._refreshing_histories:
                return
            self._refreshing_histories.add(key)

        def runner() -> None:
            try:
                items = self._fetch_history(token, chat_id, proxy=proxy)
                self._set_history(user_id, key_id, chat_id, items)
                if on_done:
                    try:
                        on_done(items)
                    except Exception as exc:
                        logger.warning(f"history_async on_done failed for user {user_id} key {key_id}: {exc}")
            except Exception as exc:
                logger.warning(f"Failed to refresh chat history cache for user {user_id} key {key_id}: {exc}")
            finally:
                with self._lock:
                    self._refreshing_histories.discard(key)

        Thread(target=runner, daemon=True).start()


chat_cache = ChatCache()
set_chat_cache(chat_cache)


class PresenceCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[int, dict[str, Any]] = {}
        self._refreshing: set[int] = set()

    def get_cached(self, steamid64: int) -> tuple[dict | None, float | None]:
        with self._lock:
            entry = self._entries.get(steamid64)
            if not entry:
                return None, None
            return dict(entry["data"]), entry["ts"]

    def set_cached(self, steamid64: int, data: dict) -> None:
        with self._lock:
            self._entries[steamid64] = {"data": dict(data), "ts": time.time()}

    def refresh_async(self, steamid64: int, fetcher) -> None:
        with self._lock:
            if steamid64 in self._refreshing:
                return
            self._refreshing.add(steamid64)

        def runner() -> None:
            try:
                data = fetcher()
                if data is None:
                    return
                self.set_cached(steamid64, data)
            except Exception as exc:
                logger.warning(f"Failed to refresh presence cache for {steamid64}: {exc}")
            finally:
                with self._lock:
                    self._refreshing.discard(steamid64)

        Thread(target=runner, daemon=True).start()


presence_cache = PresenceCache()

if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")


def _frontend_assets_mounted() -> bool:
    return any(getattr(route, "path", None) == "/assets" for route in app.router.routes)


def _maybe_build_frontend() -> None:
    if FRONTEND_DIST_DIR.exists():
        return
    if os.getenv("FRONTEND_AUTO_BUILD", "true").lower() not in ("1", "true", "yes", "on"):
        return
    frontend_dir = BASE_DIR.parent / "frontend"
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        logger.warning("Frontend package.json not found; skipping auto build.")
        return
    logger.info("Frontend build missing; attempting auto-build.")
    try:
        subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)
    except Exception as exc:
        logger.warning(f"Frontend auto-build failed: {exc}")


@app.on_event("startup")
def start_background_services() -> None:
    try:
        set_event_loop(asyncio.get_event_loop())
    except Exception:
        pass
    _maybe_build_frontend()
    if FRONTEND_ASSETS_DIR.exists() and not _frontend_assets_mounted():
        app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")
    try:
        init_presence_bot(
            enabled=STEAM_PRESENCE_ENABLED,
            login=STEAM_PRESENCE_LOGIN,
            password=STEAM_PRESENCE_PASSWORD,
            shared_secret=STEAM_PRESENCE_SHARED_SECRET or None,
            identity_secret=STEAM_PRESENCE_IDENTITY_SECRET or None,
            refresh_token=STEAM_PRESENCE_REFRESH_TOKEN or None,
        )
    except Exception as exc:
        logger.warning(f"Failed to init Steam presence bot: {exc}")
    bot_manager.start_all()
    logger.info("Startup complete (per-user FunPay bots initialized if keys are present).")


def _steamid64_from_mafile(mafile_json: str | dict) -> int | None:
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


def _fetch_bridge_presence(steamid64: int) -> dict | None:
    if not STEAM_BRIDGE_URL:
        return None
    url = f"{STEAM_BRIDGE_URL.rstrip('/')}/presence/{steamid64}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    return data


def _is_secure_request(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def _client_ip(request: Request | WebSocket) -> str:
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def _check_rate_limit(request: Request, bucket: str) -> None:
    rule = RATE_LIMIT_RULES.get(bucket)
    if not rule:
        return
    limit = rule["limit"]
    window = rule["window"]
    now = time.time()
    key = (bucket, _client_ip(request))
    with _rate_lock:
        dq = _rate_buckets[key]
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            logger.warning(f"Rate limit exceeded for {bucket} from {key[1]}")
            raise HTTPException(status_code=429, detail="Too many attempts, slow down.")
        dq.append(now)


def _to_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def require_admin(request: Request, response: Response) -> None:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session = db.get_session_user(session_id)
        if session:
            expires_at = _to_datetime(session.get("expires_at"))
            last_seen_at = _to_datetime(session.get("last_seen_at"))
            now = datetime.utcnow()
            if not expires_at or expires_at <= now:
                db.delete_session(session_id)
                _clear_session_cookie(response)
            else:
                should_refresh = (
                    last_seen_at is None
                    or (now - last_seen_at).total_seconds() >= SESSION_REFRESH_WINDOW_SECONDS
                )
                if should_refresh:
                    new_expires = now + timedelta(days=SESSION_TTL_DAYS)
                    db.refresh_session(session_id, new_expires, now)
                    _set_session_cookie(response, request, session_id)
                request.state.user = {
                    "id": session.get("user_id"),
                    "username": session.get("username"),
                    "golden_key": session.get("golden_key"),
                }
                _ensure_user_key_normalized(session.get("user_id"))
                return

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        if token:
            user = db.get_user_by_token(token)
            if user:
                request.state.user = user
                _ensure_user_key_normalized(user.get("id"))
                return
    raise HTTPException(status_code=401, detail="Unauthorized")


def _get_session_from_websocket(websocket: WebSocket) -> dict | None:
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        cookie_header = websocket.headers.get("cookie", "")
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE_NAME:
                session_id = value
                break
    if not session_id:
        return None
    session = db.get_session_user(session_id)
    if not session:
        return None
    expires_at = _to_datetime(session.get("expires_at"))
    last_seen_at = _to_datetime(session.get("last_seen_at"))
    now = datetime.utcnow()
    if expires_at and expires_at <= now:
        db.delete_session(session_id)
        return None
    should_refresh = (
        last_seen_at is None
        or (now - last_seen_at).total_seconds() >= SESSION_REFRESH_WINDOW_SECONDS
    )
    if should_refresh:
        new_expires = now + timedelta(days=SESSION_TTL_DAYS)
        db.refresh_session(session_id, new_expires, now)
    return session


def current_user_id(request: Request) -> int | None:
    user = getattr(request.state, "user", None)
    return user.get("id") if user else None


def _resolve_key_id(request: Request) -> int | None:
    header = request.headers.get("x-key-id") or request.headers.get("x-fp-key-id")
    if header:
        try:
            value = int(header)
            return value if value > 0 else None
        except Exception:
            return None
    param = request.query_params.get("key_id")
    if param:
        try:
            value = int(param)
            return value if value > 0 else None
        except Exception:
            return None
    return None


def require_funpay_token(request: Request) -> tuple[int, str, int | None, Optional[dict]]:
    user = getattr(request.state, "user", None) or {}
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    key_id = _resolve_key_id(request)
    token = None
    proxy_url = None
    proxy_username = None
    proxy_password = None
    if key_id is not None:
        key_entry = db.get_user_key(user_id, key_id)
        token = (key_entry or {}).get("golden_key")
        proxy_url = (key_entry or {}).get("proxy_url")
        proxy_username = (key_entry or {}).get("proxy_username")
        proxy_password = (key_entry or {}).get("proxy_password")
    if not token:
        default_key = db.get_default_key(user_id)
        token = (default_key or {}).get("golden_key") or user.get("golden_key")
        if default_key:
            key_id = default_key.get("id")
            proxy_url = default_key.get("proxy_url")
            proxy_username = default_key.get("proxy_username")
            proxy_password = default_key.get("proxy_password")
    if not token:
        raise HTTPException(status_code=503, detail="FunPay golden key not configured")
    if not proxy_url:
        raise HTTPException(status_code=503, detail="Proxy is required for this workspace")
    try:
        proxy = build_proxy_config(proxy_url, proxy_username, proxy_password)
    except Exception as exc:
        logger.error(f"Proxy configuration invalid for user {user_id} key {key_id}: {exc}")
        raise HTTPException(status_code=503, detail="Invalid proxy configuration")
    return user_id, token, key_id, proxy


def require_funpay_account(request: Request):
    user = getattr(request.state, "user", None)
    _, token, _, proxy = require_funpay_token(request)
    try:
        acc = FPAccount(token, proxy=proxy).get()
    except Exception:
        raise HTTPException(status_code=503, detail="FunPay session not initialized")
    return acc


class AccountCreate(BaseModel):
    account_name: str
    mafile_json: str
    login: str
    password: str
    mmr: int = Field(ge=0)
    rental_duration: int = Field(default=1, ge=0)
    rental_minutes: int = Field(default=0, ge=0, le=59)
    owner: Optional[str] = None
    key_id: Optional[int] = None


class AccountUpdate(BaseModel):
    account_name: Optional[str] = None
    mafile_json: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    mmr: Optional[int] = Field(default=None, ge=0)
    rental_duration: Optional[int] = Field(default=None, ge=0)
    rental_minutes: Optional[int] = Field(default=None, ge=0, le=59)
    key_id: Optional[int] = None


class AssignRequest(BaseModel):
    owner: str


class ExtendRequest(BaseModel):
    hours: int = Field(default=0, ge=0)
    minutes: int = Field(default=0, ge=0, le=59)


class FreezeRequest(BaseModel):
    frozen: bool = True


class ChatMessage(BaseModel):
    text: str


class LotMapping(BaseModel):
    lot_number: int = Field(ge=1)
    account_id: int = Field(ge=1)
    lot_url: Optional[str] = None
    key_id: Optional[int] = None


class SteamPasswordRequest(BaseModel):
    new_password: Optional[str] = None


class AuthRegister(BaseModel):
    username: str
    password: str
    golden_key: str


class AuthLogin(BaseModel):
    username: str
    password: str


class GoldenKeyUpdate(BaseModel):
    golden_key: str


class BlacklistCreate(BaseModel):
    owner: str
    reason: Optional[str] = None
    order_id: Optional[str] = None


class BlacklistRemove(BaseModel):
    owners: list[str]


class BlacklistUpdate(BaseModel):
    owner: str
    reason: Optional[str] = None


class KeyCreate(BaseModel):
    label: str
    golden_key: str
    make_default: bool = False
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


class KeyUpdate(BaseModel):
    label: Optional[str] = None
    golden_key: Optional[str] = None
    make_default: Optional[bool] = None
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


@app.get("/api/health")
def health() -> dict:
    funpay_available = db.has_any_golden_key()
    return {
        "status": "ok",
        "funpay_enabled": funpay_available,
        "funpay_ready": funpay_available,
    }


@app.post("/api/auth/register")
def auth_register(payload: AuthRegister, request: Request, response: Response) -> dict:
    _check_rate_limit(request, "register")
    token = db.create_user(payload.username, payload.password, payload.golden_key)
    if not token:
        raise HTTPException(status_code=400, detail="User already exists or invalid data")
    user = db.get_user_by_username(payload.username)
    if user:
        _start_bot_for_user(user)
        now = datetime.utcnow()
        expires_at = now + timedelta(days=SESSION_TTL_DAYS)
        session_id = db.create_session(user["id"], expires_at, now)
        _set_session_cookie(response, request, session_id)
    return {"username": payload.username}


@app.post("/api/auth/login")
def auth_login(payload: AuthLogin, request: Request, response: Response) -> dict:
    _check_rate_limit(request, "login")
    user = db.verify_user_credentials(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    now = datetime.utcnow()
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
    session_id = db.create_session(user["id"], expires_at, now)
    _set_session_cookie(response, request, session_id)
    _start_bot_for_user(user)
    return {"username": user["username"]}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        db.delete_session(session_id)
        _clear_session_cookie(response)
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        db.logout_token(token)
    return {"success": True}


@app.get("/api/auth/me", dependencies=[Depends(require_admin)])
def auth_me(request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    return {"username": user.get("username"), "id": user.get("id")}


@app.put("/api/auth/golden-key", dependencies=[Depends(require_admin)])
def auth_update_golden(payload: GoldenKeyUpdate, request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    ok = db.update_golden_key(user["id"], payload.golden_key)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update golden key")
    _start_bot_for_user(user)
    return {"success": True}


@app.get("/api/keys", dependencies=[Depends(require_admin)])
def list_keys(request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    items = db.list_user_keys(user.get("id"))
    return {"items": items}


@app.post("/api/keys", dependencies=[Depends(require_admin)])
def create_key(payload: KeyCreate, request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    label = (payload.label or "").strip() or "Workspace"
    golden_key = (payload.golden_key or "").strip()
    if not golden_key:
        raise HTTPException(status_code=400, detail="golden_key is required")
    proxy_url = (payload.proxy_url or "").strip()
    proxy_username = (payload.proxy_username or "").strip() or None
    proxy_password = (payload.proxy_password or "").strip() or None
    if not proxy_url:
        raise HTTPException(status_code=400, detail="proxy_url is required")
    key_id = db.add_user_key(
        user.get("id"),
        label,
        golden_key,
        payload.make_default,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )
    if key_id is None:
        raise HTTPException(status_code=400, detail="Failed to create key")
    bot_manager.start_for_user_key(
        user.get("id"),
        key_id,
        golden_key,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )
    return {"id": key_id, "cloned": None}


@app.patch("/api/keys/{key_id}", dependencies=[Depends(require_admin)])
def update_key(key_id: int, payload: KeyUpdate, request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    proxy_url = None
    proxy_username = None
    proxy_password = None
    if payload.proxy_url is not None:
        proxy_url = payload.proxy_url.strip()
        if not proxy_url:
            raise HTTPException(status_code=400, detail="proxy_url is required")
    if payload.proxy_username is not None:
        proxy_username = payload.proxy_username.strip()
    if payload.proxy_password is not None:
        proxy_password = payload.proxy_password.strip()
    ok = db.update_user_key(
        user.get("id"),
        key_id,
        label=payload.label,
        golden_key=payload.golden_key,
        make_default=payload.make_default,
        proxy_url=proxy_url,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update key")
    if payload.golden_key or proxy_url is not None or proxy_username is not None or proxy_password is not None:
        key = db.get_user_key(user.get("id"), key_id)
        if key and key.get("golden_key"):
            bot_manager.start_for_user_key(
                user.get("id"),
                key_id,
                key.get("golden_key"),
                proxy_url=key.get("proxy_url"),
                proxy_username=key.get("proxy_username"),
                proxy_password=key.get("proxy_password"),
            )
    return {"success": True}


@app.post("/api/keys/{key_id}/default", dependencies=[Depends(require_admin)])
def set_default_key(key_id: int, request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    ok = db.update_user_key(user.get("id"), key_id, make_default=True)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to set default key")
    key = db.get_user_key(user.get("id"), key_id)
    if key and key.get("golden_key"):
        bot_manager.start_for_user_key(
            user.get("id"),
            key_id,
            key.get("golden_key"),
            proxy_url=key.get("proxy_url"),
            proxy_username=key.get("proxy_username"),
            proxy_password=key.get("proxy_password"),
        )
    return {"success": True}


@app.delete("/api/keys/{key_id}", dependencies=[Depends(require_admin)])
def delete_key(key_id: int, request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    ok = db.delete_user_key(user.get("id"), key_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to delete key")
    bot_manager.stop_for_user_key(user.get("id"), key_id)
    return {"success": True}


@app.get("/api/stats", dependencies=[Depends(require_admin)])
def stats(request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    return db.get_rental_statistics(uid, key_id=key_id)


@app.get("/api/notifications", dependencies=[Depends(require_admin)])
def notifications(limit: int = 50) -> dict:
    return {"items": list_notifications(limit=limit)}


@app.get("/api/funpay/stats", dependencies=[Depends(require_admin)])
def funpay_stats(request: Request, refresh: bool = False) -> dict:
    user_id, token, key_id, proxy = require_funpay_token(request)
    now = datetime.utcnow()
    latest = db.get_latest_balance_snapshot(user_id, key_id=key_id)

    latest_dt = None
    if latest and latest.get("created_at"):
        value = latest.get("created_at")
        if isinstance(value, datetime):
            latest_dt = value
        else:
            try:
                latest_dt = datetime.fromisoformat(str(value))
            except Exception:
                try:
                    latest_dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
                except Exception:
                    latest_dt = None

    should_refresh = refresh or latest is None
    if latest_dt and not refresh:
        age = (now - latest_dt).total_seconds()
        if age < BALANCE_REFRESH_SECONDS:
            should_refresh = False
        else:
            should_refresh = True

    if should_refresh:
        try:
            balance = _fetch_funpay_balance(token, proxy=proxy)
            if balance:
                db.insert_balance_snapshot(
                    user_id,
                    balance.get("total_rub"),
                    balance.get("available_rub"),
                    balance.get("total_usd"),
                    balance.get("total_eur"),
                    key_id=key_id,
                )
                latest = {
                    **balance,
                    "created_at": now,
                }
        except Exception as exc:
            logger.warning(f"Failed to refresh FunPay balance: {exc}")

    snapshots = db.get_balance_snapshots(user_id, BALANCE_SERIES_DAYS, key_id=key_id)
    if not snapshots and latest and latest.get("total_rub") is not None:
        snapshots = [
            {
                "total_rub": latest.get("total_rub"),
                "available_rub": latest.get("available_rub"),
                "total_usd": latest.get("total_usd"),
                "total_eur": latest.get("total_eur"),
                "created_at": latest.get("created_at") or now,
            }
        ]
    balance_series = _balance_series_from_snapshots(snapshots, BALANCE_SERIES_DAYS)

    order_counts = db.get_order_counts_by_day(
        user_id,
        actions=["issued", "extended"],
        days=STATS_SERIES_DAYS,
        key_id=key_id,
    )
    review_counts = db.get_review_counts_by_day(user_id, STATS_SERIES_DAYS)

    payload = {
        "balance": latest,
        "balance_series": balance_series,
        "orders": {
            "daily": _build_daily_series(order_counts, 14),
            "weekly": _build_weekly_series(order_counts, 8),
            "monthly": _build_monthly_series(order_counts, 12),
        },
        "reviews": {
            "daily": _build_daily_series(review_counts, 14),
            "weekly": _build_weekly_series(review_counts, 8),
            "monthly": _build_monthly_series(review_counts, 12),
        },
        "generated_at": now,
    }
    return _etag_response(request, payload)


@app.get("/api/orders/resolve", dependencies=[Depends(require_admin)])
def resolve_order_owner(request: Request, order_id: str) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    order_key = (order_id or "").strip()
    if not order_key:
        raise HTTPException(status_code=400, detail="order_id is required")
    items = db.search_order_history(query=order_key, limit=5, user_id=uid, key_id=key_id)
    if not items:
        raise HTTPException(status_code=404, detail="Order not found")
    order_key_lower = order_key.lower()
    match = next(
        (item for item in items if str(item.get("order_id") or "").lower() == order_key_lower),
        None,
    )
    item = match or items[0]
    owner = str(item.get("owner") or "").strip()
    if not owner:
        raise HTTPException(status_code=404, detail="Order buyer not found")
    return {
        "order_id": item.get("order_id") or order_key,
        "owner": owner,
        "action": item.get("action"),
        "created_at": item.get("created_at"),
    }


@app.get("/api/orders/history", dependencies=[Depends(require_admin)])
def orders_history(
    request: Request,
    query: str = "",
    limit: int = 200,
    fast: bool = True,
    include_chat: bool = True,
) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    q = (query or "").strip()
    limit_value = max(1, min(int(limit or 200), 500))
    steamid_query = q if re.fullmatch(r"7656119\d{10}", q) else None

    accounts = None
    account_ids: list[int] | None = None
    account_names: list[str] | None = None

    if steamid_query:
        accounts = db.get_all_accounts(uid, key_id=key_id)
        account_ids = []
        account_names = []
        for acc in accounts:
            steamid64 = _steamid64_from_mafile(acc.get("mafile_json"))
            if steamid64 is not None and str(steamid64) == steamid_query:
                if acc.get("id") is not None:
                    try:
                        account_ids.append(int(acc["id"]))
                    except (TypeError, ValueError):
                        pass
                if acc.get("account_name"):
                    account_names.append(acc["account_name"])
        if not account_ids and not account_names:
            return {"items": []}
        items = db.search_order_history(
            query=None,
            limit=limit_value,
            user_id=uid,
            account_ids=account_ids,
            account_names=account_names,
            key_id=key_id,
        )
    else:
        items = db.search_order_history(
            query=q or None,
            limit=limit_value,
            user_id=uid,
            key_id=key_id,
        )

    if accounts is None:
        accounts = db.get_all_accounts(uid, key_id=key_id)

    account_by_id = {}
    account_by_name = {}
    steam_map = {}
    for acc in accounts:
        acc_id = acc.get("id")
        if acc_id is not None:
            account_by_id[acc_id] = acc
        name = acc.get("account_name")
        if name:
            account_by_name[name] = acc
        steamid64 = _steamid64_from_mafile(acc.get("mafile_json"))
        if steamid64 is not None:
            steam_value = str(steamid64)
            if acc_id is not None:
                steam_map[acc_id] = steam_value
            if name:
                steam_map[name] = steam_value
            login = acc.get("login")
            if login:
                steam_map[login] = steam_value

    chat_map = {}
    token = None
    proxy = None
    if include_chat:
        try:
            _, token, resolved_key_id, proxy = require_funpay_token(request)
            key_id = resolved_key_id
        except HTTPException:
            token = None
    if include_chat and token:
        cached_chats, ts = chat_cache.get_cached_chats(uid, key_id)
        if cached_chats:
            chat_map = {
                chat.get("name"): chat.get("id")
                for chat in cached_chats
                if chat.get("name")
            }
            if fast and (ts is None or time.time() - ts > CHAT_LIST_TTL):
                chat_cache.refresh_chats_async(uid, key_id, token, proxy=proxy)
        else:
            if fast:
                chat_cache.refresh_chats_async(uid, key_id, token, proxy=proxy)
            else:
                try:
                    chats = chat_cache.refresh_chats_sync(uid, key_id, token, proxy=proxy)
                    chat_map = {
                        chat.get("name"): chat.get("id")
                        for chat in chats
                        if chat.get("name")
                    }
                except Exception:
                    chat_map = {}

    for item in items:
        buyer = item.get("owner")
        item["buyer"] = buyer
        if not item.get("steam_id"):
            acc_id = item.get("account_id")
            if acc_id in steam_map:
                item["steam_id"] = steam_map.get(acc_id)
            else:
                item["steam_id"] = steam_map.get(item.get("account_name"))
        acc = None
        if item.get("account_id") in account_by_id:
            acc = account_by_id.get(item.get("account_id"))
        elif item.get("account_name") in account_by_name:
            acc = account_by_name.get(item.get("account_name"))
        if acc and not item.get("login"):
            item["login"] = acc.get("login")
        if include_chat:
            chat_id = chat_map.get(buyer) if buyer else None
            item["chat_url"] = f"https://funpay.com/chat/?node={quote(str(chat_id))}" if chat_id else None
        else:
            item["chat_url"] = None

    allowed_actions = {"issued", "extended", "refunded", "closed", "paid"}
    action_priority = {"refunded": 5, "closed": 4, "extended": 3, "issued": 2, "paid": 1}

    def created_key(value: Any) -> float:
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)):
            return float(value)
        if value:
            try:
                return datetime.fromisoformat(str(value)).timestamp()
            except Exception:
                return 0.0
        return 0.0

    filtered = []
    for item in items:
        action = str(item.get("action") or "").lower()
        if action in allowed_actions:
            filtered.append(item)

    dedup: dict[str, dict] = {}
    for item in filtered:
        order_id = str(item.get("order_id") or "")
        if not order_id:
            continue
        action = str(item.get("action") or "").lower()
        priority = action_priority.get(action, 0)
        existing = dedup.get(order_id)
        if not existing:
            dedup[order_id] = item
            continue
        existing_action = str(existing.get("action") or "").lower()
        existing_priority = action_priority.get(existing_action, 0)
        if priority > existing_priority:
            dedup[order_id] = item
            continue
        if priority == existing_priority:
            if created_key(item.get("created_at")) > created_key(existing.get("created_at")):
                dedup[order_id] = item

    merged = list(dedup.values())
    merged.sort(key=lambda row: created_key(row.get("created_at")), reverse=True)

    for item in merged:
        if str(item.get("action") or "").lower() == "paid":
            item["action"] = "issued"

    payload = {"items": merged}
    return _etag_response(request, payload)


@app.get("/api/blacklist", dependencies=[Depends(require_admin)])
def blacklist_list(request: Request, query: str = "") -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    items = db.list_blacklist(uid, query=query or None, key_id=key_id)
    return {"items": items}


@app.post("/api/blacklist", dependencies=[Depends(require_admin)])
def blacklist_add(payload: BlacklistCreate, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    owner = (payload.owner or "").strip()
    order_id = (payload.order_id or "").strip()
    if not owner and order_id:
        items = db.search_order_history(query=order_id, limit=5, user_id=uid, key_id=key_id)
        if not items:
            raise HTTPException(status_code=404, detail="Order not found")
        order_key = order_id.lower()
        match = next(
            (item for item in items if str(item.get("order_id") or "").lower() == order_key),
            None,
        )
        item = match or items[0]
        owner = str(item.get("owner") or "").strip()
    if not owner:
        raise HTTPException(status_code=400, detail="Owner is required")
    success = db.add_blacklist_entry(owner, payload.reason, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=400, detail="User already blacklisted")
    return {"success": True}


@app.patch("/api/blacklist/{entry_id}", dependencies=[Depends(require_admin)])
def blacklist_update(entry_id: int, payload: BlacklistUpdate, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    owner = (payload.owner or "").strip()
    if not owner:
        raise HTTPException(status_code=400, detail="Owner is required")
    updated = db.update_blacklist_entry(entry_id, owner, payload.reason, uid, key_id=key_id)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to update blacklist entry")
    return {"success": True}


@app.post("/api/blacklist/remove", dependencies=[Depends(require_admin)])
def blacklist_remove(payload: BlacklistRemove, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    removed = db.remove_blacklist_entries(payload.owners, uid, key_id=key_id)
    return {"removed": removed}


@app.post("/api/blacklist/clear", dependencies=[Depends(require_admin)])
def blacklist_clear(request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    removed = db.clear_blacklist(uid, key_id=key_id)
    return {"removed": removed}


def _payload_etag(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _etag_response(request: Request, payload: Any) -> Response:
    encoded_payload = jsonable_encoder(payload)
    user = getattr(request.state, "user", None) or {}
    user_id = user.get("id")
    etag = _payload_etag({"user_id": user_id, "payload": encoded_payload})
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate, stale-while-revalidate=30, stale-if-error=300",
        "Vary": "Cookie",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=encoded_payload, headers=headers)


def _ws_payload(payload: Any) -> Any:
    return jsonable_encoder(payload)


def _is_admin_call_message(text: str | None) -> bool:
    if not text:
        return False
    value = str(text).strip().lower()
    return value.startswith("!admin") or value.startswith("!админ")


def _annotate_admin_calls(items: list[dict]) -> list[dict]:
    annotated: list[dict] = []
    for item in items:
        entry = dict(item)
        entry["admin_call"] = _is_admin_call_message(entry.get("text") or "")
        annotated.append(entry)
    return annotated


def _attach_admin_call_counts(
    items: list[dict], user_id: int, key_id: int | None = None
) -> list[dict]:
    counts = db.get_admin_call_counts(user_id, key_id=key_id)
    merged: list[dict] = []
    for item in items:
        entry = dict(item)
        chat_id = entry.get("id")
        if chat_id is not None:
            meta = counts.get(int(chat_id))
            entry["admin_calls"] = int(meta.get("count", 0)) if meta else 0
            entry["admin_last_called_at"] = meta.get("last_called_at") if meta else None
        merged.append(entry)
    return merged


def _format_match_time(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    try:
        total = max(0, int(seconds))
    except Exception:
        return None
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value)).date()
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue
    return None


def _build_daily_series(counts: dict[str, int], days: int) -> list[int]:
    total_days = max(1, int(days))
    today = datetime.utcnow().date()
    start = today - timedelta(days=total_days - 1)
    series: list[int] = []
    for idx in range(total_days):
        day = start + timedelta(days=idx)
        series.append(int(counts.get(day.isoformat(), 0)))
    return series


def _build_weekly_series(counts: dict[str, int], weeks: int) -> list[int]:
    total_weeks = max(1, int(weeks))
    today = datetime.utcnow().date()
    current_week_start = today - timedelta(days=today.weekday())
    series: list[int] = []
    for idx in range(total_weeks):
        week_start = current_week_start - timedelta(days=7 * (total_weeks - 1 - idx))
        week_total = 0
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            week_total += int(counts.get(day.isoformat(), 0))
        series.append(week_total)
    return series


def _add_months(base: datetime.date, delta: int) -> datetime.date:
    month_index = (base.year * 12 + (base.month - 1)) + delta
    year = month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, 1).date()


def _build_monthly_series(counts: dict[str, int], months: int) -> list[int]:
    total_months = max(1, int(months))
    today = datetime.utcnow().date()
    current_month_start = today.replace(day=1)
    series: list[int] = []
    for idx in range(total_months):
        month_start = _add_months(current_month_start, -(total_months - 1 - idx))
        next_month = _add_months(month_start, 1)
        month_total = 0
        day = month_start
        while day < next_month:
            month_total += int(counts.get(day.isoformat(), 0))
            day += timedelta(days=1)
        series.append(month_total)
    return series


def _balance_series_from_snapshots(snapshots: list[dict], days: int) -> list[float]:
    total_days = max(1, int(days))
    today = datetime.utcnow().date()
    start = today - timedelta(days=total_days - 1)
    daily: dict[str, float] = {}
    for snap in snapshots:
        snap_date = _coerce_date(snap.get("created_at"))
        if not snap_date:
            continue
        key = snap_date.isoformat()
        value = snap.get("total_rub")
        if value is None:
            continue
        try:
            daily[key] = float(value)
        except Exception:
            continue
    series: list[float] = []
    last_value: float | None = None
    for idx in range(total_days):
        day = start + timedelta(days=idx)
        key = day.isoformat()
        if key in daily:
            last_value = daily[key]
        if last_value is None:
            series.append(0.0)
        else:
            series.append(last_value)
    return series


def _fetch_funpay_balance(token: str, proxy: Optional[dict] = None) -> dict | None:
    account = FPAccount(token, proxy=proxy).get()
    subcats = account.get_sorted_subcategories().get(fp_enums.SubCategoryTypes.COMMON, {}) or {}
    subcat_ids = list(subcats.keys())
    random.shuffle(subcat_ids)
    for subcat_id in subcat_ids:
        try:
            lots = account.get_subcategory_public_lots(fp_enums.SubCategoryTypes.COMMON, subcat_id) or []
        except Exception:
            lots = []
        if not lots:
            continue
        lot = random.choice(lots)
        balance = account.get_balance(lot.id)
        return {
            "total_rub": balance.total_rub,
            "available_rub": balance.available_rub,
            "total_usd": balance.total_usd,
            "total_eur": balance.total_eur,
        }
    return None


def _presence_empty() -> dict:
    return {
        "in_game": False,
        "in_match": False,
        "lobby_info": "",
        "hero_name": None,
        "hero_token": None,
        "presence_label": "Оффлайн",
        "hero_level": None,
        "match_seconds": None,
        "match_time": None,
    }


def _presence_for_steamid(
    steamid64: int | None,
    bridge_presence: dict | None = None,
) -> dict:
    if not steamid64 or not STEAM_BRIDGE_URL:
        return _presence_empty()
    if bridge_presence is None:
        bridge_presence = _fetch_bridge_presence(steamid64)
    if not bridge_presence:
        return _presence_empty()
    in_match = bool(bridge_presence.get("in_match"))
    in_game = bool(bridge_presence.get("in_game"))
    hero_name = bridge_presence.get("hero_name") or None
    hero_level = None
    match_seconds = bridge_presence.get("match_seconds")
    match_time = bridge_presence.get("match_time")
    if match_time is None and match_seconds is not None:
        match_time = _format_match_time(match_seconds)
    if in_match:
        extras = []
        if hero_name:
            extras.append(hero_name)
        if match_time:
            extras.append(match_time)
        presence_label = f"В матче({')('.join(extras)})" if extras else "В матче"
    elif in_game:
        presence_label = "В игре"
    else:
        presence_label = "Оффлайн"
    return {
        "in_game": bool(bridge_presence.get("in_game")),
        "in_match": bool(bridge_presence.get("in_match")),
        "lobby_info": bridge_presence.get("lobby_info") or "",
        "hero_name": hero_name,
        "hero_token": bridge_presence.get("hero_token") or None,
        "presence_label": presence_label,
        "hero_level": hero_level,
        "match_seconds": match_seconds,
        "match_time": match_time,
    }


def _presence_for_steamid_cached(
    steamid64: int | None,
    max_age: float = PRESENCE_TTL,
    fast: bool = True,
) -> dict:
    if not steamid64 or not STEAM_BRIDGE_URL:
        return _presence_empty()

    cached, ts = presence_cache.get_cached(steamid64)
    now = time.time()
    if cached is not None and ts is not None and now - ts <= max_age:
        return cached

    def should_keep_cached(data: dict) -> bool:
        if cached is None or ts is None:
            return False
        if time.time() - ts > PRESENCE_OFFLINE_GRACE:
            return False
        if not (cached.get("in_game") or cached.get("in_match")):
            return False
        return not data.get("in_game") and not data.get("in_match")

    def fetch_presence() -> dict | None:
        bridge_presence = _fetch_bridge_presence(steamid64)
        if not bridge_presence:
            return None
        data = _presence_for_steamid(steamid64, bridge_presence=bridge_presence)
        if should_keep_cached(data):
            return None
        return data

    if cached is None and fast:
        presence_cache.refresh_async(steamid64, fetch_presence)
        return _presence_empty()

    if cached is not None and fast:
        presence_cache.refresh_async(steamid64, fetch_presence)
        return cached

    bridge_presence = _fetch_bridge_presence(steamid64)
    if not bridge_presence:
        return cached if cached is not None else _presence_for_steamid(steamid64)
    data = _presence_for_steamid(steamid64, bridge_presence=bridge_presence)
    if should_keep_cached(data):
        return cached
    presence_cache.set_cached(steamid64, data)
    return data


@app.get("/api/accounts", dependencies=[Depends(require_admin)])
async def accounts(request: Request, include_steamid: bool = False, lite: bool = False) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    if lite:
        items = db.get_all_accounts_light(uid, key_id=key_id)
        return {"items": items}
    items = db.get_all_accounts(uid, key_id=key_id)
    if not items:
        return {"items": items}

    for acc in items:
        if include_steamid:
            steamid64 = _steamid64_from_mafile(acc.get("mafile_json"))
            acc["steamid"] = str(steamid64) if steamid64 is not None else None
        acc.pop("mafile_json", None)
    return {"items": items}


@app.get("/api/lots", dependencies=[Depends(require_admin)])
def lots(request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    return {"items": db.list_lot_mappings(uid, key_id=key_id)}


@app.post("/api/lots", dependencies=[Depends(require_admin)])
def create_lot_mapping(payload: LotMapping, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = payload.key_id if payload.key_id is not None else _resolve_key_id(request)
    success = db.set_lot_mapping(payload.lot_number, payload.account_id, payload.lot_url, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True}


@app.delete("/api/lots/{lot_number}", dependencies=[Depends(require_admin)])
def delete_lot_mapping(lot_number: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    db.delete_lot_mapping(lot_number, uid, key_id=key_id)
    return {"success": True}


@app.get("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def account_detail(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    account = db.get_account_by_id(account_id, uid, key_id=key_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/accounts", dependencies=[Depends(require_admin)])
def create_account(payload: AccountCreate, request: Request) -> dict:
    if not payload.mafile_json.strip():
        raise HTTPException(status_code=400, detail="mafile_json is required")
    total_minutes = payload.rental_duration * 60 + payload.rental_minutes
    if total_minutes <= 0:
        raise HTTPException(status_code=400, detail="Rental duration must be greater than 0")
    uid = current_user_id(request)
    key_id = payload.key_id if payload.key_id is not None else _resolve_key_id(request)
    success = db.add_account(
        payload.account_name,
        "",
        payload.login,
        payload.password,
        payload.rental_duration,
        payload.owner,
        mafile_json=payload.mafile_json,
        user_id=uid,
        duration_minutes=total_minutes,
        mmr=payload.mmr,
        key_id=key_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to create account")
    return {"status": "ok"}


@app.patch("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def update_account(account_id: int, payload: AccountUpdate, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    fields = payload.dict(exclude_none=True)
    duration_hours = fields.pop("rental_duration", None)
    duration_minutes = fields.pop("rental_minutes", None)
    if duration_hours is not None or duration_minutes is not None:
        if duration_hours is None or duration_minutes is None:
            existing = db.get_account_by_id(account_id, uid, key_id=key_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Account not found")
            if duration_hours is None:
                duration_hours = int(existing.get("rental_duration") or 0)
            if duration_minutes is None:
                existing_minutes = existing.get("rental_duration_minutes")
                if existing_minutes is None:
                    existing_minutes = int(existing.get("rental_duration") or 0) * 60
                duration_minutes = int(existing_minutes) % 60
        total_minutes = int(duration_hours) * 60 + int(duration_minutes)
        if total_minutes <= 0:
            raise HTTPException(status_code=400, detail="Rental duration must be greater than 0")
        fields["rental_duration"] = int(duration_hours)
        fields["rental_duration_minutes"] = total_minutes
    success = db.update_account(account_id, fields, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update account")
    return {"status": "ok"}


@app.delete("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def delete_account(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    success = db.delete_account_by_id(account_id, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/assign", dependencies=[Depends(require_admin)])
def assign_account(account_id: int, payload: AssignRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    success = db.set_account_owner(account_id, payload.owner, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=400, detail="Account already assigned")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/release", dependencies=[Depends(require_admin)])
def release_account(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    success = db.release_account(account_id, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/extend", dependencies=[Depends(require_admin)])
def extend_account(account_id: int, payload: ExtendRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    total_minutes = payload.hours * 60 + payload.minutes
    if total_minutes <= 0:
        raise HTTPException(status_code=400, detail="Extension must be greater than 0")
    success = db.extend_rental_duration(account_id, payload.hours, payload.minutes, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rental")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/freeze", dependencies=[Depends(require_admin)])
def freeze_account(account_id: int, payload: FreezeRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    success = db.set_account_frozen(account_id, payload.frozen, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True, "frozen": payload.frozen}


@app.post("/api/rentals/{account_id}/freeze", dependencies=[Depends(require_admin)])
async def freeze_rental(account_id: int, payload: FreezeRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    account = db.get_account_by_id(account_id, uid, key_id=key_id)
    if not account or not account.get("owner") or account.get("owner") == "OTHER_ACCOUNT":
        raise HTTPException(status_code=404, detail="Rental not found")

    owner = str(account.get("owner") or "").strip()
    now = datetime.utcnow() + timedelta(hours=3)
    if payload.frozen:
        if account.get("rental_frozen"):
            return {"success": True, "frozen": True}
        ok = db.set_rental_freeze_state(account_id, True, frozen_at=now, user_id=uid, key_id=key_id)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to freeze rental")
        try:
            mafile_json = account.get("mafile_json")
            if mafile_json:
                await logout_all_steam_sessions(
                    steam_login=account.get("login") or account.get("account_name"),
                    steam_password=account.get("password"),
                    mafile_json=mafile_json,
                )
        except Exception as exc:
            logger.warning(f"Failed to deauthorize Steam sessions for account {account_id}: {exc}")
        if owner:
            bot_manager.send_message(
                uid,
                owner,
                "Администратор заморозил вашу аренду. Вход и Steam Guard временно отключены. "
                "Если нужна помощь — !админ.",
                key_id=key_id,
            )
        return {"success": True, "frozen": True}

    if not account.get("rental_frozen"):
        return {"success": True, "frozen": False}

    frozen_at = account.get("rental_frozen_at")
    rental_start = account.get("rental_start")
    new_start = None
    if rental_start and frozen_at:
        try:
            start_dt = rental_start if isinstance(rental_start, datetime) else datetime.strptime(
                str(rental_start), "%Y-%m-%d %H:%M:%S"
            )
            frozen_dt = frozen_at if isinstance(frozen_at, datetime) else datetime.strptime(
                str(frozen_at), "%Y-%m-%d %H:%M:%S"
            )
            delta = now - frozen_dt
            if delta.total_seconds() < 0:
                delta = timedelta(0)
            new_start = start_dt + delta
        except Exception as exc:
            logger.warning(f"Failed to adjust rental_start for account {account_id}: {exc}")
            new_start = None

    ok = db.set_rental_freeze_state(account_id, False, rental_start=new_start, user_id=uid, key_id=key_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to unfreeze rental")
    return {"success": True, "frozen": False}


@app.post("/api/accounts/{account_id}/steam/deauthorize", dependencies=[Depends(require_admin)])
async def steam_deauthorize(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    account = db.get_account_by_id(account_id, uid, key_id=key_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    mafile_json = account.get("mafile_json")
    if not mafile_json:
        raise HTTPException(status_code=400, detail="mafile_json is required for Steam actions")

    if DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE:
        bot = get_presence_bot()
        if bot is not None:
            steamid64 = _steamid64_from_mafile(mafile_json)
            if steamid64 is not None:
                if not bot.wait_ready(timeout=0.5):
                    raise HTTPException(status_code=503, detail="Steam presence bot is not ready yet. Try again.")
                snapshot = bot.get_cached(steamid64)
                if snapshot is None:
                    snapshot = await bot.fetch_presence(steamid64)
                if snapshot and snapshot.in_match:
                    steam_display = snapshot.rich_presence.get("steam_display") if snapshot.rich_presence else None
                    extra = f" ({steam_display})" if steam_display else ""
                    raise HTTPException(
                        status_code=409,
                        detail=f"Аккаунт сейчас в матче Dota 2{extra}. Попробуйте снова после окончания матча.",
                    )

    ok = await logout_all_steam_sessions(
        steam_login=account.get("login") or account.get("account_name"),
        steam_password=account.get("password"),
        mafile_json=mafile_json,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to deauthorize Steam sessions")
    return {"success": True}


@app.post("/api/accounts/{account_id}/steam/password", dependencies=[Depends(require_admin)])
async def steam_change_password(account_id: int, payload: SteamPasswordRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    account = db.get_account_by_id(account_id, uid, key_id=key_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    mafile_json = account.get("mafile_json")
    if not mafile_json:
        raise HTTPException(status_code=400, detail="mafile_json is required for Steam actions")

    new_password = payload.new_password.strip() if payload.new_password else None
    if new_password == "":
        new_password = None

    try:
        updated_password = await changeSteamPassword(
            path_to_maFile=None,
            password=account.get("password"),
            mafile_json=mafile_json,
            new_password=new_password,
            steam_login=account.get("login") or account.get("account_name"),
        )
    except ErrorSteamPasswordChange as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Steam password change failed: {exc}") from exc

    login = account.get("login")
    if login:
        db.update_password_by_login(login, updated_password)
    else:
        db.update_account(account_id, {"password": updated_password}, uid, key_id=key_id)

    return {"success": True, "new_password": updated_password}


@app.get("/api/rentals/active", dependencies=[Depends(require_admin)])
def active_rentals(
    request: Request,
    expand: str = "",
    fast: bool = True,
    max_age: float = PRESENCE_TTL,
    include_steamid: bool = False,
) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    expand_set = {part.strip().lower() for part in (expand or "").split(",") if part.strip()}
    include_presence = "presence" in expand_set or "all" in expand_set or not expand_set
    include_chat = "chat" in expand_set or "all" in expand_set
    max_age = max(0.0, float(max_age))

    include_mafile = include_presence or include_steamid
    items = db.get_active_users(uid, include_mafile=include_mafile, key_id=key_id)
    token = None
    proxy = None
    if include_chat:
        try:
            _, token, resolved_key_id, proxy = require_funpay_token(request)
            key_id = resolved_key_id
        except HTTPException:
            token = None
    admin_calls_by_owner = db.get_admin_call_counts_by_owner(uid, key_id=key_id)

    chat_map = {}
    if include_chat and token:
        cached_chats, ts = chat_cache.get_cached_chats(uid, key_id)
        if cached_chats:
            chat_map = {
                chat.get("name"): chat.get("id")
                for chat in cached_chats
                if chat.get("name")
            }
            if fast and (ts is None or time.time() - ts > CHAT_LIST_TTL):
                chat_cache.refresh_chats_async(uid, key_id, token, proxy=proxy)
        else:
            if fast:
                chat_cache.refresh_chats_async(uid, key_id, token, proxy=proxy)
            else:
                try:
                    chats = chat_cache.refresh_chats_sync(uid, key_id, token, proxy=proxy)
                    chat_map = {
                        chat.get("name"): chat.get("id")
                        for chat in chats
                        if chat.get("name")
                    }
                except Exception:
                    chat_map = {}

    for item in items:
        steamid64 = _steamid64_from_mafile(item.get("mafile_json"))
        item["steamid"] = str(steamid64) if steamid64 is not None else None

        if include_presence:
            item.update(_presence_for_steamid_cached(steamid64, max_age=max_age, fast=fast))

        item.pop("mafile_json", None)

        if include_chat:
            owner = item.get("owner")
            chat_id = chat_map.get(owner)
            if chat_id:
                item["chat_url"] = f"https://funpay.com/chat/?node={quote(str(chat_id))}"
            else:
                item["chat_url"] = None
        else:
            item["chat_url"] = None

        owner = str(item.get("owner") or "").strip().lower()
        if owner:
            meta = admin_calls_by_owner.get(owner)
            item["admin_calls"] = int(meta.get("count", 0)) if meta else 0
            item["admin_last_called_at"] = meta.get("last_called_at") if meta else None
        else:
            item["admin_calls"] = 0
            item["admin_last_called_at"] = None

    return {"items": items}


@app.get("/api/rentals/user/{owner}", dependencies=[Depends(require_admin)])
def user_rentals(owner: str, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    return {"items": db.get_user_active_accounts(owner, uid, key_id=key_id)}


@app.post("/api/rentals/user/{owner}/extend", dependencies=[Depends(require_admin)])
def extend_owner(owner: str, payload: ExtendRequest, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    total_minutes = payload.hours * 60 + payload.minutes
    if total_minutes <= 0:
        raise HTTPException(status_code=400, detail="Extension must be greater than 0")
    success = db.add_time_to_owner_accounts(owner, payload.hours, payload.minutes, uid, key_id=key_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rentals")
    return {"status": "ok"}


@app.get("/api/chats", dependencies=[Depends(require_admin)])
def chats(
    request: Request,
    fast: bool = True,
    refresh: bool = False,
    max_age: float = CHAT_LIST_TTL,
) -> dict:
    user_id, token, key_id, proxy = require_funpay_token(request)
    max_age = max(0.0, float(max_age))
    cached, ts = chat_cache.get_cached_chats(user_id, key_id)
    now = time.time()

    if fast and cached is not None:
        if refresh or ts is None or now - ts > max_age:
            chat_cache.refresh_chats_async(user_id, key_id, token, proxy=proxy)
        items_with_calls = _attach_admin_call_counts(cached, user_id, key_id)
        return _etag_response(request, {"items": items_with_calls})

    try:
        items = chat_cache.refresh_chats_sync(user_id, key_id, token, proxy=proxy)
        items_with_calls = _attach_admin_call_counts(items, user_id, key_id)
        return _etag_response(request, {"items": items_with_calls})
    except Exception as exc:
        if cached is not None:
            items_with_calls = _attach_admin_call_counts(cached, user_id, key_id)
            return _etag_response(request, {"items": items_with_calls})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/stream/chats", dependencies=[Depends(require_admin)])
async def stream_chats(
    request: Request,
    max_age: float = CHAT_LIST_TTL,
    interval: float = 2.5,
) -> Response:
    user_id, token, key_id, proxy = require_funpay_token(request)
    max_age = max(0.0, float(max_age))
    interval = max(1.0, float(interval))

    async def event_stream():
        last_etag = None
        last_ping = time.time()
        while True:
            if await request.is_disconnected():
                break
            cached, ts = chat_cache.get_cached_chats(user_id, key_id)
            now = time.time()
            items = cached
            if cached is None or ts is None or now - ts > max_age:
                try:
                    items = chat_cache.refresh_chats_sync(user_id, key_id, token, proxy=proxy)
                except Exception:
                    items = cached or []
            merged = _attach_admin_call_counts(items or [], user_id, key_id)
            payload = {"items": merged}
            encoded = jsonable_encoder(payload)
            etag = _payload_etag({"user_id": user_id, "payload": encoded})
            if etag != last_etag:
                last_etag = etag
                data = json.dumps(encoded, ensure_ascii=False)
                yield f"event: chats\ndata: {data}\n\n"
                last_ping = now
            elif now - last_ping > 15:
                yield ": ping\n\n"
                last_ping = now
            await asyncio.sleep(interval)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.post("/api/admin-calls/{chat_id}/clear", dependencies=[Depends(require_admin)])
def clear_admin_call(chat_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    key_id = _resolve_key_id(request)
    cleared = db.clear_admin_call(chat_id, uid, key_id=key_id)
    return {"cleared": bool(cleared)}


@app.get("/api/chats/{chat_id}/history", dependencies=[Depends(require_admin)])
def chat_history(
    chat_id: int,
    request: Request,
    limit: int = 50,
    fast: bool = True,
    refresh: bool = False,
    max_age: float = CHAT_HISTORY_TTL,
) -> dict:
    user_id, token, key_id, proxy = require_funpay_token(request)
    max_age = max(0.0, float(max_age))
    limit = max(1, min(int(limit), CHAT_HISTORY_MAX))

    cached, ts = chat_cache.get_cached_history(user_id, key_id, chat_id)
    now = time.time()
    if fast and cached is not None:
        if refresh:
            try:
                items = chat_cache.refresh_history_sync(user_id, key_id, chat_id, token, proxy=proxy)
                items = _annotate_admin_calls(items[-limit:])
                return _etag_response(request, {"items": items})
            except Exception:
                items = _annotate_admin_calls(cached[-limit:])
                return _etag_response(request, {"items": items})
        if ts is None or now - ts > max_age:
            chat_cache.refresh_history_async(user_id, key_id, chat_id, token, proxy=proxy)
        items = _annotate_admin_calls(cached[-limit:])
        return _etag_response(request, {"items": items})

    try:
        items = chat_cache.refresh_history_sync(user_id, key_id, chat_id, token, proxy=proxy)
        items = _annotate_admin_calls(items[-limit:])
        return _etag_response(request, {"items": items})
    except Exception as exc:
        if cached is not None:
            items = _annotate_admin_calls(cached[-limit:])
            return _etag_response(request, {"items": items})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/stream/chats/{chat_id}/history", dependencies=[Depends(require_admin)])
async def stream_chat_history(
    chat_id: int,
    request: Request,
    limit: int = 80,
    max_age: float = CHAT_HISTORY_TTL,
    interval: float = 2.0,
) -> Response:
    user_id, token, key_id, proxy = require_funpay_token(request)
    max_age = max(0.0, float(max_age))
    interval = max(1.0, float(interval))
    limit = max(1, min(int(limit), CHAT_HISTORY_MAX))

    async def event_stream():
        last_etag = None
        last_ping = time.time()
        while True:
            if await request.is_disconnected():
                break
            cached, ts = chat_cache.get_cached_history(user_id, key_id, chat_id)
            now = time.time()
            items = cached
            if cached is None or ts is None or now - ts > max_age:
                try:
                    items = chat_cache.refresh_history_sync(user_id, key_id, chat_id, token, proxy=proxy)
                except Exception:
                    items = cached or []
            payload = {"items": _annotate_admin_calls((items or [])[-limit:])}
            encoded = jsonable_encoder(payload)
            etag = _payload_etag({"user_id": user_id, "payload": encoded})
            if etag != last_etag:
                last_etag = etag
                data = json.dumps(encoded, ensure_ascii=False)
                yield f"event: history\ndata: {data}\n\n"
                last_ping = now
            elif now - last_ping > 15:
                yield ": ping\n\n"
                last_ping = now
            await asyncio.sleep(interval)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    # Capture the main event loop for cross-thread websocket broadcasts
    set_event_loop(asyncio.get_running_loop())
    session = _get_session_from_websocket(websocket)
    if not session:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    user_id = session.get("user_id")
    if user_id is None:
        await websocket.close(code=4401)
        return
    raw_key_id = (
        websocket.query_params.get("key_id")
        or websocket.query_params.get("keyId")
        or websocket.query_params.get("key")
    )
    key_id: int | None = None
    proxy_url = None
    proxy_username = None
    proxy_password = None
    if raw_key_id:
        try:
            key_id = int(raw_key_id)
        except Exception:
            key_id = None
    token = ""
    if key_id is not None:
        key_entry = db.get_user_key(int(user_id), key_id)
        token = (key_entry or {}).get("golden_key") or ""
        proxy_url = (key_entry or {}).get("proxy_url")
        proxy_username = (key_entry or {}).get("proxy_username")
        proxy_password = (key_entry or {}).get("proxy_password")
    if not token:
        default_key = db.get_default_key(int(user_id))
        token = (default_key or {}).get("golden_key") or session.get("golden_key") or ""
        if default_key:
            key_id = default_key.get("id")
            proxy_url = default_key.get("proxy_url")
            proxy_username = default_key.get("proxy_username")
            proxy_password = default_key.get("proxy_password")

    proxy = None
    if token:
        if not proxy_url:
            await websocket.send_json(_ws_payload({"type": "error", "message": "Proxy is required for this workspace"}))
            await websocket.close(code=4000)
            return
        try:
            proxy = build_proxy_config(proxy_url, proxy_username, proxy_password)
        except Exception as exc:
            await websocket.send_json(_ws_payload({"type": "error", "message": f"Invalid proxy: {exc}"}))
            await websocket.close(code=4001)
            return

    await realtime_manager.connect(websocket, int(user_id), key_id)

    try:
        await websocket.send_json(_ws_payload({"type": "hello", "user_id": int(user_id), "key_id": key_id}))

        items: list[dict] = []
        if token:
            cached, ts = chat_cache.get_cached_chats(int(user_id), key_id)
            now = time.time()
            fresh = cached is not None and ts is not None and now - ts <= CHAT_LIST_TTL
            if fresh:
                items = cached or []
            else:
                # send quickly with whatever we have (maybe empty) then refresh async
                items = cached or []
                chat_cache.refresh_chats_async(
                    int(user_id),
                    key_id,
                    token,
                    proxy=proxy,
                    on_done=lambda updated: broadcast_to_user(
                        int(user_id),
                        {"type": "chats:list", "items": _attach_admin_call_counts(updated, int(user_id), key_id)},
                        key_id,
                    ),
                )
            items = _attach_admin_call_counts(items, int(user_id), key_id)
        await websocket.send_json(_ws_payload({"type": "chats:list", "items": items}))

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                continue

            if not isinstance(data, dict):
                continue
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json(_ws_payload({"type": "pong"}))
                continue

            if msg_type == "subscribe":
                chat_id_raw = data.get("chat_id")
                try:
                    chat_id = int(chat_id_raw)
                except Exception:
                    await websocket.send_json(_ws_payload({"type": "error", "message": "Invalid chat id"}))
                    continue
                await realtime_manager.subscribe(websocket, chat_id)
                history_items: list[dict] = []
                if token:
                    cached, ts = chat_cache.get_cached_history(int(user_id), key_id, chat_id)
                    now = time.time()
                    fresh = cached is not None and ts is not None and now - ts <= CHAT_HISTORY_TTL
                    if fresh:
                        history_items = cached or []
                    else:
                        history_items = cached or []
                        chat_cache.refresh_history_async(
                            int(user_id),
                            key_id,
                            chat_id,
                            token,
                            proxy=proxy,
                            on_done=lambda updated: broadcast_to_user_chat(
                                int(user_id),
                                chat_id,
                                {
                                    "type": "chat:history",
                                    "chat_id": chat_id,
                                    "items": _annotate_admin_calls(updated[-CHAT_HISTORY_MAX:]),
                                },
                                key_id,
                            ),
                        )
                history_items = _annotate_admin_calls(history_items[-CHAT_HISTORY_MAX:])
                await websocket.send_json(
                    _ws_payload({"type": "chat:history", "chat_id": chat_id, "items": history_items})
                )
                continue

            if msg_type == "unsubscribe":
                chat_id_raw = data.get("chat_id")
                try:
                    chat_id = int(chat_id_raw)
                except Exception:
                    continue
                await realtime_manager.unsubscribe(websocket, chat_id)
                continue

            if msg_type == "send":
                chat_id_raw = data.get("chat_id")
                text = (data.get("text") or "").strip()
                if not text:
                    await websocket.send_json(_ws_payload({"type": "send:error", "message": "Message text is required"}))
                    continue
                if not token:
                    await websocket.send_json(_ws_payload({"type": "send:error", "message": "FunPay token not configured"}))
                    continue
                try:
                    chat_id = int(chat_id_raw)
                except Exception:
                    await websocket.send_json(_ws_payload({"type": "send:error", "message": "Invalid chat id"}))
                    continue
                try:
                    account = FPAccount(token, proxy=proxy).get()
                    cached_chat = chat_cache.get_chat_summary(int(user_id), key_id, chat_id)
                    chat_name = cached_chat.get("name") if cached_chat else None
                    message = account.send_message(chat_id, text, chat_name)
                    sent_time = _extract_message_time(getattr(message, "html", None))
                    if not sent_time:
                        sent_time = _normalize_time_label(datetime.now().strftime("%H:%M:%S"))
                    item = {
                        "id": message.id,
                        "text": message.text,
                        "author": message.author,
                        "author_id": message.author_id,
                        "chat_id": message.chat_id,
                        "chat_name": message.chat_name,
                        "image_link": message.image_link,
                        "by_bot": message.by_bot,
                        "type": message.type.name if message.type else None,
                        "sent_time": sent_time,
                    }
                    publish_chat_message(int(user_id), key_id, chat_id, item)
                    await websocket.send_json(
                        _ws_payload({"type": "send:ok", "chat_id": chat_id, "message_id": message.id})
                    )
                except Exception as exc:
                    await websocket.send_json(_ws_payload({"type": "send:error", "message": str(exc)}))
                continue

    finally:
        await realtime_manager.disconnect(websocket)

@app.post("/api/chats/{chat_id}/send", dependencies=[Depends(require_admin)])
def chat_send(chat_id: int, payload: ChatMessage, request: Request) -> dict:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Message text is required")
    user_id, token, key_id, proxy = require_funpay_token(request)
    try:
        account = FPAccount(token, proxy=proxy).get()
        cached_chat = chat_cache.get_chat_summary(user_id, key_id, chat_id)
        chat_name = cached_chat.get("name") if cached_chat else None
        message = account.send_message(chat_id, payload.text, chat_name)
        sent_time = _extract_message_time(getattr(message, "html", None))
        if not sent_time:
            sent_time = _normalize_time_label(datetime.now().strftime("%H:%M:%S"))
        item = {
            "id": message.id,
            "text": message.text,
            "author": message.author,
            "author_id": message.author_id,
            "chat_id": message.chat_id,
            "chat_name": message.chat_name,
            "image_link": message.image_link,
            "by_bot": message.by_bot,
            "type": message.type.name if message.type else None,
            "sent_time": sent_time,
        }
        chat_cache.append_message(user_id, key_id, chat_id, item)
        return {"status": "ok", "message_id": message.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _frontend_build_missing_response() -> HTMLResponse:
    message = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Frontend build missing</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 40px; color: #1f2937; }
      code, pre { background: #f3f4f6; padding: 12px; border-radius: 6px; display: block; }
      h1 { font-size: 24px; margin-bottom: 12px; }
    </style>
  </head>
  <body>
    <h1>Frontend build not found</h1>
    <p>The React frontend has not been built yet. Build it and redeploy:</p>
    <pre>cd frontend
npm install
npm run build</pre>
  </body>
</html>"""
    return HTMLResponse(message, status_code=503)

@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return _frontend_build_missing_response()


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> FileResponse:
    if path.startswith(("api", "assets")):
        raise HTTPException(status_code=404)
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return _frontend_build_missing_response()
