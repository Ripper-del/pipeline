import asyncio
import os
import random
import math
import argparse
import sys
import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# OpenAI Integration (Optional)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    try:
        import openai
    except ImportError:
        openai = None
else:
    openai = None

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
        "comments": ["takie prawdziwe haha", "to dosłownie ja", "potrzebuję tego w życiu", "mega trafne", "dlaczego to jest tak prawdziwe?", "hahaha", "dokładnie"]
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

async def generate_dynamic_comment(video_desc, lang):
    """Generates natural comments using OpenAI GPT engine."""
    if not openai or not OPENAI_API_KEY:
        return None
    try:
        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        system_prompt = (
            "You are a regular TikTok user writing a short, casual comment on a video. "
            "The comment must be written in the specified language, be very natural, casual, "
            "lowercase, without emojis, and sound human-like (short, slangy, like a real person, not a bot). "
            "Do not write anything else besides the comment itself."
        )
        user_prompt = f"Language: {lang}\nVideo description: {video_desc}\nWrite comment:"
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=30,
            temperature=0.8
        )
        comment = response.choices[0].message.content.strip().strip('"').lower()
        return comment
    except Exception as e:
        print(f"    [!] OpenAI GPT call failed: {e}")
        return None

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
                print("    [+] Liked video.")
                return True
        except Exception:
            continue
    print("    [!] Could not locate like button.")
    return False

async def post_comment(page, text):
    """Enters comment text and publishes it to the post."""
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
                # Type comments slowly to bypass robotic signature triggers
                await page.keyboard.type(text, delay=random.randint(60, 140))
                input_found = True
                break
        except Exception:
            continue
            
    if not input_found:
        print("    [!] Could not find comment input box.")
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
                print(f"    [+] Posted comment: '{text}'")
                return True
        except Exception:
            continue
            
    # Try pressing Enter as a fallback
    await page.keyboard.press("Enter")
    print(f"    [+] Posted comment via Enter key: '{text}'")
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

async def run_automation(mode, profile_id, geo, limit, api_url, headless):
    geo_data = GEO_DATABASE.get(geo)
    if not geo_data:
        print(f"[!] Invalid GEO: {geo}")
        sys.exit(1)
        
    print(f"[*] Starting automator in '{mode}' mode. GEO: '{geo}' (Lang: '{geo_data['lang']}')")
    
    ws_endpoint = None
    if profile_id:
        try:
            ws_endpoint = await get_adspower_ws(api_url, profile_id)
        except Exception as e:
            print(f"[!] Connection failed: {e}")
            sys.exit(1)
            
    async with async_playwright() as p:
        if ws_endpoint:
            print("[*] Connecting Playwright to AdsPower antidetect browser session...")
            browser = await p.chromium.connect_over_cdp(ws_endpoint)
            # Fetch active context
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            print("[*] Launching standard Playwright Chromium (AdsPower ID not provided)...")
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
        print("[*] Browser initialized. Navigating to TikTok...")
        try:
            await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[!] Error loading TikTok: {e}")
            await browser.close()
            sys.exit(1)
            
        matching_count = 0
        processed_videos = 0
        
        # Loop through search queries or FYP
        for query in geo_data["queries"]:
            if processed_videos >= limit:
                break
                
            print(f"[*] Querying search for warm-up keyword: '{query}'")
            search_url = f"https://www.tiktok.com/search?q={query}"
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"[!] Error querying keyword '{query}': {e}")
                continue
                
            # Loop for scrolling and interacting inside this keyword search
            for scroll_round in range(5):
                if processed_videos >= limit:
                    break
                    
                # Ease-in-out math scroll to load contents
                print(f"[*] Simulating human scrolling (round {scroll_round + 1}/5)...")
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
                    
                print(f"[*] Inspecting video: {video_url}")
                try:
                    await video_elem.click()
                    await page.wait_for_timeout(3000) # wait for overlay
                    
                    # Fetch description
                    desc = await get_video_description(page)
                    print(f"    Description: '{desc}'")
                    
                    # Determine relevance (dating / adult related keywords)
                    dating_kws = ["dating", "relationship", "single", "girlfriend", "boyfriend", "sevgili", "flört", "citas", "rencontre", "couple", "namoro", "出会い", "소개팅", "hẹn hò"]
                    is_relevant = any(kw in desc.lower() for kw in dating_kws) or any(kw in query.lower() for kw in dating_kws)
                    
                    if is_relevant:
                        matching_count += 1
                        print(f"    [+] Video identified as relevant ({matching_count} total).")
                        
                        # Human-like watch simulation (retention warm-up)
                        watch_time = random.randint(6, 15)
                        print(f"    [*] Simulating retention: watching for {watch_time} seconds...")
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
                                print(f"    [+] Spy Trigger! Match count is {matching_count} (every 5th video).")
                                
                        if should_interact:
                            # 1. Like
                            await like_video(page)
                            await page.wait_for_timeout(random.randint(1000, 2000))
                            
                            # 2. Comment
                            comment_text = await generate_dynamic_comment(desc, geo_data["lang"])
                            if not comment_text:
                                comment_text = random.choice(geo_data["comments"])
                            
                            await post_comment(page, comment_text)
                            await page.wait_for_timeout(random.randint(2000, 4000))
                            
                    else:
                        print("    [-] Video is not relevant. Skipping.")
                        
                    processed_videos += 1
                    
                    # Close video overlay (usually by pressing Escape key or clicking close button)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(2000)
                    
                except Exception as e:
                    print(f"    [!] Error during video interaction: {e}")
                    # Ensure overlay is closed
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(2000)
                    
        print("[*] Automation run finished.")
        if ws_endpoint:
            await browser.close()
            # Stop the AdsPower profile via Local API
            await stop_adspower_profile(api_url, profile_id)
        else:
            await browser.close()

def main():
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
