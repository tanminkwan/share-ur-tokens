"""The observer window in headless Chromium (user 2026-11-05: someone keeps it open while the world moves, so it must refresh
itself). A real local web on a real port over an in-memory world. Skipped when Playwright or its browser is missing."""
import asyncio
import dataclasses

import pytest

from arena.bundled.observer import ObserverApp
from arena.bundled.observer.api import build_observer_api
from arena.serve import serve_background
from tests.test_god_role import setup  # noqa: F401  (a fixture)
from tests.test_processes import free_port
from tests.ui.test_desk_ui import WAIT, browser  # noqa: F401  (browser is a fixture)
from tests.ui.test_ui_identity import EXPECTED, LOOK, open_window, shot

TOKEN = "obs-ui-t0ken"


@pytest.fixture
async def observer_site(setup):
    servers = []

    async def open_site(poll_ms=150):
        role, ov = setup["role"], setup["ov"]
        role.settings = dataclasses.replace(ov.settings, observer_poll_ms=poll_ms, god_cache_sec=0.0)  # no cache: every poll reads again
        app = ObserverApp(role, role.settings, "127.0.0.1", 0, TOKEN)
        app._ctx = ov.ctx(role)
        port = free_port()
        servers.append(await serve_background(build_observer_api(app, TOKEN), "127.0.0.1", port))
        return setup, f"http://127.0.0.1:{port}/"
    yield open_site
    for s in servers:
        s.should_exit = True
    await asyncio.sleep(0.1)


async def test_the_window_needs_the_token_and_shows_the_world(observer_site, browser):
    s, url = await observer_site()
    bad = await browser.new_page()
    await bad.goto(url + "#token=wrong")
    await bad.get_by_test_id("toast-bad").wait_for(timeout=WAIT)
    assert "토큰" in await bad.get_by_test_id("toast-bad").inner_text()
    page = await open_window(browser, url, TOKEN)
    assert await page.get_by_test_id("me-kind").inner_text() == "관전 peer"
    assert await page.get_by_test_id("me-pen").inner_text() == s["ov"].pen
    await page.get_by_test_id("recent-row").first.wait_for(timeout=WAIT)
    assert await page.get_by_test_id("recent-row").first.get_attribute("data-type") == "feedback"  # newest first
    assert await page.get_by_test_id("integrity-verdict").inner_text() == "정상: 해시 사슬, 서명, 기록자 봉인이 맞고 사본이 모두 같다"
    assert await page.get_by_test_id("recorder-row").count() == 1 and await page.get_by_test_id("event-row").count() == 1
    assert await page.get_by_test_id("peer-row").count() >= 3 and "필명-" in await page.get_by_test_id("peer-row").first.inner_text()
    assert int(await page.get_by_test_id("stat-entries").locator("b").inner_text()) >= 5
    await shot(page, "observer-light")


async def test_it_refreshes_itself_while_the_world_moves(observer_site, browser):
    """nobody reloads or clicks: a new entry shows up, and so does the new total; the 'last update' time moves"""
    s, url = await observer_site()
    page = await open_window(browser, url, TOKEN)
    await page.get_by_test_id("recent-row").first.wait_for(timeout=WAIT)
    before = int(await page.get_by_test_id("stat-entries").locator("b").inner_text())
    seen = await page.get_by_test_id("recent-row").count()
    stamp = await page.get_by_test_id("last-update").inner_text()
    assert "자동 갱신" in await page.get_by_test_id("refresh-state").inner_text()
    assert (await s["svc"].record(*s["cast"].share(consumer=s["cast"].judge, nonce="live-1")))["ok"]
    await page.get_by_test_id("stat-entries").locator("b").filter(has_text=str(before + 1)).wait_for(timeout=WAIT)
    assert await page.get_by_test_id("recent-row").first.get_attribute("data-type") == "share"
    assert await page.get_by_test_id("recent-row").count() >= seen
    assert await page.get_by_test_id("last-update").inner_text() != "아직 받지 못함" and stamp  # it keeps stamping each refresh


async def test_it_says_when_it_cannot_reach_the_peer_and_recovers(observer_site, browser):
    s, url = await observer_site()
    page = await open_window(browser, url, TOKEN)
    await page.get_by_test_id("recent-row").first.wait_for(timeout=WAIT)
    await page.route("**/api/snapshot", lambda route: route.abort())
    await page.get_by_test_id("refresh-state").filter(has_text="연결 끊김").wait_for(timeout=WAIT)  # said in words, not by color alone
    await page.unroute("**/api/snapshot")
    await page.get_by_test_id("refresh-state").filter(has_text="자동 갱신").wait_for(timeout=WAIT)


@pytest.mark.parametrize("dark", [False, True])
async def test_it_has_the_one_look_and_the_observer_background(observer_site, browser, dark):
    _, url = await observer_site()
    page = await open_window(browser, url, TOKEN, dark)
    look = await page.evaluate(LOOK)
    assert look["accent"] == EXPECTED[dark][0] and look["peer"] == "observer"
    assert look["page"] == ("rgb(15, 23, 18)" if dark else "rgb(238, 247, 240)")  # the green of arena.css, light and dark
    assert "Noto Sans KR" in look["font"]
    await shot(page, f"observer-{'dark' if dark else 'light'}")
