"""Test-only stand-in apps for the idea-contest motif. They are NOT part of the platform: the platform is generic and
the contest exists only to exercise it. Each double uses one platform extension point."""
from arena.crypto import canon, h, verify
from arena.llm import ask_json
from arena.peer.app import Decision, PeerApp
from arena.peer.owner import Answer

KIND = "아이디어 공모"
POLICY = {"roles": ["record", "review"], "conflict_roles": ["record", "review"],
          "verdict_roles": {"review": "review", "adopt": "issuer"}, "hidden_roles": ["review"]}
ENDORSER_LABEL = "직책:대표이사"
AUDIENCE = {"소속": "삼성SDS"}
OPEN, REVIEW = "applicants", "reviewers"
CONTENT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "idea"],
                  "properties": {"title": {"type": "string"}, "idea": {"type": "string"}}}
SCORES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["reviews"], "properties": {"reviews": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "score", "comment"],
                               "properties": {"id": {"type": "string"}, "score": {"type": "number"}, "comment": {"type": "string"}}}}}}


class EndorseByOwner(PeerApp):
    """endorse_event: ask the owner (the CEO) whether to put the company's name on the event (an endorsement after the
    event is declared: weight for it, the publisher's own choice; user 2026-11-04)"""
    name = "endorse-by-owner"

    def offers(self):
        return ["endorse"]

    async def endorse_event(self, ctx, body, request):
        a = await ctx.owner.ask("다음 이벤트에 회사 이름으로 공동 서명해 달라는 요청을 받았습니다. 공동 서명할까요?", f"이벤트 내용: {request.get('text', '')}")
        return Decision(a.yes, a.why)


class AcceptRole(PeerApp):
    """offers one role and asks the owner whether to take it"""

    def __init__(self, role):
        self.role, self.name = role, f"accept-{role}"

    def offers(self):
        return [self.role]

    async def accept_role(self, ctx, role, request):
        if role != self.role:
            return None
        a = await ctx.owner.ask(f"이 이벤트에서 '{role}' 역할을 맡아 달라는 요청이 왔습니다. 지금 무엇을 평가하라는 것이 아니라, "
                                 f"나중에 이 역할을 맡을지 정하는 것입니다. 맡을까요?", f"이벤트 내용: {request.get('text', '')}")
        return Decision(a.yes, a.why)


class Judge(PeerApp):
    """the reviewer's judging app (the evaluation element's EvaluationProvider): scores from the owner; the platform's
    EvaluationDesk checks the handovers and signs the verdicts"""
    name = "judge"

    async def evaluate(self, ctx, items, request):
        listing = "\n".join(f"- {i['content_hash'][:8]}: {i['content']}" for i in items)
        d = await ctx.owner.write("각 항목에 1~10점과 한 문장 의견을 주세요. id는 목록의 값을 그대로 쓰세요.", listing, SCORES_SCHEMA)
        full = {i["content_hash"][:8]: i["content_hash"] for i in items}
        return [{"content_hash": full[r["id"]], "score": float(r["score"]), "comment": r["comment"]} for r in d["reviews"] if r["id"] in full]


class LLMOwner:
    """test double for a person: an LLM plays them (used by the live motif test)"""
    ANSWER = {"type": "object", "additionalProperties": False, "required": ["yes", "why"],
              "properties": {"yes": {"type": "boolean"}, "why": {"type": "string"}}}

    def __init__(self, llm, log, who, persona):
        self.llm, self.log, self.who, self.persona = llm, log, who, persona

    async def ask(self, question, context=""):
        d = await ask_json(self.llm, self.log, self.who, fallback=lambda: {"yes": False, "why": "LLM 응답 없음"},
                           system=f"당신은 AI가 아니라 사람입니다. {self.persona} 질문에 당신의 판단으로 답하세요. "
                                  "yes에는 예/아니오를, why에는 그렇게 정한 이유를 한 문장으로 쓰세요.",
                           user=f"{question}\n\n{context}", schema=self.ANSWER)
        return Answer(bool(d["yes"]), d["why"])

    async def write(self, task, context, schema):
        return await self.llm.ask_json(system=f"당신은 AI가 아니라 사람입니다. {self.persona}", user=f"{task}\n\n{context}", schema=schema)
