import json
from pathlib import Path
from threading import Thread
from threading import Lock
from typing import Optional
from urllib.parse import quote
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    ADMIN_API_KEY,
    DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE,
    STEAM_BRIDGE_URL,
)
from DatabaseHandler.databaseSetup import SQLiteDB
from FunPayAPI import Account as FPAccount
from logger import logger
from notifications import list_notifications
from SteamHandler.changePassword import changeSteamPassword
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence_bot import get_presence_bot
from SteamHandler.steampassword.exceptions import ErrorSteamPasswordChange
import requests
from FunpayHandler.bot import FunpayBot


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "Public"

app = FastAPI(title="FunpaySeller")
db = SQLiteDB()


class BotManager:
    def __init__(self):
        self._bots: dict[int, dict] = {}
        self._lock = Lock()

    def start_for_user(self, user_id: int, golden_key: str) -> None:
        if not golden_key:
            return
        with self._lock:
            existing = self._bots.get(user_id)
            if existing and existing.get("key") == golden_key and existing.get("thread") and existing["thread"].is_alive():
                return
            try:
                bot = FunpayBot(token=golden_key, db=db)
                thread = Thread(target=bot.start, daemon=True)
                thread.start()
                self._bots[user_id] = {"bot": bot, "key": golden_key, "thread": thread}
                logger.info(f"FunPay bot started for user {user_id}")
            except Exception as exc:
                logger.error(f"Failed to start FunPay bot for user {user_id}: {exc}")

    def start_all(self) -> None:
        for user in db.list_users_with_keys():
            try:
                self.start_for_user(user["id"], user["golden_key"])
            except Exception as exc:
                logger.error(f"Failed to start bot for user {user.get('id')}: {exc}")


bot_manager = BotManager()

app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")


@app.on_event("startup")
def start_background_services() -> None:
    bot_manager.start_all()
    # One-shot presence check for debugging a specific SteamID
    try:
        test_sid = 76561198749779076
        presence = _fetch_bridge_presence(test_sid)
        logger.info(f"Test bridge presence for {test_sid}: {presence or 'no data'}")
    except Exception as exc:
        logger.warning(f"Test bridge presence check failed: {exc}")
    logger.info("Startup complete (per-user FunPay bots initialized if keys are present).")


def _steamid64_from_mafile(mafile_json: str | dict) -> int | None:
    try:
        data = json.loads(mafile_json) if isinstance(mafile_json, str) else mafile_json
        value = (data or {}).get("Session", {}).get("SteamID")
        if value is None:
            value = (data or {}).get("steamid") or (data or {}).get("SteamID")
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _fetch_bridge_presence(steamid64: int) -> dict:
    if not STEAM_BRIDGE_URL:
        return {}
    base = STEAM_BRIDGE_URL.rstrip("/")
    if base.endswith("/presence"):
        url = f"{base}/{steamid64}"
    else:
        url = f"{base}/presence/{steamid64}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json() or {}
    except Exception:
        return {}


def require_admin(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        if token:
            user = db.get_user_by_token(token)
            if user:
                request.state.user = user
                return
    # fallback to legacy admin key
    if ADMIN_API_KEY:
        key = request.headers.get("x-admin-key")
        if key == ADMIN_API_KEY:
            request.state.user = {"id": 0, "username": "admin"}
            return
    raise HTTPException(status_code=401, detail="Unauthorized")


def current_user_id(request: Request) -> int | None:
    user = getattr(request.state, "user", None)
    return user.get("id") if user else None


def require_funpay_account(request: Request):
    user = getattr(request.state, "user", None)
    token = (user or {}).get("golden_key") or FUNPAY_GOLDEN_KEY
    if not token:
        raise HTTPException(status_code=503, detail="FunPay golden key not configured")
    try:
        acc = FPAccount(token).get()
    except Exception:
        raise HTTPException(status_code=503, detail="FunPay session not initialized")
    return acc


class AccountCreate(BaseModel):
    account_name: str
    mafile_json: str
    login: str
    password: str
    rental_duration: int = Field(default=1, ge=1)
    owner: Optional[str] = None


class AccountUpdate(BaseModel):
    account_name: Optional[str] = None
    mafile_json: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    rental_duration: Optional[int] = Field(default=None, ge=1)


class AssignRequest(BaseModel):
    owner: str


class ExtendRequest(BaseModel):
    hours: int = Field(ge=1)


class ChatMessage(BaseModel):
    text: str


class LotMapping(BaseModel):
    lot_number: int = Field(ge=1)
    account_id: int = Field(ge=1)
    lot_url: Optional[str] = None


class SteamPasswordRequest(BaseModel):
    new_password: Optional[str] = None


class AuthRegister(BaseModel):
    username: str
    password: str
    golden_key: str


class AuthLogin(BaseModel):
    username: str
    password: str


class GoldenKeyUpdate(BaseModel):
    golden_key: str


@app.get("/api/health")
def health() -> dict:
    funpay_available = db.has_any_golden_key()
    return {
        "status": "ok",
        "funpay_enabled": funpay_available,
        "funpay_ready": funpay_available,
    }


@app.post("/api/auth/register")
def auth_register(payload: AuthRegister) -> dict:
    token = db.create_user(payload.username, payload.password, payload.golden_key)
    if not token:
        raise HTTPException(status_code=400, detail="User already exists or invalid data")
    user = db.get_user_by_username(payload.username)
    if user:
        bot_manager.start_for_user(user["id"], user["golden_key"])
    return {"token": token, "username": payload.username}


@app.post("/api/auth/login")
def auth_login(payload: AuthLogin) -> dict:
    user = db.verify_user_credentials(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(32)
    db.update_session_token(user["id"], token)
    bot_manager.start_for_user(user["id"], user["golden_key"])
    return {"token": token, "username": user["username"]}


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
        db.logout_token(token)
    return {"success": True}


@app.get("/api/auth/me", dependencies=[Depends(require_admin)])
def auth_me(request: Request) -> dict:
    user = getattr(request.state, "user", None) or {}
    return {"username": user.get("username"), "id": user.get("id")}


@app.put("/api/auth/golden-key", dependencies=[Depends(require_admin)])
def auth_update_golden(payload: GoldenKeyUpdate, request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    ok = db.update_golden_key(user["id"], payload.golden_key)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update golden key")
    bot_manager.start_for_user(user["id"], payload.golden_key)
    return {"success": True}


@app.get("/api/stats", dependencies=[Depends(require_admin)])
def stats(request: Request) -> dict:
    uid = current_user_id(request)
    return db.get_rental_statistics(uid)


@app.get("/api/notifications", dependencies=[Depends(require_admin)])
def notifications(limit: int = 50) -> dict:
    return {"items": list_notifications(limit=limit)}


def _presence_for_steamid(steamid64: int | None) -> dict:
    if not steamid64 or not STEAM_BRIDGE_URL:
        return {"in_game": False, "in_match": False, "lobby_info": ""}
    bridge_presence = _fetch_bridge_presence(steamid64)
    if not bridge_presence:
        return {"in_game": False, "in_match": False, "lobby_info": ""}
    return {
        "in_game": bool(bridge_presence.get("in_game")),
        "in_match": bool(bridge_presence.get("in_match")),
        "lobby_info": bridge_presence.get("lobby_info") or "",
    }


@app.get("/api/accounts", dependencies=[Depends(require_admin)])
async def accounts(request: Request) -> dict:
    uid = current_user_id(request)
    items = db.get_all_accounts(uid)
    if not items:
        return {"items": items}

    for acc in items:
        steamid64 = _steamid64_from_mafile(acc.get("mafile_json"))
        acc["steamid"] = str(steamid64) if steamid64 is not None else None
        acc.pop("mafile_json", None)
    return {"items": items}


@app.get("/api/lots", dependencies=[Depends(require_admin)])
def lots(request: Request) -> dict:
    uid = current_user_id(request)
    return {"items": db.list_lot_mappings(uid)}


@app.post("/api/lots", dependencies=[Depends(require_admin)])
def create_lot_mapping(payload: LotMapping, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.set_lot_mapping(payload.lot_number, payload.account_id, payload.lot_url, uid)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True}


@app.delete("/api/lots/{lot_number}", dependencies=[Depends(require_admin)])
def delete_lot_mapping(lot_number: int, request: Request) -> dict:
    uid = current_user_id(request)
    db.delete_lot_mapping(lot_number, uid)
    return {"success": True}


@app.get("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def account_detail(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    account = db.get_account_by_id(account_id, uid)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/accounts", dependencies=[Depends(require_admin)])
def create_account(payload: AccountCreate, request: Request) -> dict:
    if not payload.mafile_json.strip():
        raise HTTPException(status_code=400, detail="mafile_json is required")
    uid = current_user_id(request)
    success = db.add_account(
        payload.account_name,
        "",
        payload.login,
        payload.password,
        payload.rental_duration,
        payload.owner,
        mafile_json=payload.mafile_json,
        user_id=uid,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to create account")
    return {"status": "ok"}


@app.patch("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def update_account(account_id: int, payload: AccountUpdate, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.update_account(account_id, payload.dict(exclude_none=True), uid)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update account")
    return {"status": "ok"}


@app.delete("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def delete_account(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.delete_account_by_id(account_id, uid)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/assign", dependencies=[Depends(require_admin)])
def assign_account(account_id: int, payload: AssignRequest, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.set_account_owner(account_id, payload.owner, uid)
    if not success:
        raise HTTPException(status_code=400, detail="Account already assigned")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/release", dependencies=[Depends(require_admin)])
def release_account(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.release_account(account_id, uid)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/extend", dependencies=[Depends(require_admin)])
def extend_account(account_id: int, payload: ExtendRequest, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.extend_rental_duration(account_id, payload.hours, uid)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rental")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/steam/deauthorize", dependencies=[Depends(require_admin)])
async def steam_deauthorize(account_id: int, request: Request) -> dict:
    uid = current_user_id(request)
    account = db.get_account_by_id(account_id, uid)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    mafile_json = account.get("mafile_json")
    if not mafile_json:
        raise HTTPException(status_code=400, detail="mafile_json is required for Steam actions")

    if DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE:
        bot = get_presence_bot()
        if bot is not None:
            steamid64 = _steamid64_from_mafile(mafile_json)
            if steamid64 is not None:
                if not bot.wait_ready(timeout=0.5):
                    raise HTTPException(status_code=503, detail="Steam presence bot is not ready yet. Try again.")
                snapshot = bot.get_cached(steamid64)
                if snapshot is None:
                    snapshot = await bot.fetch_presence(steamid64)
                if snapshot and snapshot.in_match:
                    steam_display = snapshot.rich_presence.get("steam_display") if snapshot.rich_presence else None
                    extra = f" ({steam_display})" if steam_display else ""
                    raise HTTPException(
                        status_code=409,
                        detail=f"Аккаунт сейчас в матче Dota 2{extra}. Попробуйте снова после окончания матча.",
                    )

    ok = await logout_all_steam_sessions(
        steam_login=account.get("login") or account.get("account_name"),
        steam_password=account.get("password"),
        mafile_json=mafile_json,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to deauthorize Steam sessions")
    return {"success": True}


@app.post("/api/accounts/{account_id}/steam/password", dependencies=[Depends(require_admin)])
async def steam_change_password(account_id: int, payload: SteamPasswordRequest, request: Request) -> dict:
    uid = current_user_id(request)
    account = db.get_account_by_id(account_id, uid)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    mafile_json = account.get("mafile_json")
    if not mafile_json:
        raise HTTPException(status_code=400, detail="mafile_json is required for Steam actions")

    new_password = payload.new_password.strip() if payload.new_password else None
    if new_password == "":
        new_password = None

    try:
        updated_password = await changeSteamPassword(
            path_to_maFile=None,
            password=account.get("password"),
            mafile_json=mafile_json,
            new_password=new_password,
            steam_login=account.get("login") or account.get("account_name"),
        )
    except ErrorSteamPasswordChange as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Steam password change failed: {exc}") from exc

    login = account.get("login")
    if login:
        db.update_password_by_login(login, updated_password)
    else:
        db.update_account(account_id, {"password": updated_password})

    return {"success": True, "new_password": updated_password}


@app.get("/api/rentals/active", dependencies=[Depends(require_admin)])
def active_rentals(request: Request) -> dict:
    uid = current_user_id(request)
    items = db.get_active_users(uid)
    try:
        account = require_funpay_account(request)
    except HTTPException:
        account = None

    for item in items:
        mafile_json = item.get("mafile_json")
        steamid64 = _steamid64_from_mafile(mafile_json)
        item["steamid"] = str(steamid64) if steamid64 is not None else None
        item.update(_presence_for_steamid(steamid64))
        item.pop("mafile_json", None)
        owner = item.get("owner")
        if not owner:
            item["chat_url"] = None
            continue
        if account is None:
            item["chat_url"] = None
            continue
        try:
            chat = account.get_chat_by_name(owner, True)
            if chat:
                item["chat_url"] = f"https://funpay.com/chat/?node={quote(str(chat.id))}"
            else:
                item["chat_url"] = None
        except Exception:
            item["chat_url"] = None

    return {"items": items}


@app.get("/api/rentals/user/{owner}", dependencies=[Depends(require_admin)])
def user_rentals(owner: str, request: Request) -> dict:
    uid = current_user_id(request)
    return {"items": db.get_user_active_accounts(owner, uid)}


@app.post("/api/rentals/user/{owner}/extend", dependencies=[Depends(require_admin)])
def extend_owner(owner: str, payload: ExtendRequest, request: Request) -> dict:
    uid = current_user_id(request)
    success = db.add_time_to_owner_accounts(owner, payload.hours, uid)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rentals")
    return {"status": "ok"}


@app.get("/api/chats", dependencies=[Depends(require_admin)])
def chats(account=Depends(require_funpay_account)) -> dict:
    try:
        chats_map = account.get_chats(update=True)
        items = []
        for chat in chats_map.values():
            items.append(
                {
                    "id": chat.id,
                    "name": chat.name,
                    "last_message_text": chat.last_message_text,
                    "unread": chat.unread,
                    "node_msg_id": chat.node_msg_id,
                    "user_msg_id": chat.user_msg_id,
                }
            )
        return {"items": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/chats/{chat_id}/history", dependencies=[Depends(require_admin)])
def chat_history(chat_id: int, limit: int = 50, account=Depends(require_funpay_account)) -> dict:
    try:
        messages = account.get_chat_history(chat_id) or []
        trimmed = messages[-limit:]
        items = []
        for message in trimmed:
            items.append(
                {
                    "id": message.id,
                    "text": message.text,
                    "author": message.author,
                    "author_id": message.author_id,
                    "chat_id": message.chat_id,
                    "chat_name": message.chat_name,
                    "image_link": message.image_link,
                    "by_bot": message.by_bot,
                    "by_vertex": message.by_vertex,
                    "type": message.type.name if message.type else None,
                }
            )
        return {"items": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chats/{chat_id}/send", dependencies=[Depends(require_admin)])
def chat_send(chat_id: int, payload: ChatMessage, account=Depends(require_funpay_account)) -> dict:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Message text is required")
    try:
        chat = account.get_chat_by_id(chat_id, make_request=True)
        chat_name = chat.name if chat else None
        message = account.send_message(chat_id, payload.text, chat_name)
        return {"status": "ok", "message_id": message.id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> FileResponse:
    if path.startswith(("api", "static")):
        raise HTTPException(status_code=404)
    return FileResponse(PUBLIC_DIR / "index.html")
