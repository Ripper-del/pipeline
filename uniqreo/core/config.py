import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# One bot process handles everything now (uniqueization, /upload, lead funnel,
# ops-group control panel), so it uses the same token as the rest of the
# pipeline's Telegram notifications (automator.py, uploader.py, s2s_server).
BOT_TOKEN = os.getenv("REDIRECT_BOT_TOKEN")

SMARTLINK_URL = os.getenv("SMARTLINK_URL")

try:
    SOURCE_THREAD_ID = int(os.getenv("SOURCE_THREAD_ID", 0))
    TARGET_THREAD_ID = int(os.getenv("TARGET_THREAD_ID", 0))
except ValueError:
    SOURCE_THREAD_ID = 0
    TARGET_THREAD_ID = 0

# Telegram user IDs allowed to run /upload (drives a real AdsPower browser + posts
# live video to TikTok, so it must not be reachable by arbitrary users). Empty by
# default -> fails closed: nobody can upload until this is explicitly configured.
ADMIN_TELEGRAM_IDS = set()
for _raw_id in os.getenv("ADMIN_TELEGRAM_IDS", "").split(","):
    _raw_id = _raw_id.strip()
    if _raw_id:
        try:
            ADMIN_TELEGRAM_IDS.add(int(_raw_id))
        except ValueError:
            logger.warning(f"Ignoring invalid ADMIN_TELEGRAM_IDS entry: {_raw_id!r}")

if not all([API_ID, API_HASH, BOT_TOKEN, SMARTLINK_URL]):
    raise ValueError("API_ID, API_HASH, REDIRECT_BOT_TOKEN and SMARTLINK_URL are all required.")