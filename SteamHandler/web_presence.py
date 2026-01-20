import requests
from typing import Optional


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
        personastate = int(player.get("personastate", 0))
        in_game = bool(gameid)
        if in_game:
            state = "in_game"
        elif personastate != 0:
            state = "not_in_game"
        else:
            state = "offline"
        return {
            "presence_in_match": False,
            "presence_display": display,
            "presence_state": state,
        }
    except Exception:
        return None
