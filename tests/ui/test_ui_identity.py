"""One look for every window (.claude/skills/arena-ui): desk, console and chat load the same arena.css; the peer's kind
tints the background and is named in the header (never color alone); dark follows the system. Headless Chromium.
Set ARENA_UI_SHOTS=<folder> to keep screenshots of each window, light and dark."""
import os

import pytest

from tests.test_assistant import eco  # noqa: F401  (eco is a fixture)
from tests.ui.test_chat_ui import chat_site  # noqa: F401  (a fixture)
from tests.ui.test_console_ui import TOKEN as CONSOLE_TOKEN, console_site  # noqa: F401  (a fixture)
from tests.ui.test_desk_ui import TOKEN as DESK_TOKEN, WAIT, browser, site  # noqa: F401  (fixtures)
from tests.test_chat import TOKEN as CHAT_TOKEN

LOOK = """() => { const r = getComputedStyle(document.documentElement), b = getComputedStyle(document.body);
  return { accent: r.getPropertyValue('--accent').trim(), page: b.backgroundColor, font: b.fontFamily,
           peer: document.documentElement.dataset.peer || null }; }"""


async def open_window(browser, url, token, dark=False):
    page = await browser.new_page(color_scheme="dark" if dark else "light", viewport={"width": 1280, "height": 800})
    await page.goto(url + f"#token={token}")
    await page.get_by_test_id("me-kind").wait_for(timeout=WAIT)
    return page


async def shot(page, name):
    folder = os.environ.get("ARENA_UI_SHOTS")
    if folder:
        os.makedirs(folder, exist_ok=True)
        await page.screenshot(path=os.path.join(folder, f"{name}.png"), full_page=True)


EXPECTED = {False: ("#1f6fcc", "rgb(255, 255, 255)"), True: ("#6aa6f2", "rgb(17, 19, 21)")}  # accent, page: the same in every window


@pytest.mark.parametrize("name", ["desk", "console", "chat"])
async def test_every_window_has_the_one_look_light_and_dark(eco, site, console_site, chat_site, browser, name):
    if name == "desk":
        url, token = (await site())[2], DESK_TOKEN
    elif name == "console":
        url, token = (await console_site())[2], CONSOLE_TOKEN
    else:
        url, token = (await chat_site())[3], CHAT_TOKEN
    for dark in (False, True):
        page = await open_window(browser, url, token, dark)
        look = await page.evaluate(LOOK)
        assert (look["accent"], look["page"]) == EXPECTED[dark], (name, dark, look)
        assert "Noto Sans KR" in look["font"] and look["peer"] == "personal"
        assert await page.get_by_test_id("me-kind").inner_text() == "개인 peer"
        await shot(page, f"{name}-{'dark' if dark else 'light'}")
        await page.close()


@pytest.mark.parametrize("kind,label,light,dark", [("sphinx", "스핑크스", "rgb(251, 246, 233)", "rgb(23, 20, 12)"),
                                                   ("observer", "관전 peer", "rgb(238, 247, 240)", "rgb(15, 23, 18)")])
async def test_the_peer_s_kind_tints_its_window_and_is_named(eco, console_site, browser, kind, label, light, dark):
    p, _, url = await console_site()
    p.config.kind = kind
    for is_dark, expected in ((False, light), (True, dark)):
        page = await open_window(browser, url, CONSOLE_TOKEN, is_dark)
        look = await page.evaluate(LOOK)
        assert look["peer"] == kind and look["page"] == expected
        assert await page.get_by_test_id("me-kind").inner_text() == label  # not by color alone
        await shot(page, f"console-{kind}-{'dark' if is_dark else 'light'}")
        await page.close()


async def test_every_kind_has_its_own_background_and_name(eco, console_site, browser):
    """all the kinds of peer_kinds.py: each its own background in light and in dark, each named in the header"""
    from arena.bundled.peer_kinds import PEER_KINDS
    p, _, url = await console_site()
    for dark in (False, True):
        seen = {}
        for kind, label in PEER_KINDS.items():
            p.config.kind = kind
            page = await open_window(browser, url, CONSOLE_TOKEN, dark)
            look = await page.evaluate(LOOK)
            assert look["peer"] == kind and await page.get_by_test_id("me-kind").inner_text() == label
            seen[kind] = look["page"]
            await shot(page, f"kind-{kind}-{'dark' if dark else 'light'}")
            await page.close()
        assert len(set(seen.values())) == len(PEER_KINDS), seen  # no two kinds share a background

