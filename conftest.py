import os
import sys

# Some modules raise at import time if required env vars are missing (e.g.
# uniqreo/core/config.py). Set harmless placeholder values so importing them
# under pytest doesn't require a real .env file.
os.environ.setdefault("API_ID", "12345")
os.environ.setdefault("API_HASH", "test_api_hash")
# uniqreo/bot.py is now the one merged Telegram bot process; it authenticates
# with REDIRECT_BOT_TOKEN (see core/config.py).
os.environ.setdefault("REDIRECT_BOT_TOKEN", "123456:test-bot-token")
os.environ.setdefault("SMARTLINK_URL", "https://example.com/?u=")
os.environ.setdefault("LEAD_CHAT_ID", "-100123456789")
os.environ.setdefault("LEAD_THREAD_ID", "1")
os.environ.setdefault("S2S_POSTBACK_SECRET", "test-secret")

# Services live in folders with hyphens or without __init__.py, so they can't be
# imported as normal packages (e.g. `s2s-postback-server` isn't a valid module
# name). Add each service directory straight to sys.path instead, mirroring how
# they're actually run in production (each as its own top-level script directory).
ROOT = os.path.dirname(os.path.abspath(__file__))
for relative_path in ("tiktok_scraper", "s2s-postback-server", "uniqreo"):
    full_path = os.path.join(ROOT, relative_path)
    if full_path not in sys.path:
        sys.path.insert(0, full_path)
