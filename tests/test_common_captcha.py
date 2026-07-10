"""Unit tests for tiktok_scraper/common/captcha.py using a fake Playwright-like page.
No pytest-asyncio dependency - async coroutines are driven with asyncio.run()."""
import asyncio

from common.captcha import page_has_captcha, wait_for_captcha_resolution


class _FakeLocator:
    def __init__(self, visible):
        self._visible = visible

    async def is_visible(self, timeout=1000):
        return self._visible


class _FakePage:
    """Simulates a page where the FIRST captcha selector is visible or not."""
    def __init__(self, captcha_visible):
        self.captcha_visible = captcha_visible

    def locator(self, sel):
        loc = _FakeLocator(self.captcha_visible)
        loc.first = loc
        return loc


def test_page_has_captcha_false_when_nothing_visible():
    page = _FakePage(captcha_visible=False)
    assert asyncio.run(page_has_captcha(page)) is False


def test_page_has_captcha_true_when_selector_visible():
    page = _FakePage(captcha_visible=True)
    assert asyncio.run(page_has_captcha(page)) is True


def test_wait_for_captcha_resolution_noop_when_no_captcha():
    page = _FakePage(captcha_visible=False)
    calls = {"detected": 0, "resolved": 0}

    async def on_detected():
        calls["detected"] += 1

    async def on_resolved():
        calls["resolved"] += 1

    found = asyncio.run(wait_for_captcha_resolution(page, on_detected=on_detected, on_resolved=on_resolved))
    assert found is False
    assert calls == {"detected": 0, "resolved": 0}


def test_wait_for_captcha_resolution_calls_callbacks_in_order():
    # Captcha is visible for the first 2 polls, then disappears.
    remaining_visible_polls = [True, True]

    class SeqPage:
        def locator(self, sel):
            visible = bool(remaining_visible_polls)
            loc = _FakeLocator(visible)
            loc.first = loc
            return loc

    page = SeqPage()
    calls = {"detected": 0, "resolved": 0}

    async def on_detected():
        calls["detected"] += 1

    async def on_resolved():
        calls["resolved"] += 1

    async def fake_sleep(_seconds):
        if remaining_visible_polls:
            remaining_visible_polls.pop()

    async def run():
        orig_sleep = asyncio.sleep
        asyncio.sleep = fake_sleep
        try:
            return await wait_for_captcha_resolution(page, on_detected=on_detected, on_resolved=on_resolved, poll_interval=0)
        finally:
            asyncio.sleep = orig_sleep

    found = asyncio.run(run())
    assert found is True
    assert calls == {"detected": 1, "resolved": 1}
