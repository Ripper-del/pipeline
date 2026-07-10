import hmac
import html
import logging
import os
import aiohttp
from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="iMonetizeIt S2S Postback Receiver")

BOT_TOKEN = os.getenv("REDIRECT_BOT_TOKEN")
CHAT_ID = os.getenv("LEAD_CHAT_ID")
THREAD_ID = os.getenv("LEAD_THREAD_ID")
POSTBACK_SECRET = os.getenv("S2S_POSTBACK_SECRET")

if not all([BOT_TOKEN, CHAT_ID, THREAD_ID]):
    logger.warning("Проверь, что REDIRECT_BOT_TOKEN, LEAD_CHAT_ID и LEAD_THREAD_ID заполнены в .env!")
if not POSTBACK_SECRET:
    logger.warning("S2S_POSTBACK_SECRET не задан - /postback будет отклонять ВСЕ запросы (fail closed).")


def safe_float(value, default=0.0):
    """Parses partner-supplied numeric strings without ever raising - malformed
    postback data must not crash the endpoint (partner needs a 200 OK, or it retries)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def send_to_telegram(text: str):
    """Асинхронная отправка сообщения в конкретную ветку Telegram-чата"""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Пропускаю отправку в Telegram: REDIRECT_BOT_TOKEN или LEAD_CHAT_ID не заданы.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if THREAD_ID:
        try:
            payload["message_thread_id"] = int(THREAD_ID)
        except ValueError:
            logger.warning(f"LEAD_THREAD_ID не является числом ({THREAD_ID!r}), отправляю без привязки к ветке.")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    err_info = await response.text()
                    logger.error(f"Ошибка от Telegram API: {err_info}")
        except Exception as e:
            logger.error(f"Системная ошибка при отправке в ТГ: {e}")


@app.get("/health")
async def health():
    """Liveness probe for Docker healthcheck - no side effects, never touches Telegram."""
    return {"status": "ok"}


@app.get("/postback")
async def handle_postback(
        secret: str = Query("", description="Общий секрет для подтверждения подлинности постбэка"),
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

    # Без корректного secret запрос не может быть подтверждён как пришедший от
    # партнёрки - отклоняем, не давая заспамить канал лидов фейковыми конверсиями.
    if not POSTBACK_SECRET or not hmac.compare_digest(secret, POSTBACK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid or missing secret")

    # Считаем итоговый чек (в зависимости от того, упали деньги сразу на баланс или в холд)
    payout_value = safe_float(payout)
    real_money = payout if payout_value > 0 else hold_payout
    status_icon = "🔥" if payout_value > 0 else "⏳"
    status_text = "НАЧИСЛЕНО" if payout_value > 0 else "В ХОЛДЕ"

    # Формируем сочную сводку для рабочего чата (партнёрские поля экранируем -
    # это внешний ввод, и без экранирования один "<" сломает HTML-парсинг у Telegram)
    message = (
        f"{status_icon} <b>НОВАЯ КОНВЕРСИЯ [{status_text}]!</b>\n\n"
        f"💵 <b>Доход:</b> <code>${html.escape(str(real_money))}</code>\n"
        f"🌍 <b>Гео:</b> #{html.escape(country)}\n"
        f"📱 <b>Система:</b> {html.escape(os_sys)}\n"
        f"📡 <b>Связь:</b> {html.escape(connection_type)} ({html.escape(carrier)})\n"
        f"🎯 <b>Тип трафика:</b> {html.escape(traffic_type)}\n\n"
        f"👤 <b>TG ID лида:</b> <code>{html.escape(click_id)}</code>\n"
        f"👆 <i>(можно скопировать кликом для проверки базы)</i>"
    )

    await send_to_telegram(message)
    logger.info(f"Зафиксирован лид на ${real_money} (Гео: {country}, ID: {click_id})")

    # Партнерке обязательно нужно вернуть 200 OK, иначе она будет слать повторы
    return {"status": "success", "message": "Postback delivered"}


if __name__ == "__main__":
    import uvicorn

    logger.info("S2S Сервер запущен на порту 8000...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
