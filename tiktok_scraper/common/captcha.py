import asyncio

CAPTCHA_SELECTORS = [
    "iframe[src*='captcha']",
    "div.captcha_verify_container",
    ".secsdk-captcha-drag-wrapper",
    "#tiktok-verify-ele",
    "[class*='captcha']",
]


async def page_has_captcha(page, timeout=1000):
    """Checks whether any known TikTok captcha challenge is currently visible on the page."""
    for sel in CAPTCHA_SELECTORS:
        try:
            elem = page.locator(sel).first
            if await elem.is_visible(timeout=timeout):
                return True
        except Exception:
            continue
    return False


async def wait_for_captcha_resolution(page, on_detected=None, on_resolved=None, poll_interval=4):
    """Blocks until a detected captcha disappears from the page (i.e. solved by an operator).
    Returns True if a captcha was found (and later resolved), False if none was present.
    Callers that must not block forever (e.g. headless runs) should check page_has_captcha
    themselves instead of calling this."""
    if not await page_has_captcha(page):
        return False

    if on_detected:
        await on_detected()

    while await page_has_captcha(page):
        await asyncio.sleep(poll_interval)

    if on_resolved:
        await on_resolved()
    return True
