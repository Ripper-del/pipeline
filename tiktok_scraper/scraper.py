import asyncio
import logging
import os
import json
import random
import argparse
import sys
from playwright.async_api import async_playwright

from common.captcha import page_has_captcha

logger = logging.getLogger(__name__)

def extract_videos_from_search_json(json_data):
    """Defensively extracts video metadata from various potential TikTok search response structures."""
    videos = []

    # Check for common keys in TikTok search API response
    items = json_data.get("item_list") or json_data.get("itemList") or json_data.get("data")
    if not items or not isinstance(items, list):
        if isinstance(json_data, list):
            items = json_data
        else:
            return videos

    for item in items:
        # Search API returns items that might contain a nested 'item' dictionary
        video_data = item.get("item") if isinstance(item.get("item"), dict) else item

        video_id = video_data.get("id") or video_data.get("item_id")
        desc = video_data.get("desc") or video_data.get("description") or ""

        # Author details
        author_data = video_data.get("author") or {}
        username = author_data.get("uniqueId") or author_data.get("unique_id") or author_data.get("nickname") or ""

        # Stats
        stats = video_data.get("stats") or video_data.get("statistics") or {}

        if video_id and username:
            video_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
            videos.append({
                "video_id": str(video_id),
                "username": username,
                "video_url": video_url,
                "description": desc,
                "stats": {
                    "likes": stats.get("diggCount") or stats.get("likeCount") or 0,
                    "comments_count": stats.get("commentCount") or 0,
                    "shares": stats.get("shareCount") or 0,
                    "views": stats.get("playCount") or stats.get("viewCount") or 0,
                },
                "create_time": video_data.get("createTime") or video_data.get("create_time"),
            })
    return videos

def extract_comments_from_json(json_data):
    """Defensively extracts comment metadata from TikTok comment API response."""
    parsed_comments = []
    comments_list = json_data.get("comments") or json_data.get("data")
    if not comments_list or not isinstance(comments_list, list):
        return parsed_comments

    for item in comments_list:
        comment_id = item.get("cid") or item.get("id")
        text = item.get("text") or item.get("share_desc") or ""

        user_data = item.get("user") or item.get("author") or {}
        username = user_data.get("unique_id") or user_data.get("uniqueId") or user_data.get("nickname") or ""

        likes = item.get("digg_count") or item.get("like_count") or 0
        create_time = item.get("create_time") or item.get("createTime")

        if comment_id and text:
            parsed_comments.append({
                "comment_id": str(comment_id),
                "username": username,
                "text": text,
                "likes": likes,
                "create_time": create_time
            })
    return parsed_comments

def dedupe_by_key(items, key):
    """De-duplicates a list of dicts by a given key, keeping first-seen order."""
    seen = {}
    for item in items:
        seen[item[key]] = item
    return list(seen.values())

def make_response_collector(matcher, extractor, results, label):
    """Builds a Playwright response handler that extracts matching items into `results`."""
    async def handler(response):
        if response.status == 200 and matcher(response.url):
            try:
                data = await response.json()
                items = extractor(data)
                if items:
                    results.extend(items)
                    logger.info(f"Intercepted {label} chunk. Extracted {len(items)} items.")
            except Exception:
                # Non-JSON or unexpected payload shape; ignore and keep listening.
                pass
    return handler

async def goto_with_retry(page, url, retries=3, base_delay=3):
    """Navigates to `url`, retrying transient failures with backoff. Returns True on success."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(random.randint(2500, 4000))
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"Navigation attempt {attempt}/{retries} failed for {url}: {e}")
            if attempt < retries:
                delay = base_delay * attempt
                logger.info(f"Retrying in {delay}s...")
                await asyncio.sleep(delay)
    logger.error(f"Giving up on {url} after {retries} attempts ({last_error})")
    return False

async def resolve_captcha_if_present(page, headless):
    """Detects a captcha challenge. If headed, blocks until an operator solves it manually.
    If headless, there is no one to solve it, so returns False so the caller can skip the page."""
    if not await page_has_captcha(page):
        return True

    logger.warning("CAPTCHA detected.")
    if headless:
        logger.warning("Running headless - cannot solve CAPTCHA automatically. Skipping this page.")
        return False

    logger.info("Please solve the CAPTCHA manually in the browser window...")
    while await page_has_captcha(page):
        await asyncio.sleep(4)
    logger.info("CAPTCHA resolved. Resuming.")
    return True

def load_existing_results(output_file):
    """Loads a previous run's output for --resume, tolerating a missing or corrupt file."""
    if not os.path.exists(output_file):
        return []
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception as e:
        logger.warning(f"Could not read existing results file for resume ({e}). Starting fresh.")
    return []

def save_results(output_file, results):
    """Writes results atomically so a crash mid-write never corrupts the output file."""
    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    tmp_file = f"{output_file}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, output_file)

async def run_scraper(query, desc_keywords, comment_keywords, limit, output_file, headless, resume, proxy):
    logger.info(f"Starting TikTok Scraper. Search query: '{query}'")
    if desc_keywords:
        logger.info(f"Description filters: {desc_keywords}")
    if comment_keywords:
        logger.info(f"Comment filters: {comment_keywords}")

    final_results = []
    done_ids = set()
    if resume:
        final_results = load_existing_results(output_file)
        done_ids = {v["video_id"] for v in final_results}
        if done_ids:
            logger.info(f"Resume mode: {len(done_ids)} videos already scraped, will be skipped.")

    async with async_playwright() as p:
        logger.info("Launching browser...")
        launch_kwargs = dict(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--window-size=1280,720"
            ]
        )
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = await p.chromium.launch(**launch_kwargs)

        try:
            # Use typical desktop chrome user-agent and viewport
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )

            page = await context.new_page()

            # Storage for video search results intercepted from API
            search_videos = []
            search_listener = make_response_collector(
                lambda url: "api/search/" in url and "full" in url,
                extract_videos_from_search_json,
                search_videos,
                "search",
            )
            page.on("response", search_listener)

            # Navigate to TikTok search results page
            search_url = f"https://www.tiktok.com/search?q={query}"
            logger.info(f"Loading search page: {search_url}")
            if not await goto_with_retry(page, search_url):
                logger.error("Could not load search page. Aborting.")
                sys.exit(1)
            if not await resolve_captcha_if_present(page, headless):
                logger.error("Search page blocked by CAPTCHA. Aborting.")
                sys.exit(1)

            # Scroll page down several times to load more videos and trigger API requests
            for i in range(5):
                logger.info(f"Scrolling search results (page scroll {i+1}/5)...")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(random.randint(2500, 3500))

                # De-duplicate to check limit
                unique_ids = {v["video_id"] for v in search_videos}
                if len(unique_ids) >= limit:
                    break

            # Remove search listener
            page.remove_listener("response", search_listener)

            # De-duplicate results
            videos_list = dedupe_by_key(search_videos, "video_id")[:limit]
            logger.info(f"Search phase complete. Found {len(videos_list)} unique videos.")

            # Filter videos by description keywords
            filtered_videos = []
            if desc_keywords:
                logger.info("Filtering videos by description keywords...")
                for v in videos_list:
                    desc_lower = v["description"].lower()
                    if any(kw.lower() in desc_lower for kw in desc_keywords):
                        filtered_videos.append(v)
                logger.info(f"Description filter complete: {len(filtered_videos)} / {len(videos_list)} videos matched.")
            else:
                filtered_videos = videos_list
                logger.info("No description keywords specified. Matching all videos.")

            # Scraping comments for matching videos
            for idx, v in enumerate(filtered_videos):
                video_url = v["video_url"]

                if v["video_id"] in done_ids:
                    logger.info(f"[{idx+1}/{len(filtered_videos)}] Already scraped, skipping: {video_url}")
                    continue

                logger.info(f"[{idx+1}/{len(filtered_videos)}] Scraping comments for video: {video_url}")

                video_comments = []
                comment_listener = make_response_collector(
                    lambda url: "api/comment/list/" in url,
                    extract_comments_from_json,
                    video_comments,
                    "comment",
                )
                page.on("response", comment_listener)

                try:
                    if not await goto_with_retry(page, video_url):
                        logger.warning(f"Skipping video after repeated navigation failures: {video_url}")
                        continue
                    if not await resolve_captcha_if_present(page, headless):
                        logger.warning(f"Skipping video blocked by CAPTCHA: {video_url}")
                        continue

                    # Scroll comments section to trigger network calls
                    for s in range(3):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(random.randint(1500, 2500))
                finally:
                    page.remove_listener("response", comment_listener)

                # De-duplicate comments
                all_comments = dedupe_by_key(video_comments, "comment_id")

                # Filter comments by keywords
                matched_comments = []
                if comment_keywords:
                    for c in all_comments:
                        text_lower = c["text"].lower()
                        if any(kw.lower() in text_lower for kw in comment_keywords):
                            matched_comments.append(c)
                    logger.info(f"Comments filter: {len(matched_comments)} / {len(all_comments)} comments matched.")
                else:
                    matched_comments = all_comments
                    logger.info(f"Kept all {len(all_comments)} comments.")

                v["matched_comments"] = matched_comments
                v["total_scraped_comments"] = len(all_comments)
                final_results.append(v)
                done_ids.add(v["video_id"])

                # Persist progress after every video so a crash never loses completed work
                save_results(output_file, final_results)

                # Grace timeout between video pages
                await page.wait_for_timeout(random.randint(1500, 2500))

            logger.info(f"Saving results to: {output_file}")
            save_results(output_file, final_results)
            logger.info("Scraping completed successfully.")
        finally:
            await browser.close()

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="TikTok CLI Scraper & Filter Utility")
    parser.add_argument("--search", "-s", required=True, help="Search query for TikTok videos")
    parser.add_argument("--desc-keywords", "-d", help="Comma-separated keywords to filter in video descriptions")
    parser.add_argument("--comment-keywords", "-c", help="Comma-separated keywords to filter in comments")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Maximum number of search results to retrieve (default: 10)")
    parser.add_argument("--output", "-o", default="results.json", help="Path to output JSON file (default: results.json)")
    parser.add_argument("--headless", action="store_false", dest="gui", help="Disable headless mode and run with browser GUI visible")
    parser.add_argument("--resume", action="store_true", help="Skip videos already present in --output from a previous run")
    parser.add_argument("--proxy", help="Proxy server to route the browser through, e.g. http://user:pass@host:port")

    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be a positive integer")

    desc_kws = [k.strip() for k in args.desc_keywords.split(",")] if args.desc_keywords else []
    comment_kws = [k.strip() for k in args.comment_keywords.split(",")] if args.comment_keywords else []

    asyncio.run(
        run_scraper(
            query=args.search,
            desc_keywords=desc_kws,
            comment_keywords=comment_kws,
            limit=args.limit,
            output_file=args.output,
            headless=args.gui,  # args.gui defaults True (headless); --headless flag flips it to show the GUI
            resume=args.resume,
            proxy=args.proxy,
        )
    )

if __name__ == "__main__":
    main()
