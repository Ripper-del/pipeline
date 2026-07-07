import asyncio
import os
import random
import argparse
import sys
import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# Target Telegram logs thread
UPLOAD_THREAD_ID = os.getenv("UPLOAD_THREAD_ID")

async def send_telegram_notification(text):
    """Sends status log messages directly to specified Telegram upload thread."""
    bot_token = os.getenv("REDIRECT_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("LOG_CHAT_ID") or os.getenv("LEAD_CHAT_ID")
    if not bot_token or not chat_id or not UPLOAD_THREAD_ID:
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": int(UPLOAD_THREAD_ID),
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Failed to send Telegram log: {e}")

async def get_adspower_ws(api_url, profile_id):
    """Launches AdsPower profile and extracts Playwright WebSocket endpoint."""
    url = f"{api_url.rstrip('/')}/api/v1/browser/start?user_id={profile_id}"
    print(f"[*] Connecting to AdsPower profile via Local API: {url}")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=30)
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json.get("code") == 0:
                    ws_data = resp_json.get("data", {}).get("ws", {})
                    ws_url = ws_data.get("playwright") or ws_data.get("puppeteer")
                    if ws_url:
                        return ws_url
                    else:
                        raise Exception("WebSocket connection details missing in AdsPower API response.")
                else:
                    raise Exception(f"AdsPower returned error: {resp_json.get('msg')}")
            else:
                raise Exception(f"Failed HTTP response: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"[!] Error starting AdsPower browser: {e}")
            raise e

async def stop_adspower_profile(api_url, profile_id):
    """Stops the specified AdsPower browser profile."""
    url = f"{api_url.rstrip('/')}/api/v1/browser/stop?user_id={profile_id}"
    print(f"[*] Stopping AdsPower profile: {profile_id}")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=30)
            if resp.status_code == 200:
                print("[+] Profile closed successfully.")
            else:
                print(f"[!] AdsPower responded with status {resp.status_code}")
        except Exception as e:
            print(f"[!] Error stopping AdsPower profile: {e}")

async def human_type(page, locator, text):
    """Simulates realistic human typing with micro-delays, random typos, and backspace corrections."""
    await locator.click()
    
    # Clear any previous content
    await page.keyboard.press("Meta+A") # Command+A for Mac
    await page.keyboard.press("Control+A") # Ctrl+A for Windows
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.5)
    
    qwerty_layout = {
        'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'ersfxc', 'e': 'wsdr',
        'f': 'rtgvcd', 'g': 'tyhbvf', 'h': 'yujnbg', 'i': 'ujko', 'j': 'uikmnh',
        'k': 'ijlm', 'l': 'okp', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
        'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'wedxza', 't': 'rfgy',
        'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu', 'z': 'asx'
    }
    for char in text:
        if char.lower() in qwerty_layout and random.random() < 0.04:
            wrong_char = random.choice(qwerty_layout[char.lower()])
            if char.isupper():
                wrong_char = wrong_char.upper()
                
            await page.keyboard.type(wrong_char)
            await asyncio.sleep(random.uniform(0.1, 0.2))
            
            if random.random() < 0.15:
                extra_wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
                await page.keyboard.type(extra_wrong)
                await asyncio.sleep(random.uniform(0.1, 0.2))
                await asyncio.sleep(random.uniform(0.2, 0.35))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.08, 0.15))
                await page.keyboard.press("Backspace")
            else:
                await asyncio.sleep(random.uniform(0.2, 0.3))
                await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.1, 0.2))
            
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.05, 0.12))

async def check_captcha(page, profile_id):
    """Detects if a captcha challenge is displayed and blocks execution until resolved by operator."""
    captcha_selectors = [
        "iframe[src*='captcha']",
        "div.captcha_verify_container",
        ".secsdk-captcha-drag-wrapper",
        "#tiktok-verify-ele",
        "[class*='captcha']"
    ]
    
    captcha_found = False
    for sel in captcha_selectors:
        try:
            elem = page.locator(sel).first
            if await elem.is_visible(timeout=1000):
                captcha_found = True
                break
        except Exception:
            continue
            
    if captcha_found:
        msg = f"🚨 <b>[CAPTCHA ALERT]</b>\nНа профиле <code>{profile_id}</code> обнаружена капча!\nПожалуйста, решите её вручную в окне браузера."
        print(f"[!] Captcha detected on profile {profile_id}. Waiting for manual resolution...")
        await send_telegram_notification(msg)
        
        while True:
            await asyncio.sleep(4)
            still_has_captcha = False
            for sel in captcha_selectors:
                try:
                    elem = page.locator(sel).first
                    if await elem.is_visible(timeout=1000):
                        still_has_captcha = True
                        break
                except Exception:
                    continue
            if not still_has_captcha:
                break
                
        ok_msg = f"✅ <b>[CAPTCHA RESOLVED]</b>\nКапча на профиле <code>{profile_id}</code> успешно решена. Залив продолжается."
        print(f"[+] Captcha resolved. Resuming upload.")
        await send_telegram_notification(ok_msg)

async def run_uploader(video_path, profile_id, caption, api_url, headless):
    if not os.path.exists(video_path):
        err = f"❌ [!] Video file not found: {video_path}"
        print(err)
        await send_telegram_notification(err)
        sys.exit(1)
        
    print(f"[*] Starting TikTok Uploader. Video: '{video_path}', Profile: '{profile_id}'")
    await send_telegram_notification(f"🚀 <b>[TikTok Uploader]</b>\nЗапуск автозалива креатива.\nПрофиль: <code>{profile_id}</code>\nФайл: <code>{os.path.basename(video_path)}</code>")
    
    ws_endpoint = None
    try:
        ws_endpoint = await get_adspower_ws(api_url, profile_id)
    except Exception as e:
        err = f"❌ [!] Failed to start AdsPower profile: {e}"
        print(err)
        await send_telegram_notification(err)
        sys.exit(1)
        
    async with async_playwright() as p:
        print("[*] Connecting Playwright to AdsPower session...")
        browser = await p.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Navigate to TikTok Studio / Upload Center
        upload_url = "https://www.tiktok.com/tiktokstudio/upload?lang=en"
        print(f"[*] Navigating to: {upload_url}")
        try:
            await page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            await check_captcha(page, profile_id)
        except Exception as e:
            # Fallback to alternative upload URL
            fallback_url = "https://www.tiktok.com/creator-center/upload?lang=en"
            print(f"[!] Studio failed, attempting fallback URL: {fallback_url} (Error: {e})")
            try:
                await page.goto(fallback_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
                await check_captcha(page, profile_id)
            except Exception as fe:
                err = f"❌ [!] Failed to load TikTok upload pages: {fe}"
                print(err)
                await send_telegram_notification(err)
                await browser.close()
                await stop_adspower_profile(api_url, profile_id)
                sys.exit(1)
                
        # Resolve frame/page target (TikTok sometimes renders upload panel in an iframe)
        target = page
        iframe_elements = page.frame_locator("iframe").first
        try:
            # Wait for file inputs inside frames or main body
            file_input_page = page.locator('input[type="file"]')
            file_input_frame = iframe_elements.locator('input[type="file"]')
            
            if await file_input_frame.count() > 0:
                target = iframe_elements
                print("[*] File input located inside iframe.")
            elif await file_input_page.count() > 0:
                target = page
                print("[*] File input located on main page.")
            else:
                # Wait a bit longer
                await page.wait_for_timeout(5000)
                if await file_input_frame.count() > 0:
                    target = iframe_elements
                    print("[*] File input located inside iframe (delayed).")
                else:
                    target = page
                    print("[*] Using main page context.")
        except Exception:
            target = page
            
        try:
            print("[*] Uploading video file...")
            file_input = target.locator('input[type="file"]').first
            await file_input.set_input_files(video_path)
            await page.wait_for_timeout(3000)
            await send_telegram_notification("⏳ <b>[TikTok Uploader]</b> Видео выбрано. Идет загрузка на сервер...")
            
            # Wait for upload completion: Post button changes from disabled to enabled
            print("[*] Waiting for video upload to process...")
            post_btn_selector = "button:has-text('Post'), button:has-text('Опубликовать'), [data-e2e='post_button']"
            post_btn = target.locator(post_btn_selector).first
            
            await post_btn.wait_for(state="visible", timeout=180000) # wait up to 3 mins
            
            # Polling to check if Post button becomes enabled
            for wait_sec in range(90):
                if not await post_btn.is_disabled():
                    print("[+] Video uploaded and processed successfully.")
                    break
                await asyncio.sleep(2)
            else:
                print("[!] Warning: Upload timeout or video is still processing.")
                
            # Fill description/caption
            print(f"[*] Entering video description: '{caption}'")
            await send_telegram_notification("✍️ <b>[TikTok Uploader]</b> Видео загружено. Прописываю хэштеги и описание...")
            
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
                # Simulates typing description/hashtags naturally with human-like typos
                await human_type(page, desc_box, caption)
                await page.wait_for_timeout(2000)
            else:
                print("[!] Could not locate description box. Pressing Post anyway...")
                
            # Post the video
            await check_captcha(page, profile_id)
            print("[*] Clicking Post button...")
            await post_btn.click()
            await page.wait_for_timeout(5000)
            
            success_msg = f"🎉 <b>[TikTok Uploader]</b>\nВидео успешно опубликовано!\nПрофиль: <code>{profile_id}</code>\nТекст: <i>{caption}</i>"
            print("[*] Upload flow finished.")
            await send_telegram_notification(success_msg)
            
        except Exception as e:
            err = f"❌ [!] Error during upload automation: {e}"
            print(err)
            await send_telegram_notification(err)
        finally:
            await browser.close()
            await stop_adspower_profile(api_url, profile_id)

def main():
    parser = argparse.ArgumentParser(description="TikTok Video Auto-Uploader via AdsPower")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--profile-id", required=True, help="AdsPower profile ID")
    parser.add_argument("--caption", default="#dating #datingadvice", help="Video description / caption")
    parser.add_argument("--api-url", default="http://localhost:50325", help="AdsPower Local API url")
    parser.add_argument("--headless", action="store_true", help="Launch browser headless")
    
    args = parser.parse_args()
    
    asyncio.run(
        run_uploader(
            video_path=args.video,
            profile_id=args.profile_id,
            caption=args.caption,
            api_url=args.api_url,
            headless=args.headless
        )
    )

if __name__ == "__main__":
    main()
