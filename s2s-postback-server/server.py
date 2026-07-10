import asyncio
import hmac
import html
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import aiohttp
from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("REDIRECT_BOT_TOKEN")
CHAT_ID = os.getenv("LEAD_CHAT_ID")
THREAD_ID = os.getenv("LEAD_THREAD_ID")
POSTBACK_SECRET = os.getenv("S2S_POSTBACK_SECRET")
DAILY_REPORT_HOUR_UTC = int(os.getenv("DAILY_REPORT_HOUR_UTC", "21"))

DATA_DIR = os.getenv("DATA_DIR", "data")
DB_FILE = os.path.join(DATA_DIR, "leads.db")

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


def init_db():
    """Initializes SQLite schema for persisting accepted leads/conversions."""
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            click_id TEXT,
            payout REAL,
            hold_payout REAL,
            is_charged INTEGER,
            country TEXT,
            os_sys TEXT,
            traffic_type TEXT,
            connection_type TEXT,
            carrier TEXT,
            created_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


def save_lead(click_id, payout_value, hold_payout_value, is_charged, country, os_sys, traffic_type, connection_type, carrier):
    """Persists an accepted postback so daily/weekly stats don't depend on scrolling Telegram."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leads (click_id, payout, hold_payout, is_charged, country, os_sys, traffic_type, connection_type, carrier, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (click_id, payout_value, hold_payout_value, int(is_charged), country, os_sys, traffic_type, connection_type, carrier, int(time.time())))
    conn.commit()
    conn.close()


def get_lead_stats_since(since_ts):
    """Aggregates lead count and revenue (charged vs. held) since a given unix timestamp."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN is_charged = 1 THEN payout ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN is_charged = 0 THEN hold_payout ELSE 0 END), 0)
        FROM leads
        WHERE created_at >= ?
    """, (since_ts,))
    count, charged_total, hold_total = c.fetchone()
    conn.close()
    return {"count": count, "charged_total": charged_total, "hold_total": hold_total}


def compute_next_run(now, target_hour):
    """Returns the next UTC datetime (>= now) at which the daily report should fire."""
    next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


def format_daily_report(stats):
    """Formats the aggregated lead stats into an HTML Telegram message."""
    return (
        f"📊 <b>Отчёт за сутки</b>\n\n"
        f"Лидов: <code>{stats['count']}</code>\n"
        f"Начислено: <code>${stats['charged_total']:.2f}</code>\n"
        f"В холде: <code>${stats['hold_total']:.2f}</code>"
    )


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


async def daily_report_loop():
    """Sleeps until DAILY_REPORT_HOUR_UTC each day, then posts a lead summary to
    Telegram. Fires every day regardless of lead count - doubles as a liveness signal."""
    logger.info(f"Daily report scheduled for {DAILY_REPORT_HOUR_UTC:02d}:00 UTC")
    while True:
        now = datetime.now(timezone.utc)
        next_run = compute_next_run(now, DAILY_REPORT_HOUR_UTC)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            since_ts = int(next_run.timestamp()) - 86400
            stats = await asyncio.to_thread(get_lead_stats_since, since_ts)
            await send_to_telegram(format_daily_report(stats))
            logger.info(f"Sent daily lead report: {stats}")
        except Exception as e:
            logger.error(f"Error building/sending daily report: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(daily_report_loop())
    yield


app = FastAPI(title="iMonetizeIt S2S Postback Receiver", lifespan=lifespan)


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
    hold_payout_value = safe_float(hold_payout)
    is_charged = payout_value > 0
    real_money = payout if is_charged else hold_payout
    status_icon = "🔥" if is_charged else "⏳"
    status_text = "НАЧИСЛЕНО" if is_charged else "В ХОЛДЕ"

    # Сохраняем лид до отправки в Telegram, чтобы статистика не зависела от
    # доступности Telegram API.
    await asyncio.to_thread(
        save_lead, click_id, payout_value, hold_payout_value, is_charged,
        country, os_sys, traffic_type, connection_type, carrier,
    )

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
