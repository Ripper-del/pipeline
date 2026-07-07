import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
from dotenv import load_dotenv
from pyrogram import Client, filters
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

active_funnels = set()

async def schedule_followups(client: Client, chat_id: int, personal_link: str):
    """Функция  для повторной отправки сообщений через 24 и 48 часов соответсвенно"""

    await asyncio.sleep(86400)

    try:
        await client.send_message(
            chat_id=chat_id,
            text=("Hey! Are you still there? My private video is waiting for you... 💋\n\n"
                "Register quickly to see it now before it's gone!"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ WATCH NOW", url=personal_link)]
            ]),
            disable_web_page_preview=True
        )
        print(f"📩 [24H] Отправлен первый дожим юзеру {chat_id}")
    except UserIsBlocked:
        print(f"⚠️ [24H] Юзер {chat_id} заблокировал бота. Отмена дальнейшего дожима.")
        return  # Прерываем функцию, чтобы не ждать еще день ради заблокировавшего юзера

    except Exception as e:
        print(f"⚠️ [24H] Ошибка отправки юзеру {chat_id}: {e}")

    await asyncio.sleep(86400)

    try:
        await client.send_message(
            chat_id=chat_id,
            text=(
                "Last chance! 😈 I'm deleting my profile soon...\n\n"
                "Don't miss out, tap the button below:"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ UNLOCK FULL VIDEO", url=personal_link)]
            ]),
            disable_web_page_preview=True
        )
        print(f"📩 [48H] Отправлен второй дожим юзеру {chat_id}")
    except UserIsBlocked:
        print(f"⚠️ [48H] Юзер {chat_id} заблокировал бота. Отмена дальнейшего дожима.")
        return
    except Exception as e:
        print(f"⚠️ [48H] Ошибка отправки юзеру {chat_id}: {e}")

    active_funnels.discard(chat_id)
    print(f"✅ Воронка дожима для {chat_id} полностью завершена.")


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
    if tg_id not in active_funnels:
        active_funnels.add(tg_id)
        asyncio.create_task(schedule_followups(client, message.chat.id, personal_link))


if __name__ == "__main__":
    print("🤖 Bot is loaded and waiting for traffic...")
    app.run()