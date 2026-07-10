import asyncio
import logging
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from common.adspower import get_adspower_ws, stop_adspower_profile
from common.captcha import wait_for_captcha_resolution
from common.human_input import clear_and_type
from common.telegram_notify import send_telegram_message

logger = logging.getLogger(__name__)

load_dotenv()

# Target Telegram logs thread
UPLOAD_THREAD_ID = os.getenv("UPLOAD_THREAD_ID")

async def send_telegram_notification(text):
    """Sends status log messages directly to specified Telegram upload thread."""
    bot_token = os.getenv("REDIRECT_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("LOG_CHAT_ID") or os.getenv("LEAD_CHAT_ID")
    await send_telegram_message(bot_token, chat_id, text, UPLOAD_THREAD_ID)

async def check_captcha(page, profile_id):
    """Detects if a captcha challenge is displayed and blocks execution until resolved by operator."""
    async def alert():
        msg = f"🚨 <b>[CAPTCHA ALERT]</b>\nНа профиле <code>{profile_id}</code> обнаружена капча!\nПожалуйста, решите её вручную в окне браузера."
        logger.warning(f"Captcha detected on profile {profile_id}. Waiting for manual resolution...")
        await send_telegram_notification(msg)

    async def resolved():
        ok_msg = f"✅ <b>[CAPTCHA RESOLVED]</b>\nКапча на профиле <code>{profile_id}</code> успешно решена. Залив продолжается."
        logger.info("Captcha resolved. Resuming upload.")
        await send_telegram_notification(ok_msg)

    await wait_for_captcha_resolution(page, on_detected=alert, on_resolved=resolved)

async def run_uploader(video_path, profile_id, caption, api_url, headless):
    if not os.path.exists(video_path):
        err = f"Video file not found: {video_path}"
        logger.error(err)
        await send_telegram_notification(f"❌ [!] {err}")
        return False

    logger.info(f"Starting TikTok Uploader. Video: '{video_path}', Profile: '{profile_id}'")
    await send_telegram_notification(f"🚀 <b>[TikTok Uploader]</b>\nЗапуск автозалива креатива.\nПрофиль: <code>{profile_id}</code>\nФайл: <code>{os.path.basename(video_path)}</code>")

    ws_endpoint = None
    try:
        ws_endpoint = await get_adspower_ws(api_url, profile_id)
    except Exception as e:
        err = f"Failed to start AdsPower profile: {e}"
        logger.error(err)
        await send_telegram_notification(f"❌ [!] {err}")
        return False

    async with async_playwright() as p:
        logger.info("Connecting Playwright to AdsPower session...")
        browser = await p.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to TikTok Studio / Upload Center
        upload_url = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
        logger.info(f"Navigating to: {upload_url}")
        try:
            await page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            await check_captcha(page, profile_id)
        except Exception as e:
            fallback_url = "https://www.tiktok.com/creator-center/upload?lang=en"
            logger.warning(f"Studio failed, attempting fallback: {fallback_url} (Error: {e})")
            try:
                await page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                await check_captcha(page, profile_id)
            except Exception as fe:
                err = f"Failed to load TikTok upload pages: {fe}"
                logger.error(err)
                await send_telegram_notification(f"❌ [!] {err}")
                await browser.close()
                await stop_adspower_profile(api_url, profile_id)
                return False

        # Resolve frame/page target
        target = page
        iframe_elements = page.frame_locator("iframe").first
        try:
            file_input_page = page.locator('input[type="file"]')
            file_input_frame = iframe_elements.locator('input[type="file"]')

            if await file_input_frame.count() > 0:
                target = iframe_elements
                logger.info("File input located inside iframe.")
            elif await file_input_page.count() > 0:
                target = page
                logger.info("File input located on main page.")
            else:
                await page.wait_for_timeout(5000)
                if await file_input_frame.count() > 0:
                    target = iframe_elements
                    logger.info("File input located inside iframe (delayed).")
                else:
                    target = page
                    logger.info("Using main page context.")
        except Exception:
            target = page

        try:
            logger.info("Uploading video file...")
            file_input = target.locator('input[type="file"]').first
            await file_input.set_input_files(video_path)
            await page.wait_for_timeout(3000)
            await send_telegram_notification("⏳ <b>[TikTok Uploader]</b> Видео выбрано. Идет загрузка на сервер...")

            # Wait for upload completion: Post button changes from disabled to enabled
            logger.info("Waiting for video upload to process...")
            post_btn_selector = "button:has-text('Post'), button:has-text('Опубликовать'), [data-e2e='post_button']"
            post_btn = target.locator(post_btn_selector).first

            await post_btn.wait_for(state="visible", timeout=180000)

            for wait_sec in range(90):
                if not await post_btn.is_disabled():
                    logger.info("Video uploaded and processed successfully.")
                    break
                await asyncio.sleep(2)
            else:
                logger.warning("Upload timeout or video is still processing.")

            # Fill description/caption
            logger.info(f"Entering video description: '{caption}'")
            await send_telegram_notification("✍️ <b>[TikTok Uploader]</b> Видео загружено. Прописываю хэштеги...")

            desc_selectors = [
                "[data-e2e='post-textbox']",
                "div[contenteditable='true']",
                "div.public-DraftEditor-content",
                "textarea"
            ]
            desc_box = None
            for sel in desc_selectors:
                try:
                    box = target.locator(sel).first
                    if await box.is_visible(timeout=3000):
                        desc_box = box
                        break
                except Exception:
                    continue

            if desc_box:
                await clear_and_type(page, desc_box, caption)
                await page.wait_for_timeout(2000)
            else:
                logger.warning("Could not locate description box.")

            # Post the video
            await check_captcha(page, profile_id)
            logger.info("Clicking Post button...")
            await post_btn.click()
            await page.wait_for_timeout(5000)

            success_msg = f"🎉 <b>[TikTok Uploader]</b>\nВидео успешно опубликовано!\nПрофиль: <code>{profile_id}</code>\nТекст: <i>{caption}</i>"
            logger.info("Upload flow finished.")
            await send_telegram_notification(success_msg)
            return True

        except Exception as e:
            err = f"Error during upload automation: {e}"
            logger.error(err)
            await send_telegram_notification(f"❌ [!] {err}")
            return False
        finally:
            await browser.close()
            await stop_adspower_profile(api_url, profile_id)
