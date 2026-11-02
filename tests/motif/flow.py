"""The idea-contest motif, end to end, using only platform APIs plus the test doubles. Shared by the in-memory world
and the real-process world. `w` provides: org, rec, ceo, rev, applicants (peers). Submissions and handing them to the
reviewer use the built-in elements (P6-V2): the org's IntakeDesk and the reviewer's EvaluationDesk."""
import time

from arena.crypto import canon, h
from tests.motif.doubles import APPROVER_LABEL, AUDIENCE, KIND, OPEN, POLICY, REVIEW


def ELEMENTS() -> dict:
    """the built-in elements the contest switches on (P6-V2)"""
    return {"intake": {"deadline": time.time() + 3600, "max_per_author": 1, "receiver": "issuer",
                       "audience": [f"{k}:{v}" for k, v in AUDIENCE.items()]},
            "evaluation": {"evaluator_role": "review", "verdict": "review", "per_item": 1}}


async def lid(recorder) -> dict:
    """{"ledger_id": ...}: every payload signed for a ledger begun by a genesis names that ledger (P5-G4)"""
    x = (await recorder.health()).get("ledger_id")
    return {"ledger_id": x} if x else {}


async def found_group(founder, recorder, group, closed):
    """the founding peer notarizes a broker group once, when it creates it"""
    gid = await founder.group_id(group)
    health = await founder.brokers[group].health()
    p = {"group_id": gid, "founder": founder.identity.pub, "closed": closed, "brokers": [health["pub"]], **(await lid(recorder))}
    return await recorder.record("group", p, {founder.identity.pub: founder.sign(p)})

CALL = "신입 사원이 입사 첫 달에 빨리 적응하도록 돕는 아이디어를 모집합니다."


def nonce(*parts):
    return h(canon([*parts, time.time()]))[:12]


async def open_event(w, text=CALL, reviewer=None, post=True):
    """organizer: recorder contract -> CEO approval -> event declaration -> reviewer contract -> notice.
    reviewer: a pre-checked candidate (else the broker's top review hit); post=False builds the notice but does not post it"""
    org, out = w.org, {"approved": False}
    g_open, g_rev = await org.group_id(OPEN), await org.group_id(REVIEW)  # every entry names the group it happened in
    rec_hit = (await org.brokers[OPEN].find("원장 기록 보관 열람 통제", role="record", identity=org.identity))["peers"][0]
    R = org.recorder(rec_hit["recorder_url"])
    L = await lid(R)
    ev_id = "contest-" + nonce(text)[:6]
    c_rec = {"event_id": ev_id, "role": "record", "issuer": org.identity.pub, "contractor": rec_hit["pub"], "nonce": nonce("rec"), "group_id": g_open, **L}
    eng = await org.call(rec_hit["url"], {"op": "engage", "role": "record", "contract": c_rec, "request": {"text": text}})
    assert eng["ok"], eng
    ceo_hit = (await org.brokers[OPEN].find("대표이사 결재", labels=[APPROVER_LABEL], identity=org.identity))["peers"][0]
    event = {"event_id": ev_id, "issuer": org.identity.pub, "kind": KIND, "policy": POLICY, "approvers": [ceo_hit["pub"]], "group_id": g_open,
             "elements": ELEMENTS(), **L}
    apr = await org.call(ceo_hit["url"], {"op": "approve", "event": event, "request": {"title": text[:30], "text": text}})
    out.update(event_id=ev_id, approval=apr, recorder=rec_hit, ceo=ceo_hit, R=R)
    if not apr.get("ok"):
        return out
    ev_rec = await R.record("event", event, {org.identity.pub: org.sign(event), ceo_hit["pub"]: apr["sig"]})
    cr = await R.record("contract", c_rec, {org.identity.pub: org.sign(c_rec), rec_hit["pub"]: eng["sig"]})
    rev_hit = reviewer or (await org.brokers[REVIEW].find("공모 심사 평가 기준", role="review", identity=org.identity))["peers"][0]
    c_rev = {"event_id": ev_id, "role": "review", "issuer": org.identity.pub, "contractor": rev_hit["pub"], "nonce": nonce("rev"), "group_id": g_rev, **L}
    eng2 = await org.call(rev_hit["url"], {"op": "engage", "role": "review", "contract": c_rev, "request": {"text": text}})
    assert eng2["ok"], eng2
    cv = await R.record("contract", c_rev, {org.identity.pub: org.sign(c_rev), rev_hit["pub"]: eng2["sig"]})
    assert ev_rec["ok"] and cr["ok"] and cv["ok"], (ev_rec, cr, cv)
    notice = {"notice_id": ev_id, "kind": KIND, "title": text[:30], "text": text, "audience": AUDIENCE,
              "until": time.time() + 600, "issuer_pub": org.identity.pub, "issuer_url": org.config.url,
              "event_hash": ev_rec["hash"], "approver_pub": ceo_hit["pub"],
              "recorder_pub": rec_hit["pub"], "recorder_url": rec_hit["recorder_url"],
              "contracts": [{"role": "record", "hash": cr["hash"]}, {"role": "review", "hash": cv["hash"]}], "group_id": g_open,
              "elements": event["elements"]}
    posted = await org.brokers[OPEN].post_notice(org.identity, notice) if post else None
    out.update(approved=True, event_hash=ev_rec["hash"], reviewer=rev_hit, notice=notice, posted=posted, groups=(g_open, g_rev))
    return out


async def check_notice(p, n):
    """applicant: is the event declared and approved by someone holding the approver label? are the contracts real?"""
    R = p.recorder(n["recorder_url"])
    ev = await R.verify(n["event_hash"])
    approver = next((x for x in (await p.brokers[OPEN].list_profiles(p.identity))["profiles"] if x["pub"] == n["approver_pub"]), None)
    contracts = [await R.verify(c["hash"]) for c in n["contracts"]]
    return {"event_ok": ev["exists"] and ev["seal_ok"] and ev["type"] == "event" and ev["event_id"] == n["notice_id"]
                        and ev["issuer"] == n["issuer_pub"] and n["approver_pub"] in ev["approvers"],
            "approver_label_ok": bool(approver and APPROVER_LABEL in approver.get("labels", [])),
            "contracts_ok": all(c["exists"] and c["seal_ok"] and c["event_id"] == n["notice_id"] for c in contracts),
            "contracts": contracts}


def text_of(content: dict) -> str:
    return f"[{content['title']}] {content['idea']}"


async def apply(p, n, content):
    """applicant: publish first, then submit to the organizer's IntakeDesk, which checks, co-signs and records the share"""
    R = p.recorder(n["recorder_url"])
    L = await lid(R)
    text = text_of(content)
    ch = h(text.encode("utf-8"))
    pub_p = {"author": p.identity.pub, "content_hash": ch, "event_id": n["notice_id"], "group_id": n["group_id"], **L}
    r1 = await R.record("publish", pub_p, {p.identity.pub: p.sign(pub_p)})
    if not p.receipts.keep(r1, "publish", pub_p, expected_recorder=n["recorder_pub"]):
        return {"ok": False, "error": r1.get("error", "recorder seal mismatch")}
    share_p = {"provider": p.identity.pub, "consumer": n["issuer_pub"], "content_hash": ch, "terms": "submission", "nonce": nonce(ch),
               "event_id": n["notice_id"], "group_id": n["group_id"], **L}
    sub = await p.call(n["issuer_url"], {"op": "intake.submit", "event_id": n["notice_id"], "content": text, "share": share_p,
                                         "sig": p.sign(share_p), "recorder_url": n["recorder_url"]})
    if not sub.get("ok"):
        return sub
    assert p.receipts.keep(sub, "share", share_p, expected_recorder=n["recorder_pub"]), sub
    return {"ok": True, "content_hash": ch}


def submissions(w, ev) -> dict:
    """what the organizer's IntakeDesk received: content hash -> {author, content, ...}"""
    from arena.peer.elements.intake import IntakeDesk
    return {x["content_hash"]: x for x in w.org.app_by_id(IntakeDesk.app_id).list(ev)}


async def review_and_adopt(w, opened, top=1):
    """organizer: hand every submission to the contracted reviewer's EvaluationDesk, record the handovers and the signed
    verdicts, then adopt the best by score (adopting is the contest's own judgement, done here in the motif, not the platform)"""
    org, R, rv, ev = w.org, opened["R"], opened["reviewer"], opened["event_id"]
    g_open, g_rev = opened["groups"]
    L = await lid(R)
    items = []
    for k, v in submissions(w, ev).items():
        sh = {"provider": org.identity.pub, "consumer": rv["pub"], "content_hash": k, "terms": "evaluation", "nonce": nonce(k, rv["pub"]),
              "event_id": ev, "group_id": g_rev, **L}
        items.append({"share": sh, "sig": org.sign(sh), "content": v["content"]})
    res = await org.call(rv["url"], {"op": "evaluation.request", "event_id": ev, "recorder_url": opened["recorder"]["recorder_url"], "items": items})
    assert res["ok"], res
    for it in items:
        r = await R.record("share", it["share"], {org.identity.pub: it["sig"], rv["pub"]: res["receipts"][it["share"]["content_hash"]]})
        assert r["ok"], r
    scores = {}
    for x in res["verdicts"]:
        assert h(x["comment"].encode()) == x["payload"]["comment_hash"]
        r = await R.record("feedback", x["payload"], {rv["pub"]: x["sig"]})
        assert r["ok"], r
        scores[x["payload"]["content_hash"]] = x["payload"]["score"]
    adopted = sorted(scores, key=lambda k: -scores[k])[:top]
    for k in adopted:
        p = {"evaluator": org.identity.pub, "event_id": ev, "content_hash": k, "verdict": "adopt", "reason_hash": h(b"highest score"),
             "group_id": g_open, **L}
        r = await R.record("feedback", p, {org.identity.pub: org.sign(p)})
        assert r["ok"], r
    return {"scores": scores, "adopted": adopted}
