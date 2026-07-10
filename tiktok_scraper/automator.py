import asyncio
import logging
import os
import random
import math
import argparse
import sys
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from common.adspower import get_adspower_ws, stop_adspower_profile
from common.captcha import wait_for_captcha_resolution
from common.human_input import type_like_human
from common.telegram_notify import send_telegram_message

logger = logging.getLogger(__name__)

load_dotenv()

# Database of 15 Popular GEOs and Languages for Adult Dating Warmup/Spy
GEO_DATABASE = {
    "US": {
        "lang": "en",
        "queries": ["dating advice", "relationship tips", "single life", "meet singles", "dating apps", "adult dating humor"],
        "comments": ["so true lol", "this is literally me", "need this in my life tbh", "accurate", "why is this so real", "lmao", "facts"]
    },
    "UK": {
        "lang": "en",
        "queries": ["uk dating", "london singles", "relationship advice", "single life uk", "dating apps uk"],
        "comments": ["spot on mate", "actually so true", "need this", "lmao", "too real", "bloody accurate", "haha love this"]
    },
    "DE": {
        "lang": "de",
        "queries": ["dating tipps", "beziehung ratschlag", "singles deutschland", "flirten lernen", "dating app erfahrung"],
        "comments": ["so wahr haha", "das bin ich", "brauche das jetzt", "zu real", "stimmt vollkommen", "echt so", "auf jeden fall"]
    },
    "FR": {
        "lang": "fr",
        "queries": ["conseils couple", "relation amoureuse", "celibataire paris", "rencontre amoureuse", "drague technique"],
        "comments": ["tellement vrai haha", "c'est trop moi", "j'adore", "c'est exactement ça", "wow c'est tellement réel", "ptdr", "incroyable"]
    },
    "ES": {
        "lang": "es",
        "queries": ["consejos de pareja", "relaciones amorosas", "solteras en españa", "como ligar", "citas divertidas"],
        "comments": ["jaja tan real", "literalmente yo", "necesito esto en mi vida", "muy cierto", "por qué es tan real esto?", "jajaja", "tal cual"]
    },
    "IT": {
        "lang": "it",
        "queries": ["consigli coppia", "relazioni sentimentali", "single italia", "come rimorchiare", "incontri online"],
        "comments": ["troppo vero haha", "sono letteralmente io", "ne ho bisogno nella mia vita", "accurato", "perché è così reale?", "ahahah", "esatto"]
    },
    "BR": {
        "lang": "pt",
        "queries": ["conselhos de namoro", "relacionamentos", "solteiras brasil", "como paquerar", "aplicativos de namoro"],
        "comments": ["muito verdade kkkk", "eu todinha", "preciso disso pra ontem", "super real", "por que isso é tão verdade?", "kkkkk", "fato"]
    },
    "NL": {
        "lang": "nl",
        "queries": ["dating tips", "relatie advies", "singles nederland", "flirten tips", "datingapps nl"],
        "comments": ["zo waar haha", "dit ben ik", "heb dit nodig", "cliché maar waar", "waarom is dit zo herkenbaar?", "lmao", "klopt helemaal"]
    },
    "PL": {
        "lang": "pl",
        "queries": ["porady randkowe", "związki miłosne", "single polska", "jak flirtować", "aplikacje randkowe"],
        "comments": ["takie prawdziwe haha", "to dosłownie ja", "potrzebuję tego w życiu", "mega randka", "dlaczego to jest tak prawdziwe?", "hahaha", "dokładnie"]
    },
    "TR": {
        "lang": "tr",
        "queries": ["ilişki tavsiyeleri", "flört taktikleri", "sevgili bulma", "yalnızlık komik", "dating uygulamaları"],
        "comments": ["çok doğru ya haha", "aynen ben", "buna ihtiyacım var", "çok gerçekçi", "neden bu kadar doğru?", "asdfghjk", "gerçekler"]
    },
    "RO": {
        "lang": "ro",
        "queries": ["sfaturi relatii", "cupluri amuzante", "single romania", "cum sa agati", "aplicatii de dating"],
        "comments": ["atat de adevarat haha", "asta sunt eu", "am nevoie de asta in viata mea", "foarte corect", "de ce e atat de real?", "lmao", "exact"]
    },
    "JP": {
        "lang": "ja",
        "queries": ["恋愛アドバイス", "カップルの日常", "マッチングアプリあるある", "出会い系", "モテる方法"],
        "comments": ["本当にそれな笑", "私すぎて草", "これ欲しいやつだ", "的確すぎる", "なんでこんなにリアルなの？", "ウケる", "それ"]
    },
    "KR": {
        "lang": "ko",
        "queries": ["연애 조언", "커플 일상", "소개팅 꿀팁", "데이팅 앱 후기", "썸 타는 법"],
        "comments": ["진짜 인정 ㅋㅋㅋ", "완전 내 얘기네", "내 인생에 이게 필요해", "핵공감", "왜 이렇게 현실적임?", "ㅋㅋㅋ", "맞말"]
    },
    "VN": {
        "lang": "vi",
        "queries": ["tư vấn tình yêu", "hẹn hò hài hước", "độc thân vui vẻ", "cách tán gái", "ứng dụng hẹn hò"],
        "comments": ["thật sự luôn haha", "chuẩn mình luôn", "cần cái này lắm nha", "quá đúng", "sao lại chân thực thế nhỉ?", "kaka", "chính xác"]
    },
    "CA": {
        "lang": "en",
        "queries": ["canada dating", "toronto singles", "relationship advice", "dating apps canada", "single life canada"],
        "comments": ["so true eh", "actually so accurate", "need this tbh", "lmao too real", "why is this so true", "haha love it", "facts"]
    }
}

async def math_scroll(page, offset, steps=25, duration=1.5):
    """Human-like scroll simulation using a cubic bezier transition and hand jitter (sine wave)."""
    step_delay = duration / steps
    
    def ease_in_out(t):
        # Cubic spline ease-in-out
        return 3 * t**2 - 2 * t**3
        
    accumulated_scroll = 0
    for i in range(1, steps + 1):
        t = i / steps
        target_step_offset = offset * ease_in_out(t)
        delta = target_step_offset - accumulated_scroll
        
        # Add random sine-wave jitter (tremor)
        jitter = math.sin(t * math.pi * 3) * random.uniform(-1.5, 1.5)
        actual_delta = delta + jitter
        
        # Perform scroll offset wheel event
        await page.mouse.wheel(0, actual_delta)
        accumulated_scroll += delta
        
        await asyncio.sleep(step_delay * random.uniform(0.85, 1.15))

async def like_video(page):
    """Attempts to click like button using various potential selectors."""
    selectors = [
        "[data-e2e='like-icon']",
        "[data-e2e='browse-like']",
        "button:has-text('Like')",
        "button[aria-label*='Like']"
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info("Liked video.")
                return True
        except Exception:
            continue
    logger.warning("Could not locate like button.")
    return False

async def post_comment(page, text):
    """Enters comment text using human typing simulation and publishes it to the post."""
    input_selectors = [
        "[data-e2e='comment-input']",
        "div[contenteditable='true']",
        "[placeholder*='comment']",
        "[placeholder*='коммент']"
    ]
    input_found = False
    for sel in input_selectors:
        try:
            comment_box = page.locator(sel).first
            if await comment_box.is_visible(timeout=3000):
                await comment_box.click()
                # Run the realistic human typing simulation
                await type_like_human(page, text)
                input_found = True
                break
        except Exception:
            continue
            
    if not input_found:
        logger.warning("Could not find comment input box.")
        return False

    # Find publish button
    publish_selectors = [
        "[data-e2e='comment-post']",
        "button:has-text('Post')",
        "button:has-text('Опубликовать')"
    ]
    for sel in publish_selectors:
        try:
            pub_btn = page.locator(sel).first
            if await pub_btn.is_visible(timeout=2000):
                await pub_btn.click()
                logger.info(f"Posted comment: '{text}'")
                return True
        except Exception:
            continue

    # Try pressing Enter as a fallback
    await page.keyboard.press("Enter")
    logger.info(f"Posted comment via Enter key: '{text}'")
    return True

async def get_video_description(page):
    """Retrieves video description from DOM."""
    selectors = [
        "[data-e2e='browse-video-desc']",
        "h1[data-e2e='video-desc']",
        ".video-desc"
    ]
    for sel in selectors:
        try:
            elem = page.locator(sel).first
            if await elem.is_visible(timeout=2000):
                return await elem.inner_text()
        except Exception:
            continue
    return ""

async def send_telegram_notification(text, thread_id):
    """Sends status log messages directly to specified Telegram threads."""
    if not thread_id:
        return
    bot_token = os.getenv("REDIRECT_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    chat_id = os.getenv("LOG_CHAT_ID") or os.getenv("LEAD_CHAT_ID")
    await send_telegram_message(bot_token, chat_id, text, thread_id)

async def check_captcha(page, profile_id, thread_id):
    """Detects if a captcha challenge is displayed and blocks execution until resolved by operator."""
    async def alert():
        msg = f"🚨 <b>[CAPTCHA ALERT]</b>\nНа профиле <code>{profile_id}</code> обнаружена капча!\nПожалуйста, решите её вручную в окне браузера."
        logger.warning(f"Captcha detected on profile {profile_id}. Waiting for manual resolution...")
        if thread_id:
            await send_telegram_notification(msg, thread_id)

    async def resolved():
        ok_msg = f"✅ <b>[CAPTCHA RESOLVED]</b>\nКапча на профиле <code>{profile_id}</code> успешно решена. Бот продолжает работу."
        logger.info("Captcha resolved. Resuming automation.")
        if thread_id:
            await send_telegram_notification(ok_msg, thread_id)

    await wait_for_captcha_resolution(page, on_detected=alert, on_resolved=resolved)

async def run_automation(mode, profile_id, geo, limit, api_url, headless):
    geo_data = GEO_DATABASE.get(geo)
    if not geo_data:
        logger.error(f"Invalid GEO: {geo}")
        sys.exit(1)

    # Resolve target thread for logs
    thread_id = os.getenv("WARMUP_THREAD_ID") if mode == "warmup" else os.getenv("SPY_THREAD_ID")

    log_text = f"🤖 <b>[TikTok Automator]</b>\nЗапущен режим: <code>{mode}</code>\nГЕО: <code>{geo}</code>\nПрофиль AdsPower: <code>{profile_id or 'Local'}</code>"
    logger.info(f"Starting automator in '{mode}' mode. GEO: '{geo}' (Lang: '{geo_data['lang']}')")
    if thread_id:
        await send_telegram_notification(log_text, thread_id)

    ws_endpoint = None
    if profile_id:
        try:
            ws_endpoint = await get_adspower_ws(api_url, profile_id)
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            sys.exit(1)
            
    async with async_playwright() as p:
        if ws_endpoint:
            logger.info("Connecting Playwright to AdsPower antidetect browser session...")
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            # Fetch active context
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            logger.info("Launching standard Playwright Chromium (AdsPower ID not provided)...")
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

        logger.info("Browser initialized. Navigating to TikTok...")
        matching_count = 0
        processed_videos = 0

        # Entire automation body runs under try/finally so an unexpected exception
        # (e.g. a Playwright "Target closed" error) never leaks the browser process
        # or leaves the AdsPower profile running in the background.
        try:
            try:
                await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
            except Exception as e:
                logger.error(f"Error loading TikTok: {e}")
                sys.exit(1)

            # Loop through search queries or FYP
            for query in geo_data["queries"]:
                if processed_videos >= limit:
                    break

                logger.info(f"Querying search for warm-up keyword: '{query}'")
                search_url = f"https://www.tiktok.com/search?q={query}"
                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)
                    await check_captcha(page, profile_id, thread_id)
                except Exception as e:
                    logger.warning(f"Error querying keyword '{query}': {e}")
                    continue

                # Loop for scrolling and interacting inside this keyword search
                for scroll_round in range(5):
                    if processed_videos >= limit:
                        break

                    await check_captcha(page, profile_id, thread_id)
                    # Ease-in-out math scroll to load contents
                    logger.info(f"Simulating human scrolling (round {scroll_round + 1}/5)...")
                    await math_scroll(page, offset=random.randint(600, 1000), duration=random.uniform(1.2, 2.0))
                    await page.wait_for_timeout(2000)

                    # Fetch visible video cards
                    video_elements = page.locator("a[href*='/video/']")
                    count = await video_elements.count()
                    if count == 0:
                        continue

                    # Pick a random visible video card to click and inspect
                    target_idx = random.randint(0, min(count - 1, 3))
                    video_elem = video_elements.nth(target_idx)

                    video_url = await video_elem.get_attribute("href")
                    if not video_url:
                        continue

                    logger.info(f"Inspecting video: {video_url}")
                    try:
                        await video_elem.click()
                        await page.wait_for_timeout(3000) # wait for overlay

                        # Fetch description
                        desc = await get_video_description(page)
                        logger.info(f"Description: '{desc}'")

                        # Determine relevance (dating / adult related keywords)
                        dating_kws = ["dating", "relationship", "single", "girlfriend", "boyfriend", "sevgili", "flört", "citas", "rencontre", "couple", "namoro", "出会い", "소개팅", "hẹn hò"]
                        is_relevant = any(kw in desc.lower() for kw in dating_kws) or any(kw in query.lower() for kw in dating_kws)

                        if is_relevant:
                            matching_count += 1
                            logger.info(f"Video identified as relevant ({matching_count} total).")
                            if thread_id:
                                await send_telegram_notification(f"🎯 <b>Найдено целевое видео:</b> {video_url}\n📝 Описание: {desc[:150]}...", thread_id)

                            # Human-like watch simulation (retention warm-up)
                            watch_time = random.randint(6, 15)
                            logger.info(f"Simulating retention: watching for {watch_time} seconds...")
                            await page.wait_for_timeout(watch_time * 1000)

                            # Decide interaction based on mode
                            should_interact = False
                            if mode == "warmup":
                                # Warmup interacts with all matching videos to tune recommendation feed
                                should_interact = True
                            elif mode == "spy":
                                # Spy mode likes/comments on every 5th matching video
                                should_interact = (matching_count % 5 == 0)
                                if should_interact:
                                    logger.info(f"Spy Trigger! Match count is {matching_count} (every 5th video).")

                            if should_interact:
                                await check_captcha(page, profile_id, thread_id)
                                # 1. Like
                                liked = await like_video(page)
                                await page.wait_for_timeout(random.randint(1000, 2000))

                                # 2. Comment
                                comment_text = random.choice(geo_data["comments"])
                                commented = await post_comment(page, comment_text)
                                await page.wait_for_timeout(random.randint(2000, 4000))

                                if thread_id:
                                    interaction_status = f"✅ <b>Взаимодействие:</b> {video_url}\n👀 Удержание: {watch_time} сек\n❤️ Лайк: {'ок' if liked else 'не найден'}\n💬 Коммент: \"{comment_text}\""
                                    await send_telegram_notification(interaction_status, thread_id)

                        else:
                            logger.info("Video is not relevant. Skipping.")

                        processed_videos += 1

                        # Close video overlay (usually by pressing Escape key or clicking close button)
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(2000)

                    except Exception as e:
                        logger.warning(f"Error during video interaction: {e}")
                        # Ensure overlay is closed
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(2000)

            logger.info("Automation run finished.")
            if thread_id:
                await send_telegram_notification(f"⏹️ <b>Автоматизация завершена.</b>\nРежим: <code>{mode}</code>\nОбработано видео: <code>{processed_videos}</code>\nЦелевых совпадений: <code>{matching_count}</code>", thread_id)
        finally:
            # Always release the browser (and the AdsPower profile, if used) even if
            # the automation loop above exited via an unhandled exception.
            await browser.close()
            if ws_endpoint:
                await stop_adspower_profile(api_url, profile_id)

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="TikTok AdsPower Automator (Warm-up & Spy Modes)")
    parser.add_argument("--mode", choices=["warmup", "spy"], required=True, help="Automation mode: warmup or spy")
    parser.add_argument("--profile-id", help="AdsPower profile user_id. If omitted, will check .env's ADSPOWER_PROFILE_ID or run standard Playwright")
    parser.add_argument("--geo", default="US", choices=list(GEO_DATABASE.keys()), help="Target country/GEO code (default: US)")
    parser.add_argument("--limit", type=int, default=15, help="Number of videos to inspect/interact with (default: 15)")
    parser.add_argument("--api-url", default="http://localhost:50325", help="AdsPower Local API url (default: http://localhost:50325)")
    parser.add_argument("--headless", action="store_true", help="Launch fallback browser in headless mode (if not using AdsPower)")
    
    args = parser.parse_args()
    
    # Resolve profile ID
    p_id = args.profile_id or os.getenv("ADSPOWER_PROFILE_ID")
    a_url = args.api_url or os.getenv("ADSPOWER_API_URL", "http://localhost:50325")
    
    asyncio.run(
        run_automation(
            mode=args.mode,
            profile_id=p_id,
            geo=args.geo,
            limit=args.limit,
            api_url=a_url,
            headless=args.headless
        )
    )

if __name__ == "__main__":
    main()
