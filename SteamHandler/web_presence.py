import requests
from typing import Optional


_DOTA2_APP_ID = "570"


def fetch_web_presence(steamid64: int, api_key: str, timeout: float = 6.0) -> Optional[dict]:
    """
    Fetch basic presence info via Steam Web API (GetPlayerSummaries).

    Returns dict with presence_in_match/presence_display or None on failure.
    """
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/",
            params={"key": api_key, "steamids": str(int(steamid64))},
            timeout=timeout,
        )
        resp.raise_for_status()
        players = resp.json().get("response", {}).get("players", [])
        if not players:
            return None
        player = players[0]
        gameid = str(player.get("gameid") or "")
        display = player.get("gameextrainfo") or ""
        in_match = gameid == _DOTA2_APP_ID
        return {
            "presence_in_match": in_match,
            "presence_display": display,
        }
    except Exception:
        return None
