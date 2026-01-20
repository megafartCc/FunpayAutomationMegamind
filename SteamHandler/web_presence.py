from __future__ import annotations

from typing import Any

import requests


_PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"


def fetch_player_summaries(steamids: list[int], api_key: str, timeout: float = 6.0) -> dict[str, Any]:
    if not api_key or not steamids:
        return {}
    chunk = ",".join(str(int(sid)) for sid in steamids)
    resp = requests.get(
        _PLAYER_SUMMARIES_URL,
        params={"key": api_key, "steamids": chunk},
        timeout=timeout,
    )
    resp.raise_for_status()
    players = resp.json().get("response", {}).get("players", [])
    return {str(player.get("steamid")): player for player in players}
