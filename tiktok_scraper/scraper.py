import asyncio
import os
import json
import argparse
import sys
from playwright.async_api import async_playwright

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

async def run_scraper(query, desc_keywords, comment_keywords, limit, output_file, headless):
    print(f"[*] Starting TikTok Scraper. Search query: '{query}'")
    if desc_keywords:
        print(f"[*] Description filters: {desc_keywords}")
    if comment_keywords:
        print(f"[*] Comment filters: {comment_keywords}")
        
    async with async_playwright() as p:
        print("[*] Launching browser...")
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--window-size=1280,720"
            ]
        )
        
        # Use typical desktop chrome user-agent and viewport
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        
        page = await context.new_page()
        
        # Storage for video search results intercepted from API
        search_videos = []
        
        async def on_response_search(response):
            if "api/search/" in response.url and "full" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    videos = extract_videos_from_search_json(data)
                    search_videos.extend(videos)
                    print(f"  [+] Intercepted search chunk. Extracted {len(videos)} videos.")
                except Exception as e:
                    # Silent failure for non-JSON responses
                    pass
                    
        page.on("response", on_response_search)
        
        # Navigate to TikTok search results page
        search_url = f"https://www.tiktok.com/search?q={query}"
        print(f"[*] Loading search page: {search_url}")
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[!] Error loading search page: {e}")
            await browser.close()
            sys.exit(1)
            
        # Scroll page down several times to load more videos and trigger API requests
        for i in range(5):
            print(f"[*] Scrolling search results (page scroll {i+1}/5)...")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)
            
            # De-duplicate to check limit
            unique_ids = {v["video_id"] for v in search_videos}
            if len(unique_ids) >= limit:
                break
                
        # Remove search listener
        page.remove_listener("response", on_response_search)
        
        # De-duplicate results
        unique_videos = {}
        for v in search_videos:
            unique_videos[v["video_id"]] = v
            
        videos_list = list(unique_videos.values())[:limit]
        print(f"[*] Search phase complete. Found {len(videos_list)} unique videos.")
        
        # Filter videos by description keywords
        filtered_videos = []
        if desc_keywords:
            print(f"[*] Filtering videos by description keywords...")
            for v in videos_list:
                desc_lower = v["description"].lower()
                if any(kw.lower() in desc_lower for kw in desc_keywords):
                    filtered_videos.append(v)
            print(f"[*] Description filter complete: {len(filtered_videos)} / {len(videos_list)} videos matched.")
        else:
            filtered_videos = videos_list
            print("[*] No description keywords specified. Matching all videos.")
            
        # Final output storage
        final_results = []
        
        # Scraping comments for matching videos
        for idx, v in enumerate(filtered_videos):
            video_url = v["video_url"]
            print(f"[*] [{idx+1}/{len(filtered_videos)}] Scraping comments for video: {video_url}")
            
            video_comments = []
            
            async def on_response_comments(response):
                if "api/comment/list/" in response.url and response.status == 200:
                    try:
                        data = await response.json()
                        comments = extract_comments_from_json(data)
                        video_comments.extend(comments)
                        print(f"    [+] Intercepted comment chunk. Extracted {len(comments)} comments.")
                    except Exception as e:
                        pass
                        
            page.on("response", on_response_comments)
            
            try:
                await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
                
                # Scroll comments section to trigger network calls
                for s in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)
                    
            except Exception as e:
                print(f"    [!] Error loading comments: {e}")
            finally:
                page.remove_listener("response", on_response_comments)
                
            # De-duplicate comments
            unique_comments = {}
            for c in video_comments:
                unique_comments[c["comment_id"]] = c
                
            all_comments = list(unique_comments.values())
            
            # Filter comments by keywords
            matched_comments = []
            if comment_keywords:
                for c in all_comments:
                    text_lower = c["text"].lower()
                    if any(kw.lower() in text_lower for kw in comment_keywords):
                        matched_comments.append(c)
                print(f"    [*] Comments filter: {len(matched_comments)} / {len(all_comments)} comments matched.")
            else:
                matched_comments = all_comments
                print(f"    [*] Kept all {len(all_comments)} comments.")
                
            v["matched_comments"] = matched_comments
            v["total_scraped_comments"] = len(all_comments)
            final_results.append(v)
            
            # Grace timeout between video pages
            await page.wait_for_timeout(2000)
            
        # Write matching data to output JSON file
        print(f"[*] Saving results to: {output_file}")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_results, f, ensure_ascii=False, indent=2)
            
        print("[*] Scraping completed successfully.")
        await browser.close()

def main():
    parser = argparse.ArgumentParser(description="TikTok CLI Scraper & Filter Utility")
    parser.add_argument("--search", "-s", required=True, help="Search query for TikTok videos")
    parser.add_argument("--desc-keywords", "-d", help="Comma-separated keywords to filter in video descriptions")
    parser.add_argument("--comment-keywords", "-c", help="Comma-separated keywords to filter in comments")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Maximum number of search results to retrieve (default: 10)")
    parser.add_argument("--output", "-o", default="results.json", help="Path to output JSON file (default: results.json)")
    parser.add_argument("--headless", action="store_false", dest="gui", help="Disable headless mode and run with browser GUI visible")
    
    args = parser.parse_args()
    
    desc_kws = [k.strip() for k in args.desc_keywords.split(",")] if args.desc_keywords else []
    comment_kws = [k.strip() for k in args.comment_keywords.split(",")] if args.comment_keywords else []
    
    asyncio.run(
        run_scraper(
            query=args.search,
            desc_keywords=desc_kws,
            comment_keywords=comment_kws,
            limit=args.limit,
            output_file=args.output,
            headless=args.gui # if args.gui is True, headless is False
        )
    )

if __name__ == "__main__":
    main()
