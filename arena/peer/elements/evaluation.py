"""The evaluation element, peer side (P6-C2 ~ C4). The host hands items to a contracted evaluator; the evaluator's
EvaluationDesk checks each handover by code, gets verdicts from an app with the EvaluationProvider capability (or the
basic assistant), signs the verdict payloads in code and returns them with its handover signatures; the host records
both. What the event then does with the verdicts is its own judgement (an app's or an API-providing peer's job)."""
from __future__ import annotations

from ...crypto import h, verify
from ..assistant.state import nonce
from ..assistant.tools import S, Tool, _obj, ledger_tag
from ..plugin import ASSISTANT_APP_ID, BaseApp, MessageHead, EvaluationProvider
from . import PeerElement, register_peer_element


class EvaluationDesk(BaseApp):
    name, version, app_id = "platform.evaluation", "1.0", "4b9e2c7d-1a3f-4e6b-8c5d-9f0a2b4c6d81"

    def __init__(self, settings):
        self.s = settings

    def ops(self):
        return {"evaluation.request": self._request}

    async def _request(self, ctx, msg, head: MessageHead):
        ev, url, items = msg.get("event_id"), msg.get("recorder_url"), msg.get("items") or []
        trust = await ctx.recorder_trust(url) if url else {"ok": False, "why": "recorder_url 없음"}
        if not trust["ok"]:
            return {"ok": False, "error": f"기록자를 믿을 수 없다: {trust.get('why')}"}
        decl = next((e for e in (await ctx.recorder(url).event_entries(ev)).get("entries", []) if e["type"] == "event"), None)
        cfg = ((decl or {}).get("elements") or {}).get("evaluation")
        if cfg is None:
            return {"ok": False, "error": "이 이벤트는 평가 요소를 켜지 않았다"}
        if not items or len(items) > self.s.evaluation_max_items:
            return {"ok": False, "error": f"한 번에 1~{self.s.evaluation_max_items}개 항목을 넘긴다"}
        for it in items:
            sh = it.get("share") or {}
            if (sh.get("consumer") != ctx.pub or sh.get("purpose") != "evaluation" or sh.get("event_id") != ev or sh.get("provider") != decl["issuer"]
                    or h(str(it.get("content", "")).encode("utf-8")) != sh.get("content_hash") or not verify(decl["issuer"], sh, it.get("sig", ""))):
                return {"ok": False, "error": "넘김 기록, 내용 해시나 개최자 서명이 맞지 않는 항목이 있다"}
        judges = [(a, c) for a, c in ctx.apps_with(EvaluationProvider) if a.app_id != ASSISTANT_APP_ID]
        judges += [(a, c) for a, c in ctx.apps_with(EvaluationProvider) if a.app_id == ASSISTANT_APP_ID]  # the basic assistant last
        if not judges:
            return {"ok": False, "error": "평가할 앱이 없다"}
        app, actx = judges[0]
        got = await app.evaluate(actx, [{"content_hash": it["share"]["content_hash"], "content": it["content"]} for it in items],
                               {"event_id": ev, "verdict": cfg["verdict"]})
        wanted = {it["share"]["content_hash"] for it in items}
        verdict_list = []
        for r in got or []:
            if r.get("content_hash") not in wanted:
                continue
            p = {"evaluator": ctx.pub, "event_id": ev, "content_hash": r["content_hash"], "verdict": cfg["verdict"], "score": float(r.get("score", 0)),
                 "comment_hash": h(str(r.get("comment", "")).encode("utf-8")), "group_id": decl.get("group_id") or items[0]["share"]["group_id"],
                 **({"ledger_id": trust["ledger_id"]} if trust.get("ledger_id") else {})}
            verdict_list.append({"payload": p, "sig": ctx.sign(p), "comment": str(r.get("comment", ""))})
        ctx.log.emit("evaluation", ctx.pen, f"[{ev}] {len(items)}개 항목 평가, 판정 {len(verdict_list)}개")
        return {"ok": True, "receipts": {it["share"]["content_hash"]: ctx.sign(it["share"]) for it in items}, "verdicts": verdict_list}


# ---------------- assistant tools (host) ----------------
async def request_evaluation(A, ctx, st, evaluator):
    cfg = st.elements["evaluation"]
    pub, _ = await A.resolve_peer(ctx, st, evaluator, need_url=False)
    if not pub or [cfg["evaluator_role"], pub] not in st.contracts:
        return {"ok": False, "error": f"{evaluator}는 {cfg['evaluator_role']} 역할로 계약한 peer가 아니다"}
    todo = [x for x in await ctx.submissions(st.event_id) if pub not in [r["evaluator"] for r in st.evaluations.get(x["content_hash"], [])]]
    if not todo:
        return {"ok": False, "error": "넘길 새 제출이 없다"}
    todo = todo[:ctx.settings.evaluation_max_items]
    tag = await ledger_tag(ctx, st)
    items = []
    for x in todo:
        sh = {"provider": ctx.pub, "consumer": pub, "content_hash": x["content_hash"], "purpose": "evaluation", "nonce": nonce(x["content_hash"], pub),
              "event_id": st.event_id, "group_id": st.group_id, **tag}
        items.append({"share": sh, "sig": ctx.sign(sh), "content": x["content"]})
    out = await ctx.call_peer(pub, {"op": "evaluation.request", "event_id": st.event_id, "recorder_url": st.recorder_url, "items": items},
                              group=st.group_id, event=st.event_id)
    if not out.get("ok"):
        return {"ok": False, "error": out.get("error")}
    rec, errors = ctx.recorder(st.recorder_url), []
    for it in items:
        ch = it["share"]["content_hash"]
        r = await rec.record("share", it["share"], {ctx.pub: it["sig"], pub: out["receipts"].get(ch, "")})
        if not r.get("ok"):
            errors.append(r.get("error"))
    n = 0
    for v in out["verdicts"]:
        r = await rec.record("feedback", v["payload"], {pub: v["sig"]})
        if r.get("ok"):
            n += 1
            st.evaluations.setdefault(v["payload"]["content_hash"], []).append({"evaluator": pub, "score": v["payload"]["score"],
                                                                            "comment": v["comment"], "hash": r["hash"]})
        else:
            errors.append(r.get("error"))
    return {"ok": not errors, "handed": len(items), "verdicts": n, **({"errors": errors} if errors else {})}


async def verdicts(A, ctx, st):
    subs = {x["content_hash"]: x for x in await ctx.submissions(st.event_id)}
    rows = []
    for ch, vs in st.evaluations.items():
        rows.append({"item": (subs.get(ch) or {}).get("content", "")[:80], "author": A.handle(ctx, st, (subs.get(ch) or {}).get("author", "")) if ch in subs else "",
                     "verdicts": [{"evaluator": A.handle(ctx, st, v["evaluator"]), "score": v["score"], "comment": v["comment"]} for v in vs]})
    return {"ok": True, "items": rows, "note": "판정 목록이다. 판정으로 무엇을 할지는 이 이벤트의 규칙이 정한다"}


register_peer_element(PeerElement("evaluation", app=EvaluationDesk, tools=(
    Tool("request_evaluation", "{evaluator}: 받은 제출 가운데 아직 넘기지 않은 것을 계약한 평가자(필명)에게 넘기고, 돌아온 서명된 판정을 원장에 기록한다",
         _obj(evaluator=S), request_evaluation, host_only=True, element="evaluation", label="평가 맡기기"),
    Tool("verdicts", "{}: 항목별 판정(평가자, 점수, 의견)을 본다", None, verdicts, host_only=True, element="evaluation", label="판정 보기"),
)))
