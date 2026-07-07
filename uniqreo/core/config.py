from dotenv import load_dotenv
import os

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

BOT_TOKEN = os.getenv("BOT_TOKEN")

try:
    SOURCE_THREAD_ID = int(os.getenv("SOURCE_THREAD_ID", 0))
    TARGET_THREAD_ID = int(os.getenv("TARGET_THREAD_ID", 0))
except ValueError:
    SOURCE_THREAD_ID = 0
    TARGET_THREAD_ID = 0

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("all API_ID, API_HASH, BOT_TOKEN are required.")