import asyncio
import logging
import os
import aiohttp
import sqlite3
import time
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

GREEN_API_URL = os.getenv("GREEN_API_URL", "https://api.green-api.com").rstrip("/")
ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN_INSTANCE")
BASE_SMARTLINK = os.getenv("SMARTLINK_URL")

if not all([ID_INSTANCE, API_TOKEN, BASE_SMARTLINK]):
    raise ValueError("ERROR: GREEN_API_ID_INSTANCE, GREEN_API_TOKEN_INSTANCE, and SMARTLINK_URL must be set in .env")

DB_DIR = os.getenv("DATA_DIR", "data")
DB_FILE = os.path.join(DB_DIR, "followups.db")
HEARTBEAT_FILE = os.getenv("HEARTBEAT_FILE", "/tmp/heartbeat")

def init_db():
    """Initializes SQLite database schema for storing scheduled follow-up messages."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            personal_link TEXT,
            step INTEGER,
            scheduled_time INTEGER,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

def add_followups(chat_id, personal_link):
    """Saves 24H and 48H follow-up tasks to the SQLite database to withstand container restarts."""
    now = int(time.time())
    time_24h = now + 86400
    time_48h = now + 172800

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Avoid duplicate pending tasks for the same chat
    c.execute("SELECT count(*) FROM followups WHERE chat_id = ? AND status = 'pending'", (chat_id,))
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO followups (chat_id, personal_link, step, scheduled_time, status)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, personal_link, 1, time_24h, 'pending'))
        c.execute("""
            INSERT INTO followups (chat_id, personal_link, step, scheduled_time, status)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, personal_link, 2, time_48h, 'pending'))
        conn.commit()
    conn.close()

def get_pending_followups():
    """Queries all follow-up tasks that are due for delivery."""
    now = int(time.time())
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, chat_id, personal_link, step
        FROM followups
        WHERE status = 'pending' AND scheduled_time <= ?
    """, (now,))
    rows = c.fetchall()
    conn.close()
    return rows

def update_followup_status(followup_id, status):
    """Updates the status of a follow-up task (e.g., 'sent', 'failed')."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE followups SET status = ? WHERE id = ?", (status, followup_id))
    conn.commit()
    conn.close()

def has_been_contacted(chat_id):
    """Checks whether this chat already received the welcome message in a previous run."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM followups WHERE chat_id = ?", (chat_id,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

async def heartbeat_loop(interval=30):
    """Touches a heartbeat file periodically so a Docker healthcheck can tell a
    hung (but not crashed) bot process apart from a genuinely live one."""
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception as e:
            logger.warning(f"Could not write heartbeat file: {e}")
        await asyncio.sleep(interval)

async def send_whatsapp_message(session: aiohttp.ClientSession, chat_id: str, text: str) -> bool:
    """Send a message to a specific WhatsApp chat using Green API's sendMessage endpoint."""
    url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    try:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                return True
            else:
                err_text = await response.text()
                logger.error(f"Green-API Error ({response.status}) when sending to {chat_id}: {err_text}")
                return False
    except Exception as e:
        logger.error(f"HTTP request exception when sending to {chat_id}: {e}")
        return False

async def followup_poller(session: aiohttp.ClientSession):
    """Periodically checks the database for pending follow-ups and sends them."""
    logger.info("WhatsApp Follow-up Poller task started...")
    while True:
        try:
            pending = await asyncio.to_thread(get_pending_followups)
            for row in pending:
                fid, chat_id, personal_link, step = row
                wa_id = chat_id.split("@")[0]

                if step == 1:
                    text = (
                        f"Hey! Are you still there? My private video is waiting for you... 💋\n\n"
                        f"Register quickly to see it now before it's gone!\n\n"
                        f"▶️ WATCH NOW: {personal_link}"
                    )
                    prefix = "24H"
                else:
                    text = (
                        f"Last chance! 😈 I'm deleting my profile soon...\n\n"
                        f"Don't miss out, click the link below:\n\n"
                        f"▶️ UNLOCK FULL VIDEO: {personal_link}"
                    )
                    prefix = "48H"

                logger.info(f"[{prefix}] Sending scheduled follow-up to {wa_id}...")
                success = await send_whatsapp_message(session, chat_id, text)

                if success:
                    await asyncio.to_thread(update_followup_status, fid, 'sent')
                    logger.info(f"[{prefix}] Follow-up sent to {wa_id}")
                else:
                    await asyncio.to_thread(update_followup_status, fid, 'failed')
                    logger.error(f"[{prefix}] Failed to send follow-up to {wa_id}")

        except Exception as e:
            logger.error(f"Error in followup_poller loop: {e}")

        await asyncio.sleep(20)

async def handle_notification(session: aiohttp.ClientSession, notification: dict):
    """Processes incoming Webhook notification from Green API."""
    body = notification.get("body", {})
    type_webhook = body.get("typeWebhook")

    if type_webhook != "incomingMessageReceived":
        return

    sender_data = body.get("senderData", {})
    chat_id = sender_data.get("chatId")  # e.g., 79999999999@c.us

    if not chat_id or not chat_id.endswith("@c.us"):
        return  # Only respond to private chats

    if await asyncio.to_thread(has_been_contacted, chat_id):
        # Welcome + follow-up funnel was already sent to this chat in a previous message;
        # avoid re-sending it on every subsequent reply the user sends.
        return

    wa_id = chat_id.split("@")[0]
    personal_link = f"{BASE_SMARTLINK}{wa_id}"

    welcome_text = (
        "🤫 The video you're looking for is inside...\n\n"
        "To bypass age restrictions and watch the full uncensored version, "
        "verify your age by creating a quick free account via the link below. 🔞\n\n"
        f"▶️ WATCH NOW: {personal_link}"
    )

    logger.info(f"User {wa_id} initiated contact. Generating link: {personal_link}")

    success = await send_whatsapp_message(session, chat_id, welcome_text)
    if success:
        # Save scheduled follow-up notifications to database
        await asyncio.to_thread(add_followups, chat_id, personal_link)

async def main():
    logger.info("WhatsApp Redirect Bot is loading...")
    init_db()

    async with aiohttp.ClientSession() as session:
        receive_url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/receiveNotification/{API_TOKEN}?receiveTimeout=20"

        # Start follow-up poller and heartbeat tasks
        asyncio.create_task(followup_poller(session))
        asyncio.create_task(heartbeat_loop())

        logger.info("WhatsApp Bot is running and waiting for traffic...")

        backoff = 2
        while True:
            try:
                async with session.get(receive_url) as response:
                    if response.status == 200:
                        backoff = 2  # Reset backoff on successful contact
                        data = await response.json()
                        if data:
                            receipt_id = data.get("receiptId")
                            if receipt_id:
                                try:
                                    await handle_notification(session, data)
                                except Exception as e:
                                    logger.error(f"Error handling notification: {e}")
                                finally:
                                    # Always delete notification from the queue after processing
                                    delete_url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/deleteNotification/{API_TOKEN}/{receipt_id}"
                                    async with session.delete(delete_url) as del_resp:
                                        if del_resp.status != 200:
                                            del_txt = await del_resp.text()
                                            logger.warning(f"Failed to delete notification {receipt_id}: {del_txt}")
                    else:
                        err_txt = await response.text()
                        logger.warning(f"Error receiving notification ({response.status}): {err_txt}. Backing off for {backoff} seconds...")
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
            except asyncio.CancelledError:
                logger.info("Bot is stopping...")
                break
            except Exception as e:
                logger.error(f"Connection error or exception: {e}. Backing off for {backoff} seconds...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("WhatsApp Bot stopped by user.")
