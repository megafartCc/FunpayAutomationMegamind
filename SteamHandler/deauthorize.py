from __future__ import annotations

import json
from typing import Any

from lxml.html import document_fromstring
from yarl import URL

from SteamHandler.steampassword.steam import CustomSteam
from logger import logger


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_mafile(mafile_json: str | dict) -> dict[str, Any]:
    if isinstance(mafile_json, dict):
        return mafile_json
    return json.loads(mafile_json)


async def logout_all_steam_sessions(
    *,
    steam_login: str,
    steam_password: str,
    mafile_json: str | dict,
) -> bool:
    """
    Best-effort: logs into Steam with 2FA (shared_secret) and clicks the equivalent of
    "sign out of all other devices" from the sessions page.
    """
    data = _parse_mafile(mafile_json)
    steamid = None
    try:
        steamid = int(data.get("Session", {}).get("SteamID"))
    except Exception:
        steamid = None

    steam = CustomSteam(
        login=steam_login,
        password=steam_password,
        steamid=steamid,
        shared_secret=data.get("shared_secret"),
        identity_secret=data.get("identity_secret"),
        device_id=data.get("device_id"),
    )

    await steam.login_to_steam()

    headers = {"User-Agent": _BROWSER_UA, "Accept": "text/html,*/*"}

    account_resp = await steam.raw_request(
        "https://store.steampowered.com/account/",
        method="GET",
        headers=headers,
        allow_redirects=True,
    )
    account_html = await account_resp.text()
    account_page = document_fromstring(account_html)

    sessions_href = None
    for a in account_page.cssselect("a[href*='sessions']"):
        href = a.get("href")
        if href:
            sessions_href = href
            break
    if not sessions_href:
        sessions_href = "https://store.steampowered.com/account/sessions/"

    sessions_url = str(URL(str(account_resp.url)).join(URL(sessions_href)))
    sessions_resp = await steam.raw_request(
        sessions_url,
        method="GET",
        headers=headers,
        allow_redirects=True,
    )
    sessions_html = await sessions_resp.text()
    sessions_page = document_fromstring(sessions_html)

    target_form = None
    for form in sessions_page.cssselect("form"):
        inputs = form.cssselect("input")
        for inp in inputs:
            value = (inp.get("value") or "").lower()
            name = (inp.get("name") or "").lower()
            if "logout" in value or "logout" in name:
                target_form = form
                break
        if target_form is not None:
            break

    if target_form is None:
        logger.warning("Steam sessions logout form not found.")
        return False

    action = target_form.get("action") or sessions_url
    action_url = str(URL(str(sessions_resp.url)).join(URL(action)))
    method = (target_form.get("method") or "post").upper()

    payload: dict[str, str] = {}
    for inp in target_form.cssselect("input"):
        name = inp.get("name")
        if not name:
            continue
        payload[name] = inp.get("value") or ""

    if "sessionid" not in payload:
        try:
            payload["sessionid"] = await steam.sessionid("store.steampowered.com")
        except Exception:
            pass

    final_resp = await steam.raw_request(
        action_url,
        method=method,
        headers={
            **headers,
            "Origin": "https://store.steampowered.com",
            "Referer": sessions_url,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
        allow_redirects=True,
    )

    ok = int(getattr(final_resp, "status", 0)) in {200, 302}
    if not ok:
        logger.warning(f"Steam sessions logout failed: status={getattr(final_resp, 'status', None)}")
    return ok

