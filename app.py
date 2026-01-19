from pathlib import Path
from threading import Thread

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import FUNPAY_GOLDEN_KEY
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


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict:
    return db.get_rental_statistics()


@app.get("/api/notifications")
def notifications(limit: int = 50) -> dict:
    return {"items": list_notifications(limit=limit)}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> FileResponse:
    if path.startswith(("api", "static")):
        raise HTTPException(status_code=404)
    return FileResponse(PUBLIC_DIR / "index.html")
