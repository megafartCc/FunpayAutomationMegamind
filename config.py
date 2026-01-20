import os

from dotenv import load_dotenv


load_dotenv()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


FUNPAY_GOLDEN_KEY = os.getenv("FUNPAY_GOLDEN_KEY", "").strip()
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip() or FUNPAY_GOLDEN_KEY
HOURS_FOR_REVIEW = _get_int("HOURS_FOR_REVIEW", 1)
AUTO_EXTEND_ENABLED = _get_bool("AUTO_EXTEND_ENABLED", True)
MAX_EXTENSION_HOURS = _get_int("MAX_EXTENSION_HOURS", 24)
RENTAL_CHECK_INTERVAL = _get_int("RENTAL_CHECK_INTERVAL", 60)

AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE = _get_bool("AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE", True)
STEAM_WEB_API_KEY = os.getenv("STEAM_WEB_API_KEY", "").strip()
EXPIRE_WAIT_DOTA_ON_EXPIRE = _get_bool("EXPIRE_WAIT_DOTA_ON_EXPIRE", False)
EXPIRE_INGAME_GRACE_MINUTES = _get_int("EXPIRE_INGAME_GRACE_MINUTES", 90)
BLOCK_MANUAL_DEAUTHORIZE_WHILE_IN_MATCH = _get_bool("BLOCK_MANUAL_DEAUTHORIZE_WHILE_IN_MATCH", True)

DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")

MYSQLHOST = os.getenv("MYSQLHOST", "").strip()
MYSQLPORT = _get_int("MYSQLPORT", 3306)
MYSQLUSER = os.getenv("MYSQLUSER", "").strip()
MYSQLPASSWORD = os.getenv("MYSQLPASSWORD", "").strip()
MYSQLDATABASE = os.getenv("MYSQLDATABASE", "").strip()

DATABASE_ENGINE = os.getenv(
    "DATABASE_ENGINE",
    "mysql" if MYSQLHOST and MYSQLDATABASE else "sqlite",
).strip().lower()
