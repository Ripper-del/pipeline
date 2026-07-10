import logging
import httpx

logger = logging.getLogger(__name__)


async def send_telegram_message(bot_token, chat_id, text, thread_id=None, timeout=10):
    """Sends an HTML-formatted status message to a Telegram chat, optionally routed
    into a specific forum topic/thread. Silently no-ops if bot_token or chat_id is missing."""
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if thread_id:
        try:
            payload["message_thread_id"] = int(thread_id)
        except (TypeError, ValueError):
            logger.warning(f"Ignoring non-numeric Telegram thread id: {thread_id!r}")

    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=timeout)
    except Exception as e:
        logger.error(f"Failed to send Telegram log: {e}")
