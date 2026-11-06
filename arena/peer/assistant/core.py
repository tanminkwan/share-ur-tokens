"""The basic assistant app: reads an event's natural-language rules and, for every new input (a notice change, a
message, a direct request, a signature request, an idle check), lets the LLM pick the next generic tool until it waits.
It only ever sees its AppContext. Tools are registered (tools.py); state is saved per event (state.py, event_store.py).

SOLID (re-check 2026-11-03): the assistant is the event loop and the platform-facing app; each other job is its own
part, composed here: Directory (profiles), Handles (names), LedgerView (reading the ledger), Reveals (revealed values),
Messenger (signed bodies), Toolbox (tools and their checks), Prompt (state line, system prompt), Drives (the owner's seat).
Tools work through the ToolHost interface (tools.py), which this class implements by delegating to those parts."""
from __future__ import annotations

import asyncio
import json
import os

from ...crypto import h, verify
from ...llm import ask_json
from ..event_store import EventStore, FolderEventStore
from ..elements import element_tools
from ..events import announce_event, event_times, schedule_event_times
from ..plugin import ASSISTANT_APP_ID, Decision, MessageHead
from ..scheduler import fmt_time
from .directory import Directory
from .drives import Drives
from ..endorsements import tokens_of
from .timeline import Timeline
from .waiting_calls import TIMER as WAITING_TIMER, WaitingCalls
from .handles import HEX64, Handles  # noqa: F401  (HEX64 kept importable from here)
from .ledger_view import LedgerView
from .messenger import Messenger
from .prompt import Prompt
from .reveals import Reveals
from .state import EventState
from .toolbox import Toolbox
from .tools import Tool, default_tools


class EventAssistant:
    name, version, app_id = "assistant", "1.0", ASSISTANT_APP_ID
    SETTLED_NOTE = LedgerView.SETTLED_NOTE
    DRIVES = Drives.ALL
    READ_ONLY = Drives.READ_ONLY

    def __init__(self, settings, group: str = "public", store: EventStore | None = None, tools: list[Tool] | None = None):
        self.s, self.group, self._store_given = settings, group, store
        self.events: dict[str, EventState] = {}
        self._stores: dict[str, EventStore] = {}
        self.directory = Directory(group)
        self.handles = Handles(settings, self.directory)
        self.ledger = LedgerView(settings, self.handles, self.directory)
        self.reveals = Reveals(settings, self.handles, self.ledger)
        self.messenger = Messenger()
        self.prompt = Prompt(self.handles)
        self.drives = Drives(settings)
        self.waiting = WaitingCalls(settings)
        self.timeline = Timeline(settings, self.handles)
        self.toolbox = Toolbox(self.handles, tools if tools is not None else default_tools() + element_tools())
        self.tools = self.toolbox.tools

    def add_tool(self, tool: Tool) -> None:
        """extend the assistant without changing it"""
        self.toolbox.add(tool)

    # ---------------- capabilities (the platform-facing app) ----------------
    def offers(self):
        out = []
        for st in self.events.values():
            if st.joined:
                out += [r for r in st.offer_roles if r not in out]
        return out

    def ops(self):
        return {"event_message": self._op_message, "attest_request": self._op_attest_request, "attest_signature": self._op_attest_signature}

    async def accept_role(self, ctx, role, request):
        st = self.events.get(request.get("event_id"))
        if st is None:
            return None
        ok = st.joined and request.get("rules_hash") == st.rules_hash
        return Decision(ok, "참가 신청한 이벤트, 같은 규칙" if ok else "참가 신청하지 않았거나 규칙이 다른 계약")

    async def on_request(self, ctx, request, sender):
        st = self.events.get(request.get("event_id"))
        if st:
            st.peers[sender] = request.get("issuer_url", st.peers.get(sender))
            await self.directory.refresh(ctx)
            self.timeline.received(ctx, st, sender, "request", request.get("text", ""))
            await self.feed(ctx, st.event_id, f"[직접 요청] 보낸 이 pub={sender}\n{request.get('text', '')}\n"
                                              f"data={json.dumps(request.get('data', {}), ensure_ascii=False)}")

    async def start(self, ctx):
        restored = await self.restore(ctx)
        if restored:
            ctx.log.emit("assistant", ctx.pen, f"참여 중인 이벤트 {restored}건을 로컬에서 불러와 이어 감")

        async def loop():
            last_ledger = 0.0
            while True:
                try:
                    if ctx.clock() - last_ledger >= self.s.assistant_ledger_watch_sec:
                        last_ledger = ctx.clock()
                        await self.ledger_check(ctx)
                    await self.idle_check(ctx)
                except Exception as e:
                    ctx.log.emit("assistant", ctx.pen, f"점검 실패: {type(e).__name__}: {e}")
                await asyncio.sleep(self.s.assistant_watch_sec)
        self._watch = asyncio.create_task(loop())

    def busy(self) -> bool:
        return any(st.task is not None and not st.task.done() for st in self.events.values())

    # ---------------- evaluating items handed over (EvaluationProvider, the evaluation element's fallback judge) ----------------
    EVALUATION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdicts"], "properties": {"verdicts": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "score", "comment"],
                                   "properties": {"id": {"type": "string"}, "score": {"type": "number"}, "comment": {"type": "string"}}}}}}

    async def evaluate(self, ctx, items, request) -> list:
        """judge items by the event's natural-language rules: a score (1-10) and one sentence each; ids are short refs"""
        st = self.events.get(request.get("event_id"))
        ids = {it["content_hash"][:self.s.assistant_ref_len]: it["content_hash"] for it in items}
        listing = "\n".join(f"- {it['content_hash'][:self.s.assistant_ref_len]}: {it['content']}" for it in items)
        d = await ask_json(ctx.llm, ctx.log, ctx.pen, fallback=lambda: {"verdicts": []}, schema=self.EVALUATION_SCHEMA, effort=self.s.assistant_effort,
                           system=("당신은 이 이벤트의 평가자 비서입니다. 아래 이벤트 규칙에 따라 각 항목에 1~10점과 한 문장 의견을 주세요. "
                                   "id는 목록의 값을 그대로 쓰세요.\n\n[이벤트 규칙]\n" + (st.rules if st else "")),
                           messages=[{"role": "user", "content": listing}])
        return [{"content_hash": ids[r["id"]], "score": r["score"], "comment": r["comment"]} for r in d.get("verdicts", []) if r.get("id") in ids]

    # ---------------- ToolHost (tools.py): what tools use, delegated to the parts ----------------
    def handle(self, ctx, st, pub):
        return self.handles.handle(ctx, st, pub)

    def shorten(self, ctx, st, text):
        return self.handles.shorten(ctx, st, text)

    def expand(self, st, obj):
        return self.handles.expand(st, obj)

    def _known_pubs(self, ctx, st):
        return self.handles.known_pubs(ctx, st)

    async def resolve_peer(self, ctx, st, ref, need_url=True):
        return await self.handles.resolve_peer(ctx, st, ref, need_url)

    async def check_handles(self, ctx, st, obj):
        return await self.handles.check_handles(ctx, st, obj)

    async def offers_role(self, ctx, pub, role):
        return await self.directory.offers_role(ctx, pub, role)

    async def offering_op(self, ctx, op):
        return await self.directory.offering_op(ctx, op)

    async def progress_entries(self, ctx, st):
        return await self.ledger.progress_entries(ctx, st)

    async def progress_lines(self, ctx, st):
        return await self.ledger.progress_lines(ctx, st)

    def progress_line(self, ctx, st, e):
        return self.ledger.progress_line(ctx, st, e)

    async def attest_precheck(self, ctx, st, kind, subject, pubs):
        return await self.ledger.attest_precheck(ctx, st, kind, subject, pubs)

    def reveal_records(self, obj):
        return self.reveals.records(obj)

    async def fill_reveals(self, ctx, st, obj):
        return await self.reveals.fill(ctx, st, obj)

    async def verify_reveals(self, ctx, st, obj):
        return await self.reveals.verify(ctx, st, obj)

    def sign_body(self, ctx, body):
        return self.messenger.sign_body(ctx, body)

    async def post(self, ctx, st, url, op, body, pub=None):
        return await self.messenger.post(ctx, st, url, op, body, pub)

    async def send(self, ctx, st, to_url, text, data, pub=None):
        return await self.messenger.send(ctx, st, to_url, text, data, pub)

    # ---------------- persistence ----------------
    def store(self, ctx) -> EventStore:
        if self._store_given is not None:
            return self._store_given
        if ctx.pub not in self._stores:
            self._stores[ctx.pub] = FolderEventStore(os.path.join(ctx.data_dir, "events"))
        return self._stores[ctx.pub]

    def save(self, ctx, st: EventState) -> None:
        self.store(ctx).save(st.event_id, st.to_dict(), st.secrets)

    async def restore(self, ctx) -> int:
        """reload the events this peer takes part in (after a restart) and continue from where it stopped"""
        n = 0
        for state, secrets in self.store(ctx).load_all():
            st = EventState.from_dict(state, secrets)
            self.events[st.event_id] = st
            n += 1
        return n

    # ---------------- holding an event ----------------
    async def host_event(self, ctx, *, title, kind, rules, policy, instruction, audience=None, recorder=None, elements=None, codebook=None,
                         schedule=None):
        """open an event run in the primordial way: natural-language rules, app = the basic assistant"""
        out = await announce_event(ctx, group=self.group, title=title, kind=kind, rules=rules, policy=policy,
                                   mode="assistant", apps=[], audience=audience, recorder=recorder, elements=elements, codebook=codebook,
                                   schedule=schedule)
        ev, rec = out["event_id"], out["recorder"] or {"recorder_url": "", "pub": ""}  # no recorder: a group without a ledger
        st = self.events[ev] = EventState(ev, "host", title, rules, out["rules_hash"], out["group_id"], rec["recorder_url"], rec["pub"], ctx.pub, ctx.url,
                                          policy=dict(policy), elements=dict(elements or {}))
        st.instruction = instruction
        st.event_hash, st.notice = out["event_hash"] or "", dict(out["notice"])
        st.drive = self.initial_drive(ctx)
        st.schedule = event_times(out["notice"])
        schedule_event_times(ctx, out["notice"])  # the host wakes at its own event's times too
        self.save(ctx, st)
        ctx.log.emit("assistant", ctx.pen, f"이벤트 개최 {ev} '{title}' (규칙 해시 {out['rules_hash'][:10]}, 방식 assistant{'' if st.on_ledger else ', 원장 없는 그룹'})")
        await self.feed(ctx, ev, f"[소유자의 지시] {instruction}", kind="owner")
        return ev

    # ---------------- events handed over by the platform's event router ----------------
    async def on_event(self, ctx, notice, change):
        ev = notice["notice_id"]
        st = self.events.get(ev)
        if change == "new" and st is None:
            st = self.events[ev] = EventState(ev, "participant", notice.get("title", ""), notice["rules"], h(notice["rules"].encode()),
                                              notice["group_id"], notice.get("recorder_url", ""), notice.get("recorder_pub", ""), notice["issuer_pub"],
                                              notice["issuer_url"], offer_roles=list(notice.get("policy", {}).get("roles", [])), policy=dict(notice.get("policy", {})),
                                              elements=dict(notice.get("elements") or {}), schedule=event_times(notice), drive=self.initial_drive(ctx),
                                              notice_ver=notice.get("ver", 1))
            st.peers[notice["issuer_pub"]] = notice["issuer_url"]
            st.event_hash = notice.get("event_hash", "")
            self._read_endorsements(ctx, st, notice)
            self.save(ctx, st)
            checked = ("규칙과 실행 방식이 원장에 공증된 것과 같음을 확인했다." if st.on_ledger else
                       "이 broker 그룹에는 원장이 없다: 공지는 개최자 서명만 확인했고, 이 이벤트의 일은 원장에 기록되지 않는다.")
            await self.feed(ctx, ev, f"[새 공지] '{notice.get('title', '')}' (개최자 pub={notice['issuer_pub']}). {checked}", kind="notice")
        elif st is not None and change == "updated":
            st.notice_ver = notice.get("ver", st.notice_ver)
            self._read_endorsements(ctx, st, notice)
            await self.feed(ctx, ev, f"[공지 수정] 버전 {st.notice_ver}: {notice.get('text', '')}", kind="notice")
        elif st is not None and change == "closed" and not st.notice_closed:
            st.notice_closed = True
            await self.feed(ctx, ev, "[공지 마감] 개최자가 이 이벤트의 공지를 마감했다.", kind="notice")

    def _read_endorsements(self, ctx, st, notice) -> None:
        """a notice may carry endorsement tokens (signatures off the ledger): keep those that check out for this event"""
        before = {e["endorser"] for e in st.endorsements}
        for t in tokens_of(notice):
            if t["body"]["endorser"] not in before:
                st.endorsements.append({"endorser": t["body"]["endorser"], "how": "signature", "token": t})
                self.timeline.note(ctx, st, "system", "endorse", f"{self.handles.handle(ctx, st, t['body']['endorser'])}이(가) 이 이벤트에 공동 서명했다(서명 확인)")

    async def endorse_event(self, ctx, body, request):
        """another peer asks me to co-sign its event: my owner decides (it puts my name on someone else's event)"""
        st = self.events.get(body["event_id"])
        title = st.title if st else str(request.get("title", body["event_id"]))
        who = self.handles.handle(ctx, st, body["issuer"]) if st else body["issuer"][:12]
        a = await ctx.owner.ask(f"{who}이(가) 이벤트 '{title}'에 공동 서명을 청합니다. 이 이벤트에 내 이름을 걸까요?",
                                str(request.get("text", "")))
        if st and a.yes:
            self.timeline.note(ctx, st, "owner", "endorse", "이 이벤트에 공동 서명했다")
        return Decision(a.yes, a.why)

    async def keep_endorsement(self, ctx, st, done: dict) -> dict:
        """an endorsement I asked for came in: remember it; a token goes onto the event's notice (re-posted)"""
        if not done.get("ok"):
            return done
        endorser = done["token"]["body"]["endorser"] if done.get("token") else done.get("endorser")
        st.endorsements.append({"endorser": endorser, "how": done["how"], **({"hash": done["hash"]} if done.get("hash") else {"token": done["token"]})})
        if done["how"] == "signature" and st.notice:
            st.notice = dict(st.notice, endorsements=[e["token"] for e in st.endorsements if e.get("token")],
                             ver=st.notice.get("ver", 1) + 1)  # the broker takes an update only with a newer version
            posted = await ctx.brokers[self.group].post_notice(ctx.identity, st.notice)
            done = dict(done, notice_reposted=bool(posted.get("ok")))
        self.timeline.note(ctx, st, "system", "endorse", f"{self.handles.handle(ctx, st, endorser)}이(가) 공동 서명했다({done['how']})")
        self.save(ctx, st)
        return done

    async def on_timer(self, ctx, timer):
        """the scheduler woke me at a time (P6-S3): the event's notarized schedule, or a reminder I set myself"""
        st = self.events.get(timer.get("event_id"))
        if st is None or st.closed:
            return
        d, when = timer.get("data", {}), fmt_time(timer["at"])
        if timer["kind"] == WAITING_TIMER:  # look again at calls that came back pending; tell only what was finished
            done = [r for r in await self.waiting.check(self, ctx, st) if not r.get("pending")]
            self.save(ctx, st)
            if done:
                await self.feed(ctx, st.event_id, "[기다리던 답] 상대가 답해 코드가 마저 처리했다: " + json.dumps(done, ensure_ascii=False), kind="timer")
            return
        if timer["kind"] == "remind":
            text = f"[내 예약] {when}: {d.get('note', '')} (내가 remind로 걸어 둔 시각이 되었다)"
        else:
            what = " ".join(x for x in (d.get("code", ""), d.get("subject", "")) if x)
            text = (f"[일정 시각] {when} {what}{': ' + d['note'] if d.get('note') else ''}. 원장에 공증된 이 이벤트의 일정 시각이 되었다(코드가 깨움). "
                    "규칙에 따라 지금 할 일을 하라")
        await self.feed(ctx, st.event_id, text, kind="timer")

    async def ledger_check(self, ctx):
        """new entries of others in my open events' ledger wake me up (each entry once); the first look only remembers where it is"""
        for st in list(self.events.values()):
            if st.closed:
                continue
            entries = await self.progress_entries(ctx, st)
            if not entries:
                continue
            first, top = st.ledger_seen == 0, max(e["seq"] for e in entries)
            new = [e for e in entries if e["seq"] > st.ledger_seen and not any(e.get(k) == ctx.pub for k in self.ledger.MINE) and self.ledger.concerns_me(ctx, st, e)]
            st.ledger_seen = max(st.ledger_seen, top)
            self.save(ctx, st)
            if new and not first:
                lines = [self.progress_line(ctx, st, e) for e in new]
                await self.feed(ctx, st.event_id, f"[원장 새 기록] 이 이벤트의 원장에 다른 사람의 기록이 올랐다(코드가 읽음). {self.SETTLED_NOTE}\n" + "\n".join(lines), kind="ledger")

    async def idle_check(self, ctx):
        """an open event with no input for a while: wake up and ask myself whether the rules leave something to do"""
        now = ctx.clock()
        for st in self.events.values():
            if st.closed or st.inbox or (st.task is not None and not st.task.done()) or st.idle_checks >= self.s.assistant_idle_max_checks:
                continue
            if now - st.last_input_at >= self.s.assistant_idle_sec * (2 ** st.idle_checks):
                st.idle_checks += 1
                if not st.on_ledger:
                    await self.feed(ctx, st.event_id, "[점검] 한동안 새 입력이 없다. 지금까지 주고받은 말을 보고 규칙상 지금 내가 해야 할 일이 "
                                                      "남았는지 확인하고, 있으면 하라(이 그룹에는 원장이 없다).", idle=True)
                    continue
                progress = "\n".join(await self.progress_lines(ctx, st)) or "없음"
                await self.feed(ctx, st.event_id, "[점검] 한동안 새 입력이 없다. 아래 원장 기록을 보고 규칙상 지금 내가 해야 할 일이 남았는지 "
                                                  f"확인하고, 있으면 하라. 다른 사람이 이미 한 일을 기다리고 있지 않은지도 보라.\n[진행 현황] (원장, 코드가 읽음) {self.SETTLED_NOTE}\n{progress}", idle=True)

    # ---------------- the agent loop ----------------
    async def learn_keys(self, ctx, st, text: str) -> None:
        await self.handles.learn_keys(ctx, st, text, self.ledger)

    async def feed(self, ctx, event_id: str, text: str, idle: bool = False, kind: str = "message"):
        """a new input for an event. Who handles it depends on the event's drive (P6-P4): in manual the owner gets it on the
        desk and no LLM runs; otherwise the LLM takes a turn (and the owner still hears of notices and scheduled times)"""
        st = self.events[event_id]
        if kind == "owner":
            self.timeline.note(ctx, st, "owner", "instruction", text.removeprefix("[소유자의 지시] "))
        elif kind in ("notice", "timer"):
            self.timeline.note(ctx, st, "system", kind, text.split("\n", 1)[0])
        elif kind == "ledger":  # the entries themselves, not the sentence before them
            self.timeline.note(ctx, st, "system", kind, text.split("\n", 1)[1] if "\n" in text else text)
        note = self.drives.notifier(ctx)
        if st.drive == "manual":
            if idle:
                return  # nobody to wake: the owner sees the event on the desk
            st.transcript.append(self.shorten(ctx, st, f"[입력] {text}"))
            self.save(ctx, st)
            if note and kind != "owner":
                note.notify(kind, *self.drives.title_body(self.shorten(ctx, st, text)), event_id)
            return
        if note and kind in Drives.NOTIFY_IN_AUTO:
            note.notify(kind, *self.drives.title_body(self.shorten(ctx, st, text)), event_id)
        await self.learn_keys(ctx, st, text)
        st.inbox.append(text)
        st.last_input_at = ctx.clock()
        if not idle:
            st.idle_checks = 0
        if st.task is None or st.task.done():
            st.task = asyncio.create_task(self._work(ctx, st))

    async def _work(self, ctx, st):
        while st.inbox:
            await self._turn(ctx, st, st.inbox.pop(0))

    def _tools_for(self, st) -> list[str]:
        return self.toolbox.offered(st)

    def state_line(self, ctx, st) -> str:
        """the code-made line on where this event stands (shown to the LLM, and to the owner on the desk)"""
        return self.prompt.state_line(ctx, st)

    def _system(self, ctx, st) -> str:
        return self.prompt.system(ctx, st, self.toolbox.lines(st))

    async def _turn(self, ctx, st, text):
        st.transcript.append(self.shorten(ctx, st, f"[입력] {text}"))
        allowed = self._tools_for(st)
        choose = {"type": "object", "additionalProperties": False, "required": ["thought", "tool"],
                  "properties": {"thought": {"type": "string"}, "tool": {"type": "string", "enum": allowed}}}
        for _ in range(self.s.assistant_max_steps):
            system = self._system(ctx, st)
            recent = "\n".join(st.transcript[-self.s.assistant_transcript_max:])
            d = await ask_json(ctx.llm, ctx.log, ctx.pen, fallback=lambda: {"thought": "LLM 응답 없음", "tool": "wait"},
                               system=system, schema=choose, effort=self.s.assistant_effort,
                               messages=[{"role": "user", "content": f"[지금까지]\n{recent}\n\n다음에 쓸 도구는?"}])
            name = d.get("tool", "wait")
            if name == "wait":
                st.transcript.append(f"[기다림] {d.get('thought', '')[:self.s.text_thought_chars]}")
                if d.get("thought"):
                    self.timeline.note(ctx, st, "agent", "thought", d["thought"][:self.s.text_thought_chars])
                ctx.log.emit("assistant", ctx.pen, f"[{st.event_id}] 기다림: {d.get('thought', '')[:self.s.text_log_chars]}")
                self.save(ctx, st)
                return
            tool, args = self.tools.get(name), {}
            if tool is not None and tool.args:
                args = await ask_json(ctx.llm, ctx.log, ctx.pen, fallback=lambda: {}, system=system, schema=tool.args,
                                      effort=self.s.assistant_effort,
                                      messages=[{"role": "user", "content": f"[지금까지]\n{recent}\n\n[생각] {d.get('thought', '')}\n"
                                                                            f"도구 {name}의 인자를 채우세요."}])
            inner = args.get("arguments", args.get("args")) if isinstance(args, dict) else None
            if isinstance(inner, dict) and set(args) <= {"tool", "name", "arguments", "args"}:  # {"tool": .., "arguments": {..}} -> {..}
                args = inner
            key = [name, json.dumps(args, ensure_ascii=False, sort_keys=True)]
            if st.drive == "suggest" and name not in Drives.READ_ONLY and not await self.drives.approved(
                    ctx, st, name, args, d.get("thought", ""), lambda t: self.shorten(ctx, st, t)):
                st.transcript.append(self.shorten(ctx, st, f"[소유자 거절] {name} {json.dumps(args, ensure_ascii=False)[:self.s.text_args_chars]}: "
                                                           "소유자가 이 행동을 승인하지 않았다"))
                ctx.log.emit("assistant", ctx.pen, f"[{st.event_id}] {name} 제안 → 소유자 거절")
                self.save(ctx, st)
                break
            if key == st.last_action:  # the same successful call twice in a row: do not run it again
                result = {"error": "이미 했다: 같은 도구를 같은 인자로 방금 실행했다. 결과를 보고 다음 단계로 가거나 wait"}
            else:
                result = await self._run_tool(ctx, st, name, dict(args))
                # a call that failed may be retried as it is once things changed (comparison run with-2: a reveal refused
                # before the assignment could never be retried, and the round stalled)
                failed = isinstance(result, dict) and (result.get("ok") is False or bool(result.get("error")))
                st.last_action = [] if failed else key
            self._note_action(ctx, st, "행동", name, args, result)
        self.save(ctx, st)

    def _note_action(self, ctx, st, who: str, name: str, args: dict, result) -> None:
        """one action and its result in the event's record and the log (the LLM's turn and the owner's hand alike)"""
        self.timeline.action(ctx, st, "agent" if who == "행동" else "owner", name, args, result)
        st.transcript.append(self.shorten(ctx, st, f"[{who}] {name} {json.dumps(args, ensure_ascii=False)[:self.s.text_args_chars]}"))
        st.transcript.append(self.shorten(ctx, st, f"{name} 결과: {json.dumps(result, ensure_ascii=False)[:self.s.text_result_chars]}"))
        ctx.log.emit("assistant", ctx.pen, f"[{st.event_id}] {'' if who == '행동' else who + ': '}{name} → "
                                           f"{json.dumps(result, ensure_ascii=False)[:self.s.text_log_chars]}")
        self.save(ctx, st)

    async def _run_tool(self, ctx, st, name, args):
        return await self.toolbox.run(self, ctx, st, name, args)

    # ---------------- drives (P6-P4): the owner's seat ----------------
    def allowed_drives(self, ctx) -> tuple:
        return self.drives.allowed(ctx)

    def initial_drive(self, ctx) -> str:
        return self.drives.initial(ctx)

    def set_drive(self, ctx, event_id: str, drive: str) -> dict:
        st = self.events.get(event_id)
        if st is None:
            return {"ok": False, "error": "모르는 이벤트"}
        why = self.drives.refuse(ctx, drive)
        if why:
            return {"ok": False, "error": why}
        st.drive = drive
        self.save(ctx, st)
        return {"ok": True, "drive": drive}

    def tools_view(self, st) -> list[dict]:
        return self.toolbox.owner_view(st)

    def conversation(self, ctx, st, lines: int) -> dict:
        """what a person watching an event reads: the timeline, and whom this peer may speak to in it"""
        pubs = [p for p in [st.issuer_pub, *st.peers, *st.applicants, *(c[1] for c in st.contracts)] if p and p != ctx.pub]
        seen, peers = set(), []
        for p in pubs:
            if p not in seen:
                seen.add(p)
                peers.append({"pub": p, "handle": self.handles.handle(ctx, st, p)})
        return {"timeline": st.timeline[-lines:], "peers": peers}

    async def owner_run(self, ctx, event_id: str, name: str, args: dict) -> dict:
        """the owner runs a tool by hand (any drive): the same code path as the LLM's, so the same checks hold"""
        st = self.events.get(event_id)
        if st is None:
            return {"ok": False, "error": "모르는 이벤트"}
        if name not in self._tools_for(st) or name == "wait":
            return {"ok": False, "error": f"이 이벤트에서 쓸 수 없는 도구: {name}"}
        args = {k: self.expand(st, v) if isinstance(v, str) else v for k, v in (args or {}).items()}
        result = await self._run_tool(ctx, st, name, dict(args))
        self._note_action(ctx, st, "소유자 행동", name, args, result)
        return result

    # ---------------- signed messages from other assistants ----------------
    async def _op_message(self, ctx, msg, head: MessageHead):
        who, st = self.messenger.check(ctx, msg), self.events.get(msg.get("event_id"))
        if not who:
            return {"ok": False, "error": "signed message required"}
        if not st:
            return {"ok": False, "error": "unknown event"}
        if not self.messenger.head_ok(st, msg, head):
            return {"ok": False, "error": "group or event does not match this event"}
        st.peers[who] = msg.get("url")
        data = msg.get("data", {}) or {}
        notes = ""
        if isinstance(data, dict) and data.get("type") == "join":  # identification by code: a join counts only with this event's rules
            if data.get("rules_hash") == st.rules_hash and st.role == "host":
                if who not in st.applicants:
                    st.applicants.append(who)
                notes += f"\n[코드 확인] 참가 신청: 규칙 해시 일치, 신청자 {len(st.applicants)}명"
            else:
                notes += "\n[코드 확인] 참가 신청이 아님: 규칙 해시가 다르다"
        notes += self.reveals.summary(ctx, st, data, await self.verify_reveals(ctx, st, data))
        await self.directory.refresh(ctx)
        joined = isinstance(data, dict) and data.get("type") == "join"
        self.timeline.received(ctx, st, who, "join" if joined else "message", msg.get("text", "") or ("참가 신청" if joined else ""))
        await self.feed(ctx, st.event_id, f"[메시지] 보낸 이 pub={who}\n{msg.get('text', '')}\n"
                                          f"data={json.dumps(data, ensure_ascii=False)}{notes}")
        return {"ok": True}

    async def _op_attest_request(self, ctx, msg, head: MessageHead):
        who, st = self.messenger.check(ctx, msg), self.events.get(msg.get("event_id"))
        p = msg.get("payload", {})
        if not who or not st or not self.messenger.head_ok(st, msg, head) or who not in p.get("parties", []) or ctx.pub not in p.get("parties", []) \
                or p.get("event_id") != st.event_id or p.get("group_id") != st.group_id:
            return {"ok": False, "error": "not a valid signature request for me"}
        checks = await self.verify_reveals(ctx, st, p.get("value"))
        st.pending[msg["request_id"]] = {"payload": p, "from_pub": who, "from_url": msg.get("url"), "reveals_ok": all(ok for ok, _ in checks)}
        st.peers[who] = msg.get("url")
        await self.directory.refresh(ctx)
        self.timeline.received(ctx, st, who, "sign_request", f"공동 확인 서명 요청: {p.get('kind')} {p.get('subject') or ''}".strip())
        await self.feed(ctx, st.event_id, f"[서명 요청] request_id={msg['request_id']} 제안자 pub={who}\n"
                                          f"kind={p.get('kind')} subject={p.get('subject')} parties={p.get('parties')}\n"
                                          f"value={json.dumps(p.get('value'), ensure_ascii=False)}{self.reveals.summary(ctx, st, p.get('value'), checks)}")
        return {"ok": True}

    async def _op_attest_signature(self, ctx, msg, head: MessageHead):
        who, st = self.messenger.check(ctx, msg), self.events.get(msg.get("event_id"))
        prop = st.proposals.get(msg.get("request_id")) if st else None
        if not who or not prop or not self.messenger.head_ok(st, msg, head) or who not in prop["payload"]["parties"]:
            return {"ok": False, "error": "unknown proposal or party"}
        if msg.get("declined"):
            await self.directory.refresh(ctx)
            self.timeline.received(ctx, st, who, "declined", f"공동 확인 거절: {msg.get('reason', '')}")
            await self.feed(ctx, st.event_id, f"[공동 확인 거절] request_id={msg['request_id']} 거절한 이 pub={who} 이유: {msg.get('reason', '')}")
            return {"ok": True}
        if not verify(who, prop["payload"], msg.get("attest_sig", "")):
            return {"ok": False, "error": "bad signature"}
        prop["sigs"][who] = msg["attest_sig"]
        if set(prop["sigs"]) == set(prop["payload"]["parties"]):
            r = await ctx.recorder(st.recorder_url).record("attest", prop["payload"], prop["sigs"])
            ctx.receipts.keep(r, "attest", prop["payload"], expected_recorder=st.recorder_pub)
            await self.feed(ctx, st.event_id, (f"[공동 확인 기록됨] request_id={msg['request_id']} hash={r['hash']}" if r.get("ok")
                                               else f"[공동 확인 기록 실패] request_id={msg['request_id']} {r.get('error')}"))
        return {"ok": True}
