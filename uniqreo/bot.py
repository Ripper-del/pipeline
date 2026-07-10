import asyncio
import logging
import os
import shutil
import tempfile
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from core.config import API_ID, API_HASH, BOT_TOKEN, SOURCE_THREAD_ID, TARGET_THREAD_ID, ADMIN_TELEGRAM_IDS
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
)

# limits the amount of simultaneous renders/uploads
semaphore = asyncio.Semaphore(3)
upload_semaphore = asyncio.Semaphore(2)

HEARTBEAT_FILE = os.getenv("HEARTBEAT_FILE", "/tmp/heartbeat")

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

async def process_and_upload(client: Client, cmd_msg: Message, video_msg: Message, profile_id: str, caption: str):
    """Downloads, uniqueizes, and uploads the video in the background under semaphore limit."""
    async with upload_semaphore:
        task_dir_in = ""
        task_dir_out = ""
        output_path = ""
        status_msg = await cmd_msg.reply_text("⏳ <b>[TikTok Uploader]</b> Скачиваю и уникализирую видео...")

        try:
            os.makedirs("tmp_input", exist_ok=True)
            os.makedirs("tmp_output", exist_ok=True)
            # Each task gets its own subdirectory so two concurrent uploads with the
            # same original filename can never clobber each other's file mid-render.
            task_dir_in = tempfile.mkdtemp(dir="tmp_input")
            task_dir_out = tempfile.mkdtemp(dir="tmp_output")

            # Download file
            input_path = await video_msg.download(file_name=f"{task_dir_in}/")
            filename = os.path.basename(input_path)
            output_path = f"{task_dir_out}/unique_{filename}"

            # Uniqueize video
            await process_video(input_path, output_path)
            await status_msg.edit_text("✅ Видео уникализировано. Начинаю запуск браузера и автозалив...")

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
                await status_msg.edit_text("🎉 Видео успешно опубликовано в TikTok!")
            else:
                await status_msg.edit_text("❌ Ошибка при автозаливе. Проверьте логи в Telegram-ветке.")

        except Exception as e:
            logger.error(f"Error in upload flow: {e}")
            await status_msg.edit_text(f"❌ Ошибка при обработке: {e}")
        finally:
            if task_dir_in:
                shutil.rmtree(task_dir_in, ignore_errors=True)
            if task_dir_out:
                shutil.rmtree(task_dir_out, ignore_errors=True)

@app.on_message(filters.command("upload"))
async def upload_handler(client: Client, message: Message):
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
    asyncio.create_task(process_and_upload(client, message, target_msg, profile_id, caption))

@app.on_message()
async def main_handler(client: Client, message: Message):
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

    # Skip commands
    if message.text and message.text.startswith("/"):
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
            input_path = await message.download(file_name=f"{task_dir_in}/")
            filename = os.path.basename(input_path)
            output_path = f"{task_dir_out}/unique_{filename}"

            # routing
            if message.photo:
                output_path = f"{task_dir_out}/{filename}.jpg"
                await asyncio.to_thread(process_photo, input_path, output_path)
            elif message.video:
                await process_video(input_path, output_path)

            # sending clear file
            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                reply_to_message_id=TARGET_THREAD_ID,
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

async def main():
    await app.start()
    asyncio.create_task(heartbeat_loop())
    logger.info("BOT IS RUNNING! WAITING FOR MESSAGES...")
    await idle()
    await app.stop()

if __name__ == '__main__':
    asyncio.run(main())
