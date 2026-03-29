from os import environ as env
from dotenv import load_dotenv

load_dotenv()


def _parse_admin_credentials():
    credentials = {}

    raw_credentials = str(env.get("ADMIN_CREDENTIALS", "")).strip()
    if raw_credentials:
        for item in raw_credentials.split(","):
            part = item.strip()
            if not part or ":" not in part:
                continue
            username, password = part.split(":", 1)
            username = username.strip()
            password = password.strip()
            if username and password:
                credentials[username] = password

    legacy_username = str(env.get("ADMIN_USERNAME", "admin")).strip()
    legacy_password = str(env.get("ADMIN_PASSWORD", "")).strip()
    if legacy_username and legacy_password:
        credentials.setdefault(legacy_username, legacy_password)

    return credentials

class Telegram:
    API_ID = int(env.get("API_ID"))
    API_HASH = str(env.get("API_HASH"))
    BOT_TOKEN = str(env.get("BOT_TOKEN"))
    USER_SESSION_STRING = str(env.get("USER_SESSION_STRING", ""))
    OWNER_ID = int(env.get('OWNER_ID', '7978482443'))
    WORKERS = int(env.get("WORKERS", "6"))  # 6 workers = 6 commands at once
    DATABASE_URL = str(env.get('DATABASE_URL'))
    UPDATES_CHANNEL = str(env.get('UPDATES_CHANNEL', "Telegram"))
    SESSION_NAME = str(env.get('SESSION_NAME', 'FileStream'))
    FORCE_SUB_ID = env.get('FORCE_SUB_ID', None)
    FORCE_SUB = env.get('FORCE_SUB', False)
    FORCE_SUB = True if str(FORCE_SUB).lower() == "true" else False
    SLEEP_THRESHOLD = int(env.get("SLEEP_THRESHOLD", "60"))
    FILE_PIC = env.get('FILE_PIC', "https://graph.org/file/5bb9935be0229adf98b73.jpg")
    START_PIC = env.get('START_PIC', "https://graph.org/file/290af25276fa34fa8f0aa.jpg")
    VERIFY_PIC = env.get('VERIFY_PIC', "https://graph.org/file/736e21cc0efa4d8c2a0e4.jpg")
    MULTI_CLIENT = False
    FLOG_CHANNEL = int(env.get("FLOG_CHANNEL", None))   # Logs channel for file logs
    ULOG_CHANNEL = int(env.get("ULOG_CHANNEL", None))   # Logs channel for user logs
    MODE = env.get("MODE", "primary")
    SECONDARY = True if MODE.lower() == "secondary" else False
    AUTH_USERS = list(set(int(x) for x in str(env.get("AUTH_USERS", "")).split()))
    ADMIN_USERNAME = str(env.get("ADMIN_USERNAME", "admin"))
    ADMIN_PASSWORD = str(env.get("ADMIN_PASSWORD", ""))
    ADMIN_CREDENTIALS = _parse_admin_credentials()
    WEB_SESSION_SECRET = str(env.get("WEB_SESSION_SECRET", BOT_TOKEN))
    WEB_SESSION_TTL = int(env.get("WEB_SESSION_TTL", "2592000"))
    TMDB_API_KEY = str(env.get("TMDB_API_KEY", ""))
    TMDB_READ_ACCESS_TOKEN = str(env.get("TMDB_READ_ACCESS_TOKEN", ""))

class Server:
    PORT = int(env.get("PORT", 8080))
    BIND_ADDRESS = str(env.get("BIND_ADDRESS", "0.0.0.0"))
    PING_INTERVAL = int(env.get("PING_INTERVAL", "1200"))
    STREAM_CHUNK_SIZE = int(env.get("STREAM_CHUNK_SIZE", str(4 * 1024 * 1024)))
    HAS_SSL = str(env.get("HAS_SSL", "0").lower()) in ("1", "true", "t", "yes", "y")
    NO_PORT = str(env.get("NO_PORT", "0").lower()) in ("1", "true", "t", "yes", "y")
    FQDN = str(env.get("FQDN", BIND_ADDRESS))
    URL = "http{}://{}{}/".format(
        "s" if HAS_SSL else "", FQDN, "" if NO_PORT else ":" + str(PORT)
    )
