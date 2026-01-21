from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass
from typing import Any
import traceback
try:  # py311+ has ExceptionGroup in builtins
    from types import ExceptionGroup  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        from exceptiongroup import ExceptionGroup  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        ExceptionGroup = None  # type: ignore[assignment]

from backend.logger import logger

try:
    from steam import Client as SteamClient
    from steam import User as SteamUser
    from steam.gateway import ConnectionClosed, WebSocketClosure  # type: ignore

    _STEAMIO_AVAILABLE = True
except Exception:  # pragma: no cover
    SteamClient = None  # type: ignore[assignment]
    SteamUser = None  # type: ignore[assignment]
    ConnectionClosed = None  # type: ignore[assignment]
    WebSocketClosure = None  # type: ignore[assignment]
    _STEAMIO_AVAILABLE = False


_DOTA2_APP_ID = 570


def is_in_dota_match(user: Any) -> bool:
    game = getattr(user, "game", None)
    if game is not None and getattr(game, "id", None) != _DOTA2_APP_ID:
        return False

    app = getattr(user, "app", None)
    if app is None or getattr(app, "id", None) != _DOTA2_APP_ID:
        return False

    rich_presence = getattr(user, "rich_presence", None) or {}

    text = " ".join([str(k) for k in rich_presence.keys()] + [str(v) for v in rich_presence.values()]).lower()
    if any(x in text for x in ("mainmenu", "main menu", "spectator", "idle")):
        return False

    if "level" in rich_presence:
        return True

    steam_display = str(
        rich_presence.get("steam_display")
        or rich_presence.get("steamDisplay")
        or rich_presence.get("SteamDisplay")
        or ""
    )
    if "HeroSelection" in steam_display or "StrategyTime" in steam_display:
        return True

    return False


def _get_steamid64(user: Any) -> int | None:
    steam_id = getattr(user, "steam_id", None)
    as_64 = getattr(steam_id, "as_64", None)
    if as_64 is not None:
        try:
            return int(as_64)
        except Exception:
            return None
    id64 = getattr(user, "id64", None)
    if id64 is not None:
        try:
            return int(id64)
        except Exception:
            return None
    return None


@dataclass(frozen=True)
class PresenceSnapshot:
    in_match: bool
    ts: float
    rich_presence: dict[str, str]


class SteamPresenceBot:
    """
    Runs a steamio (steam.py-style) client in a background thread and caches
    rich presence states for friends.
    """

    def __init__(
        self,
        *,
        login: str,
        password: str,
        shared_secret: str | None = None,
        identity_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        if not _STEAMIO_AVAILABLE:
            raise RuntimeError("steamio is not installed")
        self._login = login
        self._password = password
        self._shared_secret = shared_secret or None
        self._identity_secret = identity_secret or None
        self._refresh_token = refresh_token or None

        self._client: SteamClient | None = None  # type: ignore[assignment]
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._presence: dict[int, PresenceSnapshot] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def _build_client(self) -> SteamClient:
        client = SteamClient()  # type: ignore[call-arg]

        @client.event  # type: ignore[attr-defined]
        async def on_ready() -> None:
            self._loop = asyncio.get_running_loop()
            self._ready.set()
            logger.info("Steam presence bot ready.")

        @client.event  # type: ignore[attr-defined]
        async def on_user_update(before: SteamUser, after: SteamUser) -> None:  # type: ignore[name-defined]
            steamid64 = _get_steamid64(after)
            if steamid64 is None:
                return
            rp = getattr(after, "rich_presence", None) or {}
            snapshot = PresenceSnapshot(in_match=is_in_dota_match(after), ts=time.time(), rich_presence=dict(rp))
            with self._lock:
                self._presence[steamid64] = snapshot

        return client

    def _run(self) -> None:
        """
        Keep the steam client running; if it crashes, recreate client/loop and retry with backoff.
        """
        backoff = 5
        while True:
            try:
                self._client = self._build_client()
                login_params = {"username": self._login, "password": self._password}
                try:
                    sig = inspect.signature(self._client.login)  # type: ignore[attr-defined]
                    if "shared_secret" in sig.parameters and self._shared_secret:
                        login_params["shared_secret"] = self._shared_secret
                    if "identity_secret" in sig.parameters and self._identity_secret:
                        login_params["identity_secret"] = self._identity_secret
                    if "refresh_token" in sig.parameters and self._refresh_token:
                        login_params["refresh_token"] = self._refresh_token
                except Exception:
                    if self._shared_secret:
                        login_params["shared_secret"] = self._shared_secret

                self._client.run(**login_params)  # type: ignore[arg-type]
                backoff = 5
            except Exception as exc:
                def _is_gateway_close(e: BaseException, depth: int = 0) -> bool:
                    if depth > 5:  # safety against deep recursion
                        return False
                    if ConnectionClosed and isinstance(e, ConnectionClosed):
                        return True
                    if WebSocketClosure and isinstance(e, WebSocketClosure):
                        return True
                    if ExceptionGroup and isinstance(e, ExceptionGroup):
                        return any(_is_gateway_close(inner, depth + 1) for inner in e.exceptions)
                    if hasattr(e, "exceptions"):  # duck-type fallback for TaskGroup errors
                        try:
                            return any(_is_gateway_close(inner, depth + 1) for inner in e.exceptions)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    cause = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
                    if cause and _is_gateway_close(cause, depth + 1):
                        return True
                    msg = str(e).lower()
                    return "connection closed" in msg or "websocketclosure" in msg

                if _is_gateway_close(exc):
                    logger.warning(f"Steam presence gateway closed. Will retry in {backoff}s.")
                else:
                    logger.error(f"Steam presence bot crashed: {exc}\n{traceback.format_exc()}")
                self._ready.clear()
                # ensure loop reset
                self._loop = None
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def get_cached(self, steamid64: int) -> PresenceSnapshot | None:
        with self._lock:
            return self._presence.get(int(steamid64))

    async def fetch_presence(self, steamid64: int, timeout: float = 8.0) -> PresenceSnapshot | None:
        """
        Force-refresh a user's data via steamio and cache it.
        """
        if self._loop is None:
            return None

        async def runner() -> PresenceSnapshot | None:
            try:
                user = await self._client.fetch_user(int(steamid64))  # type: ignore[attr-defined]
            except Exception:
                return None
            rp = getattr(user, "rich_presence", None) or {}
            snapshot = PresenceSnapshot(in_match=is_in_dota_match(user), ts=time.time(), rich_presence=dict(rp))
            with self._lock:
                self._presence[int(steamid64)] = snapshot
            return snapshot

        fut = asyncio.run_coroutine_threadsafe(runner(), self._loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=timeout)
        except Exception:
            return None


_bot_singleton: SteamPresenceBot | None = None


def get_presence_bot() -> SteamPresenceBot | None:
    return _bot_singleton


def init_presence_bot(
    *,
    enabled: bool,
    login: str,
    password: str,
    shared_secret: str | None,
    identity_secret: str | None,
    refresh_token: str | None,
) -> SteamPresenceBot | None:
    global _bot_singleton
    if not enabled:
        _bot_singleton = None
        return None
    if not login or not password:
        logger.warning("Steam presence is enabled but STEAM_PRESENCE_LOGIN/PASSWORD are missing.")
        _bot_singleton = None
        return None
    bot = SteamPresenceBot(
        login=login,
        password=password,
        shared_secret=shared_secret,
        identity_secret=identity_secret,
        refresh_token=refresh_token,
    )
    bot.start()
    _bot_singleton = bot
    return bot
