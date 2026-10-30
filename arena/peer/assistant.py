"""The basic assistant: the primordial way to hold or join an event.

An event's rules are natural language in its notice; their hash is notarized in the event declaration and in every
role contract. Each peer's basic assistant reads the rules and, for every new input (a notice, a message, a direct
request, a signature request), lets the LLM pick the next action among generic tools until it decides to wait.
No tool knows any kind of event. Apps are specialisations that freeze a procedure into code.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import os

from ..crypto import canon, h, pen_name, verify
from ..llm import ask_json
from .app import Decision, PeerApp
from .event_store import EventStore, FolderEventStore

def _obj(**props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


S, PARTY = {"type": "string"}, _obj(pub={"type": "string"}, url={"type": "string"})
# each tool's argument shape; free-form JSON travels as a string field (*_json) and is parsed by the tool runner
TOOL_ARGS: dict[str, dict | None] = {
    "ask_owner": _obj(question=S), "join_event": None, "contract": _obj(role=S, peer_pub=S, peer_url=S),
    "send": _obj(to_url=S, text=S, data_json=S), "solicit": _obj(targets={"type": "array", "items": S}, text=S, data_json=S),
    "publish_text": _obj(text=S), "commit": _obj(label=S, value=S), "my_reveal": _obj(label=S),
    "check_reveal": _obj(publish_hash=S, author_pub=S, label=S, value=S, salt=S), "verify": _obj(hash=S),
    "propose_attest": _obj(kind=S, subject=S, value_json=S, parties={"type": "array", "items": PARTY}),
    "cosign": _obj(request_id=S), "decline": _obj(request_id=S, reason=S), "close_event": _obj(result_hash=S),
    "note": _obj(text=S), "wait": None,
}


def commit_hash(label: str, value, salt: str, pub: str) -> str:
    return h(canon({"label": label, "value": value, "salt": salt, "pub": pub}))


def _nonce(*parts) -> str:
    import os
    return h(canon([*parts, time.time(), os.urandom(8).hex()]))[:16]


@dataclass
class EventState:
    event_id: str
    role: str  # "host" | "participant"
    title: str
    rules: str
    rules_hash: str
    group_id: str
    recorder_url: str
    recorder_pub: str
    issuer_pub: str
    issuer_url: str
    offer_roles: list = field(default_factory=list)
    transcript: list = field(default_factory=list)
    secrets: dict = field(default_factory=dict)      # label -> {value, salt, commit, publish_hash}
    pending: dict = field(default_factory=dict)      # signature requests waiting for me: id -> {payload, from_pub, from_url}
    proposals: dict = field(default_factory=dict)    # my attest proposals: id -> {payload, sigs, urls}
    peers: dict = field(default_factory=dict)        # pub -> url learned from messages and contracts
    joined: bool = False
    closed: bool = False
    notice_ver: int = 1
    notice_closed: bool = False
    inbox: list = field(default_factory=list)
    task: asyncio.Task | None = None

    KEEP = ("event_id", "role", "title", "rules", "rules_hash", "group_id", "recorder_url", "recorder_pub", "issuer_pub", "issuer_url",
            "offer_roles", "transcript", "pending", "proposals", "peers", "joined", "closed", "notice_ver", "notice_closed")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEEP}

    @classmethod
    def from_dict(cls, d: dict, secrets: dict) -> "EventState":
        st = cls(**{k: d[k] for k in cls.KEEP if k in d})
        st.secrets = dict(secrets)
        return st


# ---------------- tools: generic, no event kind anywhere ----------------
TOOLS: dict[str, tuple[str, bool]] = {
    "ask_owner": ("{question}: 소유자(사람)에게 예/아니오로 묻는다. 결과 yes, why", False),
    "join_event": ("{}: 이 이벤트에 참가 신청을 한다(개최자에게 메시지로 알림). 참가자만", False),
    "contract": ("{role, peer_pub, peer_url}: 그 peer와 이 이벤트의 역할 계약을 맺어 원장에 기록한다. 계약에는 규칙 해시가 들어간다", True),
    "send": ("{to_url, text, data_json}: 상대 peer에게 이 이벤트의 메시지를 보낸다(data_json은 JSON 객체를 담은 문자열)", False),
    "solicit": ("{targets: [url...], text, data_json}: 고른 peer들에게 직접 요청을 한 번에 보낸다(data_json은 JSON 객체 문자열)", False),
    "publish_text": ("{text}: 글을 원장에 먼저 등록한다. 결과 content_hash, publish_hash", False),
    "commit": ("{label, value}: 값에 비밀값을 붙인 해시를 원장에 먼저 등록하고 값은 숨겨 둔다. 결과 label, commit, publish_hash", False),
    "my_reveal": ("{label}: 내가 먼저 등록한 값과 비밀값을 꺼낸다(상대에게 보낼 공개값)", False),
    "check_reveal": ("{publish_hash, author_pub, label, value, salt}: 상대가 보낸 공개값이 상대가 먼저 등록한 해시와 맞는지 원장으로 확인한다. 결과 match", False),
    "verify": ("{hash}: 원장 항목이 있는지와 공개 정보를 확인한다", False),
    "propose_attest": ("{kind, subject, value_json, parties: [{pub, url}...]}: 공동 확인을 제안한다(value_json은 JSON 문자열). 당사자가 나 혼자면 바로 기록하고, 아니면 다른 당사자에게 서명 요청을 보낸다", False),
    "cosign": ("{request_id}: 받은 서명 요청에 서명해 돌려준다(내용이 내가 본 것과 같을 때만)", False),
    "decline": ("{request_id, reason}: 받은 서명 요청을 거절하고 이유를 알린다", False),
    "close_event": ("{result_hash}: 이 이벤트를 원장에서 닫고 공지를 마감한다", True),
    "note": ("{text}: 나중을 위해 메모를 남긴다", False),
    "wait": ("{}: 이번 입력에 대해 할 일을 다 했다. 다음 입력을 기다린다", False),
}


class EventAssistant(PeerApp):
    name = "assistant"

    def __init__(self, settings, group: str = "public", store: EventStore | None = None):
        self.s, self.group, self._store_given = settings, group, store
        self.events: dict[str, EventState] = {}
        self.seen: set[str] = set()
        self.since: float = 0.0  # broker time of the last board read: next time ask only for changes after it
        self._stores: dict[str, EventStore] = {}

    def store(self, peer) -> EventStore:
        if self._store_given is not None:
            return self._store_given
        if peer.identity.pub not in self._stores:
            self._stores[peer.identity.pub] = FolderEventStore(os.path.join(self.s.event_store_dir, peer.identity.pub[:16]))
        return self._stores[peer.identity.pub]

    def save(self, peer, st: EventState) -> None:
        self.store(peer).save(st.event_id, st.to_dict(), st.secrets)

    async def restore(self, peer) -> int:
        """reload the events this peer takes part in (after a restart) and continue from where it stopped"""
        n = 0
        for state, secrets in self.store(peer).load_all():
            st = EventState.from_dict(state, secrets)
            self.events[st.event_id] = st
            self.seen.add(st.event_id)
            n += 1
        return n

    # ---- platform extension points ----
    def offers(self):
        out = []
        for st in self.events.values():
            if st.joined:
                out += [r for r in st.offer_roles if r not in out]
        return out

    def ops(self):
        return {"event_message": self._op_message, "attest_request": self._op_attest_request, "attest_signature": self._op_attest_signature}

    async def accept_role(self, peer, role, request):
        st = self.events.get(request.get("event_id"))
        if st is None:
            return None
        ok = st.joined and request.get("rules_hash") == st.rules_hash
        return Decision(ok, "참가 신청한 이벤트, 같은 규칙" if ok else "참가 신청하지 않았거나 규칙이 다른 계약")

    async def on_request(self, peer, request, sender):
        st = self.events.get(request.get("event_id"))
        if st:
            st.peers[sender] = request.get("issuer_url", st.peers.get(sender))
            await self.feed(peer, st.event_id, f"[직접 요청] 보낸 이 pub={sender}\n{request.get('text', '')}\ndata={json.dumps(request.get('data', {}), ensure_ascii=False)}")

    async def start(self, peer):
        restored = await self.restore(peer)
        if restored:
            peer.log.emit("assistant", peer.pen, f"참여 중인 이벤트 {restored}건을 로컬에서 불러와 이어 감")

        async def loop():
            while True:
                try:
                    await self.watch_once(peer)
                except Exception as e:
                    peer.log.emit("assistant", peer.pen, f"게시판 확인 실패: {type(e).__name__}: {e}")
                await asyncio.sleep(self.s.assistant_watch_sec)
        self._watch = asyncio.create_task(loop())

    def busy(self) -> bool:
        return any(st.task is not None and not st.task.done() for st in self.events.values())

    # ---- holding an event (the person's instruction + rules) ----
    async def host_event(self, peer, *, title, kind, rules, policy, instruction, audience=None, recorder=None):
        broker = peer.brokers[self.group]
        gid = await peer.group_id(self.group)
        rec = recorder or (await broker.find("기록", role="record", identity=peer.identity))["peers"][0]
        ev = "ev-" + _nonce(title)[:10]
        rules_hash = h(rules.encode())
        decl = {"event_id": ev, "issuer": peer.identity.pub, "kind": kind, "policy": policy, "approvers": [], "group_id": gid, "rules_hash": rules_hash}
        r = await peer.recorder(rec["recorder_url"]).record("event", decl, {peer.identity.pub: peer.sign(decl)})
        if not r.get("ok"):
            raise RuntimeError(f"event declaration refused: {r.get('error')}")
        notice = {"notice_id": ev, "kind": kind, "title": title, "text": f"{title}: 규칙은 rules에 있다", "rules": rules, "policy": policy,
                  "until": peer.clock() + self.s.event_notice_ttl_sec, "issuer_pub": peer.identity.pub, "issuer_url": peer.config.url,
                  "event_hash": r["hash"], "recorder_pub": rec["pub"], "recorder_url": rec["recorder_url"], "group_id": gid,
                  **({"audience": audience} if audience else {})}
        posted = await broker.post_notice(peer.identity, notice)
        if not posted.get("ok"):
            raise RuntimeError(f"notice refused: {posted.get('error')}")
        self.seen.add(ev)
        self.events[ev] = EventState(ev, "host", title, rules, rules_hash, gid, rec["recorder_url"], rec["pub"], peer.identity.pub, peer.config.url,
                                     offer_roles=[])
        self.save(peer, self.events[ev])
        peer.log.emit("assistant", peer.pen, f"이벤트 개최 {ev} '{title}' (규칙 해시 {rules_hash[:10]})")
        await self.feed(peer, ev, f"[소유자의 지시] {instruction}")
        return ev

    # ---- finding events to join ----
    async def watch_once(self, peer):
        """read only what changed on the board since the last read: new notices, updated ones (ver), closed ones"""
        r = await peer.brokers[self.group].changed_notices(peer.identity, self.since)
        if not r.get("ok"):
            return
        self.since = r["now"]
        for n in r["notices"]:
            ev = n["notice_id"]
            st = self.events.get(ev)
            if st is not None:
                if n.get("closed") and not st.notice_closed:
                    st.notice_closed = True
                    await self.feed(peer, ev, "[공지 마감] 개최자가 이 이벤트의 공지를 마감했다.")
                elif n.get("ver", 1) > st.notice_ver:
                    st.notice_ver = n.get("ver", 1)
                    await self.feed(peer, ev, f"[공지 수정] 버전 {st.notice_ver}: {n.get('text', '')}")
                continue
            if ev in self.seen or "rules" not in n or n.get("issuer_pub") == peer.identity.pub or n.get("closed"):
                continue
            self.seen.add(ev)
            v = await peer.recorder(n["recorder_url"]).verify(n["event_hash"])
            if not (v.get("exists") and v.get("type") == "event" and v.get("event_id") == ev and v.get("issuer") == n["issuer_pub"]
                    and v.get("rules_hash") == h(n["rules"].encode())):
                peer.log.emit("assistant", peer.pen, f"공지 {ev}의 규칙 글이 원장에 공증된 규칙과 다름 → 무시")
                continue
            st = self.events[ev] = EventState(ev, "participant", n.get("title", ""), n["rules"], v["rules_hash"], n["group_id"], n["recorder_url"],
                                              n["recorder_pub"], n["issuer_pub"], n["issuer_url"], offer_roles=list(n.get("policy", {}).get("roles", [])),
                                              notice_ver=n.get("ver", 1))
            st.peers[n["issuer_pub"]] = n["issuer_url"]
            self.save(peer, st)
            await self.feed(peer, ev, f"[새 공지] '{n.get('title', '')}' (개최자 pub={n['issuer_pub']}). 규칙의 해시가 원장과 같음을 확인했다.")

    # ---- the agent loop ----
    async def feed(self, peer, event_id: str, text: str):
        st = self.events[event_id]
        st.inbox.append(text)
        if st.task is None or st.task.done():
            st.task = asyncio.create_task(self._work(peer, st))

    async def _work(self, peer, st):
        while st.inbox:
            await self._turn(peer, st, st.inbox.pop(0))

    def _tools_for(self, st) -> list[str]:
        return [n for n, (_, host) in TOOLS.items() if st.role == "host" or not host]

    def _system(self, peer, st) -> str:
        tools = "\n".join(f"- {n} {TOOLS[n][0]}" for n in self._tools_for(st))
        state = (f"내 먼저 등록 라벨: {', '.join(st.secrets) or '없음'} / 내가 받은 서명 요청: {', '.join(st.pending) or '없음'} / "
                 f"내가 제안한 공동 확인: {', '.join(st.proposals) or '없음'} / 참가 신청: {'함' if st.joined else '안 함'} / 닫힘: {st.closed}")
        return (f"당신은 peer '{peer.pen}'의 비서 에이전트입니다. 이벤트 '{st.title}'(event_id {st.event_id}, broker 그룹 {st.group_id})에 "
                f"{'개최자' if st.role == 'host' else '참가자'}로 참여합니다. 아래 이벤트 규칙을 정확히 따르세요. 규칙에 없는 일은 하지 말고, "
                "확실하지 않으면 note로 적은 뒤 wait 하세요. 소유자(사람)에게 묻는 말은 한국어로 씁니다.\n\n[이벤트 규칙]\n" + st.rules +
                f"\n\n[나] pub={peer.identity.pub} url={peer.config.url}\n[개최자] pub={st.issuer_pub} url={st.issuer_url}\n"
                f"[지금 상태] {state}\n\n[쓸 수 있는 도구]\n{tools}\n\n"
                "먼저 도구 하나를 고르면, 그 도구의 인자를 따로 묻습니다. 이번 입력에 대해 규칙이 정한 일을 다 했으면 wait를 고르세요.")

    async def _turn(self, peer, st, text):
        st.transcript.append(f"[입력] {text}")
        allowed = self._tools_for(st)
        choose = {"type": "object", "additionalProperties": False, "required": ["thought", "tool"],
                  "properties": {"thought": {"type": "string"}, "tool": {"type": "string", "enum": allowed}}}
        for _ in range(self.s.assistant_max_steps):
            system = self._system(peer, st)
            recent = "\n".join(st.transcript[-self.s.assistant_transcript_max:])
            d = await ask_json(peer.llm, peer.log, peer.pen, fallback=lambda: {"thought": "LLM 응답 없음", "tool": "wait"},
                               system=system, schema=choose, effort=self.s.assistant_effort,
                               messages=[{"role": "user", "content": f"[지금까지]\n{recent}\n\n다음에 쓸 도구는?"}])
            tool = d.get("tool", "wait")
            if tool == "wait":
                st.transcript.append(f"[기다림] {d.get('thought', '')[:120]}")
                self.save(peer, st)
                return
            args = {}
            if TOOL_ARGS.get(tool):
                args = await ask_json(peer.llm, peer.log, peer.pen, fallback=lambda: {}, system=system, schema=TOOL_ARGS[tool],
                                      effort=self.s.assistant_effort,
                                      messages=[{"role": "user", "content": f"[지금까지]\n{recent}\n\n[생각] {d.get('thought', '')}\n"
                                                                            f"도구 {tool}의 인자를 채우세요."}])
            result = await self._run_tool(peer, st, tool, dict(args))
            st.transcript.append(f"[행동] {tool} {json.dumps(args, ensure_ascii=False)[:400]}")
            st.transcript.append(f"{tool} 결과: {json.dumps(result, ensure_ascii=False)[:1500]}")
            peer.log.emit("assistant", peer.pen, f"[{st.event_id}] {tool} → {json.dumps(result, ensure_ascii=False)[:120]}")
            self.save(peer, st)
        self.save(peer, st)

    async def _run_tool(self, peer, st, tool, args):
        if tool not in TOOLS:
            return {"error": f"없는 도구: {tool}"}
        shape = TOOL_ARGS.get(tool) or {"required": []}
        missing = [k for k in shape["required"] if k not in args]
        if missing:
            return {"error": f"인자가 맞지 않음: {', '.join(missing)} 없음"}
        for k in ("data_json", "value_json"):
            if k in args:
                try:
                    args[k[:-5]] = json.loads(args.pop(k) or "{}")
                except ValueError:
                    return {"error": f"인자가 맞지 않음: {k}가 JSON이 아님"}
        if TOOLS[tool][1] and st.role != "host":
            return {"error": "개최자만 쓸 수 있는 도구"}
        if st.closed and tool not in ("note", "verify"):
            return {"error": "닫힌 이벤트"}
        try:
            return await getattr(self, f"_t_{tool}")(peer, st, **args)
        except TypeError as e:
            return {"error": f"인자가 맞지 않음: {e}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    # ---- signed messages between assistants ----
    def _sign(self, peer, body: dict) -> dict:
        b = dict(body, pub=peer.identity.pub, ts=peer.clock())
        return dict(b, sig=peer.sign(b))

    def _check(self, peer, msg: dict) -> str | None:
        body = {k: v for k, v in msg.items() if k != "sig"}
        ok = (msg.get("pub") and abs(peer.clock() - float(msg.get("ts", 0))) <= peer.settings.sig_window_sec
              and verify(msg["pub"], body, msg.get("sig", "")))
        return msg["pub"] if ok else None

    def _head_ok(self, peer, st, msg) -> bool:
        """group/event inside the signed body must be this event's, and the head (if any) must say the same"""
        meta = getattr(peer, "_meta", {}) or {}
        if msg.get("group_id") != st.group_id or msg.get("event_id") != st.event_id:
            return False
        return (not meta.get("group_id") or meta["group_id"] == st.group_id) and (not meta.get("event_id") or meta["event_id"] == st.event_id)

    async def _op_message(self, peer, msg):
        who, st = self._check(peer, msg), self.events.get(msg.get("event_id"))
        if not who:
            return {"ok": False, "error": "signed message required"}
        if not st:
            return {"ok": False, "error": "unknown event"}
        if not self._head_ok(peer, st, msg):
            return {"ok": False, "error": "group or event does not match this event"}
        st.peers[who] = msg.get("url")
        pen = pen_name(who, peer.settings.pen_name_prefix, peer.settings.pen_name_len)
        await self.feed(peer, st.event_id, f"[메시지] 보낸 이 {pen} pub={who} url={msg.get('url')}\n{msg.get('text', '')}\n"
                                           f"data={json.dumps(msg.get('data', {}), ensure_ascii=False)}")
        return {"ok": True}

    async def _op_attest_request(self, peer, msg):
        who, st = self._check(peer, msg), self.events.get(msg.get("event_id"))
        p = msg.get("payload", {})
        if not who or not st or not self._head_ok(peer, st, msg) or who not in p.get("parties", []) or peer.identity.pub not in p.get("parties", []) \
                or p.get("event_id") != st.event_id or p.get("group_id") != st.group_id:
            return {"ok": False, "error": "not a valid signature request for me"}
        st.pending[msg["request_id"]] = {"payload": p, "from_pub": who, "from_url": msg.get("url")}
        st.peers[who] = msg.get("url")
        await self.feed(peer, st.event_id, f"[서명 요청] request_id={msg['request_id']} 제안자 pub={who}\n"
                                           f"kind={p.get('kind')} subject={p.get('subject')} parties={p.get('parties')}\nvalue={json.dumps(p.get('value'), ensure_ascii=False)}")
        return {"ok": True}

    async def _op_attest_signature(self, peer, msg):
        who, st = self._check(peer, msg), self.events.get(msg.get("event_id"))
        prop = st.proposals.get(msg.get("request_id")) if st else None
        if not who or not prop or not self._head_ok(peer, st, msg) or who not in prop["payload"]["parties"]:
            return {"ok": False, "error": "unknown proposal or party"}
        if msg.get("declined"):
            await self.feed(peer, st.event_id, f"[공동 확인 거절] request_id={msg['request_id']} 거절한 이 pub={who} 이유: {msg.get('reason', '')}")
            return {"ok": True}
        if not verify(who, prop["payload"], msg.get("attest_sig", "")):
            return {"ok": False, "error": "bad signature"}
        prop["sigs"][who] = msg["attest_sig"]
        if set(prop["sigs"]) == set(prop["payload"]["parties"]):
            r = await peer.recorder(st.recorder_url).record("attest", prop["payload"], prop["sigs"])
            peer.receipts.keep(r, "attest", prop["payload"], expected_recorder=st.recorder_pub)
            await self.feed(peer, st.event_id, (f"[공동 확인 기록됨] request_id={msg['request_id']} hash={r['hash']}" if r.get("ok")
                                                else f"[공동 확인 기록 실패] request_id={msg['request_id']} {r.get('error')}"))
        return {"ok": True}

    # ---- tool implementations ----
    async def _record(self, peer, st, kind, payload):
        r = await peer.recorder(st.recorder_url).record(kind, payload, {peer.identity.pub: peer.sign(payload)})
        if r.get("ok"):
            peer.receipts.keep(r, kind, payload, expected_recorder=st.recorder_pub)
        return r

    async def _t_ask_owner(self, peer, st, question):
        a = await peer.owner.ask(question, st.rules)
        peer.log.emit("decide", peer.pen, f"소유자에게 물음 '{question[:40]}' → {'예' if a.yes else '아니오'}: {a.why}")
        return {"yes": a.yes, "why": a.why}

    async def _t_join_event(self, peer, st):
        if st.role == "host":
            return {"error": "개최자는 참가 신청하지 않는다"}
        st.joined = True
        r = await self._t_send(peer, st, st.issuer_url, "참가 신청", {"type": "join", "rules_hash": st.rules_hash})
        if not r.get("ok"):
            st.joined = False
        return r

    async def _t_contract(self, peer, st, role, peer_pub, peer_url):
        c = {"event_id": st.event_id, "role": role, "issuer": peer.identity.pub, "contractor": peer_pub, "nonce": _nonce(peer_pub, role),
             "group_id": st.group_id, "rules_hash": st.rules_hash}
        eng = await peer.call(peer_url, {"op": "engage", "role": role, "contract": c, "request": {"event_id": st.event_id, "rules_hash": st.rules_hash}},
                              group=st.group_id, event=st.event_id)
        if not eng.get("ok"):
            return {"ok": False, "error": eng.get("error")}
        r = await peer.recorder(st.recorder_url).record("contract", c, {peer.identity.pub: peer.sign(c), peer_pub: eng["sig"]})
        if r.get("ok"):
            st.peers[peer_pub] = peer_url
        return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}

    async def _t_send(self, peer, st, to_url, text, data=None):
        msg = self._sign(peer, {"op": "event_message", "event_id": st.event_id, "group_id": st.group_id, "text": text, "data": data or {},
                                "url": peer.config.url})
        return await peer.call(to_url, msg, group=st.group_id, event=st.event_id)

    async def _t_solicit(self, peer, st, targets, text, data=None):
        req = {"request_id": f"{st.event_id}-{_nonce(text)[:8]}", "event_id": st.event_id, "text": text, "data": data or {},
               "issuer_pub": peer.identity.pub, "issuer_url": peer.config.url, "until": peer.clock() + self.s.event_request_ttl_sec,
               "group_id": st.group_id}
        acks = await peer.solicit(list(targets), req)
        return {"request_id": req["request_id"], "acks": {u: bool(a.get("ok")) for u, a in acks.items()}}

    async def _t_publish_text(self, peer, st, text):
        p = {"author": peer.identity.pub, "content_hash": h(str(text).encode()), "event_id": st.event_id, "group_id": st.group_id}
        r = await self._record(peer, st, "publish", p)
        return {"ok": bool(r.get("ok")), "content_hash": p["content_hash"], "publish_hash": r.get("hash"), "error": r.get("error")}

    async def _t_commit(self, peer, st, label, value):
        if label in st.secrets:
            return {"error": f"라벨 {label}은 이미 먼저 등록했다", **{k: st.secrets[label][k] for k in ("commit", "publish_hash")}}
        salt = _nonce(label)
        c = commit_hash(label, value, salt, peer.identity.pub)
        p = {"author": peer.identity.pub, "content_hash": c, "event_id": st.event_id, "group_id": st.group_id}
        r = await self._record(peer, st, "publish", p)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error")}
        st.secrets[label] = {"value": value, "salt": salt, "commit": c, "publish_hash": r["hash"]}
        return {"ok": True, "label": label, "commit": c, "publish_hash": r["hash"]}

    async def _t_my_reveal(self, peer, st, label):
        s = st.secrets.get(label)
        return {"label": label, **{k: s[k] for k in ("value", "salt", "commit", "publish_hash")}} if s else {"error": f"먼저 등록한 라벨 {label}이 없다"}

    async def _t_check_reveal(self, peer, st, publish_hash, author_pub, label, value, salt):
        v = await peer.recorder(st.recorder_url).verify(publish_hash)
        if not (v.get("exists") and v.get("type") == "publish" and v.get("author") == author_pub and v.get("event_id") == st.event_id):
            return {"match": False, "reason": "그 등록이 원장에 없거나 다른 사람·다른 이벤트의 등록"}
        ok = v.get("content_hash") == commit_hash(label, value, salt, author_pub)
        return {"match": ok, **({} if ok else {"reason": "공개값이 먼저 등록한 해시와 맞지 않음"})}

    async def _t_verify(self, peer, st, hash):
        return await peer.recorder(st.recorder_url).verify(hash)

    async def _t_propose_attest(self, peer, st, kind, subject, value, parties):
        pubs = [x["pub"] for x in parties]
        p = {"event_id": st.event_id, "kind": kind, "subject": subject, "value": value, "parties": pubs, "nonce": _nonce(kind, subject),
             "group_id": st.group_id}
        if pubs == [peer.identity.pub]:
            r = await self._record(peer, st, "attest", p)
            return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}
        if peer.identity.pub not in pubs:
            return {"error": "제안하는 나도 당사자여야 한다"}
        rid = f"{st.event_id}-{_nonce(subject)[:8]}"
        st.proposals[rid] = {"payload": p, "sigs": {peer.identity.pub: peer.sign(p)}}
        acks = {}
        for x in parties:
            if x["pub"] != peer.identity.pub:
                acks[x["pub"][:8]] = bool((await peer.call(x["url"], self._sign(peer, {"op": "attest_request", "event_id": st.event_id,
                                                                                       "group_id": st.group_id, "request_id": rid, "payload": p,
                                                                                       "url": peer.config.url}), group=st.group_id, event=st.event_id)).get("ok"))
        return {"request_id": rid, "sent": acks}

    async def _t_cosign(self, peer, st, request_id):
        req = st.pending.pop(request_id, None)
        if not req:
            return {"error": f"서명 요청 {request_id}이 없다"}
        return await peer.call(req["from_url"], self._sign(peer, {"op": "attest_signature", "event_id": st.event_id, "group_id": st.group_id,
                                                                    "request_id": request_id, "attest_sig": peer.sign(req["payload"]), "url": peer.config.url}),
                               group=st.group_id, event=st.event_id)

    async def _t_decline(self, peer, st, request_id, reason):
        req = st.pending.pop(request_id, None)
        if not req:
            return {"error": f"서명 요청 {request_id}이 없다"}
        return await peer.call(req["from_url"], self._sign(peer, {"op": "attest_signature", "event_id": st.event_id, "group_id": st.group_id,
                                                                    "request_id": request_id, "declined": True, "reason": reason, "url": peer.config.url}),
                               group=st.group_id, event=st.event_id)

    async def _t_close_event(self, peer, st, result_hash):
        c = {"event_id": st.event_id, "issuer": peer.identity.pub, "result_hash": result_hash, "group_id": st.group_id}
        r = await self._record(peer, st, "close", c)
        if r.get("ok"):
            st.closed = True
            await peer.brokers[self.group].close_notice(peer.identity, st.event_id)
        return {"ok": bool(r.get("ok")), "hash": r.get("hash"), "error": r.get("error")}

    async def _t_note(self, peer, st, text):
        return {"ok": True}
