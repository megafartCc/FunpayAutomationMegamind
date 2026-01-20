from __future__ import annotations

from typing import Any

import aiohttp

from logger import logger


async def is_dota2_in_game(*, steamid: int, api_key: str) -> bool:
    """
    Best-effort "is in Dota 2 match right now" check using Steam Web API.

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

