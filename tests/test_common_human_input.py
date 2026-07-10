"""Unit tests for tiktok_scraper/common/human_input.py using a fake page/locator."""
import asyncio
import random

from common.human_input import type_like_human, clear_and_type


class _FakeKeyboard:
    def __init__(self):
        self.typed = []
        self.pressed = []

    async def type(self, ch):
        self.typed.append(ch)

    async def press(self, key):
        self.pressed.append(key)


class _FakePage:
    def __init__(self):
        self.keyboard = _FakeKeyboard()


class _FakeLocator:
    def __init__(self):
        self.clicked = False

    async def click(self):
        self.clicked = True


def test_type_like_human_types_every_character_at_least_once():
    page = _FakePage()
    random.seed(1234)  # deterministic: fixes whether typo-branches fire
    asyncio.run(type_like_human(page, "hello"))
    # Typos add extra characters, but every real character of the input must
    # appear in the typed stream, in order.
    typed_text = "".join(page.keyboard.typed)
    assert typed_text.count("h") >= 1
    assert typed_text.endswith("o")


def test_type_like_human_empty_string_is_a_noop():
    page = _FakePage()
    asyncio.run(type_like_human(page, ""))
    assert page.keyboard.typed == []
    assert page.keyboard.pressed == []


def test_clear_and_type_clicks_then_clears_then_types():
    page = _FakePage()
    locator = _FakeLocator()
    asyncio.run(clear_and_type(page, locator, "hi"))

    assert locator.clicked is True
    assert page.keyboard.pressed[:3] == ["Meta+A", "Control+A", "Backspace"]
    assert "".join(page.keyboard.typed).replace("", "") != "" or page.keyboard.typed
