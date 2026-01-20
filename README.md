# FunpaySeller

FunpaySeller is a web-first rental service for Steam accounts with FunPay automation. It runs the original AutoRentSteam backend in the background and exposes a frontend dashboard plus JSON APIs.

## What is included

- FunPay automation for order fulfillment and rental lifecycle.
- Steam password rotation for expired rentals.
- Web frontend served from `/Public`.
- JSON APIs for stats and notifications.

## Code structure (backend) 

- `app.py` — FastAPI app (REST + static UI).
- `main.py` — local runner (`uvicorn app:app`).
- `FunpayHandler/` — FunPay automation.
  - `FunpayHandler/funpay.py` — compatibility wrapper (keeps old imports stable).
  - `FunpayHandler/bot.py` — main bot implementation (events, commands, background jobs).
  - `FunpayHandler/utils.py` — parsing + time formatting helpers.
  - `FunpayHandler/messages.py` — user-facing message templates.
- `DatabaseHandler/` — SQLite/MySQL access layer.
- `SteamHandler/` — Steam Guard + password rotation helpers.

## Quick start (local)

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Open http://localhost:8000

## Environment variables

Create a `.env` file (see `.env.example`):

- `FUNPAY_GOLDEN_KEY` (required)
- `ADMIN_API_KEY` (optional, protects write endpoints)
- `HOURS_FOR_REVIEW` (default: 1)
- `AUTO_EXTEND_ENABLED` (default: true)
- `MAX_EXTENSION_HOURS` (default: 24)
- `RENTAL_CHECK_INTERVAL` (default: 60)
- `DATABASE_PATH` (default: database.db)
- `DATABASE_ENGINE` (set to `mysql` to enable MySQL)
- `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE` (MySQL connection)

## APIs

- `GET /api/health`
- `GET /api/stats`
- `GET /api/notifications`

## Railway

1. Push this repo to GitHub.
2. Create a Railway project from the repo.
3. Add the environment variables from `.env.example`.
4. Ensure Python 3.11 is used (via `runtime.txt` or set `NIXPACKS_PYTHON_VERSION=3.11` in Railway).

Railway runs `uvicorn app:app` via `railway.json`.
