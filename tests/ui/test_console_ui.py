"""The console window in headless Chromium (user 2026-11-04: one window for a person to watch and to step in). A real
local web on a real port, an in-memory world, no real LLM. Skipped when Playwright or its browser is missing."""
import asyncio
import dataclasses

import pytest

from arena.bundled.console import ConsoleApp
from arena.bundled.console.api import build_console_api
from arena.bundled.owner_service import OwnerService
from arena.serve import serve_background
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import desk_peer, hosted
from tests.test_processes import free_port
from tests.ui.test_desk_ui import WAIT, browser, page_of  # noqa: F401  (browser is a fixture)

TOKEN = "ui-t0ken"


@pytest.fixture
async def console_site(eco):
    servers = []

    async def open_site(llm=False):
        p, desk = await desk_peer(eco, "me", llm=llm)
        p.settings = dataclasses.replace(p.settings, desk_poll_ms=150)
        c = ConsoleApp(OwnerService(p, desk), p.settings, "127.0.0.1", 0, TOKEN)
        p.apps.append(c)
        p._register_one(c, builtin=False)
        c.bind(p.ctx(c))
        port = free_port()
        servers.append(await serve_background(build_console_api(c, TOKEN), "127.0.0.1", port))
        return p, desk, f"http://127.0.0.1:{port}/"
    yield open_site
    for s in servers:
        s.should_exit = True
    await asyncio.sleep(0.1)


async def test_a_person_watches_the_conversation_and_answers_in_it(eco, console_site, browser):
    p, desk, url = await console_site()
    ev = await hosted(eco)
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    await OwnerService(p, desk).run_tool(ev, "join_event", {})
    await settle(eco.host)
    eco.host.llm.push("send", to=p.pen, text="환영합니다. 규칙을 읽어 주세요", data={})
    await asst(eco.host).feed(ctx(eco.host), ev, "계속")
    await settle(eco.host, p)
    page = await page_of(browser, url)
    await page.locator(f'[data-testid="event-item"][data-id="{ev}"]').click()
    incoming = page.get_by_test_id("line-in").filter(has_text="환영합니다")
    await incoming.wait_for(timeout=WAIT)
    assert await page.get_by_test_id("agent-messages").count() == 0 and await page.get_by_test_id("tell-text").count() == 0  # no LLM here
    await page.get_by_test_id("say-text").fill("네, 읽었습니다")
    await page.get_by_test_id("say-send").click()
    mine = page.get_by_test_id("line-out").filter(has_text="네, 읽었습니다")
    await mine.wait_for(timeout=WAIT)
    assert "나 →" in await mine.inner_text()
    await settle(eco.host)
    assert any(x["dir"] == "in" and x["text"] == "네, 읽었습니다" for x in asst(eco.host).events[ev].timeline)  # it reached the host
    await page.get_by_test_id("drive").wait_for(timeout=WAIT)  # stepping in further: the drive and the tools are there
    assert await page.get_by_test_id("tools-box").count() == 1


async def test_with_an_agent_the_window_shows_my_agent_and_the_instruct_box(eco, console_site, browser):
    p, desk, url = await console_site(llm=True)
    ev = await hosted(eco)
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await page_of(browser, url)
    await page.locator(f'[data-testid="event-item"][data-id="{ev}"]').click()
    await page.get_by_test_id("tell-text").wait_for(timeout=WAIT)
    p.llm.push("wait")
    await page.get_by_test_id("tell-text").fill("규칙을 보고 참가할지 정해")
    await page.get_by_test_id("tell-send").click()
    await page.get_by_test_id("line-note-instruction").wait_for(timeout=WAIT)
    await page.get_by_test_id("agent-text").wait_for(timeout=WAIT)  # my agent's panel (only with an LLM)
    p.llm.push("reply", text="아직 정하지 않았습니다")
    await page.get_by_test_id("agent-text").fill("어떻게 할 거야?")
    await page.get_by_test_id("agent-send").click()
    await page.get_by_test_id("agent-messages").get_by_text("아직 정하지 않았습니다").wait_for(timeout=WAIT)


async def test_the_console_needs_the_token(eco, console_site, browser):
    p, _, url = await console_site()
    anon = await page_of(browser, url, token=None)
    await anon.get_by_test_id("toast-bad").wait_for(timeout=WAIT)
    assert "토큰" in await anon.get_by_test_id("toast-bad").inner_text()
    page = await page_of(browser, url)
    await page.get_by_test_id("me-operator").wait_for(timeout=WAIT)
    assert await page.get_by_test_id("me-pen").inner_text() == p.pen and "#token" not in page.url


async def test_in_the_console_the_person_answers_a_question_and_writes(eco, console_site, browser):
    p, _, url = await console_site()
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


async def test_in_the_console_the_person_runs_a_tool_by_hand_and_sees_it_in_the_conversation(eco, console_site, browser):
    p, _, url = await console_site()
    ev = await hosted(eco)
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await page_of(browser, url)
    await page.locator(f'[data-testid="event-item"][data-id="{ev}"]').click()
    await page.get_by_test_id("tools-box").locator("> summary").click(timeout=WAIT)
    tool = page.get_by_test_id("tool-join_event")
    await tool.locator("summary").click(timeout=WAIT)
    await page.get_by_test_id("run-join_event").click()
    await page.get_by_test_id("toast-ok").first.wait_for(timeout=WAIT)
    await settle(eco.host)
    assert p.identity.pub in asst(eco.host).events[ev].applicants  # it reached the host
    await page.get_by_test_id("line-note-action").filter(has_text="참가 신청").wait_for(timeout=WAIT)  # my action, in the conversation


async def test_in_the_console_the_person_switches_the_drive_and_rejects_then_approves_a_suggestion(eco, console_site, browser):
    p, _, url = await console_site(llm=True)
    ev = await hosted(eco)
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await page_of(browser, url)
    await page.locator(f'[data-testid="event-item"][data-id="{ev}"]').click()
    await page.get_by_test_id("drive").wait_for(timeout=WAIT)
    await page.get_by_test_id("drive").select_option("suggest")
    await page.get_by_test_id("toast-ok").filter(has_text="suggest").wait_for(timeout=WAIT)
    assert asst(p).events[ev].drive == "suggest"
    p.llm.push("join_event")
    await asst(p).feed(ctx(p), ev, "참가하라")
    s = page.get_by_test_id("item-suggestion")
    await s.wait_for(timeout=WAIT)
    await s.get_by_test_id("reject").click()
    for _ in range(100):
        if any("거절" in x for x in asst(p).events[ev].transcript):
            break
        await asyncio.sleep(0.05)
    assert not asst(p).events[ev].joined
    p.llm.push("join_event")
    await asst(p).feed(ctx(p), ev, "다시 참가하라")
    await page.get_by_test_id("item-suggestion").get_by_test_id("approve").click(timeout=WAIT)
    for _ in range(100):
        if asst(p).events[ev].joined:
            break
        await asyncio.sleep(0.05)
    assert asst(p).events[ev].joined
    await page.get_by_test_id("line-note-action").filter(has_text="참가 신청").wait_for(timeout=WAIT)


async def test_in_the_console_the_person_opens_an_event_with_a_schedule(eco, console_site, browser):
    p, _, url = await console_site()
    page = await page_of(browser, url)
    await page.get_by_test_id("host-form").locator("summary").click(timeout=WAIT)
    await page.get_by_test_id("host-title").fill("점심 가위바위보")
    await page.get_by_test_id("host-kind").fill("놀이")
    await page.get_by_test_id("host-rules").fill("참가 신청을 하면 개최자가 member로 계약한다")
    await page.get_by_test_id("host-when").fill("2030-01-01T12:00")
    await page.get_by_test_id("host-code").select_option("session")
    await page.get_by_test_id("host-submit").click()
    await page.get_by_test_id("conversation-title").filter(has_text="점심 가위바위보").wait_for(timeout=WAIT)
    assert "session" in await page.get_by_test_id("schedule").inner_text()
    assert "schedule" in await page.get_by_test_id("timers").inner_text()
    await page.get_by_test_id("line-note-instruction").wait_for(timeout=WAIT)  # my standing instruction, in the conversation
    assert next(iter(asst(p).events.values())).role == "host"


async def test_a_half_filled_tool_form_survives_the_clock_moving(eco, console_site, browser):
    """found on a real run (2026-11-05): the state line carries the clock, so the side panel was rebuilt on every poll and a
    form being typed in closed and emptied within two seconds. Now only the state line's text is renewed."""
    from tests.conftest import FakeClock
    p, _, url = await console_site()
    p.clock = fc = FakeClock()
    ev = await hosted(eco)
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await page_of(browser, url)
    await page.locator(f'[data-testid="event-item"][data-id="{ev}"]').click()
    await page.get_by_test_id("tools-box").locator("> summary").click(timeout=WAIT)
    await page.get_by_test_id("tool-send").locator("summary").click(timeout=WAIT)
    await page.get_by_test_id("tool-send").get_by_test_id("arg-text").fill("쓰는 중인 글")
    before = await page.get_by_test_id("state-line").inner_text()
    fc.tick(60)  # a minute later: the state line is different, the form must not be
    await page.get_by_test_id("state-line").filter(has_not_text=before).wait_for(timeout=WAIT)
    assert await page.get_by_test_id("tools-box").evaluate("e => e.open") is True
    assert await page.get_by_test_id("tool-send").get_by_test_id("arg-text").input_value() == "쓰는 중인 글"
