"""P6-Q5: the chat window in headless Chromium (Playwright), against the chat app's real local web on a real port.
Scripted LLM double only."""
import asyncio

import pytest

from arena.bundled.chat.api import build_chat_api
from arena.serve import serve_background
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_chat import TOKEN, chat_peer
from tests.test_desk import hosted
from tests.test_processes import free_port
from tests.ui.test_desk_ui import WAIT, browser  # noqa: F401  (browser is a fixture)


@pytest.fixture
async def chat_site(eco):
    servers = []

    async def open_site():
        p, desk, chat = await chat_peer(eco)
        chat.s = __import__("dataclasses").replace(chat.s, desk_poll_ms=150)
        port = free_port()
        servers.append(await serve_background(build_chat_api(chat, TOKEN), "127.0.0.1", port))
        return p, desk, chat, f"http://127.0.0.1:{port}/"
    yield open_site
    for s in servers:
        s.should_exit = True
    await asyncio.sleep(0.1)


async def test_p6q5_the_person_talks_with_their_agent(eco, chat_site, browser):
    p, _, chat, url = await chat_site()
    ev = await hosted(eco, title="점심 내기")
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    page = await browser.new_page()
    await page.goto(url + f"#token={TOKEN}")
    await page.get_by_test_id("me-pen").wait_for(timeout=WAIT)
    assert await page.get_by_test_id("me-pen").inner_text() == p.pen
    p.llm.push("tell_event", event=ev, text="참가 신청해")
    p.llm.push("reply", text="'점심 내기' 비서에게 참가 신청하라고 전했습니다")
    await page.get_by_test_id("say").fill("점심 내기 참가해 줘")
    await page.get_by_test_id("send").click()
    await page.get_by_test_id("msg-agent").filter(has_text="참가 신청하라고 전했습니다").wait_for(timeout=WAIT)
    assert await page.get_by_test_id("msg-owner").first.inner_text() == "점심 내기 참가해 줘"
    await settle(p)
    assert any("[소유자의 지시] 참가 신청해" in x for x in asst(p).events[ev].transcript)


async def test_p6q5_the_agents_question_shows_in_the_chat_and_is_answered_with_a_button(eco, chat_site, browser):
    p, _, chat, url = await chat_site()
    page = await browser.new_page()
    await page.goto(url + f"#token={TOKEN}")
    await page.get_by_test_id("me-pen").wait_for(timeout=WAIT)
    asked = asyncio.create_task(p.owner.ask("이 대회에 참가할까요?", "친선"))
    card = page.get_by_test_id("ask-question")
    await card.wait_for(timeout=WAIT)
    assert "참가할까요" in await card.inner_text()
    await card.get_by_test_id("ask-yes").click()
    assert (await asyncio.wait_for(asked, 10)).yes
    await card.wait_for(state="detached", timeout=WAIT)


async def test_p6q5_without_the_token_the_chat_says_so(eco, chat_site, browser):
    _, _, _, url = await chat_site()
    page = await browser.new_page()
    await page.goto(url)
    await page.get_by_test_id("toast").filter(has_text="토큰").wait_for(timeout=WAIT)
