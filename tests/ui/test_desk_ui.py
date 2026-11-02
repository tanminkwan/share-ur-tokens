"""P6-P7, P6-P8: the owner's screen, driven in headless Chromium by Playwright against the sample peer's real owner API
(on a real port) in an in-memory world. No real LLM: the human peer has none, the agent peer uses the scripted double.
Skipped when Playwright or its browser is not installed (pip install playwright; python -m playwright install chromium)."""
import asyncio
import dataclasses

import pytest

from arena.peer.desk.api import build_owner_api
from arena.peer.desk.service import OwnerService
from arena.serve import serve_background
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import desk_peer, hosted
from tests.test_processes import free_port

TOKEN = "ui-t0ken"
WAIT = 10_000  # ms


@pytest.fixture
async def browser():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright is not installed")
    pw = await async_playwright().start()
    try:
        b = await pw.chromium.launch(headless=True)
    except Exception as e:  # the browser is not installed
        await pw.stop()
        pytest.skip(f"headless chromium unavailable: {e}")
    yield b
    await b.close()
    await pw.stop()


@pytest.fixture
async def site(eco):
    servers = []

    async def open_site(llm=False):
        p, desk = await desk_peer(eco, "me", llm=llm)
        p.settings = dataclasses.replace(p.settings, desk_poll_ms=150)
        port = free_port()
        servers.append(await serve_background(build_owner_api(OwnerService(p, desk), TOKEN), "127.0.0.1", port))
        return p, desk, f"http://127.0.0.1:{port}/"
    yield open_site
    for s in servers:
        s.should_exit = True
    await asyncio.sleep(0.1)


async def page_of(browser, url, token=TOKEN):
    page = await browser.new_page()
    await page.goto(url + (f"#token={token}" if token else ""))
    return page


async def test_p6p8_the_screen_needs_the_token_and_shows_who_answers(eco, site, browser):
    p, _, url = await site()
    anon = await page_of(browser, url, token=None)
    await anon.get_by_test_id("toast-bad").wait_for(timeout=WAIT)
    assert "토큰" in await anon.get_by_test_id("toast-bad").inner_text()
    page = await page_of(browser, url)
    await page.get_by_test_id("me-operator").wait_for(timeout=WAIT)
    assert await page.get_by_test_id("me-operator").inner_text() == "human"
    assert await page.get_by_test_id("me-pen").inner_text() == p.pen
    assert "#token" not in page.url  # the token does not stay in the address bar


async def test_p6p8_a_human_peer_joins_an_event_by_hand(eco, site, browser):
    p, _, url = await site()
    ev = await hosted(eco)
    await p.events.watch_once(p.ctx(p.events))
    page = await page_of(browser, url)
    card = page.get_by_test_id("item-notice")
    await card.wait_for(timeout=WAIT)
    await card.get_by_test_id("open-event").click()
    tool = page.get_by_test_id("tool-join_event")
    await tool.wait_for(timeout=WAIT)
    assert "manual" in await page.get_by_test_id("event-item").inner_text()
    await tool.locator("summary").click()
    await page.get_by_test_id("run-join_event").click()
    await page.get_by_test_id("toast-ok").first.wait_for(timeout=WAIT)
    await settle(eco.host)
    assert p.identity.pub in asst(eco.host).events[ev].applicants
    await page.get_by_test_id("transcript").filter(has_text="[소유자 행동] join_event").wait_for(timeout=WAIT)


async def test_p6p8_the_owner_answers_a_question_and_writes(eco, site, browser):
    p, _, url = await site()
    page = await page_of(browser, url)
    await page.get_by_test_id("no-items").wait_for(timeout=WAIT)
    asked = asyncio.create_task(p.owner.ask("이 대회에 참가할까요?", "친선 대회"))
    q = page.get_by_test_id("item-question")
    await q.wait_for(timeout=WAIT)
    await q.get_by_test_id("why").fill("주말이라 좋다")
    await q.get_by_test_id("answer-yes").click()
    a = await asyncio.wait_for(asked, 10)
    assert a.yes and a.why == "주말이라 좋다"
    wrote = asyncio.create_task(p.owner.write("짧은 소개를 써 주세요", "프로필", {"properties": {"intro": {"description": "한 줄 소개"}}}))
    w = page.get_by_test_id("item-write")
    await w.wait_for(timeout=WAIT)
    await w.get_by_test_id("field-intro").fill("가위바위보를 좋아하는 사원")
    await w.get_by_test_id("send-fields").click()
    assert await asyncio.wait_for(wrote, 10) == {"intro": "가위바위보를 좋아하는 사원"}


async def test_p6p8_suggest_drive_the_owner_rejects_then_approves(eco, site, browser):
    p, desk, url = await site(llm=True)
    ev = await hosted(eco)
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await page_of(browser, url)
    await page.get_by_test_id("event-item").click()
    await page.get_by_test_id("drive").wait_for(timeout=WAIT)
    await page.get_by_test_id("drive").select_option("suggest")
    await page.get_by_test_id("toast-ok").filter(has_text="suggest").wait_for(timeout=WAIT)
    assert asst(p).events[ev].drive == "suggest"
    p.llm.push("join_event")
    await asst(p).feed(ctx(p), ev, "참가하라")
    s = page.get_by_test_id("item-suggestion")
    await s.wait_for(timeout=WAIT)
    assert "join_event" in await s.get_by_test_id("suggested-tool").inner_text()
    await s.get_by_test_id("reject").click()
    await page.get_by_test_id("transcript").filter(has_text="[소유자 거절] join_event").wait_for(timeout=WAIT)
    assert not asst(p).events[ev].joined
    p.llm.push("join_event")
    await asst(p).feed(ctx(p), ev, "다시 참가하라")
    await page.get_by_test_id("item-suggestion").get_by_test_id("approve").click(timeout=WAIT)
    for _ in range(100):
        if asst(p).events[ev].joined:
            break
        await asyncio.sleep(0.05)
    assert asst(p).events[ev].joined


async def test_p6p8_the_owner_opens_an_event_with_a_schedule(eco, site, browser):
    p, _, url = await site()
    page = await page_of(browser, url)
    await page.get_by_test_id("host-form").locator("summary").click(timeout=WAIT)
    await page.get_by_test_id("host-title").fill("점심 가위바위보")
    await page.get_by_test_id("host-kind").fill("놀이")
    await page.get_by_test_id("host-rules").fill(RULES)
    await page.get_by_test_id("host-when").fill("2030-01-01T12:00")
    await page.get_by_test_id("host-code").select_option("session")
    await page.get_by_test_id("host-submit").click()
    await page.get_by_test_id("event-title").filter(has_text="점심 가위바위보").wait_for(timeout=WAIT)
    assert "session" in await page.get_by_test_id("schedule").inner_text()
    assert "schedule" in await page.get_by_test_id("timers").inner_text()
    st = next(iter(asst(p).events.values()))
    assert st.role == "host" and st.schedule[0]["code"] == "session"
