"""Test-only stand-in apps for the idea-contest motif. They are NOT part of the platform: the platform is generic and
the contest exists only to exercise it. Each double uses one platform extension point."""
from arena.crypto import canon, h, verify
from arena.llm import ask_json
from arena.peer.app import Decision, PeerApp
from arena.peer.owner import Answer

KIND = "아이디어 공모"
POLICY = {"roles": ["record", "review"], "conflict_roles": ["record", "review"],
          "verdict_roles": {"review": "review", "adopt": "issuer"}, "hidden_roles": ["review"]}
APPROVER_LABEL = "직책:대표이사"
AUDIENCE = {"소속": "삼성SDS"}
OPEN, REVIEW = "applicants", "reviewers"
CONTENT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "idea"],
                  "properties": {"title": {"type": "string"}, "idea": {"type": "string"}}}
SCORES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["reviews"], "properties": {"reviews": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "score", "comment"],
                               "properties": {"id": {"type": "string"}, "score": {"type": "number"}, "comment": {"type": "string"}}}}}}


class ApproveByOwner(PeerApp):
    """approve_event: ask the owner (the CEO) whether to sign the event"""
    name = "approve-by-owner"

    def offers(self):
        return ["approve"]

    async def approve_event(self, peer, event, request):
        a = await peer.owner.ask(f"'{request.get('title', '')}' 이벤트를 결재할까요?", request.get("text", ""))
        return Decision(a.yes, a.why)


class AcceptRole(PeerApp):
    """offers one role and asks the owner whether to take it"""

    def __init__(self, role):
        self.role, self.name = role, f"accept-{role}"

    def offers(self):
        return [self.role]

    async def accept_role(self, peer, role, request):
        if role != self.role:
            return None
        a = await peer.owner.ask(f"'{role}' 역할을 맡을까요?", request.get("text", ""))
        return Decision(a.yes, a.why)


class Inbox(PeerApp):
    """op submit: verify a submission (content hash, author signature, receiver, one per author, blocked roles) and sign receipt"""
    name = "inbox"

    def __init__(self):
        self.items, self.blocked = {}, {}

    def ops(self):
        return {"submit": self._submit}

    async def _submit(self, peer, msg):
        ev, pub_p, share_p = msg["event_id"], msg["publish_payload"], msg["share_payload"]
        if ev not in self.blocked:
            return {"ok": False, "error": "unknown event"}
        if pub_p["author"] in self.blocked[ev]:
            return {"ok": False, "error": "a contracted role cannot submit"}
        if h(canon(msg["content"])) != pub_p["content_hash"] or not verify(pub_p["author"], pub_p, msg["publish_sig"]):
            return {"ok": False, "error": "content hash / author signature mismatch"}
        if share_p["consumer"] != peer.identity.pub or share_p["content_hash"] != pub_p["content_hash"]:
            return {"ok": False, "error": "share payload does not match"}
        mine = self.items.setdefault(ev, {})
        if any(x["author"] == pub_p["author"] for x in mine.values()):
            return {"ok": False, "error": "one submission per peer per event"}
        mine[pub_p["content_hash"]] = {"author": pub_p["author"], "content": msg["content"]}
        return {"ok": True, "receipt_sig": peer.sign(share_p)}


class Judge(PeerApp):
    """op judge: sign receipts for what was handed over, get scores from the owner, sign review payloads (comment off-ledger)"""
    name = "judge"

    def ops(self):
        return {"judge": self._judge}

    async def _judge(self, peer, msg):
        if any(p["consumer"] != peer.identity.pub for p in msg["share_payloads"].values()):
            return {"ok": False, "error": "share payload mismatch"}
        listing = "\n".join(f"- {i['id']}: [{i['title']}] {i['idea']}" for i in msg["items"])
        d = await peer.owner.write("각 항목에 1~10점과 한 문장 의견을 주세요. id는 목록의 값을 그대로 쓰세요.", listing, SCORES_SCHEMA)
        full = {k[:8]: k for k in msg["share_payloads"]}
        out = []
        for r in d["reviews"]:
            if r["id"] in full:
                p = {"evaluator": peer.identity.pub, "event_id": msg["event_id"], "content_hash": full[r["id"]], "verdict": "review",
                     "score": float(r["score"]), "comment_hash": h(r["comment"].encode())}
                out.append({"payload": p, "sig": peer.sign(p), "comment": r["comment"]})
        return {"ok": True, "receipts": {k: peer.sign(p) for k, p in msg["share_payloads"].items()}, "reviews": out}


class LLMOwner:
    """test double for a person: an LLM plays them (used by the live motif test)"""
    ANSWER = {"type": "object", "additionalProperties": False, "required": ["yes", "why"],
              "properties": {"yes": {"type": "boolean"}, "why": {"type": "string"}}}

    def __init__(self, llm, log, who, persona):
        self.llm, self.log, self.who, self.persona = llm, log, who, persona

    async def ask(self, question, context=""):
        d = await ask_json(self.llm, self.log, self.who, fallback=lambda: {"yes": False, "why": "LLM 응답 없음"},
                           system=f"당신은 AI가 아니라 사람입니다. {self.persona} 질문에 당신의 판단으로 답하세요.",
                           user=f"{question}\n\n{context}", schema=self.ANSWER)
        return Answer(bool(d["yes"]), d["why"])

    async def write(self, task, context, schema):
        return await self.llm.ask_json(system=f"당신은 AI가 아니라 사람입니다. {self.persona}", user=f"{task}\n\n{context}", schema=schema)
