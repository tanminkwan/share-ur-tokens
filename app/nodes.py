"""A2A nodes. One node type (peer) plus the broker. Infrastructure roles (discovery, recording) and event roles
(reviewer, contestant) are behaviours a peer offers or is contracted into; the ledger is kept by a peer in the "record"
role. Every hop between nodes is a real A2A call over localhost HTTP."""
import asyncio
import json
import time

from . import llm
from .common import STORE, Identity, alias, canon, emit, h, make_agent_app, rpc, verify
from .ledger import Collector
from .personas import PERSONAS, judge_system, offline_idea, offline_review, persona_system, secretary_system

IDEA_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "idea", "first_step", "risk"],
               "properties": {"title": {"type": "string"}, "idea": {"type": "string"},
                              "first_step": {"type": "string"}, "risk": {"type": "string"}}}
SELECT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["selected"],
                 "properties": {"selected": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["pub", "reason"],
                     "properties": {"pub": {"type": "string"}, "reason": {"type": "string"}}}}}}


# ---------------- broker (discovery role; the only seeded address in the network) ----------------
class Broker:
    """Discovery only: indexes self-descriptions, matches a request to peers by context, relays a call.
    It never sees an idea or a ledger entry. It has its own key and signs the answer sheets it returns."""

    def __init__(self, port):
        self.ads, self.port, self.id = {}, port, Identity()
        self.app = make_agent_app("broker", "context-based discovery (voluntary role, seed address)", port, ["advertise", "call", "find"], self.handle)

    async def handle(self, r):
        if r["op"] == "advertise":
            ad = r["ad"]
            if not verify(ad["pub"], ad["profile"], ad["sig"]):
                return {"ok": False, "error": "bad signature"}
            known = ad["pub"] in self.ads
            self.ads[ad["pub"]] = dict(ad["profile"], pub=ad["pub"], url=ad["url"])
            emit("broker", "broker", f"{alias(ad['pub'])} 프로필 {'갱신' if known else '등록'}(v{ad['profile'].get('ver', 1)})"
                 + (f" 역할 공개: {','.join(ad['profile']['offers'])}" if ad["profile"].get("offers") else ""))
            return {"ok": True}
        if r["op"] == "call":
            return await self.call(r)
        if r["op"] == "find":  # context-based lookup, no notification
            cands = [a for a in self.ads.values() if a["pub"] != r["requester_pub"] and a.get("until", 1e18) > time.time()]  # offers expire
            chosen = await self.select(r["text"], cands, 1, 3, "요청에 가장 잘 맞는 사람 1~3명만 고르세요. 목록의 '공개한 제공 역할'은 그 사람이 자발적으로 맡겠다고 공개한 역할입니다.")
            emit("broker", "broker", f"'{r['text'][:30]}' 탐색 → {', '.join(alias(s['pub']) for s in chosen)}")
            return {"ok": True, "peers": [dict(alias=alias(s["pub"]), pub=s["pub"], peer_url=self.ads[s["pub"]]["url"],
                                               offers=self.ads[s["pub"]].get("offers", []), reason=s["reason"]) for s in chosen]}
        return {"ok": False, "error": "unknown op"}

    async def select(self, text, cands, min_n, fb_n, instruction):
        listing = "\n".join(f"- {a['pub']}: {a['summary']}" + (f" (공개한 제공 역할: {','.join(a['offers'])})" if a.get("offers") else "") for a in cands)

        def fallback():  # character-bigram overlap between the request and each profile
            def bg(s): s = s.replace(" ", ""); return {s[i:i + 2] for i in range(len(s) - 1)}
            q = bg(text)
            scored = sorted(cands, key=lambda a: -len(q & bg(a["summary"] + " ".join(a.get("offers", [])))) / (len(bg(a["summary"])) or 1))
            return {"selected": [{"pub": a["pub"], "reason": "관심 분야 키워드 유사(오프라인 매칭)"} for a in scored[:fb_n]]}

        sel = await llm.ask_json(
            actor="broker", model=llm.AGENT_MODEL, schema=SELECT_SCHEMA, fallback=fallback,
            system=f"당신은 사내 중개 broker입니다. 요청과 맥락상 맞는 사람을 목록에서 고릅니다. {instruction} 이유는 한 줄로 쓰세요. pub 값은 목록의 값을 그대로 쓰세요.",
            user=f"[요청]\n{text}\n\n[후보]\n{listing}")
        return [s for s in sel["selected"] if s["pub"] in self.ads and any(s["pub"] == c["pub"] for c in cands)]

    async def call(self, r):
        cands = [a for a in self.ads.values() if a["pub"] not in (r["requester_pub"], r.get("recorder_pub"))]
        chosen = await self.select(r["text"], cands, 6, max(6, len(cands) * 2 // 3),
                                   "공모 내용과 맥락상 의견을 줄 만한 사람을 고르세요. 관련성이 조금이라도 있으면 포함하고, 서로 다른 관점이 모이도록 최소 6명 이상 고르세요.")
        emit("broker", "broker", f"공모 {r['call_id']} → {len(chosen)}명에게 전달 (맥락 매칭)")

        async def notify(s):
            a = self.ads[s["pub"]]
            await rpc(a["url"], {"op": "call_for_ideas", "call_id": r["call_id"], "text": r["text"],
                                 "requester_url": r["requester_url"], "requester_pub": r["requester_pub"],
                                 "recorder_url": r["recorder_url"], "recorder_pub": r["recorder_pub"]})
            return {"alias": alias(a["pub"]), "peer_url": a["url"], "reason": s["reason"]}

        sheet = list(await asyncio.gather(*(notify(s) for s in chosen)))
        return {"ok": True, "answer_sheet": sheet, "broker_pub": self.id.pub, "sheet_sig": self.id.sign(sheet)}


# ---------------- event peer ("나", the requester) ----------------
class Requester:
    def __init__(self, port, broker_url):
        self.id, self.port, self.broker_url = Identity(), port, broker_url
        self.url = f"http://127.0.0.1:{port}"
        self.calls, self.ideas, self.adopted, self.reviews = {}, {}, set(), {}
        self.app = make_agent_app("requester-me", "the person who posts the idea contest", port, ["submit_idea"], self.handle)

    def ledger_url(self, call_id):
        return self.calls[call_id]["recorder"]["peer_url"]

    async def recruit(self, call_id, text, role, need):
        """discover a peer that publicly offers `role` (via broker), contact it directly, sign a role contract.
        The contract is recorded on the event's recorder; for the recorder role itself, on the newly recruited one."""
        res = await rpc(self.broker_url, {"op": "find", "requester_pub": self.id.pub, "text": need})
        label = {"record": "기록자", "review": "심사자"}[role]
        for c in res.get("peers", []):
            if role not in c.get("offers", []):
                continue
            p = {"call_id": call_id, "role": role, "issuer": self.id.pub, "contractor": c["pub"],
                 "nonce": h(f"{call_id}{role}{c['pub']}{time.time()}".encode())[:12]}
            emit("contract", "나", f"→ {c['alias']}: {label} 역할 계약 제안 (p2p 직접 연결, 공개된 역할을 broker에서 발견)")
            eng = await rpc(c["peer_url"], {"op": "engage", "call_id": call_id, "role": role, "text": text, "contract": p}, timeout=120)
            if not eng.get("ok"):
                emit("contract", "나", f"{c['alias']} 거절: {str(eng.get('error'))[:60]}")
                continue
            ledger = c["peer_url"] if role == "record" else self.ledger_url(call_id)
            rec = await rpc(ledger, {"op": "record", "type": "contract", "payload": p, "sigs": {self.id.pub: self.id.sign(p), c["pub"]: eng["sig"]}})
            if rec.get("ok"):
                self.calls[call_id][{"record": "recorder", "review": "reviewer"}[role]] = c
                emit("contract", "나", f"{label} 계약 체결: {c['alias']} (원장 #{rec['seq']}, 양쪽 서명)")
                return c
        emit("contract", "나", f"{label}를 구하지 못했습니다")
        return None

    async def post_call(self, text):
        call_id = "call-" + h(f"{text}{time.time()}".encode())[:6]
        self.calls[call_id] = {"text": text, "ts": time.time(), "sheet": [], "closed": False, "recorder": None, "reviewer": None}
        emit("request", "나", f"공모 준비 [{call_id}]: {text[:60]}")
        if not await self.recruit(call_id, text, "record", "이 공모의 원장을 기록할 기록자 역할을 맡을 사람 (기록 보관, 접근 통제, 감사 경험)"):
            emit("request", "나", "기록자가 없어 공모를 열 수 없습니다")
            return call_id
        reviewer = await self.recruit(call_id, text, "review", f"이 공모의 심사자로 필요한 사람(심사 경험, 평가 기준 전문성). 공모: {text}")
        emit("request", "나", f"공모 게시 [{call_id}] - 기록자 {self.calls[call_id]['recorder']['alias']}" + (f", 심사자 {reviewer['alias']}" if reviewer else ""))
        res = await rpc(self.broker_url, {"op": "call", "call_id": call_id, "text": text, "requester_url": self.url, "requester_pub": self.id.pub,
                                          "recorder_url": self.ledger_url(call_id), "recorder_pub": self.calls[call_id]["recorder"]["pub"]}, timeout=180)
        self.calls[call_id]["sheet"] = res.get("answer_sheet", [])
        return call_id

    async def handle(self, r):
        if r["op"] != "submit_idea":
            return {"ok": False, "error": "unknown op"}
        call = self.calls.get(r["call_id"])
        if not call or call["closed"]:
            return {"ok": False, "error": "unknown or closed call"}
        pub_payload, share_payload = r["publish_payload"], r["share_payload"]
        if call["recorder"] and pub_payload["author"] == call["recorder"]["pub"]:
            return {"ok": False, "error": "이 공모의 기록자는 응모할 수 없습니다"}
        if h(canon(r["idea"])) != pub_payload["content_hash"] or not verify(pub_payload["author"], pub_payload, r["publish_sig"]):
            return {"ok": False, "error": "content hash / author signature mismatch"}
        if share_payload["consumer"] != self.id.pub or share_payload["content_hash"] != pub_payload["content_hash"]:
            return {"ok": False, "error": "share payload does not match"}
        if any(i["author"] == pub_payload["author"] and i["call_id"] == r["call_id"] for i in self.ideas.values()):
            return {"ok": False, "error": "one idea per peer per call"}
        self.ideas[pub_payload["content_hash"]] = dict(author=pub_payload["author"], call_id=r["call_id"], idea=r["idea"], ts=time.time())
        emit("p2p", alias(pub_payload["author"]), f"→ 나: 아이디어 도착 '{r['idea']['title'][:40]}' (p2p 직접 연결, broker 미경유)")
        return {"ok": True, "receipt_sig": self.id.sign(share_payload)}

    # ---- the event peer's assistant: picks its own next action after the deadline ----
    TOOL_HELP = (
        "- list_ideas: 도착한 아이디어 목록(작성자 정보 없음)을 본다.\n"
        "- discover_peer(need): broker에게 맥락으로 peer를 찾아 달라고 한다. 결과에 peer_url과 pub이 들어 있다.\n"
        "- request_review(peer_url, peer_pub): 심사자에게 도착한 모든 아이디어의 심사를 p2p로 요청한다. "
        "peer_url에는 실제 주소(http://로 시작)를, peer_pub에는 실제 공개키 문자열을 넣는다. 계약된 심사자의 값은 첫 메시지에 적혀 있다. 같은 심사자에게 두 번 요청할 필요는 없다.\n"
        "- adopt(id, reason): 아이디어 하나를 채택하고 원장에 기록한다. id는 list_ideas의 id.\n"
        "- finish: 모든 일을 마쳤을 때.")
    ACTION_SCHEMA = {"type": "object", "additionalProperties": False,
                     "required": ["thought", "action", "need", "peer_url", "peer_pub", "id", "reason"],
                     "properties": {k: {"type": "string"} for k in ("thought", "action", "need", "peer_url", "peer_pub", "id", "reason")}}

    def tools(self, call_id):
        mine = lambda: [(k, v) for k, v in self.ideas.items() if v["call_id"] == call_id]

        async def list_ideas(_):
            return [dict(id=k[:8], **{f: v["idea"][f] for f in ("title", "idea", "first_step", "risk")}) for k, v in mine()]

        async def discover_peer(a):
            res = await rpc(self.broker_url, {"op": "find", "text": a["need"], "requester_pub": self.id.pub})
            return res.get("peers", [])

        async def request_review(a):
            if not str(a.get("peer_url", "")).startswith("http"):
                return {"error": "peer_url에는 실제 주소를 넣어야 합니다 (예: http://127.0.0.1:9111). 첫 메시지의 계약된 심사자 값을 쓰세요."}
            return await self.request_review(call_id, a["peer_url"], a["peer_pub"])

        async def adopt(a):
            full = next((k for k, _ in mine() if k.startswith(a["id"])), None)
            return {"ok": bool(full and await self.adopt(full, a["reason"]))}

        return {"list_ideas": list_ideas, "discover_peer": discover_peer, "request_review": request_review, "adopt": adopt}

    async def agent_run(self, call_id, top=2):
        self.calls[call_id]["closed"] = True
        tools = self.tools(call_id)
        if llm.live():
            try:
                await self._llm_loop(call_id, tools, top)
            except Exception as e:
                emit("assist", "나의 비서", f"에이전트 루프 실패({type(e).__name__}: {str(e)[:80]}) → 기본 절차로 대체")
        if not self.adopted:  # offline mode, or the model stopped without adopting anything
            await self._scripted(call_id, tools, top)

    async def _llm_loop(self, call_id, tools, top):
        """The model picks the next action each step (JSON action protocol, works on any backend); code only executes it."""
        system = (f"당신은 이벤트 진행자(나)의 비서 에이전트입니다. 공모가 마감되었습니다. 목표는 가장 좋은 아이디어 최대 {top}개를 채택하는 것입니다. "
                  "스스로 평가하지 말고, 먼저 도착한 아이디어를 확인한 뒤 이 공모의 계약된 심사자에게 심사를 요청하고(원장에 계약이 있는 심사자만 심사 결과가 기록됩니다), 그 심사 의견을 근거로 채택하세요. "
                  "필요하다고 판단하면 순서를 바꾸거나 다른 peer를 찾아도 됩니다. 한 번에 도구 하나만 고르세요. 쓰지 않는 인자는 빈 문자열로 두세요.\n\n"
                  f"[사용할 수 있는 도구]\n{self.TOOL_HELP}\n\naction에는 도구 이름 또는 finish를 쓰고, thought에 한 줄로 이유를 쓰세요.")
        rv = self.calls[call_id].get("reviewer")
        info = f"계약된 심사자: peer_url={rv['peer_url']} , peer_pub={rv['pub']}" if rv else "계약된 심사자가 없습니다. discover_peer로 찾으세요."
        messages = [{"role": "user", "content": f"공모 내용: {self.calls[call_id]['text']}\n{info}\n공모가 마감되었습니다. 시작하세요."}]
        for _ in range(12):
            act = await llm.ask_json(actor="나의 비서", model=llm.AGENT_MODEL, system=system, messages=messages, schema=self.ACTION_SCHEMA,
                                     fallback=lambda: {"action": "finish", "thought": "LLM 응답 없음"}, effort="low")
            name = act.get("action", "finish")
            messages.append({"role": "assistant", "content": json.dumps(act, ensure_ascii=False)})
            if name == "finish" or name not in tools:
                emit("assist", "나의 비서", f"종료: {act.get('thought', '')[:120]}")
                return
            emit("assist", "나의 비서", f"{name} - {act.get('thought', '')[:90]}")
            try:
                out = await tools[name](act)
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            messages.append({"role": "user", "content": "[도구 결과] " + json.dumps(out, ensure_ascii=False)[:6000]})

    async def _scripted(self, call_id, tools, top):
        """offline stand-in for the agent loop: the same tools in a fixed order"""
        emit("assist", "나의 비서", "기본 절차(고정 순서)로 진행: 계약된 심사자에게 심사 요청 → 점수순 채택")
        rv = self.calls[call_id].get("reviewer")
        peers = [rv] if rv else await tools["discover_peer"]({"need": "공모 아이디어 심사에 능한 사람, 평가 기준과 선별 경험"})
        if not peers:
            return
        res = await tools["request_review"]({"peer_url": peers[0]["peer_url"], "peer_pub": peers[0]["pub"]})
        ranked = sorted(res.get("reviews", []), key=lambda r: -r["score"])
        for r in ranked[:top]:
            await tools["adopt"]({"id": r["id"], "reason": f"심사 점수 {r['score']}: {r['comment'][:40]}"})

    async def request_review(self, call_id, peer_url, peer_pub):
        call = self.calls[call_id]
        if peer_pub in call.setdefault("reviewed_by", {}):  # already answered: return the same result instead of asking twice
            return {"ok": True, "reviews": call["reviewed_by"][peer_pub], "note": "이 심사자는 이미 심사를 마쳤습니다"}
        mine = [(k, v) for k, v in self.ideas.items() if v["call_id"] == call_id]
        shares = {k: {"provider": self.id.pub, "consumer": peer_pub, "content_hash": k, "terms": "review request",
                      "nonce": h(f"{k}{peer_pub}{time.time()}".encode())[:12]} for k, _ in mine}
        emit("p2p", "나", f"→ {alias(peer_pub)}: 아이디어 {len(mine)}건 심사 요청 (p2p 직접 연결)")
        res = await rpc(peer_url, {"op": "evaluate_ideas", "call_id": call_id, "call_text": call["text"],
                                   "ideas": [dict(id=k[:8], **{f: v["idea"][f] for f in ("title", "idea", "first_step", "risk")}) for k, v in mine],
                                   "share_payloads": shares}, timeout=240)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error")}
        ledger = self.ledger_url(call_id)
        for k, p in shares.items():  # proof that the requester handed these ideas to the reviewer
            await rpc(ledger, {"op": "record", "type": "share", "payload": p, "sigs": {self.id.pub: self.id.sign(p), peer_pub: res["receipts"][k]}})
        out = []
        for rv in res["reviews"]:
            if h(rv["comment"].encode()) != rv["payload"]["comment_hash"]:
                continue  # comment does not match what the reviewer signed
            rec = await rpc(ledger, {"op": "record", "type": "feedback", "payload": rv["payload"], "sigs": {peer_pub: rv["sig"]}})
            if not rec.get("ok"):
                continue
            self.reviews[rv["payload"]["content_hash"]] = dict(score=rv["payload"]["score"], comment=rv["comment"], judge=alias(peer_pub))
            out.append(dict(id=rv["payload"]["content_hash"][:8], score=rv["payload"]["score"], comment=rv["comment"]))
        call["reviewed_by"][peer_pub] = out
        emit("review", alias(peer_pub), "심사 완료: " + ", ".join(f"{o['id']}={o['score']}" for o in out))
        return {"ok": True, "reviews": out}

    async def adopt(self, content_hash, reason="채택"):
        if content_hash in self.adopted or content_hash not in self.ideas:
            return False
        STORE[h(reason.encode())] = {"reason": reason}
        p = {"evaluator": self.id.pub, "content_hash": content_hash, "verdict": "adopt", "reason_hash": h(reason.encode())}
        res = await rpc(self.ledger_url(self.ideas[content_hash]["call_id"]), {"op": "record", "type": "feedback", "payload": p, "sigs": {self.id.pub: self.id.sign(p)}})
        if res.get("ok"):
            self.adopted.add(content_hash)
            self.ideas[content_hash]["reason"] = reason
            emit("award", "나", f"채택: '{self.ideas[content_hash]['idea']['title'][:40]}' ({alias(self.ideas[content_hash]['author'])}) - {reason}")
        return res.get("ok", False)


# ---------------- peers (secretary agent + simulated human persona; may also carry the "record" role) ----------------
class PeerAgent:
    def __init__(self, persona, port, broker_url, readers=()):
        self.p, self.id, self.port, self.broker_url = persona, Identity(), port, broker_url
        self.url = f"http://127.0.0.1:{port}"
        self.workspace, self.version = list(persona["notes"]), 0  # working area: knowledge and experience that accumulate
        self.can = list(persona.get("can", []))
        skills = ["call_for_ideas", "evaluate_ideas", "engage"]
        if "record" in self.can:  # this peer keeps a ledger: a distributed ledger node run by a volunteer, not an operator
            self.ledger, self.lock = Collector(f"recorder-{alias(self.id.pub)}", identity=self.id), asyncio.Lock()
            self.readers, self.access_log = set(readers), []  # the recorder decides who may read its ledger
            skills += ["record", "audit", "read"]
        self.app = make_agent_app(f"peer-{alias(self.id.pub)}", f"pseudonymous peer {alias(self.id.pub)}", port, skills, self.handle)

    # ---- self-description: the secretary summarizes the working area and (re)publishes it ----
    async def advertise(self):
        me = alias(self.id.pub)
        notes = "\n".join(f"- {n}" for n in self.workspace[-12:])
        d = await llm.ask_json(
            actor=me, model=llm.AGENT_MODEL, user=f"[작업 노트]\n{notes}", fallback=lambda: {"summary": " ".join(dict.fromkeys(self.workspace[:1] + self.workspace[-2:]))},
            schema={"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}},
            system="당신은 사원의 비서 에이전트입니다. 사원의 작업 영역(지식과 경험 노트)을 읽고, 다른 peer들이 검색해서 연락할 수 있도록 이 사원의 정체와 할 수 있는 일을 "
                   "3문장 이내로 요약하세요. 노트에 없는 경력이나 능력은 만들지 말고, 실명은 쓰지 마세요. 심사 원칙처럼 일하는 방식이 있으면 포함하세요.")
        self.version += 1
        profile = {"summary": d["summary"], "domain": "ideas", "offers": self.can, "until": time.time() + 7 * 86400, "ver": self.version}
        emit("profile", me, f"자기 요약 게시(v{self.version}): {d['summary'][:100]}")
        await rpc(self.broker_url, {"op": "advertise", "ad": {"pub": self.id.pub, "url": self.url, "profile": profile, "sig": self.id.sign(profile)}})

    async def learn(self, event: str):
        d = await llm.ask_json(
            actor=alias(self.id.pub), model=llm.AGENT_MODEL, user=f"[방금 있었던 일]\n{event}", fallback=lambda: {"note": event},
            schema={"type": "object", "additionalProperties": False, "required": ["note"], "properties": {"note": {"type": "string"}}},
            system="당신은 사원의 비서 에이전트입니다. 방금 있었던 일에서 앞으로 도움이 될 경험이나 원칙을 사원의 작업 노트에 남길 한 줄로 정리하세요. 실명은 쓰지 마세요.")
        self.workspace.append(d["note"])
        await self.advertise()

    async def handle(self, r):
        op = r["op"]
        if op == "call_for_ideas":
            asyncio.create_task(self.work(r))  # ack immediately; the human (persona) takes time
            return {"ok": True, "ack": True}
        if op == "evaluate_ideas":
            return await self.review(r)
        if op == "engage":
            return await self.engage(r)
        if op in ("record", "audit", "read") and "record" in self.can:
            return await self.ledger_op(r)
        return {"ok": False, "error": "unknown op"}

    # ---- "record" role ----
    async def ledger_op(self, r):
        me = alias(self.id.pub)
        if r["op"] == "record":
            async with self.lock:
                entry, err = self.ledger.propose(r["type"], r["payload"], r["sigs"])
            if err:
                emit("ledger", me, f"거절: {r['type']} - {err}")
                return {"ok": False, "error": err}
            emit("ledger", me, f"#{entry['seq']} {entry['type']} 기록 (기록자 서명)")
            return {"ok": True, "seq": entry["seq"], "hash": entry["hash"], "seal": entry["seal"]}
        if r["op"] == "audit":
            return {"ok": True, "status": self.ledger.audit(), "head": self.ledger.head(), "length": len(self.ledger.chain)}
        ok = (r.get("reader") in self.readers and abs(time.time() - r.get("ts", 0)) < 60
              and verify(r["reader"], {"op": "read", "ts": r["ts"]}, r.get("sig", "")))
        self.access_log = (self.access_log + [{"ts": time.time(), "reader": alias(r.get("reader", "?" * 6)), "granted": ok}])[-50:]
        if not ok:
            emit("ledger", me, f"원장 열람 거부: {alias(r.get('reader', '?' * 6))}")
            return {"ok": False, "error": "not authorized"}
        return {"ok": True, "chain": self.ledger.chain}

    # ---- event roles ----
    async def engage(self, r):
        """an event peer asks this peer to take a role for one event; accepting means signing the contract"""
        me = alias(self.id.pub)
        if r["role"] not in self.can or r["contract"].get("contractor") != self.id.pub:
            return {"ok": False, "error": "이 역할은 제공하지 않습니다"}
        d = await llm.ask_json(
            actor=me, model=llm.AGENT_MODEL, schema={"type": "object", "additionalProperties": False, "required": ["accept", "reason"],
                                                   "properties": {"accept": {"type": "boolean"}, "reason": {"type": "string"}}},
            system=f"당신은 '{self.p['role']}'의 비서 에이전트입니다. 이 사원은 '{r['role']}' 역할(review=심사, record=원장 기록)을 공개적으로 제공하고 있습니다. "
                   "판단 기준은 공모 주제가 아니라 그 역할 자체입니다: 사원이 이 역할을 맡을 자격과 여력이 있으면 수락하세요. 공모 주제가 사원의 관심 분야와 달라도 역할 수행에는 문제가 없습니다. "
                   "거절은 이해 충돌(예: 자기가 응모하려는 공모의 심사)이나 여력 부족일 때만 하세요.",
            user=f"[역할 계약 요청]\n역할: {r['role']}\n이벤트(공모): {r['text']}", fallback=lambda: {"accept": True, "reason": "공개한 역할과 일치"})
        if not d["accept"]:
            emit("contract", me, f"역할 계약 거절: {d['reason'][:80]}")
            return {"ok": False, "error": d["reason"]}
        emit("contract", me, f"비서: '{r['role']}' 역할 계약 수락 - {d['reason'][:60]}")
        return {"ok": True, "sig": self.id.sign(r["contract"])}

    async def review(self, r):
        me = alias(self.id.pub)
        if "review" not in self.can:
            return {"ok": False, "error": "이 peer는 심사 요청을 받지 않습니다"}
        if any(p["consumer"] != self.id.pub for p in r["share_payloads"].values()):
            return {"ok": False, "error": "share payload mismatch"}
        emit("peer", me, f"비서: 심사 요청 수락, 심사 전문가(페르소나)에게 아이디어 {len(r['ideas'])}건 전달")
        listing = "\n".join(f"- {i['id']}: [{i['title']}] {i['idea']} (첫 단계: {i['first_step']} / 위험: {i['risk']})" for i in r["ideas"])
        d = await llm.ask_json(
            actor=me, model=llm.PERSONA_MODEL, effort="medium", system=judge_system(self.p), user=f"[공모]\n{r['call_text']}\n\n[아이디어]\n{listing}",
            schema={"type": "object", "additionalProperties": False, "required": ["reviews"], "properties": {"reviews": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "score", "comment"],
                "properties": {"id": {"type": "string"}, "score": {"type": "number"}, "comment": {"type": "string"}}}}}},
            fallback=lambda: offline_review(r["ideas"]))
        scores = [float(x["score"]) for x in d["reviews"]]
        if scores:
            asyncio.create_task(self.learn(f"사내 공모('{r['call_text'][:40]}')의 심사자로 아이디어 {len(scores)}건을 심사했다. 점수 범위 {min(scores)}~{max(scores)}. "
                                           "이번 심사에서 얻은 심사 원칙이나 교훈을 정리한다."))
        full = {k[:8]: k for k in r["share_payloads"]}
        receipts = {k: self.id.sign(p) for k, p in r["share_payloads"].items()}
        reviews, seen = [], set()
        for rv in d["reviews"]:
            if rv["id"] in full and rv["id"] not in seen:
                seen.add(rv["id"])
                comment_hash = h(rv["comment"].encode())  # the comment text stays off the ledger
                STORE[comment_hash] = {"comment": rv["comment"]}
                payload = {"evaluator": self.id.pub, "call_id": r["call_id"], "content_hash": full[rv["id"]], "verdict": "review",
                           "score": float(rv["score"]), "comment_hash": comment_hash}
                reviews.append({"payload": payload, "sig": self.id.sign(payload), "comment": rv["comment"]})
        return {"ok": True, "receipts": receipts, "reviews": reviews}

    async def work(self, r):
        me = alias(self.id.pub)
        if r.get("recorder_pub") == self.id.pub:
            emit("peer", me, "비서: 이 공모의 기록자이므로 응모하지 않음 (역할 충돌 방지)")
            return
        # 1) secretary agent decides whether to bother its owner
        d = await llm.ask_json(
            actor=me, model=llm.AGENT_MODEL, system=secretary_system(self.p), user=f"[사내 공모]\n{r['text']}",
            schema={"type": "object", "additionalProperties": False, "required": ["forward", "reason"],
                    "properties": {"forward": {"type": "boolean"}, "reason": {"type": "string"}}},
            fallback=lambda: {"forward": self.p["eager"] > 0.55, "reason": "참여 성향 기준(오프라인)"})
        if not d["forward"]:
            emit("peer", me, f"비서: 사원에게 전달하지 않음 - {d['reason']}")
            return
        emit("peer", me, "비서: 사원(페르소나)에게 공모 전달")
        # 2) the simulated human thinks and writes an idea
        idea = await llm.ask_json(
            actor=me, model=llm.PERSONA_MODEL, effort="low", system=persona_system(self.p), schema=IDEA_SCHEMA,
            fallback=lambda: offline_idea(self.p, r["text"]),
            user=f"[사내 아이디어 공모]\n{r['text']}\n\n아이디어를 내 주세요. title은 한 줄, idea는 3~5문장, first_step은 첫 실행 단계, risk는 가장 큰 위험.")
        # 3) secretary registers priority FIRST, then connects p2p to the requester
        idea["call_id"] = r["call_id"]
        content_hash = h(canon(idea))
        STORE[content_hash] = idea
        pub_p = {"author": self.id.pub, "content_hash": content_hash, "call_id": r["call_id"]}
        share_p = {"provider": self.id.pub, "consumer": r["requester_pub"], "content_hash": content_hash,
                   "terms": "idea submission, credit to author", "nonce": h(f"{content_hash}{time.time()}".encode())[:12]}
        first = await rpc(r["recorder_url"], {"op": "record", "type": "publish", "payload": pub_p, "sigs": {self.id.pub: self.id.sign(pub_p)}})
        if not first.get("ok"):
            emit("peer", me, f"먼저 등록 실패: {first.get('error')}")
            return
        if first.get("seal", {}).get("pub") != r.get("recorder_pub"):
            emit("peer", me, "기록자 서명이 공모에 적힌 기록자와 다릅니다 → 제출 중단")
            return
        res = await rpc(r["requester_url"], {"op": "submit_idea", "call_id": r["call_id"], "idea": idea, "publish_payload": pub_p,
                                             "publish_sig": self.id.sign(pub_p), "share_payload": share_p})
        if not res.get("ok"):
            emit("peer", me, f"요청자가 거절: {res.get('error')}")
            return
        # 4) prove the hand-over: share (both signatures)
        b = await rpc(r["recorder_url"], {"op": "record", "type": "share", "payload": share_p,
                                          "sigs": {self.id.pub: self.id.sign(share_p), r["requester_pub"]: res["receipt_sig"]}})
        if not b.get("ok"):
            emit("peer", me, f"공유 기록 실패: {b.get('error')}")
            return
        asyncio.create_task(self.learn(f"사내 공모('{r['text'][:40]}')에 아이디어 '{idea['title'][:40]}'를 제출했다."))


def build_all(base=9100):
    from .overseer import Overseer
    overseer = Overseer()
    broker = Broker(base + 110)
    broker_url = f"http://127.0.0.1:{base + 110}"
    me = Requester(base + 200, broker_url)
    peers = [PeerAgent(p, base + 1 + i, broker_url, readers=[overseer.id.pub]) for i, p in enumerate(PERSONAS)]
    overseer.broker_url = broker_url
    return broker, me, peers, overseer
