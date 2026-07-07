import os
import aiohttp
from fastapi import FastAPI, Query
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="iMonetizeIt S2S Postback Receiver")

BOT_TOKEN = os.getenv("REDIRECT_BOT_TOKEN")
CHAT_ID = os.getenv("LEAD_CHAT_ID")
THREAD_ID = os.getenv("LEAD_THREAD_ID")

if not all([BOT_TOKEN, CHAT_ID, THREAD_ID]):
    print("⚠️ ВНИМАНИЕ: Проверь, что REDIRECT_BOT_TOKEN, LEAD_CHAT_ID и LEAD_THREAD_ID заполнены в .env!")


async def send_to_telegram(text: str):
    """Асинхронная отправка сообщения в конкретную ветку Telegram-чата"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "message_thread_id": THREAD_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    err_info = await response.text()
                    print(f"❌ Ошибка от Telegram API: {err_info}")
        except Exception as e:
            print(f"❌ Системная ошибка при отправке в ТГ: {e}")


@app.get("/postback")
async def handle_postback(
        click_id: str = Query("Неизвестно", description="Telegram ID мамонта"),
        payout: str = Query("0.00", description="Выплата"),
        hold_payout: str = Query("0.00", description="Выплата в холде"),
        country: str = Query("N/A", description="Страна"),
        os_sys: str = Query("N/A", alias="os", description="ОС устройства"),
        traffic_type: str = Query("N/A", description="Тип трафика"),
        connection_type: str = Query("N/A", description="Тип соединения (Wi-Fi/Cellular)"),
        carrier: str = Query("N/A", description="Мобильный оператор")
):
    """Ловит GET-запрос от iMonetizeIt и пушит его в Telegram"""

    # Считаем итоговый чек (в зависимости от того, упали деньги сразу на баланс или в холд)
    real_money = payout if float(payout) > 0 else hold_payout
    status_icon = "🔥" if float(payout) > 0 else "⏳"
    status_text = "НАЧИСЛЕНО" if float(payout) > 0 else "В ХОЛДЕ"

    # Формируем сочную сводку для рабочего чата
    message = (
        f"{status_icon} <b>НОВАЯ КОНВЕРСИЯ [{status_text}]!</b>\n\n"
        f"💵 <b>Доход:</b> <code>${real_money}</code>\n"
        f"🌍 <b>Гео:</b> #{country}\n"
        f"📱 <b>Система:</b> {os_sys}\n"
        f"📡 <b>Связь:</b> {connection_type} ({carrier})\n"
        f"🎯 <b>Тип трафика:</b> {traffic_type}\n\n"
        f"👤 <b>TG ID лида:</b> <code>{click_id}</code>\n"
        f"👆 <i>(можно скопировать кликом для проверки базы)</i>"
    )

    await send_to_telegram(message)
    print(f"💰 Зафиксирован лид на ${real_money} (Гео: {country}, ID: {click_id})")

    # Партнерке обязательно нужно вернуть 200 OK, иначе она будет слать повторы
    return {"status": "success", "message": "Postback delivered"}


if __name__ == "__main__":
    import uvicorn

    print("🚀 S2S Сервер запущен на порту 8000...")
    uvicorn.run("s2s_server:app", host="0.0.0.0", port=8000, reload=True)