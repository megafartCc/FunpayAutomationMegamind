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
HOURS_FOR_REVIEW = _get_int("HOURS_FOR_REVIEW", 1)
AUTO_EXTEND_ENABLED = _get_bool("AUTO_EXTEND_ENABLED", True)
MAX_EXTENSION_HOURS = _get_int("MAX_EXTENSION_HOURS", 24)
RENTAL_CHECK_INTERVAL = _get_int("RENTAL_CHECK_INTERVAL", 60)

DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")
