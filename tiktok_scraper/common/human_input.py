import asyncio
import random

QWERTY_NEIGHBORS = {
    'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'ersfxc', 'e': 'wsdr',
    'f': 'rtgvcd', 'g': 'tyhbvf', 'h': 'yujnbg', 'i': 'ujko', 'j': 'uikmnh',
    'k': 'ijlm', 'l': 'okp', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'wedxza', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu', 'z': 'asx'
}


async def type_like_human(page, text):
    """Types text into whatever element currently has focus, simulating realistic
    micro-delays and occasional QWERTY-neighbor typos with backspace corrections."""
    for char in text:
        if char.lower() in QWERTY_NEIGHBORS and random.random() < 0.04:
            wrong_char = random.choice(QWERTY_NEIGHBORS[char.lower()])
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


async def clear_and_type(page, locator, text):
    """Clicks a field, clears any existing content, then types text with type_like_human."""
    await locator.click()
    await page.keyboard.press("Meta+A")  # Cmd+A on macOS
    await page.keyboard.press("Control+A")  # Ctrl+A on Windows/Linux
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.5)
    await type_like_human(page, text)
