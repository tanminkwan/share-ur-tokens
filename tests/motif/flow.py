"""The idea-contest motif, end to end, using only platform APIs plus the test doubles. Shared by the in-memory world
and the real-process world. `w` provides: org, rec, ceo, rev, applicants (peers) and inbox (the org's Inbox double)."""
import time

from arena.crypto import canon, h
from tests.motif.doubles import APPROVER_LABEL, AUDIENCE, KIND, OPEN, POLICY, REVIEW

CALL = "신입 사원이 입사 첫 달에 빨리 적응하도록 돕는 아이디어를 모집합니다."


def nonce(*parts):
    return h(canon([*parts, time.time()]))[:12]


async def open_event(w, text=CALL):
    """organizer: recorder contract -> CEO approval -> event declaration -> reviewer contract -> notice"""
    org, out = w.org, {"approved": False}
    rec_hit = (await org.brokers[OPEN].find("원장 기록 보관 열람 통제", role="record", identity=org.identity))["peers"][0]
    R = org.recorder(rec_hit["recorder_url"])
    ev_id = "contest-" + nonce(text)[:6]
    c_rec = {"event_id": ev_id, "role": "record", "issuer": org.identity.pub, "contractor": rec_hit["pub"], "nonce": nonce("rec")}
    eng = await org.call(rec_hit["url"], {"op": "engage", "role": "record", "contract": c_rec, "request": {"text": text}})
    assert eng["ok"], eng
    ceo_hit = (await org.brokers[OPEN].find("대표이사 결재", labels=[APPROVER_LABEL], identity=org.identity))["peers"][0]
    event = {"event_id": ev_id, "issuer": org.identity.pub, "kind": KIND, "policy": POLICY, "approvers": [ceo_hit["pub"]]}
    apr = await org.call(ceo_hit["url"], {"op": "approve", "event": event, "request": {"title": text[:30], "text": text}})
    out.update(event_id=ev_id, approval=apr, recorder=rec_hit, ceo=ceo_hit, R=R)
    if not apr.get("ok"):
        return out
    ev_rec = await R.record("event", event, {org.identity.pub: org.sign(event), ceo_hit["pub"]: apr["sig"]})
    cr = await R.record("contract", c_rec, {org.identity.pub: org.sign(c_rec), rec_hit["pub"]: eng["sig"]})
    rev_hit = (await org.brokers[REVIEW].find("공모 심사 평가 기준", role="review", identity=org.identity))["peers"][0]
    c_rev = {"event_id": ev_id, "role": "review", "issuer": org.identity.pub, "contractor": rev_hit["pub"], "nonce": nonce("rev")}
    eng2 = await org.call(rev_hit["url"], {"op": "engage", "role": "review", "contract": c_rev, "request": {"text": text}})
    assert eng2["ok"], eng2
    cv = await R.record("contract", c_rev, {org.identity.pub: org.sign(c_rev), rev_hit["pub"]: eng2["sig"]})
    assert ev_rec["ok"] and cr["ok"] and cv["ok"], (ev_rec, cr, cv)
    w.inbox.blocked[ev_id] = {rec_hit["pub"], rev_hit["pub"]}
    notice = {"notice_id": ev_id, "kind": KIND, "title": text[:30], "text": text, "audience": AUDIENCE,
              "until": time.time() + 600, "issuer_pub": org.identity.pub, "issuer_url": org.config.url,
              "event_hash": ev_rec["hash"], "approver_pub": ceo_hit["pub"],
              "recorder_pub": rec_hit["pub"], "recorder_url": rec_hit["recorder_url"],
              "contracts": [{"role": "record", "hash": cr["hash"]}, {"role": "review", "hash": cv["hash"]}]}
    posted = await org.brokers[OPEN].post_notice(org.identity, notice)
    out.update(approved=True, event_hash=ev_rec["hash"], reviewer=rev_hit, notice=notice, posted=posted)
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


async def apply(p, n, content):
    """applicant: publish first, submit p2p, record the share; keep recorder-signed receipts"""
    R = p.recorder(n["recorder_url"])
    ch = h(canon(content))
    pub_p = {"author": p.identity.pub, "content_hash": ch, "event_id": n["notice_id"]}
    r1 = await R.record("publish", pub_p, {p.identity.pub: p.sign(pub_p)})
    if not p.receipts.keep(r1, "publish", pub_p, expected_recorder=n["recorder_pub"]):
        return {"ok": False, "error": r1.get("error", "recorder seal mismatch")}
    share_p = {"provider": p.identity.pub, "consumer": n["issuer_pub"], "content_hash": ch, "terms": "submission", "nonce": nonce(ch)}
    sub = await p.call(n["issuer_url"], {"op": "submit", "event_id": n["notice_id"], "content": content, "publish_payload": pub_p,
                                         "publish_sig": p.sign(pub_p), "share_payload": share_p})
    if not sub.get("ok"):
        return sub
    r2 = await R.record("share", share_p, {p.identity.pub: p.sign(share_p), n["issuer_pub"]: sub["receipt_sig"]})
    assert p.receipts.keep(r2, "share", share_p, expected_recorder=n["recorder_pub"]), r2
    return {"ok": True, "content_hash": ch}


async def review_and_adopt(w, opened, top=1):
    """organizer: hand everything to the contracted reviewer, record its signed reviews, adopt the best by score"""
    org, R, rv, ev = w.org, opened["R"], opened["reviewer"], opened["event_id"]
    items = w.inbox.items.get(ev, {})
    shares = {k: {"provider": org.identity.pub, "consumer": rv["pub"], "content_hash": k, "terms": "review", "nonce": nonce(k, rv["pub"])}
              for k in items}
    res = await org.call(rv["url"], {"op": "judge", "event_id": ev, "share_payloads": shares,
                                     "items": [dict(id=k[:8], **v["content"]) for k, v in items.items()]})
    assert res["ok"], res
    for k, p in shares.items():
        r = await R.record("share", p, {org.identity.pub: org.sign(p), rv["pub"]: res["receipts"][k]})
        assert r["ok"], r
    scores = {}
    for x in res["reviews"]:
        assert h(x["comment"].encode()) == x["payload"]["comment_hash"]
        r = await R.record("feedback", x["payload"], {rv["pub"]: x["sig"]})
        assert r["ok"], r
        scores[x["payload"]["content_hash"]] = x["payload"]["score"]
    adopted = sorted(scores, key=lambda k: -scores[k])[:top]
    for k in adopted:
        p = {"evaluator": org.identity.pub, "event_id": ev, "content_hash": k, "verdict": "adopt", "reason_hash": h(b"highest score")}
        r = await R.record("feedback", p, {org.identity.pub: org.sign(p)})
        assert r["ok"], r
    return {"scores": scores, "adopted": adopted}
