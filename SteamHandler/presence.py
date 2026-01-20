from __future__ import annotations

import json
from typing import Any

import aiohttp

from logger import logger


_STEAMID64_BASE = 76561197960265728

_MATCH_KEYWORDS = (
    "in match",
    "in a match",
    "in-game: match",
    "в матче",
    "идет матч",
    "идёт матч",
)

_NOT_MATCH_KEYWORDS = (
    "in lobby",
    "in menu",
    "main menu",
    "в лобби",
    "в меню",
    "главное меню",
)


def _steamid64_to_accountid(steamid64: int) -> int | None:
    if steamid64 < _STEAMID64_BASE:
        return None
    return steamid64 - _STEAMID64_BASE


async def _fetch_json(url: str) -> dict[str, Any] | None:
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if isinstance(data, dict):
                    return data
                return None
    except Exception as exc:
        logger.warning(f"Steam presence check failed: {exc}")
        return None


def _gather_text(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str).lower()
    except Exception:
        return str(obj).lower()


async def is_dota2_running(*, steamid: int, api_key: str) -> bool:
    """
    Best-effort "Dota 2 is running" check using Steam Web API.

    Requires a Steam Web API key. Returns False if the status can't be fetched.
    """
    if not api_key:
        return False

    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
        f"?key={api_key}&steamids={steamid}"
    )

    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                data: Any = await resp.json()
    except Exception as exc:
        logger.warning(f"Steam presence check failed: {exc}")
        return False

    players = (data or {}).get("response", {}).get("players", [])
    if not players:
        return False

    player = players[0] or {}
    gameid = str(player.get("gameid") or "")
    game_name = str(player.get("gameextrainfo") or "")

    if gameid == "570":
        return True
    if "dota" in game_name.lower():
        return True
    return False


async def is_dota2_in_match(*, steamid: int, api_key: str) -> bool:
    """
    Best-effort "player is in a Dota 2 match right now" check.

    Uses steamcommunity miniprofile first (rich presence), then optionally falls back
    to GetPlayerSummaries (requires API key).

    Note: Steam presence isn't perfectly consistent across games/modes. This function
    is intentionally conservative: if Dota 2 is detected but match state can't be
    determined, it returns True to avoid deauthorizing mid-match.
    """
    accountid = _steamid64_to_accountid(int(steamid))
    if accountid is not None:
        url = f"https://steamcommunity.com/miniprofile/{accountid}/json"
        data = await _fetch_json(url)
        if data:
            text = _gather_text(data)

            if "570" not in text and "dota" not in text:
                return False

            for kw in _NOT_MATCH_KEYWORDS:
                if kw in text:
                    return False
            for kw in _MATCH_KEYWORDS:
                if kw in text:
                    return True

            gameserverip = str(data.get("gameserverip") or "").strip()
            gameserversteamid = str(data.get("gameserversteamid") or "").strip()
            if gameserverip or gameserversteamid:
                return True

            # Dota detected but no explicit match signal => be conservative.
            return True

    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
        f"?key={api_key}&steamids={steamid}"
    )

    if not api_key:
        return False

    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                data: Any = await resp.json()
    except Exception as exc:
        logger.warning(f"Steam presence check failed: {exc}")
        return False

    players = (data or {}).get("response", {}).get("players", [])
    if not players:
        return False

    player = players[0] or {}
    gameid = str(player.get("gameid") or "")
    if gameid != "570":
        return False

    gameserverip = str(player.get("gameserverip") or "").strip()
    gameserversteamid = str(player.get("gameserversteamid") or "").strip()
    return bool(gameserverip or gameserversteamid)


# Backwards-compatible alias (older name used by the bot previously).
async def is_dota2_in_game(*, steamid: int, api_key: str) -> bool:
    return await is_dota2_running(steamid=steamid, api_key=api_key)
