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
