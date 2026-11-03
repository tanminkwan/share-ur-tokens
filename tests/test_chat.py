"""P6-Q3, P6-Q4: the chat app (bundled, not required). A person talks with their own agent; the agent acts only through
the owner's use cases (tell an event's assistant, answer a pending question when the person answers in words, change a
drive, open an event). Scripted LLM double only."""
import asyncio

import httpx

from arena.bundled.chat import ChatApp
from arena.bundled.chat.api import build_chat_api
from arena.bundled.owner_service import OwnerService
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_desk import desk_peer, hosted

TOKEN = "chat-t0ken"


async def chat_peer(e, name="me"):
    p, desk = await desk_peer(e, name, llm=True)
    chat = ChatApp(OwnerService(p, desk), e.s, "127.0.0.1", 0, TOKEN)
    p.apps.append(chat)
    p._register_one(chat, builtin=False)
    chat.bind(p.ctx(chat))
    return p, desk, chat


async def test_p6q4_the_agent_answers_in_words_after_looking(eco):
    p, _, chat = await chat_peer(eco)
    ev = await hosted(eco, title="점심 내기")
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    p.llm.push("events")
    p.llm.push("reply", text="'점심 내기'에 참가자로 들어와 있습니다")
    out = await chat.say("지금 무슨 이벤트 있어?")
    assert [m["who"] for m in out] == ["owner", "agent"] and "점심 내기" in out[1]["text"]
    assert [m["text"] for m in chat.messages][-2:] == ["지금 무슨 이벤트 있어?", "'점심 내기'에 참가자로 들어와 있습니다"]
    assert ev in str(p.llm.prompts[-2]["system"])  # the agent sees my events in its prompt


async def test_p6q4_the_agent_passes_the_persons_words_to_the_event(eco):
    p, _, chat = await chat_peer(eco)
    ev = await hosted(eco)
    p.llm.push("wait")
    await p.events.watch_once(p.ctx(p.events))
    await settle(p)
    p.llm.push("tell_event", event=ev, text="참가 신청해")
    p.llm.push("reply", text="이벤트 비서에게 전했습니다")
    await chat.say("그 공모 참가 신청해 줘")
    await settle(p)
    assert any("[소유자의 지시] 참가 신청해" in x for x in asst(p).events[ev].transcript)


async def test_p6q4_a_pending_question_is_answered_in_words(eco):
    p, desk, chat = await chat_peer(eco)
    asked = asyncio.create_task(p.owner.ask("이 대회에 참가할까요?", "친선"))
    await asyncio.sleep(0)
    q = desk.list()[0]
    assert q in [x for x in desk.list()] and chat.feed()["items"][0]["kind"] == "question"
    p.llm.push("answer_item", item=q.id, yes=True, why="주말이라 좋다")
    p.llm.push("reply", text="참가하겠다고 답했습니다")
    await chat.say("응, 참가할게")
    a = await asyncio.wait_for(asked, 5)
    assert a.yes and a.why == "주말이라 좋다"


async def test_p6q4_the_chat_api_needs_its_token_and_answers_items(eco):
    p, desk, chat = await chat_peer(eco)
    app = build_chat_api(chat, TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://chat") as hc:
        assert (await hc.get("/api/feed")).status_code == 401
        auth = {"Authorization": f"Bearer {TOKEN}"}
        asked = asyncio.create_task(p.owner.ask("할까요?"))
        await asyncio.sleep(0)
        feed = (await hc.get("/api/feed", headers=auth)).json()
        assert feed["me"]["operator"] == "agent" and feed["items"][0]["kind"] == "question"
        r = await hc.post(f"/api/items/{feed['items'][0]['id']}/answer", json={"yes": False, "why": "싫다"}, headers=auth)
        assert r.json()["ok"] and not (await asyncio.wait_for(asked, 5)).yes
        p.llm.push("reply", text="안녕하세요")
        said = (await hc.post("/api/say", json={"text": "안녕"}, headers=auth)).json()["messages"]
        assert [m["text"] for m in said] == ["안녕", "안녕하세요"]
