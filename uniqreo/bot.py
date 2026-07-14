import asyncio
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import httpx
from pyrogram import Client, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from pyrogram.errors import UserIsBlocked
from core.config import (
    API_ID, API_HASH, BOT_TOKEN, SOURCE_THREAD_ID, TARGET_THREAD_ID,
    ADMIN_TELEGRAM_IDS, SMARTLINK_URL,
)
from core.photo_processor import process_photo
from core.video_processor import process_video
from uploader import run_uploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Client(
    "unique_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    # In this deployment's network, pyrogram's direct MTProto connection sends
    # fine but never receives push updates - reproduced across three separate
    # bot accounts (including a brand-new one) and confirmed via raw Bot API
    # getUpdates showing messages queued that pyrogram's dispatcher never saw.
    # The classic Bot API's getUpdates, by contrast, delivered every single
    # test message without fail throughout debugging - its stateless
    # request/response model tolerates our flaky Docker/host network far
    # better than a long-lived MTProto push socket does. So incoming messages
    # are fetched via get_updates_loop()/dispatch_update() below instead of
    # pyrogram's own update mechanism; `app` is only used for *sending*
    # (send_message/send_document/download_media), which works fine over
    # MTProto either way. no_updates=True stops pyrogram from wastefully
    # trying (and failing) to receive on its own.
    no_updates=True,
)

# limits the amount of simultaneous renders/uploads
semaphore = asyncio.Semaphore(3)
upload_semaphore = asyncio.Semaphore(2)

# Pyrogram's download/send_document calls have no built-in timeout and can
# hang indefinitely on a stalled connection instead of raising - observed
# directly on this deployment's flaky network. Bounding them means a stuck
# transfer fails cleanly (releasing its semaphore slot) instead of wedging
# that slot forever and eventually starving every future upload/render.
MEDIA_TRANSFER_TIMEOUT = 180


async def _with_hard_timeout(coro, timeout):
    """Bounds `coro` to `timeout` seconds without waiting for its cancellation
    to finish gracefully. Plain asyncio.wait_for isn't enough here: pyrogram's
    chunked file upload (save_file) spawns background worker tasks, and on
    Python 3.11+ wait_for blocks until a cancelled task's own finally-block
    cleanup completes - but that cleanup itself can hang on this deployment's
    flaky network (e.g. waiting on a queue a stuck worker never drains),
    which silently defeats the timeout entirely. Firing the cancellation and
    moving on immediately, instead of awaiting it, avoids that trap."""
    task = asyncio.ensure_future(coro)
    done, pending = await asyncio.wait({task}, timeout=timeout)
    if task in pending:
        task.cancel()
        raise asyncio.TimeoutError(f"Operation exceeded {timeout}s")
    return task.result()


MEDIA_TRANSFER_ATTEMPTS = 3


async def _with_retries(coro_factory, timeout, attempts=MEDIA_TRANSFER_ATTEMPTS, description="transfer"):
    """Retries a media transfer up to `attempts` times, each bounded by
    _with_hard_timeout. The network here is flaky enough that a single
    stalled attempt doesn't mean the transfer can never succeed - `coro_factory`
    must be a zero-arg callable returning a *fresh* coroutine each call, since
    a coroutine object can only be awaited once."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return await _with_hard_timeout(coro_factory(), timeout)
        except Exception as e:
            last_error = e
            logger.warning(f"{description}: attempt {attempt}/{attempts} failed: {e}")
    raise last_error


DB_DIR = os.getenv("DATA_DIR", "data")
DB_FILE = os.path.join(DB_DIR, "followups.db")
HEARTBEAT_FILE = os.getenv("HEARTBEAT_FILE", "/tmp/heartbeat")

# --- Ops-group control panel (per-thread reply keyboards that actually launch scripts) ---

LEAD_CHAT_ID = os.getenv("LEAD_CHAT_ID")
DEFAULT_GEO = os.getenv("DEFAULT_GEO", "US")
S2S_STATS_URL = os.getenv("S2S_STATS_URL")
S2S_POSTBACK_SECRET = os.getenv("S2S_POSTBACK_SECRET")

# Directory containing automator.py, used as the subprocess's cwd so it resolves
# `from common... import` as a sibling module exactly like a manual
# `cd tiktok_scraper && python automator.py` run would. Defaults to the sibling
# path used in local (non-Docker) dev; the Dockerfile overrides this via env
# once tiktok_scraper/ is copied to a different location inside the image.
TIKTOK_SCRAPER_DIR = os.getenv(
    "TIKTOK_SCRAPER_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tiktok_scraper"),
)

STATS_BUTTON = "📊 Статистика за сутки"
START_WARMUP_BUTTON = "▶️ Запустить прогрев"
STOP_WARMUP_BUTTON = "⏹ Остановить прогрев"
START_SPY_BUTTON = "▶️ Запустить спай"
STOP_SPY_BUTTON = "⏹ Остановить спай"
START_AUTOUPLOAD_BUTTON = "🚀 Автозалив"

_BUTTON_ACTIONS = {
    STATS_BUTTON: "stats",
    START_WARMUP_BUTTON: "start_warmup",
    STOP_WARMUP_BUTTON: "stop_warmup",
    START_SPY_BUTTON: "start_spy",
    STOP_SPY_BUTTON: "stop_spy",
    START_AUTOUPLOAD_BUTTON: "start_autoupload",
}


def parse_thread_id(value):
    """Parses a thread-id env var, tolerating unset/blank/non-numeric values."""
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def resolve_thread_button_map(lead_thread, warmup_thread, spy_thread, upload_thread=None):
    """Maps each configured (non-zero) thread id to its keyboard rows (a list
    of button-label rows, ready to hand straight to ReplyKeyboardMarkup).
    Threads left unset get no custom keyboard at all - source/target threads
    are intentionally omitted here since their action (receiving forwarded
    media) can't be triggered by a button tap. upload_thread gets a single
    "🚀 Автозалив" button: unlike /upload it doesn't carry a video itself, it
    fires on whatever video the caller most recently dropped into that same
    thread (see upload_thread_video_handler) and fans it out to every AdsPower
    profile they've bound via /addprofile. If warmup and spy point at the
    *same* thread id (e.g. to keep them in one chat/topic), both rows land in
    that one thread's keyboard instead of the second silently overwriting the
    first."""
    button_map = {}

    def add_row(thread_id, row):
        if not thread_id:
            return
        button_map.setdefault(thread_id, []).append(row)

    add_row(lead_thread, [STATS_BUTTON])
    add_row(warmup_thread, [START_WARMUP_BUTTON, STOP_WARMUP_BUTTON])
    add_row(spy_thread, [START_SPY_BUTTON, STOP_SPY_BUTTON])
    add_row(upload_thread, [START_AUTOUPLOAD_BUTTON])
    return button_map


def route_button_press(text, thread_id, button_map):
    """Matches an incoming (text, thread_id) pair from the ops group against
    button_map to an action name, or None if it isn't a recognized button tap
    for that specific thread."""
    rows = button_map.get(thread_id)
    if not rows:
        return None
    for row in rows:
        if text in row:
            return _BUTTON_ACTIONS.get(text)
    return None


def has_configured_profiles():
    """Whether any AdsPower profile is configured to automate - if not, a
    warmup/spy subprocess would only be able to fall back to a local Chromium,
    which isn't installed in this bot's (lightweight, CDP-only) container."""
    return bool(os.getenv("ADSPOWER_PROFILE_IDS") or os.getenv("ADSPOWER_PROFILE_ID"))


async def start_job(running_jobs, name, cmd_args, cwd):
    """Launches automator.py as a subprocess if `name` isn't already running.
    Returns False (no-op) if a job with that name is already in flight."""
    existing = running_jobs.get(name)
    if existing is not None and existing.returncode is None:
        return False
    proc = await asyncio.create_subprocess_exec(sys.executable, "automator.py", *cmd_args, cwd=cwd)
    running_jobs[name] = proc
    return True


async def stop_job(running_jobs, name):
    """Terminates the tracked subprocess for `name`, if one is running."""
    proc = running_jobs.get(name)
    if proc is not None and proc.returncode is None:
        proc.terminate()
        return True
    return False


def format_stats_reply(stats):
    return (
        f"📊 **Статистика за 24ч**\n\n"
        f"Лидов: `{stats['count']}`\n"
        f"Начислено: `${stats['charged_total']:.2f}`\n"
        f"В холде: `${stats['hold_total']:.2f}`"
    )


UPLOAD_THREAD_ID_INT = parse_thread_id(os.getenv("UPLOAD_THREAD_ID"))

BUTTON_MAP = resolve_thread_button_map(
    parse_thread_id(os.getenv("LEAD_THREAD_ID")),
    parse_thread_id(os.getenv("WARMUP_THREAD_ID")),
    parse_thread_id(os.getenv("SPY_THREAD_ID")),
    UPLOAD_THREAD_ID_INT,
)
running_jobs = {}
# Last video a given admin dropped in the upload thread, awaiting a
# "🚀 Автозалив" button tap (a ReplyKeyboardMarkup button can't itself carry a
# file, so the video has to be remembered server-side between the two messages).
pending_uploads = {}

# --- End of control panel section ---

# --- Bot API long-polling (see the no_updates=True comment on `app` above for why) ---


class _Peer:
    __slots__ = ("id", "username")

    def __init__(self, data):
        self.id = data["id"]
        self.username = data.get("username")


class IncomingMessage:
    """Adapter over a raw Bot API message dict, exposing just the subset of
    pyrogram.types.Message's interface our handlers use (chat/from_user/text/
    photo/video/caption/reply_to_message, plus reply_text()/download()).
    `app` (a real pyrogram Client) still does the actual sending/downloading -
    this class only stands in for the *receiving* side."""

    def __init__(self, data):
        self.message_id = data["message_id"]
        self.chat = _Peer(data["chat"])
        self.chat_type = data["chat"].get("type")
        self.message_thread_id = data.get("message_thread_id")
        self.text = data.get("text")
        self.caption = data.get("caption")
        self.video = data.get("video")
        self.photo = data.get("photo")
        from_user = data.get("from")
        self.from_user = _Peer(from_user) if from_user else None
        reply = data.get("reply_to_message")
        self.reply_to_message = IncomingMessage(reply) if reply else None

    async def reply_text(self, text, **kwargs):
        return await app.send_message(
            chat_id=self.chat.id,
            text=text,
            message_thread_id=self.message_thread_id,
            reply_to_message_id=self.message_id,
            **kwargs,
        )

    async def download(self, file_name=None):
        if self.video:
            file_id = self.video["file_id"]
        elif self.photo:
            file_id = self.photo[-1]["file_id"]
        else:
            raise ValueError("Message has no video or photo to download")
        result = await app.download_media(file_id, file_name=file_name)
        if not result:
            # pyrogram sometimes swallows an internal error (e.g. a media-DC
            # session auth failure) and just logs it instead of raising, so
            # download_media silently returns None on failure - turn that
            # into a real exception so _with_retries actually retries it.
            raise RuntimeError("download_media returned no file (pyrogram logged an internal error, see logs above)")
        return result


def _command_name(text):
    """Extracts a lowercased command name from message text ("/upload@bot arg"
    -> "upload"), or None if the text isn't a command."""
    if not text or not text.startswith("/"):
        return None
    first_word = text.split(maxsplit=1)[0][1:]
    return first_word.split("@")[0].lower() or None


async def dispatch_update(update):
    """Routes one raw Bot API update to the matching handler. Replaces
    pyrogram's own filter-based dispatch (see `app = Client(...)` above) with
    explicit, mutually-exclusive branches - simpler than fighting pyrogram's
    implicit handler-group propagation rules, and there's no risk of one
    handler silently swallowing an update meant for another."""
    raw = update.get("message")
    if not raw:
        return
    try:
        message = IncomingMessage(raw)
        command = _command_name(message.text)
        is_group = message.chat_type in ("group", "supergroup")

        if command == "start":
            if message.chat_type == "private":
                await start_handler(message)
        elif command == "upload":
            await upload_handler(message)
        elif command == "addprofile":
            await addprofile_handler(message)
        elif command == "removeprofile":
            await removeprofile_handler(message)
        elif command == "myprofiles":
            await myprofiles_handler(message)
        elif command:
            pass  # unrecognized command - ignore, matches main_handler's old behavior
        elif is_group and message.video and UPLOAD_THREAD_ID_INT is not None \
                and message.message_thread_id == UPLOAD_THREAD_ID_INT:
            await upload_thread_video_handler(message)
        elif is_group and message.text and route_button_press(message.text, message.message_thread_id, BUTTON_MAP):
            await button_handler(message)
        else:
            await main_handler(message)
    except Exception as e:
        logger.error(f"Error dispatching update {update.get('update_id')}: {e}")


async def get_updates_loop():
    """Long-polls the classic Bot API for new messages and feeds them to
    dispatch_update. See the no_updates=True comment above `app = Client(...)`
    for why this exists instead of pyrogram's own update delivery."""
    offset = 0
    async with httpx.AsyncClient(timeout=40) as http_client:
        logger.info("get_updates_loop started (Bot API long-polling).")
        while True:
            try:
                resp = await http_client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                resp.raise_for_status()
                payload = resp.json()
                for update in payload.get("result", []):
                    offset = update["update_id"] + 1
                    asyncio.create_task(dispatch_update(update))
            except Exception as e:
                logger.error(f"getUpdates polling error: {e}")
                await asyncio.sleep(5)


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
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER NOT NULL,
            profile_id TEXT NOT NULL,
            UNIQUE(user_id, profile_id)
        )
    """)
    conn.commit()
    conn.close()

def add_profile(user_id, profile_id):
    """Binds an AdsPower profile id to a Telegram user, so the "🚀 Автозалив"
    button can fan a dropped video out to all of that user's profiles.
    No-ops if already bound."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO user_profiles (user_id, profile_id) VALUES (?, ?)", (user_id, profile_id))
    conn.commit()
    conn.close()

def remove_profile(user_id, profile_id):
    """Unbinds an AdsPower profile id from a Telegram user."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM user_profiles WHERE user_id = ? AND profile_id = ?", (user_id, profile_id))
    conn.commit()
    conn.close()

def get_user_profiles(user_id):
    """Returns the list of AdsPower profile ids bound to a Telegram user."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT profile_id FROM user_profiles WHERE user_id = ?", (user_id,))
    profiles = [row[0] for row in c.fetchall()]
    conn.close()
    return profiles

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

async def followup_poller(client: Client):
    """Periodically checks the database for pending follow-ups and sends them.
    Runs as a background task for the lifetime of the bot process."""
    logger.info("Follow-up Poller task started...")
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
                    logger.info(f"[Step {step}] Отправлен дожим юзеру {chat_id}")
                except UserIsBlocked:
                    logger.warning(f"Юзер {chat_id} заблокировал бота. Отмена дальнейшего дожима.")
                    await asyncio.to_thread(cancel_pending_followups, chat_id)
                except Exception as e:
                    logger.warning(f"[Step {step}] Ошибка отправки юзеру {chat_id}: {e}")
                    await asyncio.to_thread(update_followup_status, followup_id, 'failed')
        except Exception as e:
            logger.error(f"Error in followup_poller loop: {e}")

        await asyncio.sleep(60)

async def process_and_upload(cmd_msg: "IncomingMessage", video_msg: "IncomingMessage", profile_id: str, caption: str):
    """Downloads, uniqueizes, and uploads the video in the background under semaphore limit."""
    async with upload_semaphore:
        task_dir_in = ""
        task_dir_out = ""
        output_path = ""
        status_msg = await cmd_msg.reply_text(f"⏳ <b>[TikTok Uploader]</b> Профиль <code>{profile_id}</code>: скачиваю и уникализирую видео...")

        try:
            os.makedirs("tmp_input", exist_ok=True)
            os.makedirs("tmp_output", exist_ok=True)
            # Each task gets its own subdirectory so two concurrent uploads with the
            # same original filename can never clobber each other's file mid-render.
            task_dir_in = tempfile.mkdtemp(dir="tmp_input")
            task_dir_out = tempfile.mkdtemp(dir="tmp_output")

            # Download file
            input_path = await _with_retries(
                lambda: video_msg.download(file_name=f"{task_dir_in}/"), MEDIA_TRANSFER_TIMEOUT,
                description="upload download",
            )
            filename = os.path.basename(input_path)
            output_path = f"{task_dir_out}/unique_{filename}"

            # Uniqueize video
            await process_video(input_path, output_path)
            await status_msg.edit_text(f"✅ Профиль <code>{profile_id}</code>: видео уникализировано. Начинаю запуск браузера и автозалив...")

            # Connect to AdsPower on host
            api_url = os.getenv("ADSPOWER_API_URL", "http://host.docker.internal:50325")

            # Run upload flow
            success = await run_uploader(
                video_path=output_path,
                profile_id=profile_id,
                caption=caption,
                api_url=api_url,
                headless=True
            )

            if success:
                await status_msg.edit_text(f"🎉 Профиль <code>{profile_id}</code>: видео успешно опубликовано в TikTok!")
            else:
                await status_msg.edit_text(f"❌ Профиль <code>{profile_id}</code>: ошибка при автозаливе. Проверьте логи в Telegram-ветке.")

        except Exception as e:
            logger.error(f"Error in upload flow: {e}")
            await status_msg.edit_text(f"❌ Профиль <code>{profile_id}</code>: ошибка при обработке: {e}")
        finally:
            if task_dir_in:
                shutil.rmtree(task_dir_in, ignore_errors=True)
            if task_dir_out:
                shutil.rmtree(task_dir_out, ignore_errors=True)


async def start_handler(message: "IncomingMessage"):
    tg_id = message.from_user.id

    # Собираем финальную ссылку: базовый урл + Telegram ID юзера в качестве метки
    personal_link = f"{SMARTLINK_URL}{tg_id}"

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
    logger.info(f"Link for user is generated! {tg_id}: {personal_link}")
    await asyncio.to_thread(add_followups, message.chat.id, personal_link)


async def upload_handler(message: "IncomingMessage"):
    """Handles the /upload command (triggered directly or as reply)."""
    # /upload drives a real AdsPower browser and posts live video to TikTok, so it
    # must be restricted to explicitly allow-listed operators, not any chat member.
    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        logger.warning(f"Unauthorized /upload attempt from user_id={caller_id}")
        await message.reply_text("⛔ У вас нет прав на запуск автозалива.")
        return

    # Parse command format: /upload <profile_id> [caption]
    command_parts = message.text.split(maxsplit=2) if message.text else []
    if len(command_parts) < 2:
        await message.reply_text("❌ Формат команды: `/upload <profile_id> [описание]`")
        return

    profile_id = command_parts[1]
    caption = command_parts[2] if len(command_parts) > 2 else "#dating #datingadvice"

    # Check if the message has a video or is replying to a video message
    target_msg = message
    if not message.video and message.reply_to_message:
        target_msg = message.reply_to_message

    if not target_msg.video:
        await message.reply_text("❌ Видео не обнаружено. Отправьте видео с этой командой или ответьте на видео-сообщение.")
        return

    # Schedule background processing and upload
    asyncio.create_task(process_and_upload(message, target_msg, profile_id, caption))


async def addprofile_handler(message: "IncomingMessage"):
    """Binds an AdsPower profile id to the caller so the "🚀 Автозалив" button
    in the upload thread fans a dropped video out to it too."""
    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        await message.reply_text("⛔ У вас нет прав на привязку профилей.")
        return

    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text("❌ Формат команды: `/addprofile <profile_id>`")
        return

    profile_id = parts[1].strip()
    await asyncio.to_thread(add_profile, caller_id, profile_id)
    await message.reply_text(f"✅ Профиль `{profile_id}` привязан. Теперь он участвует в кнопке «{START_AUTOUPLOAD_BUTTON}».")


async def removeprofile_handler(message: "IncomingMessage"):
    """Unbinds an AdsPower profile id from the caller."""
    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        await message.reply_text("⛔ У вас нет прав на управление профилями.")
        return

    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text("❌ Формат команды: `/removeprofile <profile_id>`")
        return

    profile_id = parts[1].strip()
    await asyncio.to_thread(remove_profile, caller_id, profile_id)
    await message.reply_text(f"🗑 Профиль `{profile_id}` отвязан.")


async def myprofiles_handler(message: "IncomingMessage"):
    """Lists AdsPower profile ids currently bound to the caller."""
    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        await message.reply_text("⛔ У вас нет прав на просмотр профилей.")
        return

    profiles = await asyncio.to_thread(get_user_profiles, caller_id)
    if not profiles:
        await message.reply_text("У вас не привязано ни одного профиля. Привяжите: `/addprofile <profile_id>`")
        return

    listing = "\n".join(f"• `{p}`" for p in profiles)
    await message.reply_text(f"📋 Ваши профили для автозалива:\n{listing}")


async def upload_thread_video_handler(message: "IncomingMessage"):
    """Remembers the latest video an operator drops in the upload thread, so
    the "🚀 Автозалив" button (which can't itself carry a file) knows what to
    upload once tapped. dispatch_update() already only routes here for videos
    in UPLOAD_THREAD_ID, so no thread check is needed in the body."""
    if LEAD_CHAT_ID and str(message.chat.id) != str(LEAD_CHAT_ID):
        return

    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        return

    pending_uploads[caller_id] = message
    await message.reply_text(f"✅ Видео принято. Нажмите «{START_AUTOUPLOAD_BUTTON}», чтобы залить его на все привязанные профили.")


async def handle_stats_button(message: "IncomingMessage"):
    if not S2S_STATS_URL or not S2S_POSTBACK_SECRET:
        await message.reply_text("⚠️ S2S_STATS_URL или S2S_POSTBACK_SECRET не настроены в .env.")
        return
    try:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(
                f"{S2S_STATS_URL.rstrip('/')}/stats",
                params={"secret": S2S_POSTBACK_SECRET, "hours": 24},
                timeout=10,
            )
        if resp.status_code != 200:
            await message.reply_text(f"⚠️ Не удалось получить статистику: HTTP {resp.status_code}")
            return
        await message.reply_text(format_stats_reply(resp.json()))
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        await message.reply_text(f"⚠️ Ошибка запроса статистики: {e}")


async def handle_start_job(message: "IncomingMessage", mode: str):
    if not has_configured_profiles():
        await message.reply_text("⚠️ Не настроен ADSPOWER_PROFILE_ID(S) в .env - запускать нечего.")
        return
    started = await start_job(running_jobs, mode, ["--mode", mode, "--geo", DEFAULT_GEO], TIKTOK_SCRAPER_DIR)
    if started:
        await message.reply_text(f"🚀 Запущено: {mode}. Прогресс появится в этой ветке.")
    else:
        await message.reply_text(f"⏳ {mode} уже запущен, дождитесь завершения или нажмите Стоп.")


async def handle_stop_job(message: "IncomingMessage", mode: str):
    stopped = await stop_job(running_jobs, mode)
    if stopped:
        await message.reply_text(f"⏹ Остановлено: {mode}.")
    else:
        await message.reply_text(f"ℹ️ Сейчас {mode} не запущен.")


async def handle_start_autoupload(message: "IncomingMessage"):
    """Fans the caller's last dropped video out to every AdsPower profile
    they've bound via /addprofile, one process_and_upload task per profile
    (queued behind the same upload_semaphore as manual /upload calls)."""
    caller_id = message.from_user.id if message.from_user else None
    if caller_id not in ADMIN_TELEGRAM_IDS:
        await message.reply_text("⛔ У вас нет прав на автозалив.")
        return

    video_message = pending_uploads.pop(caller_id, None)
    if not video_message:
        await message.reply_text("❌ Сначала отправьте видео в эту ветку, потом нажмите кнопку.")
        return

    profiles = await asyncio.to_thread(get_user_profiles, caller_id)
    if not profiles:
        await message.reply_text("⚠️ У вас не привязано ни одного профиля. Привяжите: `/addprofile <profile_id>`")
        return

    caption = video_message.caption or "#dating #datingadvice"
    await message.reply_text(f"🚀 Запускаю автозалив на {len(profiles)} профил(ей): {', '.join(profiles)}")
    for profile_id in profiles:
        asyncio.create_task(process_and_upload(message, video_message, profile_id, caption))


async def button_handler(message: "IncomingMessage"):
    if LEAD_CHAT_ID and str(message.chat.id) != str(LEAD_CHAT_ID):
        return

    action = route_button_press(message.text, message.message_thread_id, BUTTON_MAP)
    if not action:
        return

    if action == "stats":
        await handle_stats_button(message)
    elif action == "start_warmup":
        await handle_start_job(message, "warmup")
    elif action == "stop_warmup":
        await handle_stop_job(message, "warmup")
    elif action == "start_spy":
        await handle_start_job(message, "spy")
    elif action == "stop_spy":
        await handle_stop_job(message, "spy")
    elif action == "start_autoupload":
        await handle_start_autoupload(message)


async def main_handler(message: "IncomingMessage"):
    """Main handler for automated message uniqueization forwarding."""
    # listening mode
    if SOURCE_THREAD_ID == 0 or TARGET_THREAD_ID == 0:
        logger.info("==== MESSAGE CAUGHT ====")
        logger.info(f"Chat ID: {message.chat.id}")
        logger.info(f"Thread ID: {message.message_thread_id}")
        if message.from_user:
            logger.info(f"From user: {message.from_user.username}")
        logger.info("---------------------------------")
        return

    if message.message_thread_id != SOURCE_THREAD_ID:
        return

    if not (message.photo or message.video):
        return

    # uniqueization itself!!!
    async with semaphore:
        task_dir_in = ""
        task_dir_out = ""
        output_path = ""

        try:
            logger.info("Starting file rendering...")

            # creating temporary directories
            os.makedirs("tmp_input", exist_ok=True)
            os.makedirs("tmp_output", exist_ok=True)
            # Each task gets its own subdirectory so two concurrent renders with the
            # same original filename can never clobber each other's file mid-render.
            task_dir_in = tempfile.mkdtemp(dir="tmp_input")
            task_dir_out = tempfile.mkdtemp(dir="tmp_output")

            # downloading file
            input_path = await _with_retries(
                lambda: message.download(file_name=f"{task_dir_in}/"), MEDIA_TRANSFER_TIMEOUT,
                description="uniqueization download",
            )
            filename = os.path.basename(input_path)
            output_path = f"{task_dir_out}/unique_{filename}"

            # routing
            if message.photo:
                output_path = f"{task_dir_out}/{filename}.jpg"
                await asyncio.to_thread(process_photo, input_path, output_path)
            elif message.video:
                await process_video(input_path, output_path)

            # sending clear file
            await _with_retries(
                lambda: app.send_document(
                    chat_id=message.chat.id,
                    document=output_path,
                    message_thread_id=TARGET_THREAD_ID,
                ),
                MEDIA_TRANSFER_TIMEOUT,
                description="uniqueization upload",
            )
            logger.info("Successfully finished file rendering!!!")
        except Exception as e:
            logger.error(f"Error while rendering file: {e}")
            await message.reply_text(f"Error while rendering file: {e}")

        finally:
            if task_dir_in:
                shutil.rmtree(task_dir_in, ignore_errors=True)
            if task_dir_out:
                shutil.rmtree(task_dir_out, ignore_errors=True)


async def send_thread_keyboards():
    """Posts one message per configured ops-group thread with that thread's
    reply keyboard, so each topic only shows the buttons relevant to it."""
    if not LEAD_CHAT_ID:
        return
    for thread_id, rows in BUTTON_MAP.items():
        try:
            keyboard = ReplyKeyboardMarkup(rows, resize_keyboard=True)
            await app.send_message(
                chat_id=int(LEAD_CHAT_ID),
                text="Меню управления для этой ветки:",
                message_thread_id=thread_id,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning(f"Could not send control keyboard to thread {thread_id}: {e}")


async def main():
    await app.start()
    init_db()
    asyncio.create_task(followup_poller(app))
    asyncio.create_task(heartbeat_loop())
    asyncio.create_task(get_updates_loop())
    await send_thread_keyboards()
    logger.info("Bot is loaded and waiting for traffic...")
    await idle()
    await app.stop()


if __name__ == '__main__':
    asyncio.run(main())
