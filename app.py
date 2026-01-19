from pathlib import Path
from threading import Thread
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import ADMIN_API_KEY, FUNPAY_GOLDEN_KEY
from databaseHandler.databaseSetup import SQLiteDB
from funpayHandler.funpay import startFunpay
from logger import logger
from notifications import list_notifications


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"

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


class AccountCreate(BaseModel):
    account_name: str
    path_to_maFile: str
    login: str
    password: str
    rental_duration: int = Field(ge=1)
    owner: Optional[str] = None


class AccountUpdate(BaseModel):
    account_name: Optional[str] = None
    path_to_maFile: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    rental_duration: Optional[int] = Field(default=None, ge=1)


class AssignRequest(BaseModel):
    owner: str


class ExtendRequest(BaseModel):
    hours: int = Field(ge=1)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "funpay_enabled": bool(FUNPAY_GOLDEN_KEY)}


@app.get("/api/stats")
def stats() -> dict:
    return db.get_rental_statistics()


@app.get("/api/notifications")
def notifications(limit: int = 50) -> dict:
    return {"items": list_notifications(limit=limit)}


@app.get("/api/accounts")
def accounts() -> dict:
    return {"items": db.get_all_accounts()}


@app.get("/api/accounts/{account_id}")
def account_detail(account_id: int) -> dict:
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@app.post("/api/accounts", dependencies=[Depends(require_admin)])
def create_account(payload: AccountCreate) -> dict:
    success = db.add_account(
        payload.account_name,
        payload.path_to_maFile,
        payload.login,
        payload.password,
        payload.rental_duration,
        payload.owner,
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


@app.get("/api/rentals/active")
def active_rentals() -> dict:
    return {"items": db.get_active_users()}


@app.get("/api/rentals/user/{owner}")
def user_rentals(owner: str) -> dict:
    return {"items": db.get_user_active_accounts(owner)}


@app.post("/api/rentals/user/{owner}/extend", dependencies=[Depends(require_admin)])
def extend_owner(owner: str, payload: ExtendRequest) -> dict:
    success = db.add_time_to_owner_accounts(owner, payload.hours)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to extend rentals")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> FileResponse:
    if path.startswith(("api", "static")):
        raise HTTPException(status_code=404)
    return FileResponse(PUBLIC_DIR / "index.html")
