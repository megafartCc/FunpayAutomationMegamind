from __future__ import annotations

from typing import Any

import aiohttp

from logger import logger


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
    Best-effort "player is connected to a Dota 2 match server" check.

    Steam's GetPlayerSummaries usually sets `gameserverip` / `gameserversteamid`
    when the user is connected to a game server (i.e. in a match). When Dota is
    only open in menu/lobby, these fields are typically absent.
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
    if gameid != "570":
        return False

    gameserverip = str(player.get("gameserverip") or "").strip()
    gameserversteamid = str(player.get("gameserversteamid") or "").strip()
    return bool(gameserverip or gameserversteamid)


# Backwards-compatible alias (older name used by the bot previously).
async def is_dota2_in_game(*, steamid: int, api_key: str) -> bool:
    return await is_dota2_running(steamid=steamid, api_key=api_key)
