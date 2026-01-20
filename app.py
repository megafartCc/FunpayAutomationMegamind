import json
from pathlib import Path
from threading import Thread
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    ADMIN_API_KEY,
    BLOCK_MANUAL_DEAUTHORIZE_WHILE_IN_MATCH,
    FUNPAY_GOLDEN_KEY,
    STEAM_WEB_API_KEY,
)
from DatabaseHandler.databaseSetup import SQLiteDB
from FunpayHandler.funpay import get_account, startFunpay
from logger import logger
from notifications import list_notifications
from SteamHandler.changePassword import changeSteamPassword
from SteamHandler.deauthorize import logout_all_steam_sessions
from SteamHandler.presence import is_dota2_in_match
from SteamHandler.steampassword.exceptions import ErrorSteamPasswordChange


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "Public"

app = FastAPI(title="FunpaySeller")
db = SQLiteDB()

app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")


@app.on_event("startup")
def start_background_services() -> None:
    if not FUNPAY_GOLDEN_KEY:
        logger.warning("FUNPAY_GOLDEN_KEY is empty. FunPay automation not started.")
        return
    thread = Thread(target=startFunpay, daemon=True)
    thread.start()
    logger.info("FunPay automation started in background thread.")


def require_admin(request: Request) -> None:
    if not ADMIN_API_KEY:
        return
    key = request.headers.get("x-admin-key")
    if key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


def require_funpay_account():
    account = get_account()
    if account is None:
        raise HTTPException(status_code=503, detail="FunPay session not initialized")
    return account


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


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "funpay_enabled": bool(FUNPAY_GOLDEN_KEY),
        "funpay_ready": get_account() is not None,
    }


@app.get("/api/admin-key")
def admin_key() -> dict:
    return {"key": ADMIN_API_KEY}


@app.get("/api/stats")
def stats() -> dict:
    return db.get_rental_statistics()


@app.get("/api/notifications")
def notifications(limit: int = 50) -> dict:
    return {"items": list_notifications(limit=limit)}


@app.get("/api/accounts")
def accounts() -> dict:
    return {"items": db.get_all_accounts()}


@app.get("/api/lots")
def lots() -> dict:
    return {"items": db.list_lot_mappings()}


@app.post("/api/lots", dependencies=[Depends(require_admin)])
def create_lot_mapping(payload: LotMapping) -> dict:
    success = db.set_lot_mapping(payload.lot_number, payload.account_id, payload.lot_url)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"success": True}


@app.delete("/api/lots/{lot_number}", dependencies=[Depends(require_admin)])
def delete_lot_mapping(lot_number: int) -> dict:
    db.delete_lot_mapping(lot_number)
    return {"success": True}


@app.get("/api/accounts/{account_id}")
def account_detail(account_id: int) -> dict:
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/accounts", dependencies=[Depends(require_admin)])
def create_account(payload: AccountCreate) -> dict:
    if not payload.mafile_json.strip():
        raise HTTPException(status_code=400, detail="mafile_json is required")
    success = db.add_account(
        payload.account_name,
        "",
        payload.login,
        payload.password,
        payload.rental_duration,
        payload.owner,
        mafile_json=payload.mafile_json,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to create account")
    return {"status": "ok"}


@app.patch("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def update_account(account_id: int, payload: AccountUpdate) -> dict:
    success = db.update_account(account_id, payload.dict(exclude_none=True))
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update account")
    return {"status": "ok"}


@app.delete("/api/accounts/{account_id}", dependencies=[Depends(require_admin)])
def delete_account(account_id: int) -> dict:
    success = db.delete_account_by_id(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/assign", dependencies=[Depends(require_admin)])
def assign_account(account_id: int, payload: AssignRequest) -> dict:
    success = db.set_account_owner(account_id, payload.owner)
    if not success:
        raise HTTPException(status_code=400, detail="Account already assigned")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/release", dependencies=[Depends(require_admin)])
def release_account(account_id: int) -> dict:
    success = db.release_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/extend", dependencies=[Depends(require_admin)])
def extend_account(account_id: int, payload: ExtendRequest) -> dict:
    success = db.extend_rental_duration(account_id, payload.hours)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rental")
    return {"status": "ok"}


@app.post("/api/accounts/{account_id}/steam/deauthorize", dependencies=[Depends(require_admin)])
async def steam_deauthorize(account_id: int) -> dict:
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    mafile_json = account.get("mafile_json")
    if not mafile_json:
        raise HTTPException(status_code=400, detail="mafile_json is required for Steam actions")

    if BLOCK_MANUAL_DEAUTHORIZE_WHILE_IN_MATCH and STEAM_WEB_API_KEY:
        try:
            data = json.loads(mafile_json) if isinstance(mafile_json, str) else mafile_json
            steamid_value = (data or {}).get("Session", {}).get("SteamID")
            steamid = int(steamid_value) if steamid_value is not None else None
        except Exception:
            steamid = None

        if steamid is not None:
            try:
                in_match = await is_dota2_in_match(steamid=steamid, api_key=STEAM_WEB_API_KEY)
            except Exception:
                in_match = False

            if in_match:
                raise HTTPException(
                    status_code=409,
                    detail="Steam account is currently in a Dota 2 match. Try again after the match ends.",
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
async def steam_change_password(account_id: int, payload: SteamPasswordRequest) -> dict:
    account = db.get_account_by_id(account_id)
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


@app.get("/api/rentals/active")
def active_rentals() -> dict:
    items = db.get_active_users()
    account = get_account()
    if account is None:
        return {"items": items}

    for item in items:
        owner = item.get("owner")
        if not owner:
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


@app.get("/api/rentals/user/{owner}")
def user_rentals(owner: str) -> dict:
    return {"items": db.get_user_active_accounts(owner)}


@app.post("/api/rentals/user/{owner}/extend", dependencies=[Depends(require_admin)])
def extend_owner(owner: str, payload: ExtendRequest) -> dict:
    success = db.add_time_to_owner_accounts(owner, payload.hours)
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
