from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from logger import logger


_DOTA2_APP_ID = "570"

_MATCH_KEYWORDS = (
    "playing",
    "in match",
    "match",
    "ranked",
    "turbo",
    "captains mode",
    "captain's mode",
    "all pick",
    "ability draft",
    "single draft",
    "random draft",
    "custom game",
    "spectating",
    "watching",
    "играет",
    "в матче",
    "матч",
    "ранг",
    "рейтин",
    "турбо",
    "наблюдает",
    "смотрит",
)

_MENU_KEYWORDS = (
    "in main menu",
    "main menu",
    "menu",
    "in lobby",
    "lobby",
    "в меню",
    "главное меню",
    "в лобби",
)


@dataclass(frozen=True)
class DotaPresence:
    in_dota: bool
    in_match: bool
    rich_presence: str


async def _fetch_player_summary(*, steamid64: int, api_key: str) -> dict[str, Any] | None:
    if not api_key:
        return None
    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        f"?key={api_key}&steamids={steamid64}"
    )
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                payload: Any = await resp.json()
    except Exception as exc:
        logger.warning(f"Steam Web API presence check failed: {exc}")
        return None

    try:
        players = (payload or {}).get("response", {}).get("players", [])
        if not players:
            return None
        player = players[0]
        return player if isinstance(player, dict) else None
    except Exception:
        return None


def _classify_dota_presence(game_info: str) -> bool:
    info = (game_info or "").strip().lower()
    if not info:
        return False

    for kw in _MENU_KEYWORDS:
        if kw in info:
            return False

    for kw in _MATCH_KEYWORDS:
        if kw in info:
            return True

    return False


async def get_dota_presence(*, steamid64: int, api_key: str) -> DotaPresence:
    """
    Method 2 (Steam Web API): GetPlayerSummaries + gameextrainfo keyword match.

    Important: This depends on Steam privacy settings ("Game details"). If those are
    private, Steam may omit `gameid` and `gameextrainfo`, making detection impossible.
    """
    player = await _fetch_player_summary(steamid64=steamid64, api_key=api_key)
    if not player:
        return DotaPresence(in_dota=False, in_match=False, rich_presence="")

    gameid = str(player.get("gameid") or "")
    game_info = str(player.get("gameextrainfo") or "")

    in_dota = gameid == _DOTA2_APP_ID
    if not in_dota:
        return DotaPresence(in_dota=False, in_match=False, rich_presence=game_info)

    # Some accounts expose server fields; treat as match if present.
    gameserverip = str(player.get("gameserverip") or "").strip()
    gameserversteamid = str(player.get("gameserversteamid") or "").strip()
    if gameserverip or gameserversteamid:
        return DotaPresence(in_dota=True, in_match=True, rich_presence=game_info)

    return DotaPresence(in_dota=True, in_match=_classify_dota_presence(game_info), rich_presence=game_info)


async def is_dota2_in_match(*, steamid: int, api_key: str) -> bool:
    presence = await get_dota_presence(steamid64=int(steamid), api_key=api_key)
    return presence.in_match

