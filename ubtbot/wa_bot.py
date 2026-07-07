import asyncio
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

GREEN_API_URL = os.getenv("GREEN_API_URL", "https://api.green-api.com").rstrip("/")
ID_INSTANCE = os.getenv("GREEN_API_ID_INSTANCE")
API_TOKEN = os.getenv("GREEN_API_TOKEN_INSTANCE")
BASE_SMARTLINK = os.getenv("SMARTLINK_URL")

if not all([ID_INSTANCE, API_TOKEN, BASE_SMARTLINK]):
    raise ValueError("ERROR: GREEN_API_ID_INSTANCE, GREEN_API_TOKEN_INSTANCE, and SMARTLINK_URL must be set in .env")

active_funnels = set()

async def send_whatsapp_message(session: aiohttp.ClientSession, chat_id: str, text: str) -> bool:
    """Send a message to a specific WhatsApp chat using Green API's sendMessage endpoint."""
    url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    try:
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                return True
            else:
                err_text = await response.text()
                print(f"❌ Green-API Error ({response.status}) when sending to {chat_id}: {err_text}")
                return False
    except Exception as e:
        print(f"❌ HTTP request exception when sending to {chat_id}: {e}")
        return False

async def schedule_followups(session: aiohttp.ClientSession, chat_id: str, personal_link: str):
    """Wait 24 and 48 hours to send nudge messages to the user if they haven't completed conversion."""
    wa_id = chat_id.split("@")[0]
    try:
        # First follow-up after 24 hours (86400 seconds)
        await asyncio.sleep(86400)
        
        text_24h = (
            f"Hey! Are you still there? My private video is waiting for you... 💋\n\n"
            f"Register quickly to see it now before it's gone!\n\n"
            f"▶️ WATCH NOW: {personal_link}"
        )
        print(f"⌛ [24H] Attempting to send first follow-up to {wa_id}...")
        await send_whatsapp_message(session, chat_id, text_24h)

        # Second follow-up after another 24 hours (total 48 hours)
        await asyncio.sleep(86400)
        
        text_48h = (
            f"Last chance! 😈 I'm deleting my profile soon...\n\n"
            f"Don't miss out, click the link below:\n\n"
            f"▶️ UNLOCK FULL VIDEO: {personal_link}"
        )
        print(f"⌛ [48H] Attempting to send second follow-up to {wa_id}...")
        await send_whatsapp_message(session, chat_id, text_48h)
        
    except asyncio.CancelledError:
        print(f"ℹ️ Follow-up funnel for {wa_id} was cancelled.")
    except Exception as e:
        print(f"⚠️ Error in follow-up funnel for {wa_id}: {e}")
    finally:
        active_funnels.discard(wa_id)
        print(f"✅ Follow-up funnel completed for {wa_id}")

async def handle_notification(session: aiohttp.ClientSession, notification: dict):
    """Processes incoming Webhook notification from Green API."""
    body = notification.get("body", {})
    type_webhook = body.get("typeWebhook")
    
    if type_webhook != "incomingMessageReceived":
        return
        
    sender_data = body.get("senderData", {})
    chat_id = sender_data.get("chatId")  # e.g., 79999999999@c.us
    
    if not chat_id or not chat_id.endswith("@c.us"):
        return  # Only respond to private chats, ignore groups/broadcasts
        
    wa_id = chat_id.split("@")[0]
    personal_link = f"{BASE_SMARTLINK}{wa_id}"
    
    welcome_text = (
        "🤫 The video you're looking for is inside...\n\n"
        "To bypass age restrictions and watch the full uncensored version, "
        "verify your age by creating a quick free account via the link below. 🔞\n\n"
        f"▶️ WATCH NOW: {personal_link}"
    )
    
    print(f"🚀 User {wa_id} initiated contact. Generating link: {personal_link}")
    
    success = await send_whatsapp_message(session, chat_id, welcome_text)
    if success:
        if wa_id not in active_funnels:
            active_funnels.add(wa_id)
            asyncio.create_task(schedule_followups(session, chat_id, personal_link))

async def main():
    print("🤖 WhatsApp Redirect Bot is loading...")
    
    async with aiohttp.ClientSession() as session:
        receive_url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/receiveNotification/{API_TOKEN}?receiveTimeout=20"
        
        print("🤖 WhatsApp Bot is running and waiting for traffic...")
        
        while True:
            try:
                async with session.get(receive_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data:
                            receipt_id = data.get("receiptId")
                            if receipt_id:
                                try:
                                    await handle_notification(session, data)
                                except Exception as e:
                                    print(f"⚠️ Error handling notification: {e}")
                                finally:
                                    # Always delete notification from the queue after processing
                                    delete_url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/deleteNotification/{API_TOKEN}/{receipt_id}"
                                    async with session.delete(delete_url) as del_resp:
                                        if del_resp.status != 200:
                                            del_txt = await del_resp.text()
                                            print(f"⚠️ Failed to delete notification {receipt_id}: {del_txt}")
                    else:
                        err_txt = await response.text()
                        print(f"⚠️ Error receiving notification ({response.status}): {err_txt}")
                        await asyncio.sleep(5)
            except asyncio.CancelledError:
                print("🛑 Bot is stopping...")
                break
            except Exception as e:
                print(f"⚠️ Connection error or exception: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 WhatsApp Bot stopped by user.")
