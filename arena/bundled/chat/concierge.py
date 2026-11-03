"""The chat agent (concierge): one level above the per-event assistants. It knows all my events and my desk, talks with
the owner in plain words, and acts only through the owner's use cases (OwnerService): tell an event's assistant what the
owner said, answer a pending question when the owner answers it in words, change a drive, open an event. It never signs
or records anything itself; every check stays in the peer's code."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Callable

from ...llm import ask_json
from ..owner_service import OwnerService

S = {"type": "string"}
B = {"type": "boolean"}


def _obj(**props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


@dataclass(frozen=True)
class ChatTool:
    name: str
    description: str
    args: dict | None
    run: Callable[..., Awaitable[dict]]  # run(service, **args)


async def _events(svc):
    return {"events": svc.state()["events"]}


async def _event_status(svc, event):
    ev = svc.find_event(event)
    d = svc.event(ev) if ev else None
    if d is None:
        return {"error": f"모르는 이벤트: {event}"}
    return {k: d[k] for k in ("event_id", "title", "role", "drive", "closed", "state_line")} | {"recent": d["transcript"][-8:],
                                                                                            "schedule": d["schedule"]}


async def _tell_event(svc, event, text):
    ev = svc.find_event(event)
    return await svc.tell(ev, text) if ev else {"error": f"모르는 이벤트: {event}"}


async def _answer_item(svc, item, yes, why):
    it = svc.item(item)
    if it is None or it.status != "open":
        return {"error": f"열린 알림이 아니다: {item}"}
    answer = {"approve": yes} if it.kind == "suggestion" else {"yes": yes, "why": why}
    return svc.answer(item, answer)


async def _set_drive(svc, event, drive):
    ev = svc.find_event(event)
    return svc.set_drive(ev, drive) if ev else {"error": f"모르는 이벤트: {event}"}


async def _host_event(svc, title, kind, rules, roles):
    return await svc.host({"title": title, "kind": kind, "rules": rules, "policy": {"roles": [r.strip() for r in roles.split(",") if r.strip()]}})


async def _reply(svc, text):
    return {"ok": True}


TOOLS = (
    ChatTool("reply", "{text}: 소유자에게 말로 답한다. 이번 말에 대해 할 일을 다 했으면 이것으로 끝낸다", _obj(text=S), _reply),
    ChatTool("events", "{}: 내 이벤트 목록(제목, 역할, 운전석, 닫힘)", None, _events),
    ChatTool("event_status", "{event}: 이벤트 하나의 지금 상태(코드가 적은 상태 줄, 최근 기록, 일정). event는 id나 제목", _obj(event=S), _event_status),
    ChatTool("tell_event", "{event, text}: 소유자가 한 말을 그 이벤트의 비서에게 지시로 전한다(비서가 그 이벤트의 운전석대로 움직인다)",
             _obj(event=S, text=S), _tell_event),
    ChatTool("answer_item", "{item, yes, why}: 소유자가 말로 답한 열린 물음·제안에 답한다(item은 알림 id). 소유자가 분명히 답했을 때만",
             _obj(item=S, yes=B, why=S), _answer_item),
    ChatTool("set_drive", "{event, drive}: 이벤트의 운전석을 바꾼다(auto · suggest · manual). 소유자가 바라면", _obj(event=S, drive=S), _set_drive),
    ChatTool("host_event", "{title, kind, rules, roles}: 소유자가 바라는 이벤트를 연다(roles는 쉼표로)", _obj(title=S, kind=S, rules=S, roles=S), _host_event),
)


class Concierge:
    def __init__(self, service: OwnerService, settings, tools=TOOLS):
        self.svc, self.s, self.tools = service, settings, {t.name: t for t in tools}

    def _system(self) -> str:
        st = self.svc.state()
        me = st["me"]
        events = "\n".join(f"- {e['event_id']} '{e['title']}' ({'개최' if e['role'] == 'host' else '참가'}, 운전석 {e['drive']}"
                           f"{', 닫힘' if e['closed'] else ''})" for e in st["events"]) or "- 없음"
        items = "\n".join(f"- {it['id']} [{it['kind']}] {it['title'][:120]}{' (이벤트 ' + it['event_id'] + ')' if it['event_id'] else ''}"
                          for it in self.svc.items("open")) or "- 없음"
        tools = "\n".join(f"- {t.name} {t.description}" for t in self.tools.values())
        return (f"당신은 peer '{me['pen']}'의 대화 비서입니다. 소유자(사람)와 한국어로 짧고 분명하게 대화합니다. 소유자가 말한 일만 하고, "
                "권리와 책임이 생기는 일(참가, 계약, 서명)은 소유자가 분명히 원할 때만 이벤트 비서에게 전합니다. 모르면 묻습니다. "
                "서명과 원장 기록은 하지 않습니다(이벤트 비서와 코드의 일입니다).\n\n"
                f"[내 이벤트]\n{events}\n\n[열린 알림]\n{items}\n\n[쓸 수 있는 도구]\n{tools}\n\n"
                "먼저 도구 하나를 고르면 그 도구의 인자를 따로 묻습니다. 소유자에게 답할 때는 reply를 씁니다.")

    async def respond(self, ctx, history: list[dict], text: str) -> list[str]:
        """one turn of the chat: the owner said `text`; returns what the agent says back"""
        recent = "\n".join(f"{'소유자' if m['who'] == 'owner' else '비서'}: {m['text']}" for m in history[-self.s.chat_history_lines:])
        work, said = [], []
        choose = {"type": "object", "additionalProperties": False, "required": ["thought", "tool"],
                  "properties": {"thought": S, "tool": {"type": "string", "enum": list(self.tools)}}}
        for _ in range(self.s.chat_max_steps):
            system = self._system()
            prompt = f"[지금까지 대화]\n{recent}\n소유자: {text}\n\n[이번 차례에 한 일]\n" + ("\n".join(work) or "없음") + "\n\n다음에 쓸 도구는?"
            d = await ask_json(ctx.llm, ctx.log, ctx.pen, fallback=lambda: {"thought": "LLM 응답 없음", "tool": "reply"}, system=system,
                               schema=choose, effort=self.s.assistant_effort, messages=[{"role": "user", "content": prompt}])
            tool = self.tools.get(d.get("tool")) or self.tools["reply"]
            args = {}
            if tool.args:
                args = await ask_json(ctx.llm, ctx.log, ctx.pen, fallback=lambda: {"text": "지금은 답을 만들지 못했습니다."} if tool.name == "reply" else {},
                                      system=system, schema=tool.args, effort=self.s.assistant_effort,
                                      messages=[{"role": "user", "content": f"{prompt}\n\n[생각] {d.get('thought', '')}\n도구 {tool.name}의 인자를 채우세요."}])
            if tool.name == "reply":
                said.append(str(args.get("text", "")).strip() or "알겠습니다.")
                break
            missing = [k for k in (tool.args or {}).get("required", []) if k not in args]
            result = {"error": f"인자가 맞지 않음: {', '.join(missing)} 없음"} if missing else await tool.run(self.svc, **{k: args[k] for k in (tool.args or {}).get("properties", {}) if k in args})
            work.append(f"{tool.name} {json.dumps(args, ensure_ascii=False)[:300]} → {json.dumps(result, ensure_ascii=False)[:800]}")
            ctx.log.emit("chat", ctx.pen, f"{tool.name} → {json.dumps(result, ensure_ascii=False)[:120]}")
        if not said:
            said.append("요청하신 일을 처리했습니다." if work else "알겠습니다.")
        return said
