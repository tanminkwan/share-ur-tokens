"""The basic assistant app: reads an event's natural-language rules and, for every new input (a notice change, a
message, a direct request, a signature request, an idle check), lets the LLM pick the next generic tool until it waits.
It only ever sees its AppContext. Tools are registered (tools.py); state is saved per event (state.py, event_store.py)."""
from __future__ import annotations

import asyncio
import json
import os
import re

from ...crypto import h, pen_name, verify
from ...llm import ask_json
from ..event_store import EventStore, FolderEventStore
from ..elements import element_tools
from ..events import announce_event
from ..plugin import ASSISTANT_APP_ID, Decision, MessageHead
from .state import EventState, commit_hash, nonce
from .tools import Tool, default_tools


HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


class EventAssistant:
    name, version, app_id = "assistant", "1.0", ASSISTANT_APP_ID

    def __init__(self, settings, group: str = "public", store: EventStore | None = None, tools: list[Tool] | None = None):
        self.s, self.group, self._store_given = settings, group, store
        self.events: dict[str, EventState] = {}
        self._stores: dict[str, EventStore] = {}
        self.tools: dict[str, Tool] = {}
        for t in tools if tools is not None else default_tools() + element_tools():
            self.add_tool(t)

    def add_tool(self, tool: Tool) -> None:
        """extend the assistant without changing it"""
        if tool.name in self.tools:
            raise ValueError(f"tool {tool.name!r} registered twice")
        self.tools[tool.name] = tool

    # ---------------- capabilities ----------------
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

    # ---------------- what the LLM sees: handles and short refs, never 64-hex strings ----------------
    def _known_pubs(self, ctx, st) -> set:
        pubs = {ctx.pub, st.issuer_pub, *st.peers, *(c[1] for c in st.contracts), *st.roster}
        for req in st.pending.values():
            pubs |= set(req["payload"].get("parties", []))
        return pubs

    def handle(self, ctx, st, pub: str) -> str:
        name = pen_name(pub, ctx.settings.pen_name_prefix, ctx.settings.pen_name_len)
        st.aliases[name] = pub
        return name

    def shorten(self, ctx, st, text: str) -> str:
        """public keys become 필명-xxxxxx, other 64-hex values become #xxxxxxxxxx; the code remembers what they stand for"""
        pubs = self._known_pubs(ctx, st)

        def one(m):
            full = m.group(0)
            if full in pubs:
                return self.handle(ctx, st, full)
            ref = "#" + full[:self.s.assistant_ref_len]
            st.aliases[ref] = full
            return ref
        return HEX64.sub(one, text)

    def expand(self, st, obj):
        """the reverse, on what the LLM hands to a tool: exact handles and short refs become the real values"""
        if isinstance(obj, str):
            return st.aliases.get(obj.strip(), obj)
        if isinstance(obj, list):
            return [self.expand(st, x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.expand(st, v) for k, v in obj.items()}
        return obj

    async def offers_role(self, ctx, pub: str, role: str) -> bool:
        """does this peer's posted profile offer the role (a service peer takes roles it advertises, without applying)?"""
        try:
            profiles = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return False
        return any(p["pub"] == pub and role in p.get("offers", []) for p in profiles)

    async def offering_op(self, ctx, op: str) -> list[str]:
        """public keys of the peers whose posted profile offers the service op (P6-A5)"""
        try:
            profiles = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return []
        return [p["pub"] for p in profiles if op in ((p.get("service") or {}).get("ops") or {})]

    async def resolve_peer(self, ctx, st, ref: str, need_url: bool = True) -> tuple[str | None, str | None]:
        """a peer named by handle, public key or address -> (public key, address); unknown handles are looked up on the broker"""
        ref = self.expand(st, str(ref))
        if ref in (ctx.pub, ctx.pen):
            return ctx.pub, ctx.url
        if ref.startswith(("http://", "https://", "mem://")):
            return next((p for p, u in st.peers.items() if u == ref), None), ref
        pub = ref if HEX64.fullmatch(ref) else None
        if pub and (pub in st.peers or not need_url):
            return pub, st.peers.get(pub)
        try:
            profiles = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            profiles = []
        for p in profiles:
            if p["pub"] == pub or pen_name(p["pub"], ctx.settings.pen_name_prefix, ctx.settings.pen_name_len) == ref:
                st.peers.setdefault(p["pub"], p.get("url"))
                return p["pub"], st.peers[p["pub"]]
        return pub, None

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

    # ---------------- the event's progress, read from the ledger by code ----------------
    PEOPLE = ("author", "contractor", "issuer", "parties", "approvers")

    async def progress_entries(self, ctx, st) -> list[dict]:
        """this event's entries in public view; everyone named in them joins the roster (so they show as handles)"""
        try:
            r = await ctx.recorder(st.recorder_url).event_entries(st.event_id)
        except Exception:
            return []
        entries = r.get("entries", []) if r.get("ok") else []
        if "sealed" in st.elements:
            st.sealed_view = self._sealed_view(ctx, st, entries)
        if st.role == "host":
            await self._role_offers(ctx, st)
        for e in entries:
            if e["type"] == "assign":
                st.assignments.update(e.get("subjects", {}))
            if e["type"] == "attest":  # settled: requests and proposals I still hold for the same kind and subject are stale
                same = lambda x: x["payload"].get("kind") == e.get("kind") and x["payload"].get("subject") == e.get("subject")
                for box in (st.pending, st.proposals):
                    for k in [k for k, x in box.items() if same(x)]:
                        box.pop(k)
            for k in self.PEOPLE:
                for pub in (e.get(k) if isinstance(e.get(k), list) else [e.get(k)]):
                    if isinstance(pub, str) and HEX64.fullmatch(pub) and pub not in st.roster:
                        st.roster.append(pub)
        return entries

    async def _role_offers(self, ctx, st):
        """host: the policy roles nobody holds yet, with the peers whose posted profile offers each (a service peer takes a
        role it advertises without applying; live with-elements run 2: the host never found the referee to contract)"""
        held = {c[0] for c in st.contracts}
        open_roles = [r for r in st.policy.get("roles", []) if r not in held]
        if not open_roles:
            st.role_offers = {}
            return
        try:
            profiles = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return
        st.role_offers = {r: [p["pub"] for p in profiles if r in p.get("offers", []) and p["pub"] != ctx.pub] for r in open_roles}

    def _sealed_view(self, ctx, st, entries) -> list[str]:
        """for each sealed label of a subject I am assigned to: how many registered, and whether it may open (P6-D3)"""
        asg = {e2: v for e in entries if e["type"] == "assign" for e2, v in e.get("subjects", {}).items()}
        out = []
        for subject, parties in asg.items():
            if ctx.pub not in parties:
                continue
            labels = sorted({e["label"] for e in entries if e["type"] == "publish" and e.get("label")
                             and (e["label"] == subject or e["label"].rpartition("-")[0] == subject and e["label"].rpartition("-")[2].isdigit())})
            for label in labels:
                regs = {e["author"] for e in entries if e["type"] == "publish" and e.get("label") == label} & set(parties)
                opened = {e["author"] for e in entries if e["type"] == "reveal" and e.get("label") == label}
                state = f"공개 {len(opened)}/{len(parties)}" if opened else ("공개 가능" if len(regs) == len(parties) else "공개 기다림")
                out.append(f"봉인 {label}: 등록 {len(regs)}/{len(parties)}, {state}")
        return out

    async def progress_lines(self, ctx, st) -> list[str]:
        """one short line per entry, the latest ones only; handles and short refs instead of 64-hex"""
        return [self.progress_line(ctx, st, e) for e in (await self.progress_entries(ctx, st))[-self.s.assistant_progress_max:]]

    SIGNED_BY_ALL = ("attest", "contract")  # entries with more than one signer: the ledger records them only with every signature
    SETTLED_NOTE = "원장에 있는 항목은 필요한 서명이 모두 모여 확정된 것이다(코드 확인). 원장에 있는 공동 확인에 더 받을 서명은 없다."

    def progress_line(self, ctx, st, e) -> str:
        rest = {k: v for k, v in e.items() if k not in ("seq", "type", "hash", "rules_hash", "salt") and v not in (None, [], "")}
        mark = " · 서명 완료(당사자 전원, 원장 확정)" if e["type"] in self.SIGNED_BY_ALL else ""
        return self.shorten(ctx, st, f"{e['seq']} {e['type']} {json.dumps(rest, ensure_ascii=False)}{mark} (항목 {e['hash']})")

    async def attest_precheck(self, ctx, st, kind, subject, pubs) -> str | None:
        """the event policy's rules for a joint confirmation, checked by code before any signature request goes out"""
        pol = st.policy
        if pol.get("attest_kinds") and kind not in pol["attest_kinds"]:
            return f"이 이벤트가 허용하는 공동 확인 종류(kind)가 아니다: {kind} (허용: {', '.join(pol['attest_kinds'])})"
        need = pol.get("attest_roles", {}).get(kind)
        if need == "issuer" and pubs != [st.issuer_pub]:
            return f"'{kind}'는 개최자(issuer)가 혼자 기록하는 종류다. parties에는 개최자 한 명만 넣는다"
        entries = await self.progress_entries(ctx, st)  # contracts and assignments, as the ledger has them
        if need and need != "issuer":
            roles = {}
            for e in entries:
                if e["type"] == "contract" and e.get("contractor"):
                    roles.setdefault(e["contractor"], set()).add(e.get("role"))
            lacking = [self.handle(ctx, st, p) for p in pubs if need not in roles.get(p, set())]
            if lacking:
                return f"'{kind}'의 당사자는 모두 '{need}' 역할 계약이 있어야 한다(role): {', '.join(lacking)}"
        if kind in pol.get("assigned_kinds", []):
            assigned = st.assignments.get(subject)
            if assigned is None:
                return f"'{subject}'는 배정(assign)되지 않은 주제다. 배정된 주제: {', '.join(st.assignments) or '없음'}"
            if sorted(pubs) != sorted(assigned):
                return (f"당사자가 '{subject}'에 배정(assign)된 사람과 다르다. 배정: "
                        f"{'·'.join(self.handle(ctx, st, p) for p in assigned)}")
        return None

    async def check_handles(self, ctx, st, obj):
        """a whole string that looks like a handle but names nobody known (event, broker) is refused; known ones become keys"""
        pre, n = ctx.settings.pen_name_prefix, ctx.settings.pen_name_len
        bad = []

        async def one(x):
            if isinstance(x, dict):
                return {k: await one(v) for k, v in x.items()}
            if isinstance(x, list):
                return [await one(v) for v in x]
            if isinstance(x, str) and x.strip().startswith(pre) and len(x.strip()) == len(pre) + n:
                pub, _ = await self.resolve_peer(ctx, st, x.strip(), need_url=False)
                if not pub:
                    bad.append(x.strip())
                    return x
                return pub
            return x
        return await one(obj), bad

    # ---------------- identification and checks enforced by code ----------------
    REVEAL_KEYS = {"author", "label", "value", "salt", "publish_hash"}

    PARTIAL_KEYS = {"label", "value", "publish_hash"}  # a revealed value with its registration: a reveal record, even with fields missing

    def reveal_records(self, obj) -> list[dict]:
        """every reveal record (the platform's fixed shape) inside obj, complete or not"""
        if isinstance(obj, dict):
            if self.REVEAL_KEYS <= set(obj) or (self.PARTIAL_KEYS <= set(obj) and set(obj) <= self.REVEAL_KEYS):
                return [obj]
            return [r for v in obj.values() for r in self.reveal_records(v)]
        if isinstance(obj, list):
            return [r for v in obj for r in self.reveal_records(v)]
        return []

    REVEAL_REF = re.compile(r"^공개:(\S+):(\S+)$")

    async def fill_reveals(self, ctx, st, obj):
        """"공개:<handle>:<label>" -> my own reveal record or one I received and the code checked; returns (obj, missing refs)"""
        missing = []

        async def one(x):
            if isinstance(x, dict) and self.PARTIAL_KEYS <= set(x) and set(x) <= self.REVEAL_KEYS and not self.REVEAL_KEYS <= set(x):
                ref = self.expand(st, str(x["publish_hash"]).strip())
                prefix = ref[1:] if ref.startswith("#") else ref  # a short ref not seen yet is still the start of the hash
                on_ledger = next((e for e in await self.progress_entries(ctx, st)
                                  if e["type"] == "reveal" and str(e.get("commit", "")).startswith(prefix) and len(prefix) >= self.s.assistant_ref_len), None)
                if on_ledger:  # a partial record written by hand: completed exactly from the ledger reveal of that registration
                    return {"author": on_ledger["author"], "label": on_ledger["label"], "value": on_ledger["value"],
                            "salt": on_ledger["salt"], "publish_hash": on_ledger["commit"]}
                missing.append(f"불완전한 공개값(라벨 {x.get('label')}): 원장 공개가 없다")
                return x
            if isinstance(x, dict):
                return {k: await one(v) for k, v in x.items()}
            if isinstance(x, list):
                return [await one(v) for v in x]
            m = self.REVEAL_REF.match(x.strip()) if isinstance(x, str) else None
            if not m:
                return x
            who, label = self.expand(st, m.group(1)), m.group(2)
            if who in (ctx.pub, ctx.pen) and label in st.secrets:
                s = st.secrets[label]
                return {"author": ctx.pub, "label": label, "value": s["value"], "salt": s["salt"], "publish_hash": s["publish_hash"]}
            if f"{who}|{label}" in st.reveals:
                return dict(st.reveals[f"{who}|{label}"])
            on_ledger = next((e for e in await self.progress_entries(ctx, st)
                              if e["type"] == "reveal" and e.get("author") == who and e.get("label") == label), None)
            if on_ledger:  # opened on the ledger: already checked by the ledger against the sealed hash
                return {"author": who, "label": label, "value": on_ledger["value"], "salt": on_ledger["salt"], "publish_hash": on_ledger["commit"]}
            missing.append(x)
            return x
        return await one(obj), missing

    async def verify_reveals(self, ctx, st, obj) -> list[tuple[bool, str]]:
        """every reveal record inside obj, checked against the ledger: published by its author, in this event, hash matches"""
        out = []
        for r in self.reveal_records(obj):
            if not self.REVEAL_KEYS <= set(r):
                out.append((False, f"라벨 {r.get('label')}: 불완전한 공개값 묶음({', '.join(sorted(self.REVEAL_KEYS - set(r)))} 없음)"))
                continue
            v = await ctx.recorder(st.recorder_url).verify(str(r["publish_hash"]))
            if not (v.get("exists") and v.get("type") == "publish" and v.get("author") == r["author"] and v.get("event_id") == st.event_id):
                out.append((False, f"라벨 {r['label']}: 그 등록이 원장에 없거나 다른 사람·다른 이벤트의 등록"))
            elif v.get("content_hash") != commit_hash(str(r["label"]), r["value"], str(r["salt"]), r["author"]):
                out.append((False, f"라벨 {r['label']}: 공개값이 먼저 등록한 해시와 맞지 않음"))
            else:
                out.append((True, f"라벨 {r['label']}: 일치"))
                if r["author"] != ctx.pub:  # kept by code, so it can be referred to as 공개:<handle>:<label> and never retyped
                    st.reveals[f"{r['author']}|{r['label']}"] = {k: r[k] for k in self.REVEAL_KEYS}
        return out

    def _summary(self, ctx, st, obj, results) -> str:
        if not results:
            return ""
        bad = [why for ok, why in results if not ok]
        refs = [f"공개:{self.handle(ctx, st, r['author'])}:{r['label']}" for r in self.reveal_records(obj) if f"{r['author']}|{r['label']}" in st.reveals]
        return ((f"\n[코드 확인] 공개값 {len(results)}건 모두 원장과 일치" if not bad
                 else f"\n[코드 확인] 공개값 {len(results)}건 중 원장과 맞지 않음: {'; '.join(bad)}")
                + (f"\n[코드 보관] 공동 확인 값에는 {', '.join(refs)} 처럼 쓰면 코드가 이 공개값 묶음을 그대로 넣는다" if refs else ""))

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
    async def host_event(self, ctx, *, title, kind, rules, policy, instruction, audience=None, recorder=None, elements=None, codebook=None):
        """open an event run in the primordial way: natural-language rules, app = the basic assistant"""
        out = await announce_event(ctx, group=self.group, title=title, kind=kind, rules=rules, policy=policy,
                                   mode="assistant", apps=[], audience=audience, recorder=recorder, elements=elements, codebook=codebook)
        ev, rec = out["event_id"], out["recorder"]
        st = self.events[ev] = EventState(ev, "host", title, rules, out["rules_hash"], out["group_id"], rec["recorder_url"], rec["pub"], ctx.pub, ctx.url,
                                          policy=dict(policy), elements=dict(elements or {}))
        st.instruction = instruction
        self.save(ctx, st)
        ctx.log.emit("assistant", ctx.pen, f"이벤트 개최 {ev} '{title}' (규칙 해시 {out['rules_hash'][:10]}, 방식 assistant)")
        await self.feed(ctx, ev, f"[소유자의 지시] {instruction}")
        return ev

    # ---------------- events handed over by the platform's event router ----------------
    async def on_event(self, ctx, notice, change):
        ev = notice["notice_id"]
        st = self.events.get(ev)
        if change == "new" and st is None:
            st = self.events[ev] = EventState(ev, "participant", notice.get("title", ""), notice["rules"], h(notice["rules"].encode()),
                                              notice["group_id"], notice["recorder_url"], notice["recorder_pub"], notice["issuer_pub"],
                                              notice["issuer_url"], offer_roles=list(notice.get("policy", {}).get("roles", [])), policy=dict(notice.get("policy", {})),
                                              elements=dict(notice.get("elements") or {}),
                                              notice_ver=notice.get("ver", 1))
            st.peers[notice["issuer_pub"]] = notice["issuer_url"]
            self.save(ctx, st)
            await self.feed(ctx, ev, f"[새 공지] '{notice.get('title', '')}' (개최자 pub={notice['issuer_pub']}). 규칙과 실행 방식이 원장에 공증된 것과 같음을 확인했다.")
        elif st is not None and change == "updated":
            st.notice_ver = notice.get("ver", st.notice_ver)
            await self.feed(ctx, ev, f"[공지 수정] 버전 {st.notice_ver}: {notice.get('text', '')}")
        elif st is not None and change == "closed" and not st.notice_closed:
            st.notice_closed = True
            await self.feed(ctx, ev, "[공지 마감] 개최자가 이 이벤트의 공지를 마감했다.")

    MINE = ("author", "issuer")

    async def ledger_check(self, ctx):
        """new entries of others in my open events' ledger wake me up (each entry once); the first look only remembers where it is"""
        for st in list(self.events.values()):
            if st.closed:
                continue
            entries = await self.progress_entries(ctx, st)
            if not entries:
                continue
            first, top = st.ledger_seen == 0, max(e["seq"] for e in entries)
            new = [e for e in entries if e["seq"] > st.ledger_seen and not any(e.get(k) == ctx.pub for k in self.MINE) and self.concerns_me(ctx, st, e)]
            st.ledger_seen = max(st.ledger_seen, top)
            self.save(ctx, st)
            if new and not first:
                lines = [self.progress_line(ctx, st, e) for e in new]
                await self.feed(ctx, st.event_id, f"[원장 새 기록] 이 이벤트의 원장에 다른 사람의 기록이 올랐다(코드가 읽음). {self.SETTLED_NOTE}\n" + "\n".join(lines))

    WAKE_HOST = ("attest",)  # results are what a host collects; its own moves come by message or tool result

    def concerns_me(self, ctx, st, e) -> bool:
        """a new ledger entry worth a turn: one naming me, or (host) a joint confirmation, or (participant, when the event has
        assignments) one by someone I share an assignment with or by the issuer; without assignments, every entry"""
        named = [e.get("contractor"), *(e.get("parties") or []), *[p for v in (e.get("subjects") or {}).values() for p in v]]
        if ctx.pub in named:
            return True
        if st.role == "host":
            return e["type"] in self.WAKE_HOST
        mates = {p for v in st.assignments.values() if ctx.pub in v for p in v} - {ctx.pub}
        if not st.assignments:
            return True
        return e.get("author") in mates or e.get("issuer") == st.issuer_pub or bool(set(e.get("parties") or []) & mates)

    async def idle_check(self, ctx):
        """an open event with no input for a while: wake up and ask myself whether the rules leave something to do"""
        now = ctx.clock()
        for st in self.events.values():
            if st.closed or st.inbox or (st.task is not None and not st.task.done()) or st.idle_checks >= self.s.assistant_idle_max_checks:
                continue
            if now - st.last_input_at >= self.s.assistant_idle_sec * (2 ** st.idle_checks):
                st.idle_checks += 1
                progress = "\n".join(await self.progress_lines(ctx, st)) or "없음"
                await self.feed(ctx, st.event_id, "[점검] 한동안 새 입력이 없다. 아래 원장 기록을 보고 규칙상 지금 내가 해야 할 일이 남았는지 "
                                                  f"확인하고, 있으면 하라. 다른 사람이 이미 한 일을 기다리고 있지 않은지도 보라.\n[진행 현황] (원장, 코드가 읽음) {self.SETTLED_NOTE}\n{progress}", idle=True)

    # ---------------- the agent loop ----------------
    async def learn_keys(self, ctx, st, text: str) -> None:
        """64-hex values in an input that may be public keys I do not know yet: look them up in the event's ledger and on
        the broker, so the LLM sees one name (the handle) for one person from the start"""
        unknown = set(HEX64.findall(text)) - self._known_pubs(ctx, st) - set(st.aliases.values())
        if not unknown:
            return
        await self.progress_entries(ctx, st)  # adds everyone named in this event's ledger to the roster
        unknown -= set(st.roster)
        if not unknown:
            return
        try:
            profiles = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            profiles = []
        for p in profiles:
            if p["pub"] in unknown:
                st.roster.append(p["pub"])
                st.peers.setdefault(p["pub"], p.get("url"))

    async def feed(self, ctx, event_id: str, text: str, idle: bool = False):
        st = self.events[event_id]
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
        return [n for n, t in self.tools.items() if (st.role == "host" or not t.host_only) and (st.role != "host" or not t.participant_only)
                and (not st.closed or t.after_close) and (t.element is None or t.element in st.elements)]

    def _system(self, ctx, st) -> str:
        h = lambda pub: self.handle(ctx, st, pub)
        tools = "\n".join(f"- {n} {self.tools[n].description}" for n in self._tools_for(st))
        revealed = [k for k, v in st.secrets.items() if v.get("reveal_hash")]
        sent = [f"{k}→{'·'.join(h(p) for p in v)}" for k, v in st.sent_reveals.items()]
        mine = [k for k, v in st.assignments.items() if ctx.pub in v]
        assigned = (f"배정(원장): {'; '.join(f'{k}=' + '·'.join(h(p) for p in v) for k, v in st.assignments.items())} / "
                    f"내 배정: {', '.join(mine) or '없음'} / ") if st.assignments else ""
        sealed = (" / ".join(st.sealed_view) + " / ") if st.sealed_view else ""
        state = assigned + sealed + (f"내 먼저 등록 라벨: {', '.join(st.secrets) or '없음'} / 원장에 공개한 내 라벨: {', '.join(revealed) or '없음'} / "
                 f"내가 보낸 공개값: {', '.join(sent) or '없음'} / 내가 받은 서명 요청: {', '.join(st.pending) or '없음'} / "
                 f"내가 제안한 공동 확인: {', '.join(st.proposals) or '없음'} / 참가 신청: {'함' if st.joined else '안 함'} / 닫힘: {st.closed} / "
                 f"아는 peer: {', '.join(h(p) for p in st.peers) or '없음'} / "
                 f"이 이벤트에서 맺은 역할 계약 {len(st.contracts)}건: {', '.join(f'{c[0]}={h(c[1])}' for c in st.contracts) or '없음'}"
                 + ((f" / 참가 신청자(코드 확인) {len(st.applicants)}명: {', '.join(h(p) for p in st.applicants) or '없음'}"
                     f" / 아직 계약하지 않은 신청자: {', '.join(h(p) for p in st.applicants if p not in {c[1] for c in st.contracts}) or '없음'}"
                     + (" / 아직 계약 없는 역할: " + "; ".join(f"{r}(프로필에 내건 peer: {', '.join(h(p) for p in v) or '없음'})"
                                                         for r, v in st.role_offers.items()) if st.role_offers else "")
                     + " / 나는 개최자다(참가 신청은 참가자가 하는 일이고, 개최자는 신청자와 계약한다)") if st.role == "host" else ""))
        return (f"당신은 peer '{ctx.pen}'의 비서 에이전트입니다. 이벤트 '{st.title}'(event_id {st.event_id}, broker 그룹 {st.group_id})에 "
                f"{'개최자' if st.role == 'host' else '참가자'}로 참여합니다. 아래 이벤트 규칙을 정확히 따르세요. 규칙에 없는 일은 하지 말고, "
                "확실하지 않으면 note로 적은 뒤 wait 하세요. 소유자(사람)에게 묻는 말은 한국어로 씁니다. "
                "peer는 필명(필명-xxxxxx)으로, 해시는 #로 시작하는 짧은 참조로 부르며, 도구에도 그대로 넣으면 됩니다.\n\n[이벤트 규칙]\n" + st.rules
                + (f"\n\n[소유자의 지시] {self.shorten(ctx, st, st.instruction)}" if st.instruction else "")
                + (f"\n[등록 값] 이 이벤트에서 등록(commit)하는 값은 다음 중 하나다: {', '.join(st.policy['reveal_values'])}" if st.policy.get("reveal_values") else "") +
                f"\n\n[나] {h(ctx.pub)}\n[개최자] {h(st.issuer_pub)}\n[지금 상태] {state}\n\n[쓸 수 있는 도구]\n{tools}\n\n"
                "먼저 도구 하나를 고르면, 그 도구의 인자를 따로 묻습니다. 이번 입력에 대해 규칙이 정한 일을 다 했으면 wait를 고르세요.")

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
                st.transcript.append(f"[기다림] {d.get('thought', '')[:120]}")
                ctx.log.emit("assistant", ctx.pen, f"[{st.event_id}] 기다림: {d.get('thought', '')[:100]}")
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
            if key == st.last_action:  # the same successful call twice in a row: do not run it again
                result = {"error": "이미 했다: 같은 도구를 같은 인자로 방금 실행했다. 결과를 보고 다음 단계로 가거나 wait"}
            else:
                result = await self._run_tool(ctx, st, name, dict(args))
                # a call that failed may be retried as it is once things changed (comparison run with-2: a reveal refused
                # before the assignment could never be retried, and the round stalled)
                failed = isinstance(result, dict) and (result.get("ok") is False or bool(result.get("error")))
                st.last_action = [] if failed else key
            st.transcript.append(self.shorten(ctx, st, f"[행동] {name} {json.dumps(args, ensure_ascii=False)[:400]}"))
            st.transcript.append(self.shorten(ctx, st, f"{name} 결과: {json.dumps(result, ensure_ascii=False)[:1500]}"))
            ctx.log.emit("assistant", ctx.pen, f"[{st.event_id}] {name} → {json.dumps(result, ensure_ascii=False)[:120]}")
            self.save(ctx, st)
        self.save(ctx, st)

    async def _run_tool(self, ctx, st, name, args):
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"없는 도구: {name}"}
        if tool.host_only and st.role != "host":
            return {"error": "개최자만 쓸 수 있는 도구"}
        if st.closed and not tool.after_close:
            return {"error": "닫힌 이벤트"}
        missing = [k for k in (tool.args or {"required": []})["required"] if k not in args]
        if missing:
            return {"error": f"인자가 맞지 않음: {', '.join(missing)} 없음"}
        if tool.participant_only and st.role == "host":
            return {"error": "참가자만 쓰는 도구"}
        for k in ("data_json", "value_json", "subjects_json", "input_json"):
            if k in args:
                try:
                    args[k[:-5]] = json.loads(args.pop(k) or "{}")
                except ValueError:
                    return {"error": f"인자가 맞지 않음: {k}가 JSON이 아님"}
        args = self.expand(st, args)  # handles and short refs back to real keys and hashes
        args, unknown = await self.check_handles(ctx, st, args)
        if unknown:  # identification enforced by code: a mistyped or garbled handle never reaches the ledger
            return {"error": f"아무도 가리키지 않는 필명: {', '.join(unknown)}. 진행 현황이나 지금 상태에 나온 필명을 그대로 쓴다"}
        try:
            return await tool.run(self, ctx, st, **args)
        except TypeError as e:
            return {"error": f"인자가 맞지 않음: {e}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    # ---------------- signed messages between assistants ----------------
    def sign_body(self, ctx, body: dict) -> dict:
        b = dict(body, pub=ctx.pub, ts=ctx.clock())
        return dict(b, sig=ctx.sign(b))

    def _check(self, ctx, msg: dict) -> str | None:
        body = {k: v for k, v in msg.items() if k != "sig"}
        ok = (msg.get("pub") and abs(ctx.clock() - float(msg.get("ts", 0))) <= ctx.settings.sig_window_sec
              and verify(msg["pub"], body, msg.get("sig", "")))
        return msg["pub"] if ok else None

    @staticmethod
    def _head_ok(st, msg, head: MessageHead) -> bool:
        """group/event inside the signed body must be this event's, and the head (if any) must say the same"""
        if msg.get("group_id") != st.group_id or msg.get("event_id") != st.event_id:
            return False
        return (not head.group_id or head.group_id == st.group_id) and (not head.event_id or head.event_id == st.event_id)

    async def post(self, ctx, st, url, op, body: dict) -> dict:
        msg = self.sign_body(ctx, {"op": op, "event_id": st.event_id, "group_id": st.group_id, "url": ctx.url, **body})
        return await ctx.call(url, msg, group=st.group_id, event=st.event_id)

    async def send(self, ctx, st, to_url, text, data) -> dict:
        return await self.post(ctx, st, to_url, "event_message", {"text": text, "data": data})

    async def _op_message(self, ctx, msg, head: MessageHead):
        who, st = self._check(ctx, msg), self.events.get(msg.get("event_id"))
        if not who:
            return {"ok": False, "error": "signed message required"}
        if not st:
            return {"ok": False, "error": "unknown event"}
        if not self._head_ok(st, msg, head):
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
        notes += self._summary(ctx, st, data, await self.verify_reveals(ctx, st, data))
        await self.feed(ctx, st.event_id, f"[메시지] 보낸 이 pub={who}\n{msg.get('text', '')}\n"
                                          f"data={json.dumps(data, ensure_ascii=False)}{notes}")
        return {"ok": True}

    async def _op_attest_request(self, ctx, msg, head: MessageHead):
        who, st = self._check(ctx, msg), self.events.get(msg.get("event_id"))
        p = msg.get("payload", {})
        if not who or not st or not self._head_ok(st, msg, head) or who not in p.get("parties", []) or ctx.pub not in p.get("parties", []) \
                or p.get("event_id") != st.event_id or p.get("group_id") != st.group_id:
            return {"ok": False, "error": "not a valid signature request for me"}
        checks = await self.verify_reveals(ctx, st, p.get("value"))
        st.pending[msg["request_id"]] = {"payload": p, "from_pub": who, "from_url": msg.get("url"), "reveals_ok": all(ok for ok, _ in checks)}
        st.peers[who] = msg.get("url")
        await self.feed(ctx, st.event_id, f"[서명 요청] request_id={msg['request_id']} 제안자 pub={who}\n"
                                          f"kind={p.get('kind')} subject={p.get('subject')} parties={p.get('parties')}\n"
                                          f"value={json.dumps(p.get('value'), ensure_ascii=False)}{self._summary(ctx, st, p.get('value'), checks)}")
        return {"ok": True}

    async def _op_attest_signature(self, ctx, msg, head: MessageHead):
        who, st = self._check(ctx, msg), self.events.get(msg.get("event_id"))
        prop = st.proposals.get(msg.get("request_id")) if st else None
        if not who or not prop or not self._head_ok(st, msg, head) or who not in prop["payload"]["parties"]:
            return {"ok": False, "error": "unknown proposal or party"}
        if msg.get("declined"):
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
