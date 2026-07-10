import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import sqlite3
import time
from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked

load_dotenv()

BOT_TOKEN = os.getenv("REDIRECT_BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BASE_SMARTLINK = os.getenv("SMARTLINK_URL")

if not all([BOT_TOKEN, API_ID, API_HASH, BASE_SMARTLINK]):
    raise ValueError("ERROR: .env is not full.")

app = Client(
    "redirect_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

DB_DIR = os.getenv("DATA_DIR", "data")
DB_FILE = os.path.join(DB_DIR, "followups.db")

def init_db():
    """Initializes SQLite database schema for storing scheduled follow-up messages,
    so pending 24h/48h follow-ups survive container restarts (they used to live only
    in memory via asyncio.sleep and were lost on every redeploy)."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            personal_link TEXT,
            step INTEGER,
            scheduled_time INTEGER,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

def add_followups(chat_id, personal_link):
    """Saves 24H and 48H follow-up tasks to the SQLite database."""
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
    """Updates the status of a follow-up task (e.g., 'sent', 'blocked', 'failed')."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE followups SET status = ? WHERE id = ?", (status, followup_id))
    conn.commit()
    conn.close()

def cancel_pending_followups(chat_id):
    """Cancels remaining pending steps for a chat (e.g., after the user blocked the bot)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE followups SET status = 'blocked' WHERE chat_id = ? AND status = 'pending'", (chat_id,))
    conn.commit()
    conn.close()

FOLLOWUP_TEXTS = {
    1: (
        "Hey! Are you still there? My private video is waiting for you... 💋\n\n"
        "Register quickly to see it now before it's gone!"
    ),
    2: (
        "Last chance! 😈 I'm deleting my profile soon...\n\n"
        "Don't miss out, tap the button below:"
    ),
}
FOLLOWUP_BUTTONS = {
    1: "▶️ WATCH NOW",
    2: "▶️ UNLOCK FULL VIDEO",
}

async def followup_poller(client: Client):
    """Periodically checks the database for pending follow-ups and sends them.
    Runs as a background task for the lifetime of the bot process."""
    print("⌛ Follow-up Poller task started...")
    while True:
        try:
            pending = await asyncio.to_thread(get_pending_followups)
            for followup_id, chat_id, personal_link, step in pending:
                text = FOLLOWUP_TEXTS.get(step)
                button_label = FOLLOWUP_BUTTONS.get(step)
                if not text:
                    await asyncio.to_thread(update_followup_status, followup_id, 'failed')
                    continue

                try:
                    await client.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(button_label, url=personal_link)]
                        ]),
                        disable_web_page_preview=True
                    )
                    await asyncio.to_thread(update_followup_status, followup_id, 'sent')
                    print(f"📩 [Step {step}] Отправлен дожим юзеру {chat_id}")
                except UserIsBlocked:
                    print(f"⚠️ Юзер {chat_id} заблокировал бота. Отмена дальнейшего дожима.")
                    await asyncio.to_thread(cancel_pending_followups, chat_id)
                except Exception as e:
                    print(f"⚠️ [Step {step}] Ошибка отправки юзеру {chat_id}: {e}")
                    await asyncio.to_thread(update_followup_status, followup_id, 'failed')
        except Exception as e:
            print(f"⚠️ Error in followup_poller loop: {e}")

        await asyncio.sleep(60)


@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    tg_id = message.from_user.id

    # Собираем финальную ссылку: базовый урл + Telegram ID юзера в качестве метки
    personal_link = f"{BASE_SMARTLINK}{tg_id}"

    # Текст приветствия
    welcome_text = (
        "🤫 **The video you're looking for is inside...**\n\n"
        "To bypass age restrictions and watch the full uncensored version, "
        "verify your age by creating a quick free account via the button below. 🔞"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ UNLOCK FULL VIDEO", url=personal_link)]
    ])

    # Отправляем сообщение
    await message.reply_text(
        text=welcome_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
    print(f"🚀 Link for user is generated! {tg_id}: {personal_link}")
    await asyncio.to_thread(add_followups, message.chat.id, personal_link)


async def main():
    await app.start()
    init_db()
    asyncio.create_task(followup_poller(app))
    print("🤖 Bot is loaded and waiting for traffic...")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
