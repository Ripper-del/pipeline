import asyncio
import os
from pyrogram import Client, filters
from pyrogram.types import Message
from core.config import API_ID, API_HASH, BOT_TOKEN, SOURCE_THREAD_ID, TARGET_THREAD_ID
from core.photo_processor import process_photo
from core.video_processor import process_video

app = Client(
    "unique_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# limiting the amount of simultaneous renders
semaphore = asyncio.Semaphore(3)

@app.on_message()
async def main_handler(client: Client, message: Message):
    # listening mode
    if SOURCE_THREAD_ID == 0 or TARGET_THREAD_ID == 0:
        print("==== MESSAGE CAUGHT ====")
        print(f"Chat ID: {message.chat.id}")
        print(f"Thread ID: {message.message_thread_id}")
        if message.from_user:
            print(f"From user: {message.from_user.username}")
        print("---------------------------------")
        return

    # EPIC COMBAT MODE!!!!

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