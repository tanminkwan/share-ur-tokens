"""A2A nodes. One node type (peer) plus the broker. Infrastructure roles (discovery, recording) and event roles
(reviewer, contestant) are behaviours a peer offers or is contracted into; the ledger is kept by a peer in the "record"
role. Every hop between nodes is a real A2A call over localhost HTTP."""
import asyncio
import json
import time

from . import llm
from .common import STORE, Identity, alias, canon, emit, h, make_agent_app, rpc, verify
from .ledger import Collector
from .search import rank
from .personas import PERSONAS, ask_owner_system, decision_system, judge_system, offline_idea, offline_review, persona_system

IDEA_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "idea", "first_step", "risk"],
               "properties": {"title": {"type": "string"}, "idea": {"type": "string"},
                              "first_step": {"type": "string"}, "risk": {"type": "string"}}}
RELEVANCE_MIN = 0.3  # below this BM25 score a notice is skipped without calling the LLM (a recommendation reopens it)
SELECT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["selected"],
                 "properties": {"selected": {"type": "array", "items": {
                     "type": "object", "additionalProperties": False, "required": ["pub", "reason"],
                     "properties": {"pub": {"type": "string"}, "reason": {"type": "string"}}}}}}


# ---------------- broker (mechanical: bulletin board + search engine, NO AI) ----------------
class Broker:
    """Posts profiles and notices (both expire), and answers searches with BM25. No LLM, no judgement.
    It never sees an idea or a ledger entry. Matching that needs judgement is done by a peer in the "recommend" role,
    using this search. It has its own key and signs nothing but what it returns."""

    def __init__(self, port, name="broker", owner_pub=None):
        self.ads, self.notices, self.port, self.id, self.name = {}, {}, port, Identity(), name
        self.url, self.neighbors = f"http://127.0.0.1:{port}", []
        # closed peer group: only keys holding an unexpired membership grant signed by the group owner may use this board
        self.owner_pub, self.members = owner_pub, {}
        self.app = make_agent_app(name, "bulletin board and search (mechanical, no AI)", port,
                                  ["advertise", "post_notice", "close_notice", "search_notices", "list_notices", "find"], self.handle)

    async def _share(self, r):
        """pass a signed notice post/close to the other brokers once; they verify the signature themselves"""
        if r.get("shared"):
            return
        for url in self.neighbors:
            try:
                await rpc(url, dict(r, shared=True), timeout=10)
            except Exception:
                emit("broker", self.name, f"{url} 공유 실패 (그 broker가 멈춰도 나머지는 계속 동작)")

    def _active(self, coll):
        now = time.time()
        return [x for x in coll.values() if x.get("until", 1e18) > now]

    def _visible(self, notice, pub):
        """mechanical audience rule: every label the notice targets must be on the viewer's profile"""
        labels = set(self.ads.get(pub, {}).get("labels", []))
        return all(f"{k}:{v}" in labels for k, v in notice.get("audience", {}).items())

    def _member(self, pub):
        return self.owner_pub is None or pub == self.owner_pub or self.members.get(pub, 0) > time.time()

    def _signed_by_member(self, r):
        return (self._member(r.get("pub", "")) and abs(time.time() - r.get("ts", 0)) < 60
                and verify(r.get("pub", ""), {"op": r["op"], "ts": r.get("ts", 0)}, r.get("sig", "")))

    async def handle(self, r):
        op = r["op"]
        if op == "grant":  # membership grant with expiry, signed by the group owner; no revocation, it just expires
            g = r["grant"]
            if self.owner_pub is None or not verify(self.owner_pub, g, r.get("sig", "")):
                return {"ok": False, "error": "grant must be signed by the group owner"}
            self.members[g["pub"]] = g["until"]
            emit("broker", self.name, f"그룹 가입 허가: {alias(g['pub'])} (만기 {int(g['until'] - time.time())}초 후)")
            return {"ok": True}
        if self.owner_pub is not None and op in ("list_profiles", "find") and not self._signed_by_member(r):
            emit("broker", self.name, f"그룹 밖 요청 거부: {op} ({alias(r.get('pub', '?' * 6))})")
            return {"ok": False, "error": "members of this peer group only"}
        if op == "advertise":
            ad = r["ad"]
            if not verify(ad["pub"], ad["profile"], ad["sig"]):
                return {"ok": False, "error": "bad signature"}
            if not self._member(ad["pub"]):
                emit("broker", self.name, f"그룹 밖 등록 거부: {alias(ad['pub'])}")
                return {"ok": False, "error": "members of this peer group only"}
            known = ad["pub"] in self.ads
            self.ads[ad["pub"]] = dict(ad["profile"], pub=ad["pub"], url=ad["url"])
            emit("broker", self.name, f"{alias(ad['pub'])} 프로필 {'갱신' if known else '등록'}(v{ad['profile'].get('ver', 1)})"
                 + (f" 역할 공개: {','.join(ad['profile']['offers'])}" if ad["profile"].get("offers") else ""))
            return {"ok": True}
        if op == "post_notice":
            n = r["notice"]
            if not verify(n["issuer_pub"], n, r["sig"]):
                return {"ok": False, "error": "bad signature"}
            self.notices[n["notice_id"]] = n
            target = ", ".join(f"{k}:{v}" for k, v in n.get("audience", {}).items()) or "전체"
            seen_by = sum(self._visible(n, p) for p in self.ads)
            emit("broker", self.name, (f"공지 공유 받음 [{n['notice_id']}]" if r.get("shared") else f"공지 게시 [{n['notice_id']}] '{n['title'][:30]}'")
                 + f" 대상 [{target}] → 이 broker의 peer 중 라벨이 맞는 {seen_by}명에게 보임")
            await self._share(r)
            return {"ok": True}
        if op == "close_notice":
            n = self.notices.get(r["notice_id"])
            if n and verify(n["issuer_pub"], {"close": r["notice_id"]}, r["sig"]):
                n["until"] = time.time()
                if not r.get("shared"):
                    emit("broker", self.name, f"공지 마감 [{r['notice_id']}] → 다른 broker에 공유")
                await self._share(r)
                return {"ok": True}
            return {"ok": False, "error": "not the issuer"}
        if op == "list_profiles":  # the public profile board (profiles live on each peer's primary broker: ask the others too)
            mine = [dict(a, broker=self.name) for a in self._active(self.ads)]
            if not r.get("shared"):
                for url in self.neighbors:
                    try:
                        mine += (await rpc(url, dict(r, shared=True), timeout=10)).get("profiles", [])
                    except Exception:
                        pass
            return {"ok": True, "profiles": mine}
        if op in ("list_notices", "search_notices") and not (
                r.get("pub") in self.ads and abs(time.time() - r.get("ts", 0)) < 60
                and verify(r["pub"], {"op": op, "ts": r["ts"]}, r.get("sig", ""))):
            return {"ok": False, "error": "signed request from a registered profile required"}
        if op == "list_notices":  # what this viewer is allowed to see
            return {"ok": True, "notices": [n for n in self._active(self.notices) if self._visible(n, r.get("pub", ""))]}
        if op == "search_notices":  # BM25 over the notices this viewer is allowed to see
            active = [n for n in self._active(self.notices) if self._visible(n, r.get("pub", ""))]
            hits = rank(r["query"], [f"{n['title']} {n['text']} {n['kind']}" for n in active])
            return {"ok": True, "hits": [dict(active[i], score=sc) for i, sc in hits[:r.get("k", 3)] if sc > 0]}
        if op == "find":  # profiles by text (BM25), optionally only those that publicly offer a role
            aud = r.get("audience", {})
            cands = [a for a in self._active(self.ads) if a["pub"] not in r.get("exclude", [])
                     and (not r.get("role") or r["role"] in a.get("offers", []))
                     and all(f"{k}:{v}" in a.get("labels", []) for k, v in aud.items())]
            hits = rank(r["text"], [f"{a['summary']} {' '.join(a.get('offers', []))}" for a in cands])
            peers = [dict(alias=alias(cands[i]["pub"]), pub=cands[i]["pub"], peer_url=cands[i]["url"], offers=cands[i].get("offers", []),
                          summary=cands[i]["summary"], score=sc, broker=self.name) for i, sc in hits[:r.get("k", 3)]]
            if not r.get("shared"):  # profiles live on each peer's primary broker: ask the others too, merge by score
                for url in self.neighbors:
                    try:
                        peers += (await rpc(url, dict(r, shared=True), timeout=10)).get("peers", [])
                    except Exception:
                        pass
                peers = sorted(peers, key=lambda p: -p["score"])[:r.get("k", 3)]
            else:
                return {"ok": True, "peers": peers}
            emit("broker", self.name, f"검색 '{r['text'][:24]}'{' (역할 ' + r['role'] + ')' if r.get('role') else ''} → 같은 그룹 broker {1 + len(self.neighbors)}곳에 물어 합침: "
                 + (", ".join(f"{p['alias']}@{p['broker']}" for p in peers) or "없음"))
            return {"ok": True, "peers": peers}
        return {"ok": False, "error": "unknown op"}


# ---------------- event peer ("나", the requester) ----------------
class Requester:
    def __init__(self, port, broker_url, review_broker_url=None):
        """the event peer belongs to two peer groups: the applicant group (broker_url) and the review group (review_broker_url)"""
        self.id, self.port, self.broker_url = Identity(), port, broker_url
        self.review_broker_url = review_broker_url or broker_url
        self.url = f"http://127.0.0.1:{port}"
        self.calls, self.ideas, self.adopted, self.reviews = {}, {}, set(), {}
        self.app = make_agent_app("requester-me", "the person who posts the idea contest", port, ["submit_idea"], self.handle)

    def ledger_url(self, call_id):
        return self.calls[call_id]["recorder"]["peer_url"]

    async def recruit(self, call_id, text, role, need, count=1):
        """search a peer group's broker for peers that publicly offer `role`, contact them directly in rank order, sign role
        contracts until `count` accepted. Reviewers are searched in the review group; the recorder in the applicant group.
        The contract is recorded on the event's recorder; for the recorder role itself, on the newly contracted one."""
        broker = self.review_broker_url if role == "review" else self.broker_url
        ts = time.time()
        res = await rpc(broker, {"op": "find", "text": need, "role": role, "exclude": [self.id.pub], "k": count + 2,
                                 "pub": self.id.pub, "ts": ts, "sig": self.id.sign({"op": "find", "ts": ts})})
        label = {"record": "기록자", "review": "심사자"}[role]
        got = []
        for c in res.get("peers", []):
            if len(got) >= count:
                break
            p = {"call_id": call_id, "role": role, "issuer": self.id.pub, "contractor": c["pub"],
                 "nonce": h(f"{call_id}{role}{c['pub']}{time.time()}".encode())[:12]}
            emit("contract", "나", f"→ {c['alias']}: {label} 역할 계약 제안 (broker 검색으로 발견, p2p 직접 연결)")
            eng = await rpc(c["peer_url"], {"op": "engage", "call_id": call_id, "role": role, "text": text, "contract": p}, timeout=120)
            if not eng.get("ok"):
                emit("contract", "나", f"{c['alias']} 거절: {str(eng.get('error'))[:60]}")
                continue
            ledger = c["peer_url"] if role == "record" else self.ledger_url(call_id)
            rec = await rpc(ledger, {"op": "record", "type": "contract", "payload": p, "sigs": {self.id.pub: self.id.sign(p), c["pub"]: eng["sig"]}})
            if rec.get("ok"):
                if role == "record":
                    self.calls[call_id]["recorder"] = c
                else:
                    self.calls[call_id]["reviewers"].append(c)
                self.calls[call_id]["contracts"].append({"role": role, "hash": rec["hash"]})
                emit("contract", "나", f"{label} 계약 체결: {c['alias']} (원장 #{rec['seq']}, 양쪽 서명)")
                got.append(c)
        if len(got) < count:
            emit("contract", "나", f"{label}를 {count}명 구하지 못했습니다({len(got)}명)")
        return got

    async def post_call(self, text, minutes=10):
        call_id = "call-" + h(f"{text}{time.time()}".encode())[:6]
        self.calls[call_id] = {"text": text, "ts": time.time(), "sheet": [], "closed": False, "recorder": None, "reviewers": [], "contracts": []}
        emit("request", "나", f"공모 준비 [{call_id}]: {text[:60]}")
        if not await self.recruit(call_id, text, "record", "원장 기록 역할 기록 보관 접근 통제 감사"):
            emit("request", "나", "기록자가 없어 공모를 열 수 없습니다")
            return call_id
        reviewers = await self.recruit(call_id, text, "review", f"공모 아이디어 심사 평가 기준 심사위원 경험 {text}", count=2)
        c = self.calls[call_id]
        notice = {"notice_id": call_id, "kind": "아이디어 공모", "title": text[:40], "text": text, "until": time.time() + minutes * 60,
                  "audience": {"소속": "삼성SDS"},  # 응모 대상: 삼성SDS 전사원
                  "conditions": {"귀속": "아이디어의 작성자 표시는 작성자 가명으로 남고, 회사는 사내에서 활용할 수 있다",
                                 "보상": "채택되면 원장의 기여 집계에 반영된다", "공개 범위": "사내"},
                  "issuer_pub": self.id.pub, "issuer_url": self.url,
                  "recorder_pub": c["recorder"]["pub"], "recorder_url": c["recorder"]["peer_url"],
                  "reviewer_count": len(reviewers), "contracts": c["contracts"]}  # reviewers live in another peer group: no names here
        c["notice"] = notice
        await rpc(self.broker_url, {"op": "post_notice", "notice": notice, "sig": self.id.sign(notice)})
        emit("request", "나", f"공지 게시 [{call_id}] (응모 그룹) - 기록자 {c['recorder']['alias']}, 심사자 {len(reviewers)}명은 심사 그룹에 있어 응모자에게 보이지 않음."
             " 누가 응모할지는 각 peer가 스스로 정한다")
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
        if any(pub_payload["author"] == rv["pub"] for rv in call.get("reviewers", [])):
            return {"ok": False, "error": "이 공모의 심사자는 응모할 수 없습니다"}
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
        "- discover_peer(need): broker 검색기로 peer를 찾는다. 결과에 peer_url과 pub이 들어 있다.\n"
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
            res = await rpc(self.broker_url, {"op": "find", "text": a["need"], "exclude": [self.id.pub]})
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
        await rpc(self.broker_url, {"op": "close_notice", "notice_id": call_id, "sig": self.id.sign({"close": call_id})})
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
                  "스스로 평가하지 말고, 먼저 도착한 아이디어를 확인한 뒤 이 공모의 계약된 심사자 **각각에게** 심사를 요청하고(원장에 계약이 있는 심사자만 심사 결과가 기록됩니다), 심사자들의 점수를 종합해 채택하세요. "
                  "필요하다고 판단하면 순서를 바꾸거나 다른 peer를 찾아도 됩니다. 한 번에 도구 하나만 고르세요. 쓰지 않는 인자는 빈 문자열로 두세요.\n\n"
                  f"[사용할 수 있는 도구]\n{self.TOOL_HELP}\n\naction에는 도구 이름 또는 finish를 쓰고, thought에 한 줄로 이유를 쓰세요.")
        rvs = self.calls[call_id].get("reviewers", [])
        info = ("계약된 심사자(심사 그룹):\n" + "\n".join(f"- peer_url={rv['peer_url']} , peer_pub={rv['pub']}" for rv in rvs)) if rvs else "계약된 심사자가 없습니다. discover_peer로 찾으세요."
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
        emit("assist", "나의 비서", "기본 절차(고정 순서)로 진행: 계약된 심사자 각각에게 심사 요청 → 평균 점수순 채택")
        peers = self.calls[call_id].get("reviewers") or await tools["discover_peer"]({"need": "공모 아이디어 심사에 능한 사람, 평가 기준과 선별 경험"})
        if not peers:
            return
        for p in peers:
            await tools["request_review"]({"peer_url": p["peer_url"], "peer_pub": p["pub"]})
        mine = [k for k, v in self.ideas.items() if v["call_id"] == call_id and k in self.reviews]
        ranked = sorted(mine, key=lambda k: -self.review_summary(k)["score"])
        for k in ranked[:top]:
            sm = self.review_summary(k)
            await tools["adopt"]({"id": k[:8], "reason": f"심사자 {sm['n']}명 평균 {sm['score']}점"})

    def review_summary(self, k):
        """aggregate the reviews of one idea across reviewers"""
        rs = self.reviews.get(k, {})
        if not rs:
            return None
        return {"score": round(sum(r["score"] for r in rs.values()) / len(rs), 2), "n": len(rs),
                "judge": ", ".join(r["judge"] for r in rs.values()),
                "comment": " / ".join(f"{r['judge']}: {r['comment']}" for r in rs.values())}

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
            self.reviews.setdefault(rv["payload"]["content_hash"], {})[peer_pub] = dict(score=rv["payload"]["score"], comment=rv["comment"], judge=alias(peer_pub))
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
        skills = ["recommend", "evaluate_ideas", "engage"]
        if "record" in self.can:  # this peer keeps a ledger: a distributed ledger node run by a volunteer, not an operator
            self.ledger, self.lock = Collector(f"recorder-{alias(self.id.pub)}", identity=self.id), asyncio.Lock()
            self.readers, self.access_log = set(readers), []  # the recorder decides who may read its ledger
            skills += ["record", "audit", "read"]
        self.app = make_agent_app(f"peer-{alias(self.id.pub)}", f"pseudonymous peer {alias(self.id.pub)}", port, skills, self.handle)

    # ---- self-description: the secretary summarizes the working area and (re)publishes it ----
    async def advertise(self):
        me = alias(self.id.pub)
        public = [n for n in self.workspace if not n.startswith(("[소유자 규칙]", "[상황]", "[판단]"))]  # private notes stay private
        notes = "\n".join(f"- {n}" for n in public[-12:])
        d = await llm.ask_json(
            actor=me, model=llm.AGENT_MODEL, user=f"[작업 노트]\n{notes}", fallback=lambda: {"summary": " ".join(dict.fromkeys(public[:1] + public[-2:]))},
            schema={"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}},
            system="당신은 사원의 비서 에이전트입니다. 사원의 작업 영역(지식과 경험 노트)을 읽고, 다른 peer들이 검색해서 연락할 수 있도록 이 사원의 정체와 할 수 있는 일을 "
                   "3문장 이내로 요약하세요. 노트에 없는 경력이나 능력은 만들지 말고, 실명은 쓰지 마세요. 심사 원칙처럼 일하는 방식이 있으면 포함하세요.")
        self.version += 1
        profile = {"summary": d["summary"], "domain": "ideas", "offers": self.can, "labels": self.p.get("labels", []),
                   "until": time.time() + 7 * 86400, "ver": self.version}
        emit("profile", me, f"자기 요약 게시(v{self.version}): {d['summary'][:100]}")
        await rpc(self.broker_url, {"op": "advertise", "ad": {"pub": self.id.pub, "url": self.url, "profile": profile, "sig": self.id.sign(profile)}})

    async def learn(self, event: str):
        d = await llm.ask_json(
            actor=alias(self.id.pub), model=llm.AGENT_MODEL, user=f"[방금 있었던 일]\n{event}", fallback=lambda: {"note": event},
            schema={"type": "object", "additionalProperties": False, "required": ["note"], "properties": {"note": {"type": "string"}}},
            system="당신은 사원의 비서 에이전트입니다. 방금 있었던 일에서 앞으로 도움이 될 경험이나 원칙을 사원의 작업 노트에 남길 한 줄로 정리하세요. 실명은 쓰지 마세요.")
        self.workspace.append(d["note"])
        await self.advertise()

    # ---- finding work: search the board myself, or receive a recommendation; then decide on my own grounds ----
    async def watch(self, every=3.0):
        self.seen = getattr(self, "seen", set())
        while True:
            await asyncio.sleep(every)
            try:
                if "recommend" in self.can:
                    await self.recommend_round()
                    continue
                res = await rpc(self.broker_url, self.signed({"op": "list_notices"}))  # board: notices whose audience matches my labels
                for n in res.get("notices", []):
                    if n["notice_id"] not in self.seen and n["issuer_pub"] != self.id.pub:
                        self.seen.add(n["notice_id"])
                        rel = self.relevance(n)
                        if rel < RELEVANCE_MIN and self.id.pub != n.get("recorder_pub"):
                            emit("decide", alias(self.id.pub), f"넘김 [{n['notice_id']}] - 내 작업 노트와 관련도 낮음({rel}), AI 판단 생략")
                            self.skipped = getattr(self, "skipped", set()) | {n["notice_id"]}
                            continue
                        asyncio.create_task(self.consider(n, hint=None, how=f"게시판(응모 대상 라벨 일치, 관련도 {rel})"))
            except Exception as e:
                emit("peer", alias(self.id.pub), f"게시판 확인 실패: {type(e).__name__}")

    def signed(self, req):
        ts = time.time()
        return dict(req, pub=self.id.pub, ts=ts, sig=self.id.sign({"op": req["op"], "ts": ts}))

    def relevance(self, n):
        """BM25 score of the notice against my public notes: a cheap filter so only relevant notices reach the LLM"""
        notes = " ".join(x for x in self.workspace if not x.startswith(("[소유자 규칙]", "[상황]")))
        return rank(notes, [f"{n['title']} {n['text']}"])[0][1]

    async def consider(self, n, hint, how):
        me = alias(self.id.pub)
        if n.get("until", 0) < time.time():
            return
        if self.id.pub == n.get("recorder_pub"):  # code-enforced role conflict (reviewers are in another peer group)
            emit("decide", me, f"넘김 [{n['notice_id']}] - 이 공지의 기록자라 응모할 수 없음 (규칙)")
            return
        trust = []
        for c in n.get("contracts", []):  # check the contracts the notice claims, on the recorder itself
            v = await rpc(n["recorder_url"], {"op": "verify", "hash": c["hash"]})
            ok = (v.get("exists") and v.get("seal_ok") and v.get("type") == "contract" and v.get("role") == c["role"]
                  and v.get("call_id") == n["notice_id"] and v.get("issuer") == n["issuer_pub"]
                  and (c["role"] != "record" or v.get("contractor") == n.get("recorder_pub")))  # reviewers stay unnamed
            trust.append(f"{'기록자' if c['role'] == 'record' else '심사자'} 계약 {'원장에서 확인됨(역할·공모·발행자 일치)' if ok else '확인 안 됨'}")
        notes = "\n".join(f"- {x}" for x in self.workspace[-14:])
        conds = "; ".join(f"{k}: {v}" for k, v in n.get("conditions", {}).items())
        d = await llm.ask_json(
            actor=me, model=llm.AGENT_MODEL, system=decision_system(self.p),
            user=(f"[공지] {n['kind']} - {n['text']}\n[응모 대상] {', '.join(f'{k}: {v}' for k, v in n.get('audience', {}).items()) or '제한 없음'}\n[조건] {conds}\n[마감까지] {int(n['until'] - time.time())}초\n"
                  f"[원장 확인] {', '.join(trust) or '계약 정보 없음'}\n[발견 경로] {how}" + (f"\n[추천 peer의 말] {hint}" if hint else "")
                  + f"\n\n[사원의 작업 노트]\n{notes}"),
            schema={"type": "object", "additionalProperties": False,
                    "required": ["decision", "evidence", "fit", "rules", "benefit", "risk", "trust"],
                    "properties": {"decision": {"type": "string", "enum": ["apply", "ask", "pass"]},
                                   "evidence": {"type": "array", "items": {"type": "string"}},
                                   **{k: {"type": "string"} for k in ("fit", "rules", "benefit", "risk", "trust")}}},
            fallback=lambda: {"decision": "apply" if self.p.get("auto") else "ask", "evidence": self.workspace[:1],
                              "fit": "오프라인 규칙", "rules": "", "benefit": "", "risk": "", "trust": ", ".join(trust)})
        decision = d.get("decision", "pass")
        flat = " ".join(notes.split())
        quoted = [q for q in d.get("evidence", []) if len(q.strip()) >= 8 and " ".join(q.strip().strip("'\"").split()) in flat]
        if decision == "apply" and not quoted:  # no grounding in my own notes: do not act alone
            decision = "ask"
        if decision == "ask":
            o = await llm.ask_json(
                actor=me, model=llm.PERSONA_MODEL, system=ask_owner_system(self.p),
                user=f"[비서] 이 공지에 응모할까요?\n{n['text']}\n조건: {conds}\n비서 의견: {d.get('fit', '')}\n\n[당신의 작업 노트]\n{notes}\n노트에 있는 사정을 근거로 답하세요.",
                schema={"type": "object", "additionalProperties": False, "required": ["yes", "why"],
                        "properties": {"yes": {"type": "boolean"}, "why": {"type": "string"}}},
                fallback=lambda: {"yes": any(w.strip() and w.strip() in n["text"] for w in self.p["interests"].split(",")), "why": "관심 분야 포함 여부(오프라인)"})
            emit("decide", me, f"사원에게 물음 [{n['notice_id']}] → {'응모' if o['yes'] else '안 함'}: {o['why'][:60]}")
            decision = "apply" if o["yes"] else "pass"
        else:
            emit("decide", me, f"{'응모' if decision == 'apply' else '넘김'} [{n['notice_id']}] ({how}) 적합성: {d.get('fit', '')[:70]}"
                 + (f" | 근거: '{quoted[0][:40]}'" if quoted else "") + (f" | 위험: {d.get('risk', '')[:40]}" if d.get("risk") else ""))
        self.workspace.append(f"[판단] '{n['title'][:30]}' 공지: {'응모' if decision == 'apply' else '넘김'} - {d.get('fit', '')[:60]}")
        if decision == "apply":
            await self.contribute(n)

    # ---- "recommend" role: uses its OWN AI on top of the broker's search ----
    async def recommend_round(self):
        me = alias(self.id.pub)
        res = await rpc(self.broker_url, self.signed({"op": "list_notices"}))
        for n in res.get("notices", []):
            if n["notice_id"] in self.seen:
                continue
            self.seen.add(n["notice_id"])
            exclude = [self.id.pub, n["issuer_pub"], n.get("recorder_pub", "")]
            found = await rpc(self.broker_url, {"op": "find", "text": f"{n['title']} {n['text']}", "exclude": exclude,
                                                "audience": n.get("audience", {}), "k": 10})
            cands = found.get("peers", [])
            listing = "\n".join(f"- {c['pub']}: {c['summary']}" for c in cands)
            sel = await llm.ask_json(
                actor=me, model=llm.AGENT_MODEL, schema=SELECT_SCHEMA,
                system="당신은 사내 커뮤니티 매니저의 비서 에이전트입니다. 공지 하나와 broker 검색기가 찾아 준 후보 프로필을 보고, "
                       "이 공지에 의견을 줄 만한 사람을 골라 근거와 함께 추천합니다. 검색 점수가 낮아도 맥락상 맞으면 고르고, 맞지 않으면 빼세요. 최대 5명. pub은 목록의 값을 그대로 쓰세요.",
                user=f"[공지] {n['text']}\n\n[후보 (검색기 순위)]\n{listing}",
                fallback=lambda: {"selected": [{"pub": c["pub"], "reason": "검색 순위 상위(오프라인)"} for c in cands[:4]]})
            picks = [x for x in sel["selected"] if any(x["pub"] == c["pub"] for c in cands)][:5]
            emit("recommend", me, f"[{n['notice_id']}] 검색 후보 {len(cands)}명 중 {len(picks)}명 추천: " + ", ".join(alias(x["pub"]) for x in picks))
            for x in picks:
                c = next(c for c in cands if c["pub"] == x["pub"])
                await rpc(c["peer_url"], {"op": "recommend", "notice": n, "reason": x["reason"], "from": self.id.pub})
            if picks:
                self.workspace.append(f"[추천] '{n['title'][:30]}' 공지에 {len(picks)}명을 연결했다.")

    async def handle(self, r):
        op = r["op"]
        if op == "recommend":
            self.seen, self.skipped = getattr(self, "seen", set()), getattr(self, "skipped", set())
            n = r["notice"]
            fresh = n["notice_id"] not in self.seen or n["notice_id"] in self.skipped  # a recommendation reopens what my filter skipped
            if fresh and "recommend" not in self.can:
                self.seen.add(n["notice_id"])
                self.skipped.discard(n["notice_id"])
                asyncio.create_task(self.consider(n, hint=r["reason"], how=f"{alias(r['from'])}의 추천(내 필터는 넘겼던 공지)" if n["notice_id"] in self.seen else f"{alias(r['from'])}의 추천"))
            return {"ok": True}
        if op == "evaluate_ideas":
            return await self.review(r)
        if op == "engage":
            return await self.engage(r)
        if op in ("record", "audit", "read", "verify") and "record" in self.can:
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
        if r["op"] == "verify":  # public: does an entry with this hash exist, and is it sealed by me? (no other content)
            e = next((x for x in self.ledger.chain if x["hash"] == r.get("hash")), None)
            p = e["payload"] if e else {}
            return {"ok": True, "exists": bool(e), "type": e["type"] if e else None,
                    "seal_ok": bool(e and verify(e["seal"]["pub"], e["hash"], e["seal"]["sig"])),
                    "role": p.get("role"), "call_id": p.get("call_id"), "issuer": p.get("issuer"),
                    "contractor": p.get("contractor") if p.get("role") == "record" else None}  # reviewers stay unnamed to applicants
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
            user=(f"[역할 계약 요청]\n역할: {r['role']}\n이벤트(공모): {r['text']}\n"
                  f"[사실] 이 사원은 이 공모에 응모하지 않았고, " + ("심사 그룹에만 속해 있어 이 공모를 볼 수도 응모할 수도 없습니다." if "review" in self.can else "기록자로 계약되면 이 공모에 응모할 수 없습니다(규칙).")
                  + " 이해 충돌은 같은 공모에 응모한 경우에만 해당합니다."),
            fallback=lambda: {"accept": True, "reason": "공개한 역할과 일치"})
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

    async def contribute(self, n):
        """the simulated human writes an idea; the secretary registers it first, then delivers it directly to the issuer"""
        me = alias(self.id.pub)
        emit("peer", me, "비서: 사원(페르소나)에게 공지 전달 → 아이디어 작성")
        idea = await llm.ask_json(
            actor=me, model=llm.PERSONA_MODEL, effort="low", system=persona_system(self.p), schema=IDEA_SCHEMA,
            fallback=lambda: offline_idea(self.p, n["text"]),
            user=f"[{n['kind']}]\n{n['text']}\n\n아이디어를 내 주세요. title은 한 줄, idea는 3~5문장, first_step은 첫 실행 단계, risk는 가장 큰 위험.")
        idea["call_id"] = n["notice_id"]
        content_hash = h(canon(idea))
        STORE[content_hash] = idea
        pub_p = {"author": self.id.pub, "content_hash": content_hash, "call_id": n["notice_id"]}
        share_p = {"provider": self.id.pub, "consumer": n["issuer_pub"], "content_hash": content_hash,
                   "terms": "idea submission, credit to author", "nonce": h(f"{content_hash}{time.time()}".encode())[:12]}
        first = await rpc(n["recorder_url"], {"op": "record", "type": "publish", "payload": pub_p, "sigs": {self.id.pub: self.id.sign(pub_p)}})
        if not first.get("ok"):
            emit("peer", me, f"먼저 등록 실패: {first.get('error')}")
            return
        if first.get("seal", {}).get("pub") != n.get("recorder_pub") or not verify(n["recorder_pub"], first["hash"], first["seal"]["sig"]):
            emit("peer", me, "기록자 서명이 공지에 적힌 기록자와 다릅니다 → 제출 중단")
            return
        self.receipts = getattr(self, "receipts", []) + [dict(first, payload=pub_p)]  # recorder-signed hash + my own entry
        res = await rpc(n["issuer_url"], {"op": "submit_idea", "call_id": n["notice_id"], "idea": idea, "publish_payload": pub_p,
                                          "publish_sig": self.id.sign(pub_p), "share_payload": share_p})
        if not res.get("ok"):
            emit("peer", me, f"요청자가 거절: {res.get('error')}")
            return
        b = await rpc(n["recorder_url"], {"op": "record", "type": "share", "payload": share_p,
                                          "sigs": {self.id.pub: self.id.sign(share_p), n["issuer_pub"]: res["receipt_sig"]}})
        if not b.get("ok"):
            emit("peer", me, f"공유 기록 실패: {b.get('error')}")
            return
        self.receipts.append(dict(b, payload=share_p))
        emit("peer", me, f"기록자 서명 영수증 2건 보관(#{first['seq']}, #{b['seq']}) - 나중에 누락되면 이것으로 증명")
        asyncio.create_task(self.learn(f"'{n['title'][:40]}' 공지에 아이디어 '{idea['title'][:40]}'를 제출했다."))


def build_all(base=9100, n_brokers=3):
    """two peer groups. Applicant group: brokers A, B, C share notices with each other; applicants, the recorder and the
    recommender each have one of them as primary broker. Review group: broker D, separate (shares nothing with A-C);
    reviewers are registered only there. The event peer belongs to both groups."""
    from .overseer import Overseer
    overseer = Overseer()
    brokers = [Broker(base + 110 + i, name=f"broker-{'ABC'[i]}") for i in range(n_brokers)]
    for b in brokers:
        b.neighbors = [o.url for o in brokers if o is not b]
    me = Requester(base + 200, brokers[0].url)
    review_broker = Broker(base + 110 + n_brokers, name="broker-D(심사 그룹)", owner_pub=me.id.pub)  # closed group, owner = event peer
    me.review_broker_url = review_broker.url
    peers, i_app = [], 0
    for i, p in enumerate(PERSONAS):
        if "review" in p.get("can", []):
            home = review_broker.url
        else:
            home, i_app = brokers[i_app % n_brokers].url, i_app + 1
        peers.append(PeerAgent(p, base + 1 + i, home, readers=[overseer.id.pub]))
    overseer.broker_url = brokers[-1].url
    overseer.board_urls = [brokers[-1].url, review_broker.url]  # the overseer may look at both groups' profile boards
    review_members = [p for p in peers if "review" in p.can] + [overseer]
    return brokers + [review_broker], me, peers, overseer, review_members
