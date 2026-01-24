from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from backend.logger import logger


class ConnectionState:
    def __init__(self, websocket: WebSocket, user_id: int, key_id: int | None) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.key_id = key_id
        self.subscriptions: Set[int] = set()


class ConnectionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: Dict[WebSocket, ConnectionState] = {}
        self._user_index: Dict[tuple[int, int | None], Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, key_id: int | None) -> None:
        async with self._lock:
            state = ConnectionState(websocket, user_id, key_id)
            self._connections[websocket] = state
            self._user_index.setdefault((user_id, key_id), set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            state = self._connections.pop(websocket, None)
            if not state:
                return
            user_set = self._user_index.get((state.user_id, state.key_id))
            if user_set:
                user_set.discard(websocket)
                if not user_set:
                    self._user_index.pop((state.user_id, state.key_id), None)

    async def subscribe(self, websocket: WebSocket, chat_id: int) -> None:
        async with self._lock:
            state = self._connections.get(websocket)
            if not state:
                return
            state.subscriptions.add(int(chat_id))

    async def unsubscribe(self, websocket: WebSocket, chat_id: int) -> None:
        async with self._lock:
            state = self._connections.get(websocket)
            if not state:
                return
            state.subscriptions.discard(int(chat_id))

    async def _targets_for_user(self, user_id: int, key_id: int | None) -> list[ConnectionState]:
        async with self._lock:
            sockets: list[WebSocket] = []
            if key_id is None:
                for (uid, _kid), subset in self._user_index.items():
                    if uid == user_id:
                        sockets.extend(subset)
            else:
                sockets = list(self._user_index.get((user_id, key_id), set()))
            return [self._connections[socket] for socket in sockets if socket in self._connections]

    async def _targets_for_chat(self, user_id: int, chat_id: int, key_id: int | None) -> list[ConnectionState]:
        async with self._lock:
            sockets: list[WebSocket] = []
            if key_id is None:
                for (uid, _kid), subset in self._user_index.items():
                    if uid == user_id:
                        sockets.extend(subset)
            else:
                sockets = list(self._user_index.get((user_id, key_id), set()))
            states = []
            for socket in sockets:
                state = self._connections.get(socket)
                if not state:
                    continue
                if int(chat_id) in state.subscriptions:
                    states.append(state)
            return states

    async def broadcast_user(self, user_id: int, event: Dict[str, Any], key_id: int | None = None) -> None:
        targets = await self._targets_for_user(user_id, key_id)
        await self._send_to_targets(targets, event)

    async def broadcast_user_chat(
        self,
        user_id: int,
        chat_id: int,
        event: Dict[str, Any],
        key_id: int | None = None,
    ) -> None:
        targets = await self._targets_for_chat(user_id, chat_id, key_id)
        await self._send_to_targets(targets, event)

    async def _send_to_targets(self, targets: list[ConnectionState], event: Dict[str, Any]) -> None:
        if not targets:
            return
        payload = jsonable_encoder(event)
        dead: list[WebSocket] = []
        for state in targets:
            try:
                await state.websocket.send_json(payload)
            except Exception:
                dead.append(state.websocket)
        for websocket in dead:
            await self.disconnect(websocket)


manager = ConnectionManager()
_event_loop: asyncio.AbstractEventLoop | None = None
_chat_cache: Any | None = None


def set_chat_cache(cache: Any) -> None:
    global _chat_cache
    _chat_cache = cache


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """
    Remember the main FastAPI event loop so background threads
    (Funpay bot) can schedule websocket broadcasts safely.
    """
    global _event_loop
    _event_loop = loop


def _run_async(coro: Any) -> None:
    loop = _event_loop
    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)

        def _log_future_error(fut: asyncio.Future) -> None:
            exc = fut.exception()
            if exc:
                logger.warning(f"Async broadcast failed: {exc}")

        future.add_done_callback(_log_future_error)
        return

    # Fallback for tests or scripts where no loop has been set yet.
    try:
        current = asyncio.get_running_loop()
        if current.is_running():
            current.create_task(coro)
            return
    except RuntimeError:
        pass

    asyncio.run(coro)


def broadcast_to_user(user_id: int, event_dict: Dict[str, Any], key_id: int | None = None) -> None:
    _run_async(manager.broadcast_user(user_id, event_dict, key_id))


def broadcast_to_user_chat(
    user_id: int, chat_id: int, event_dict: Dict[str, Any], key_id: int | None = None
) -> None:
    _run_async(manager.broadcast_user_chat(user_id, chat_id, event_dict, key_id))


def publish_chat_message(user_id: int, key_id: int | None, chat_id: int, item: Dict[str, Any]) -> None:
    if _chat_cache:
        try:
            _chat_cache.append_message(user_id, key_id, chat_id, dict(item))
        except Exception as exc:
            logger.warning(f"Failed to append chat message to cache: {exc}")
    broadcast_to_user_chat(
        user_id,
        chat_id,
        {"type": "chat:message", "chat_id": chat_id, "item": item},
        key_id,
    )
    if _chat_cache:
        try:
            summary = _chat_cache.get_chat_summary(user_id, key_id, chat_id)
        except Exception:
            summary = None
        if summary:
            broadcast_to_user(
                user_id,
                {"type": "chats:update", "chat_id": chat_id, "item": summary},
                key_id,
            )
