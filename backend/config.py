import os

from dotenv import load_dotenv


load_dotenv()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)

def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


HOURS_FOR_REVIEW = _get_int("HOURS_FOR_REVIEW", 1)
AUTO_EXTEND_ENABLED = _get_bool("AUTO_EXTEND_ENABLED", True)
MAX_EXTENSION_HOURS = _get_int("MAX_EXTENSION_HOURS", 24)
RENTAL_CHECK_INTERVAL = _get_int("RENTAL_CHECK_INTERVAL", 60)

AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE = _get_bool("AUTO_STEAM_DEAUTHORIZE_ON_EXPIRE", True)

STEAM_PRESENCE_ENABLED = _get_bool("STEAM_PRESENCE_ENABLED", False)
STEAM_PRESENCE_LOGIN = os.getenv("STEAM_PRESENCE_LOGIN", "").strip()
STEAM_PRESENCE_PASSWORD = os.getenv("STEAM_PRESENCE_PASSWORD", "").strip()
STEAM_PRESENCE_SHARED_SECRET = os.getenv("STEAM_PRESENCE_SHARED_SECRET", "").strip()
STEAM_PRESENCE_IDENTITY_SECRET = os.getenv("STEAM_PRESENCE_IDENTITY_SECRET", "").strip()
STEAM_PRESENCE_REFRESH_TOKEN = os.getenv("STEAM_PRESENCE_REFRESH_TOKEN", "").strip()
STEAM_WEB_API_KEY = os.getenv("STEAM_WEB_API_KEY", "").strip()
STEAM_BRIDGE_URL = os.getenv("STEAM_BRIDGE_URL", "").strip()

DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE = _get_bool("DOTA_MATCH_BLOCK_MANUAL_DEAUTHORIZE", True)
DOTA_MATCH_DELAY_EXPIRE = _get_bool("DOTA_MATCH_DELAY_EXPIRE", True)
DOTA_MATCH_GRACE_MINUTES = _get_int("DOTA_MATCH_GRACE_MINUTES", 90)

DATA_ENCRYPTION_KEY = os.getenv("DATA_ENCRYPTION_KEY", "").strip()

MYSQLHOST = os.getenv("MYSQLHOST", "").strip()
MYSQLPORT = _get_int("MYSQLPORT", 3306)
MYSQLUSER = os.getenv("MYSQLUSER", "").strip()
MYSQLPASSWORD = os.getenv("MYSQLPASSWORD", "").strip()
MYSQLDATABASE = os.getenv("MYSQLDATABASE", "").strip()
DATABASE_PATH = None

REQUIRE_PAID_ORDER = _get_bool("REQUIRE_PAID_ORDER", True)
