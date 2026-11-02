"""P5-B1 ~ B3: tamper checklist and unauthorized-read checklist in one place."""
import copy
import time

import httpx
import pytest

from arena.crypto import Identity, canon, h
from arena.ledger import BODY, MemoryStore, audit_chain
from arena.peer.receipts import Receipts
from arena.recorder.api import build_recorder_app
from arena.recorder.service import RecorderService
from arena.signing import sign_request
from tests.test_ledger import Cast


@pytest.fixture
async def built(settings):
    cast, reader = Cast(), Identity.generate()
    svc = RecorderService.build(settings, Identity.generate(), MemoryStore(), readers=[reader.pub])
    receipts = Receipts()
    for e in (cast.event(policy={}), cast.publish(), cast.share(), cast.publish(content="B"), cast.share(content="B", nonce="n2")):
        r = await svc.record(*e)
        assert receipts.keep(r, e[0], e[1], expected_recorder=svc.identity.pub)
    return svc, cast, reader, receipts


def rehash(e):
    e["hash"] = h(canon({k: e[k] for k in BODY}))


# ---------------- P5-B1: audit catches every edit of history ----------------
@pytest.mark.parametrize("attack,expected", [
    ("payload", "TAMPERED at seq 2 (hash chain)"),
    ("payload+rehash", "TAMPERED at seq 2 (signature)"),  # even if the recorder rehashes and re-seals, participant signatures hold
    ("signature", "TAMPERED at seq 2 (signature)"),
    ("seal", "TAMPERED at seq 2 (recorder seal)"),
    ("insert", "TAMPERED at seq 2 (hash chain)"),
    ("reorder", "TAMPERED at seq 1 (hash chain)"),
    ("delete-middle", "TAMPERED at seq 2 (hash chain)"),
])
def test_p5b1_tamper_checklist(built, attack, expected):
    svc, cast, _, _ = built
    c = copy.deepcopy(svc.ledger.chain)
    if attack == "payload":
        c[2]["payload"]["terms"] = "changed"
    elif attack == "payload+rehash":
        c[2]["payload"]["terms"] = "changed"
        rehash(c[2])
        c[2]["seal"]["sig"] = svc.identity.sign(c[2]["hash"])  # even the recorder re-seals it
    elif attack == "signature":
        c[2]["sigs"][cast.author.pub] = cast.other.sign(c[2]["payload"])
        rehash(c[2])
        c[2]["seal"]["sig"] = svc.identity.sign(c[2]["hash"])
        for i in range(3, len(c)):
            c[i]["prev"] = c[i - 1]["hash"]
            rehash(c[i])
            c[i]["seal"]["sig"] = svc.identity.sign(c[i]["hash"])
    elif attack == "seal":
        c[2]["seal"]["sig"] = Identity.generate().sign(c[2]["hash"])
    elif attack == "insert":
        c.insert(2, copy.deepcopy(c[1]))
    elif attack == "reorder":
        c[1], c[2] = c[2], c[1]
    elif attack == "delete-middle":
        del c[2]
    assert audit_chain(c) == expected


# ---------------- P5-B2: truncating the end only shows against receipts ----------------
def test_p5b2_truncation_needs_receipts(built):
    svc, cast, _, receipts = built
    cut = copy.deepcopy(svc.ledger.chain[:3])
    assert audit_chain(cut) == "ok"  # the shorter chain is still a valid chain
    missing = receipts.missing_from(cut)
    assert [m["seq"] for m in missing] == [3, 4] and all(m["kind"] in ("publish", "share") for m in missing)
    assert receipts.missing_from(svc.ledger.chain) == []
    swapped = copy.deepcopy(svc.ledger.chain)
    swapped[4]["payload"]["terms"] = "x"
    rehash(swapped[4])
    assert [m["seq"] for m in receipts.missing_from(swapped)] == [4]  # a rewritten entry no longer matches the receipt


# ---------------- P5-B3: unauthorized reads ----------------
async def test_p5b3_unauthorized_read_checklist(built, settings):
    svc, cast, reader, _ = built
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(svc)), base_url="http://r")
    stranger = Identity.generate()
    assert (await http.get("/chain")).status_code == 401  # no signature
    assert (await http.get("/chain", headers=sign_request(stranger, "GET", "/chain"))).status_code == 403  # not allow-listed
    assert (await http.get("/chain", headers=sign_request(reader, "GET", "/access-log"))).status_code == 401  # signed for another path
    old = sign_request(reader, "GET", "/chain", now=time.time() - settings.sig_window_sec - 5)
    assert (await http.get("/chain", headers=old)).status_code == 401  # replay outside the window
    assert (await http.get("/access-log", headers=sign_request(stranger, "GET", "/access-log"))).status_code == 403
    assert (await http.get("/chain", headers=sign_request(reader, "GET", "/chain"))).status_code == 200
    log = (await http.get("/access-log", headers=sign_request(reader, "GET", "/access-log"))).json()["log"]
    assert [x["granted"] for x in log] == [False, True] and log[0]["reader"] == stranger.pub  # refusals are on record


async def test_p5b3_closed_group_and_spectator_refusals(settings):
    from arena.broker.neighbors import Caller, NoNeighbors
    from arena.broker.service import BrokerService
    from arena.search import BM25Searcher
    owner, outsider = Identity.generate(), Identity.generate()
    b = BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="D", neighbors=[], owner_pub=owner.pub, group_id="g-closed")
    assert await b.find(Caller(outsider.pub), "x") is None and await b.list_profiles(Caller.anonymous()) is None
    from arena.peer.god_role import GodRole
    from arena.signing import sign_message

    class P:
        clock, settings_ = time.time, settings
    role = GodRole(settings, viewers=[owner.pub])
    peer = P()
    peer.settings = settings
    from arena.peer.plugin import MessageHead
    r = await role._op_snapshot(peer, dict({"op": "god_snapshot"}, **sign_message(outsider, "god_snapshot")), MessageHead())
    assert r == {"ok": False, "error": "not a viewer"}
