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

AI_ENABLED = _get_bool("AI_ENABLED", False)
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.groq.com/openai/v1").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "llama-3.1-8b-instant").strip()
AI_TEMPERATURE = _get_float("AI_TEMPERATURE", 0.2)
AI_MAX_TOKENS = _get_int("AI_MAX_TOKENS", 256)
AI_TIMEOUT_SECONDS = _get_int("AI_TIMEOUT_SECONDS", 12)
AI_SUMMARY_ENABLED = _get_bool("AI_SUMMARY_ENABLED", True)
AI_SUMMARY_TRIGGER = _get_int("AI_SUMMARY_TRIGGER", 40)
AI_SUMMARY_MAX_CHARS = _get_int("AI_SUMMARY_MAX_CHARS", 1200)
AI_SUMMARY_MAX_TOKENS = _get_int("AI_SUMMARY_MAX_TOKENS", 256)
AI_CONTEXT_MESSAGES = _get_int("AI_CONTEXT_MESSAGES", 20)
AI_MESSAGE_MAX_CHARS = _get_int("AI_MESSAGE_MAX_CHARS", 500)
AI_RENTAL_HISTORY_LIMIT = _get_int("AI_RENTAL_HISTORY_LIMIT", 5)
AI_ORDER_HISTORY_LIMIT = _get_int("AI_ORDER_HISTORY_LIMIT", 5)
AI_SYSTEM_PROMPT = os.getenv("AI_SYSTEM_PROMPT", "").strip()
AI_FALLBACK_REPLY = os.getenv(
    "AI_FALLBACK_REPLY",
    "I can help with rentals. Please tell me what you need.",
).strip()
AI_PAYMENT_REQUIRED_REPLY = os.getenv(
    "AI_PAYMENT_REQUIRED_REPLY",
    "Please purchase a lot on FunPay and the bot will send details automatically after payment.",
).strip()

REQUIRE_PAID_ORDER = _get_bool("REQUIRE_PAID_ORDER", True)
