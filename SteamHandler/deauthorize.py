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


def _find_logout_form(page) -> Any | None:
    for form in page.cssselect("form"):
        action = (form.get("action") or "").lower()
        if "logout" in action:
            return form

        for el in form.cssselect("input,button"):
            name = (el.get("name") or "").lower()
            value = (el.get("value") or "").lower()
            text = (el.text_content() or "").strip().lower()
            if "logout" in name or "logout" in value or "logout" in text:
                return form
            if "выйти" in text or "разлогин" in text:
                return form
    return None


def _build_form_payload(form, sessionid: str | None) -> dict[str, str]:
    payload: dict[str, str] = {}
    for inp in form.cssselect("input"):
        name = inp.get("name")
        if not name:
            continue
        payload[name] = inp.get("value") or ""
    if sessionid and "sessionid" not in payload:
        payload["sessionid"] = sessionid
    return payload


def _find_logout_action_url(current_url: str, page) -> str | None:
    for a in page.cssselect("a[href]"):
        href = a.get("href") or ""
        if "logout" in href.lower():
            return str(URL(current_url).join(URL(href)))
    return None


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

    store_sessionid = None
    try:
        store_sessionid = await steam.sessionid("store.steampowered.com")
    except Exception:
        store_sessionid = None

    target_form = _find_logout_form(sessions_page)
    if target_form is not None:
        action = target_form.get("action") or sessions_url
        action_url = str(URL(str(sessions_resp.url)).join(URL(action)))
        method = (target_form.get("method") or "post").upper()
        payload = _build_form_payload(target_form, store_sessionid)

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

    action_url = _find_logout_action_url(str(sessions_resp.url), sessions_page)
    if action_url and store_sessionid:
        try:
            final_resp = await steam.raw_request(
                action_url,
                method="POST",
                headers={
                    **headers,
                    "Origin": "https://store.steampowered.com",
                    "Referer": sessions_url,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"sessionid": store_sessionid},
                allow_redirects=True,
            )
            ok = int(getattr(final_resp, "status", 0)) in {200, 302}
            if ok:
                return True
        except Exception:
            pass

    logger.warning("Steam sessions logout form not found. Falling back to steamcommunity logoutall.")
    try:
        community_sessionid = await steam.sessionid("steamcommunity.com")
        community_url = f"https://steamcommunity.com/my/logoutall/?sessionid={community_sessionid}"
        resp = await steam.raw_request(
            community_url,
            method="GET",
            headers={**headers, "Referer": "https://steamcommunity.com/"},
            allow_redirects=True,
        )
        ok = int(getattr(resp, "status", 0)) in {200, 302}
        if not ok:
            logger.warning(f"Steam community logoutall failed: status={getattr(resp, 'status', None)}")
        return ok
    except Exception as exc:
        logger.warning(f"Steam sessions logout not found and fallback failed: {exc}")
        return False
