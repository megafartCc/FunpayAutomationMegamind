from __future__ import annotations

import json
import sys
import asyncio
from typing import Any

from lxml.html import document_fromstring
from yarl import URL

from SteamHandler.steampassword.steam import CustomSteam
from backend.logger import logger

try:  # Optional dependency (more reliable than parsing HTML).
    from playwright.async_api import async_playwright

    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover
    async_playwright = None
    _PLAYWRIGHT_AVAILABLE = False


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


async def _deauthorize_via_twofactor_manage_action(steam: CustomSteam) -> bool:
    """
    Server-side deauthorization (no browser required).

    Steam web UI uses:
      POST https://store.steampowered.com/twofactor/manage_action
      form: sessionid=<...>&action=deauthorize

    This is the most reliable approach on Railway since it avoids Playwright/Selenium.
    """
    try:
        sessionid = await steam.sessionid("store.steampowered.com")
    except Exception:
        sessionid = None
    if not sessionid:
        return False

    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://store.steampowered.com",
        "Referer": "https://store.steampowered.com/twofactor/manage",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    try:
        resp = await steam.raw_request(
            "https://store.steampowered.com/twofactor/manage_action",
            method="POST",
            headers=headers,
            data={"sessionid": sessionid, "action": "deauthorize"},
            allow_redirects=True,
        )
    except Exception as exc:
        logger.warning(f"Steam twofactor deauthorize request failed: {exc}")
        return False

    status = int(getattr(resp, "status", 0))
    if status not in {200, 302}:
        logger.warning(f"Steam twofactor deauthorize failed: status={status}")
        return False

    try:
        content_type = (resp.headers.get("content-type") or "").lower()
        body = await resp.text()
        if "application/json" in content_type:
            try:
                data = json.loads(body)
                success = data.get("success")
                return success in {1, True, "1", "true"}
            except Exception:
                pass
        lowered = (body or "").lower()
        if "\"success\":1" in lowered or "\"success\":true" in lowered:
            return True
        # Some responses are empty/HTML but the request still succeeds.
        return True
    except Exception:
        return True


async def _ensure_playwright_chromium_installed() -> bool:
    """
    Installs Playwright's Chromium browser at runtime (needed on Railway/Docker).
    """
    if not _PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            out = (stdout or b"")[-1500:].decode("utf-8", errors="ignore")
            err = (stderr or b"")[-1500:].decode("utf-8", errors="ignore")
            logger.warning(f"playwright install chromium failed (code={proc.returncode}). stdout={out} stderr={err}")
            return False
        return True
    except Exception as exc:
        logger.warning(f"playwright install chromium failed: {exc}")
        return False


async def _logout_all_steam_sessions_playwright(steam: CustomSteam) -> bool:
    """
    Replicates the Playwright click-flow from steamautorentbot, but reuses already
    authenticated cookies from pysteamauth to avoid interactive login in browser.
    """
    if not _PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return False

    store_cookies = await steam.cookies("store.steampowered.com")
    community_cookies = await steam.cookies("steamcommunity.com")
    help_cookies = await steam.cookies("help.steampowered.com")

    def build(url: str, cookies: dict[str, str]) -> list[dict[str, str]]:
        return [{"name": k, "value": v, "url": url} for k, v in cookies.items()]

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception as exc:
            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                if await _ensure_playwright_chromium_installed():
                    browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                else:
                    raise
            else:
                raise
        context = await browser.new_context(user_agent=_BROWSER_UA, locale="ru-RU", timezone_id="Europe/Moscow")
        await context.add_cookies(
            build("https://store.steampowered.com/", dict(store_cookies))
            + build("https://steamcommunity.com/", dict(community_cookies))
            + build("https://help.steampowered.com/", dict(help_cookies))
        )
        page = await context.new_page()
        try:
            await page.goto("https://store.steampowered.com/account/sessions/", wait_until="networkidle", timeout=60000)
            selectors = [
                "#logoutAll",
                "input[value*='logout' i]",
                "input[value*='sign out' i]",
                "button:has-text('Sign out')",
                "button:has-text('Выйти')",
                "a:has-text('Sign out')",
                "a:has-text('Выйти')",
            ]

            clicked = False
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("Playwright: logout element not found on sessions page.")
                return False

            # Some flows show a confirm modal.
            confirm_selectors = [
                "button:has-text('Sign out')",
                "button:has-text('Выйти')",
                "input[value*='logout' i]",
                "input[value*='sign out' i]",
            ]
            for selector in confirm_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        await element.click()
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(1500)
            return True
        finally:
            await context.close()
            await browser.close()


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

    # Prefer server-side deauth endpoint (no browser deps).
    try:
        if await _deauthorize_via_twofactor_manage_action(steam):
            return True
    except Exception as exc:
        logger.warning(f"Steam twofactor deauthorize attempt failed: {exc}")

    # Prefer Playwright flow (closest to steamautorentbot).
    try:
        if await _logout_all_steam_sessions_playwright(steam):
            return True
    except Exception as exc:
        logger.warning(f"Playwright logout attempt failed: {exc}")

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
        candidates = [
            ("GET", f"https://steamcommunity.com/my/logoutall/?sessionid={community_sessionid}", None),
            ("POST", "https://steamcommunity.com/my/logoutall/", {"sessionid": community_sessionid}),
            ("POST", "https://steamcommunity.com/my/ajaxlogoutall/", {"sessionid": community_sessionid}),
            ("POST", "https://steamcommunity.com/my/ajaxlogoutall", {"sessionid": community_sessionid}),
        ]
        for method, url, data in candidates:
            try:
                resp = await steam.raw_request(
                    url,
                    method=method,
                    headers={
                        **headers,
                        "Referer": "https://steamcommunity.com/",
                        "Origin": "https://steamcommunity.com",
                        **({"Content-Type": "application/x-www-form-urlencoded"} if data else {}),
                    },
                    data=data,
                    allow_redirects=True,
                )
                status = int(getattr(resp, "status", 0))
                if status not in {200, 302}:
                    continue
                content_type = (resp.headers.get("content-type") or "").lower()
                body = await resp.text()
                if "application/json" in content_type or "ajaxlogoutall" in url:
                    if "\"success\":1" in body or "\"success\":true" in body:
                        return True
                    continue
                if "login" in str(resp.url) or "signin" in body.lower():
                    continue
                return True
            except Exception:
                continue
        logger.warning("Steam community logoutall candidates all failed.")
        return False
    except Exception as exc:
        logger.warning(f"Steam sessions logout not found and fallback failed: {exc}")
        return False
