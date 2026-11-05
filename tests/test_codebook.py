"""Code table editions (user 2026-11-02). The foundation peer is an optional special-purpose peer: it publishes the
built-in code table as an edition on the ledger and hands out its document. Events and profiles may say which edition
they follow; an edition gains standing by being followed, counted from the ledger. Following is optional."""
import dataclasses

import pytest

from arena.codebook import VERSION, builtin_document, document_hash
from arena.ledger import contribution
from arena.peer.foundation_role import FoundationRole
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

REC = "mem://rec/api"


async def foundation(e, documents=None):
    s = dataclasses.replace(e.s, foundation_peer_recorder_url=REC)
    f = e.peer("foundation", apps=[FoundationRole(s, documents)])
    await f.start()
    await f.advertise()
    return f


def ref(f, version=VERSION):
    role = next(a for a in f.apps if isinstance(a, FoundationRole))
    return {"entry": role.published[version], "publisher": f.identity.pub, "version": version}


async def test_the_foundation_publishes_the_builtin_edition_and_hands_out_its_document(eco):
    f = await foundation(eco)
    r = ref(f)
    v = eco.svc.verify(r["entry"])
    assert v["type"] == "codebook" and v["publisher"] == f.identity.pub and v["version"] == VERSION
    got = await f.handle({"op": "codebook.get"})
    assert got["ok"] and got["content_hash"] == v["content_hash"] == document_hash(builtin_document())
    assert "submission" in got["document"]["codes"]["purposes"] and "a2a" in got["document"]["codes"]["connections"]
    assert "코드표 판" in (await f.advertise())["offers"]
    assert eco.svc.codes()["builtin"] == {"name": "agent-arena", "version": VERSION}


async def test_editions_are_unique_and_a_new_one_needs_a_higher_version(eco):
    f = await foundation(eco)
    role = next(a for a in f.apps if isinstance(a, FoundationRole))
    first = ref(f)["entry"]
    role.published.pop(VERSION)
    assert "already published" in (await role.publish(f.ctx(role), REC, VERSION))["error"]
    role.documents["0.9"] = dict(builtin_document(version="0.9"))
    assert "higher version" in (await role.publish(f.ctx(role), REC, "0.9", supersedes=first))["error"]
    role.documents["9.0"] = dict(builtin_document(version="9.0"))
    assert (await role.publish(f.ctx(role), REC, "9.0", supersedes=first))["ok"]


async def test_an_event_may_follow_an_edition_and_its_publisher_gains_standing(eco):
    f = await foundation(eco)
    host = eco.host
    ev = await asst(host).host_event(ctx(host), title="판을 따르는 이벤트", kind="k", rules=RULES, policy={"roles": ["member"]},
                                     instruction="기다려라", elements={"sealed": {}}, codebook=ref(f))
    await settle(host)
    decl = next(e for e in eco.svc.ledger.chain if e["type"] == "event" and e["payload"]["event_id"] == ev)
    assert decl["payload"]["codebook"] == ref(f) and eco.svc.verify(decl["hash"])["codebook"] == ref(f)
    assert contribution(eco.svc.ledger.chain)[f.identity.pub]["codebook_followers"] == 1
    # without a codebook column nothing changes (following is optional)
    await asst(host).host_event(ctx(host), title="그냥 이벤트", kind="k", rules=RULES, policy={"roles": ["member"]}, instruction="기다려라")


async def test_the_ledger_checks_the_edition_an_event_follows(eco):
    narrow = builtin_document(name="narrow")
    narrow["codes"] = dict(narrow["codes"], elements=["intake"])
    alien = builtin_document(name="alien")
    alien["codes"] = dict(alien["codes"], purposes=alien["codes"]["purposes"] + ["teleport"])
    f = await foundation(eco, [narrow])
    host = eco.host
    with pytest.raises(RuntimeError, match="not codes of that edition"):
        await asst(host).host_event(ctx(host), title="x", kind="k", rules=RULES, policy={"roles": ["member"]}, instruction="-",
                                    elements={"sealed": {}}, codebook=ref(f))
    with pytest.raises(RuntimeError, match="does not match"):
        await asst(host).host_event(ctx(host), title="y", kind="k", rules=RULES, policy={"roles": ["member"]}, instruction="-",
                                    codebook=dict(ref(f), version="9.9"))
    other = eco.peer("other-foundation", apps=[FoundationRole(dataclasses.replace(eco.s, foundation_peer_recorder_url=REC), [alien])])
    await other.start()
    with pytest.raises(RuntimeError, match="does not implement teleport"):
        await asst(host).host_event(ctx(host), title="z", kind="k", rules=RULES, policy={"roles": ["member"]}, instruction="-",
                                    codebook=ref(other))


async def test_a_profile_may_say_which_edition_it_follows(eco):
    f = await foundation(eco)
    a = eco.a
    a.config.codebook = ref(f)
    assert (await a.advertise())["codebook"] == ref(f)
    bad = dict(a.last_profile, codebook={"version": "1.0"})
    r = await eco.broker.advertise({"pub": a.identity.pub, "profile": bad, "sig": a.identity.sign(bad)})
    assert not r["ok"] and "codebook" in r["error"]
