import asyncio
import os
from pyrogram import Client, filters
from pyrogram.types import Message
from core.config import API_ID, API_HASH, BOT_TOKEN, SOURCE_THREAD_ID, TARGET_THREAD_ID
from core.photo_processor import process_photo
from core.video_processor import process_video
from uploader import run_uploader

app = Client(
    "unique_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# limits the amount of simultaneous renders/uploads
semaphore = asyncio.Semaphore(3)
upload_semaphore = asyncio.Semaphore(2)

async def process_and_upload(client: Client, cmd_msg: Message, video_msg: Message, profile_id: str, caption: str):
    """Downloads, uniqueizes, and uploads the video in the background under semaphore limit."""
    async with upload_semaphore:
        input_path = ""
        output_path = ""
        status_msg = await cmd_msg.reply_text("⏳ <b>[TikTok Uploader]</b> Скачиваю и уникализирую видео...")
        
        try:
            os.makedirs("tmp_input", exist_ok=True)
            os.makedirs("tmp_output", exist_ok=True)
            
            # Download file
            input_path = await video_msg.download(file_name="tmp_input/")
            filename = os.path.basename(input_path)
            output_path = f"tmp_output/unique_{filename}"
            
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
            print(f"Error in upload flow: {e}")
            await status_msg.edit_text(f"❌ Ошибка при обработке: {e}")
        finally:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

@app.on_message(filters.command("upload"))
async def upload_handler(client: Client, message: Message):
    """Handles the /upload command (triggered directly or as reply)."""
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
        print("==== MESSAGE CAUGHT ====")
        print(f"Chat ID: {message.chat.id}")
        print(f"Thread ID: {message.message_thread_id}")
        if message.from_user:
            print(f"From user: {message.from_user.username}")
        print("---------------------------------")
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
        input_path = ""
        output_path = ""

        try:
            print("Starting file rendering...")

            # creating temporary directories
            os.makedirs("tmp_input", exist_ok=True)
            os.makedirs("tmp_output", exist_ok=True)

            # downloading file
            input_path = await message.download(file_name="tmp_input/")
            filename = os.path.basename(input_path)
            output_path = f"tmp_output/unique_{filename}"

            # routing
            if message.photo:
                output_path = f"tmp_output/{filename}.jpg"
                await asyncio.to_thread(process_photo, input_path, output_path)
            elif message.video:
                await process_video(input_path, output_path)

            # sending clear file
            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                reply_to_message_id=TARGET_THREAD_ID,
            )
            print("Successfully finished file rendering!!!")
        except Exception as e:
            print(f"Error while rendering file: {e}")
            await message.reply_text(f"Error while rendering file: {e}")

        finally:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

if __name__ == '__main__':
    print("BOT IS RUNNING! WAITING FOR MESSAGES...")
    app.run()