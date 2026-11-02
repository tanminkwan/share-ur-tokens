"""P4-E2: the idea-contest motif in collection mode (no notice): search peer for candidates, track-record pre-check
before the role contract, direct requests to chosen applicants. Test-only doubles; everything else is platform."""
import asyncio
import time

import pytest

from arena.crypto import Identity
from arena.ledger import audit_chain
from arena.peer.app import PeerApp
from arena.peer.search_role import SearchRole
from arena.peer.track import meets, track_of
from arena.signing import sign_message
from tests.fakes import FakeOwner, HashEmbedder
from tests.motif.doubles import OPEN, REVIEW, AcceptRole, Judge
from tests.motif.flow import lid, submissions, apply, check_notice, open_event, review_and_adopt
from tests.motif.test_motif_memory import SDS, MemoryWorld


class ApplyOnRequest(PeerApp):
    """test double: when a direct request arrives, check it like a notice and apply with what the owner writes"""
    name, version = "apply-on-request", "1.0"

    def __init__(self):
        self.results = []

    async def on_request(self, peer, request, sender):
        n = dict(request, notice_id=request["request_id"])
        chk = await check_notice(peer, n)
        if chk["event_ok"] and chk["approver_label_ok"] and chk["contracts_ok"]:
            content = await peer.owner.write("기획서", "\n".join(peer.area.lines()), {})
            self.results.append(await apply(peer, n, content))


@pytest.fixture
async def world(tmp_path, settings):
    w = MemoryWorld(tmp_path, settings)
    w.rev2 = w.peer("rev2", [AcceptRole("review"), Judge()], ["공모 심사 평가 기준 심사위원 신규"], groups=[REVIEW])
    for i, p in enumerate(w.applicants):
        app = ApplyOnRequest()
        await p.install(app)
        p.owner = FakeOwner(writes=[{"title": f"직접 요청에 응한 기획 {i}", "idea": "공개 영역 메모로 다듬은 기획서"}])
    w.applicants[2].area.add_note("물류 창고 재고 실사")  # less related: should not be among the chosen
    w.search_role = SearchRole(HashEmbedder(), settings)
    w.search = w.peer("search", [w.search_role], ["고급 검색 peer"], groups=[OPEN, REVIEW])
    for p in (w.rev2, w.search):
        g = {"pub": p.identity.pub, "until": time.time() + 3600}
        await w.brokers[REVIEW].grant(g, w.org_id.sign(g))
    await w.boot()
    for p in (w.rev2, w.search):
        await p.advertise()
    # an earlier event in which the experienced reviewer already served
    R = w.org.recorder("mem://rec/recorder")
    L = await lid(R)
    past = {"event_id": "past", "issuer": w.org.identity.pub, "kind": "earlier", "policy": {}, "approvers": [], "group_id": "g-review", **L}
    assert (await R.record("event", past, {w.org.identity.pub: w.org.sign(past)}))["ok"]
    c = {"event_id": "past", "role": "review", "issuer": w.org.identity.pub, "contractor": w.rev.identity.pub, "nonce": "past-1", "group_id": "g-review", **L}
    assert (await R.record("contract", c, {w.org.identity.pub: w.org.sign(c), w.rev.identity.pub: w.rev.sign(c)}))["ok"]
    await w.search_role.sync(w.search)
    return w


async def test_p4e2_collection_mode_end_to_end(world):
    w, org = world, world.org
    ask = lambda op, **kw: org.call(w.search.config.url, dict({"op": op, **kw}, **sign_message(org.identity, op)))
    # 1. reviewer candidates from the search peer (closed group: the organizer is a member), then the track-record check
    cands = (await ask("search_profiles", q="공모 심사 평가 기준", role="review", k=5))["hits"]
    assert {c["pub"] for c in cands} == {w.rev.identity.pub, w.rev2.identity.pub}
    checked = []
    for c in cands:
        t = await track_of(org, c["pub"], ["mem://rec/recorder"])
        checked.append((c, meets(t, {"roles": {"review": 1}})))
    passed = [c for c, (ok, _) in checked if ok]
    assert [c["pub"] for c in passed] == [w.rev.identity.pub]
    assert dict((c["pub"], m) for c, (_, m) in checked)[w.rev2.identity.pub] == ["roles.review 0/1"]
    # 2. open the event with the pre-checked reviewer, without posting a notice
    o = await open_event(w, reviewer=passed[0], post=False)
    assert o["approved"] and o["posted"] is None and w.brokers[OPEN].notices == {}
    # 3. applicant candidates from the search peer, then direct requests
    taken = {org.identity.pub, w.rec.identity.pub, w.ceo.identity.pub}
    hits = (await ask("search_profiles", q="신입 온보딩 프로그램 운영", labels=[SDS], exclude=sorted(taken), k=2))["hits"]
    chosen = [h["url"] for h in hits]
    assert set(chosen) <= {p.config.url for p in w.applicants} and w.applicants[2].config.url not in chosen
    request = {k: v for k, v in o["notice"].items() if k != "notice_id"}
    request["request_id"] = o["event_id"]
    acks = await org.solicit(chosen, request)
    assert all(a == {"ok": True, "received": True} for a in acks.values()), acks
    for _ in range(50):
        if len(submissions(w, o["event_id"])) == 2:
            break
        await asyncio.sleep(0.02)
    subs = submissions(w, o["event_id"])
    assert len(subs) == 2 and all(v["content"].startswith("[직접 요청에 응한 기획") for v in subs.values())
    assert w.applicants[2].inbox == deque_empty() and w.outsider.inbox == deque_empty()
    # 4. review by the contracted (pre-checked) reviewer and adoption, as before
    res = await review_and_adopt(w, o, top=1)
    assert len(res["scores"]) == 2 and len(res["adopted"]) == 1
    roles = [(e["payload"]["role"], e["payload"]["contractor"]) for e in w.ledger.chain if e["type"] == "contract" and e["payload"]["event_id"] == o["event_id"]]
    assert ("review", w.rev.identity.pub) in roles and ("review", w.rev2.identity.pub) not in roles
    assert audit_chain(w.ledger.chain) == "ok"


def deque_empty():
    from collections import deque
    return deque(maxlen=200)
