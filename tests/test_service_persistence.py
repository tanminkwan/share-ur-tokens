"""P5-C21: the broker and the recorder keep their state across restarts."""
import time

from arena.broker.neighbors import Caller, NoNeighbors
from arena.broker.service import BrokerService
from arena.broker.store import FileBrokerStore
from arena.crypto import Identity
from arena.ledger import JsonlStore
from arena.recorder.service import RecorderService
from arena.search import BM25Searcher
from tests.test_broker_service import ad, notice, profile


def broker(settings, path, owner=None):
    return BrokerService(settings, Identity.generate(), BM25Searcher(), NoNeighbors(), name="b", neighbors=[], owner_pub=owner,
                         group_id="g-closed" if owner else None, store=FileBrokerStore(str(path)))


async def test_p5c21_broker_profiles_notices_versions_and_grants_survive(tmp_path, settings):
    path = tmp_path / "broker-state.json"
    b = broker(settings, path)
    me, issuer = Identity.generate(), Identity.generate()
    await b.advertise(ad(me, profile("http://me", "인프라 담당", now=time.time())))
    n = dict(notice(issuer, "n1", now=time.time()), group_id="public", ver=1)
    await b.post_notice(n, issuer.sign(n))
    n2 = dict(n, ver=2, text="수정")
    await b.post_notice(n2, issuer.sign(n2))
    t_mid = time.time()
    again = broker(settings, path)  # the process restarted
    assert [p["pub"] for p in await again.list_profiles(Caller.anonymous(), local=True)] == [me.pub]
    vis = await again.visible_notices(me.pub)
    assert vis[0]["ver"] == 2 and vis[0]["text"] == "수정"
    assert (await again.changed_notices(me.pub, since=0))["notices"][0]["updated_at"] <= t_mid
    old = dict(n, ver=1, text="옛것")
    assert (await again.post_notice(old, issuer.sign(old)))["error"] == "older or same version"  # versions remembered
    await again.close_notice("n1", issuer.sign({"close": "n1"}))
    third = broker(settings, path)
    assert await third.visible_notices(me.pub) == [] and (await third.changed_notices(me.pub, since=0))["notices"][0]["closed"] is True
    # closed group grants
    owner, member = Identity.generate(), Identity.generate()
    cpath = tmp_path / "closed.json"
    d = broker(settings, cpath, owner=owner.pub)
    g = {"pub": member.pub, "until": time.time() + 3600}
    assert (await d.grant(g, owner.sign(g)))["ok"]
    assert broker(settings, cpath, owner=owner.pub).is_member(member.pub)


async def test_p5c21_recorder_access_log_survives(tmp_path, settings):
    import dataclasses
    s = dataclasses.replace(settings, recorder_access_log_file=str(tmp_path / "access.jsonl"))
    reader, stranger, rec = Identity.generate(), Identity.generate(), Identity.generate()
    svc = RecorderService.build(s, rec, JsonlStore(str(tmp_path / "ledger.jsonl")), readers=[reader.pub], access_log_path=s.recorder_access_log_file)
    svc.read_chain(stranger.pub)
    svc.read_chain(reader.pub)
    again = RecorderService.build(s, rec, JsonlStore(str(tmp_path / "ledger.jsonl")), readers=[reader.pub], access_log_path=s.recorder_access_log_file)
    log = again.read_access_log(reader.pub)["log"]
    assert [(x["reader"], x["granted"]) for x in log][:2] == [(stranger.pub, False), (reader.pub, True)]
