"""FG-F1..F3, FG-C3, C4, FG-A3 (dev/founding/design.md 1): god's delegates on the trunk, and the trunk taking a branch
only with a delegate's founding pass for that branch's god, or with its current god's own approval."""
import os
import time

from arena.crypto import Identity
from arena.keys.lineage import commit_entry, rotate_entry
from arena.ledger.delegation import active_delegates, delegates_view
from arena.ledger.founding import make_pass, pass_body
from arena.ledger.trust import branch_parent, chain_link_payload
from arena.recorder.client import InMemoryRecorderClient
from tests.test_trust import Child, Net, net  # noqa: F401  (net is a fixture)


def delegation(net, kind, who, god=None, nonce=None):
    g = god or net.god
    p = {"god": g.pub, "delegate": who.pub, **({"scope": "found_branch"} if kind == "delegate" else {}), "group_id": "public",
         "ledger_id": net.ledger_id, "nonce": nonce or os.urandom(4).hex()}
    return net.svc.record(kind, p, {g.pub: g.sign(p)})


def a_pass(sphinx, founder, issued=None, days=30.0, nonce=None):
    t = time.time() if issued is None else issued
    body = pass_body(founder.pub, sphinx.pub, t, t + days * 86400, nonce or os.urandom(8).hex())
    return make_pass(body, sphinx.sign(body))


async def branch(settings, net, pass_doc=None, approver=None, god=None):
    """a branch genesis, then its chain_link into the trunk with the given allowance; returns (child, result)"""
    child = Child(settings, net)
    if god is not None:
        child.god = god
    parent = InMemoryRecorderClient(net.svc)
    par = branch_parent(await parent.trust(), "mem://root")
    g = {"group_id": settings.genesis_group_id, "god": child.god.pub, "broker": Identity.generate().pub, "recorder": child.rec.pub, "parent": par}
    assert (await child.svc.record("genesis", g, {child.god.pub: child.god.sign(g)}))["ok"]
    p = chain_link_payload(await parent.trust(), child.svc.ledger.chain, child.god.pub, child.rec.pub, "team", pass_doc,
                           approver.pub if approver else None)
    sigs = {child.god.pub: child.god.sign(p), child.rec.pub: child.rec.sign(p), **({approver.pub: approver.sign(p)} if approver else {})}
    return child, await net.svc.record("chain_link", p, sigs)


async def test_fgf1_f2_only_the_current_god_delegates_on_the_trunk_and_takes_it_back(net, settings):
    s1, s2, stranger = Identity.generate(), Identity.generate(), Identity.generate()
    assert (await delegation(net, "delegate", s1))["ok"] and (await delegation(net, "delegate", s2))["ok"]
    assert set(active_delegates(net.svc.ledger.chain)) == {s1.pub, s2.pub}
    assert "already delegated" in (await delegation(net, "delegate", s1))["error"]
    assert "not the current god" in (await delegation(net, "delegate", Identity.generate(), god=stranger))["error"]
    assert "not delegated" in (await delegation(net, "undelegate", stranger))["error"]
    assert (await delegation(net, "undelegate", s1))["ok"] and set(active_delegates(net.svc.ledger.chain)) == {s2.pub}
    assert (await delegation(net, "delegate", s1))["ok"]  # taken back, then given again
    assert [d["delegate"] for d in delegates_view(net.svc.ledger.chain)] == [s2.pub, s1.pub]
    assert "scope" in (await net.svc.record("delegate", *(lambda p: (p, {net.god.pub: net.god.sign(p)}))(
        {"god": net.god.pub, "delegate": stranger.pub, "scope": "rule_all", "group_id": "public", "ledger_id": net.ledger_id, "nonce": "s"})))["error"]


async def test_fgf1_delegates_live_on_the_trunk_only(net, settings):
    child = await Child(settings, net).boot()
    p = {"god": child.god.pub, "delegate": Identity.generate().pub, "scope": "found_branch", "group_id": "public",
         "ledger_id": child.ledger_id, "nonce": "b1"}
    assert "trunk only" in (await child.svc.record("delegate", p, {child.god.pub: child.god.sign(p)}))["error"]


async def test_fgf3_c3_a_branch_with_a_delegate_s_pass_for_its_god(net, settings):
    sphinx, god = Identity.generate(), Identity.generate()
    assert (await delegation(net, "delegate", sphinx))["ok"]
    p = a_pass(sphinx, god)
    child, r = await branch(settings, net, pass_doc=p, god=god)
    assert r["ok"], r
    view = net.svc.verify(r["hash"])
    assert view["founding"] == {k: p["body"][k] for k in ("sphinx", "issued_at", "until", "nonce")} and "approver" not in view
    _, again = await branch(settings, net, pass_doc=p, god=god)
    assert "already used" in again["error"]  # one pass, one branch


async def test_fgf3_c3_c4_what_the_trunk_refuses(net, settings):
    sphinx, god = Identity.generate(), Identity.generate()
    assert (await delegation(net, "delegate", sphinx))["ok"]
    cases = {
        "exactly one of": dict(),                                                         # neither
        "exactly one of ": dict(pass_doc=a_pass(sphinx, god), approver=net.god),          # both
        "approver is not": dict(approver=Identity.generate()),                            # not the current god
        "not signed by a key god delegated": dict(pass_doc=a_pass(Identity.generate(), god)),
        "another founder": dict(pass_doc=a_pass(sphinx, Identity.generate())),           # handed on
        "not valid now": dict(pass_doc=a_pass(sphinx, god, issued=time.time() - 40 * 86400)),
    }
    for why, kw in cases.items():
        _, r = await branch(settings, net, god=god, **kw)
        assert not r["ok"] and why.strip() in r["error"], (why, r)
    bad = a_pass(sphinx, god)
    bad["sig"] = Identity.generate().sign(bad["body"])
    _, r = await branch(settings, net, pass_doc=bad, god=god)
    assert "signature does not verify" in r["error"]
    assert (await delegation(net, "undelegate", sphinx))["ok"]
    _, r = await branch(settings, net, pass_doc=a_pass(sphinx, god), god=god)
    assert "not signed by a key god delegated" in r["error"]  # taken back: its new passes no longer count
    _, r = await branch(settings, net, approver=net.god, god=god)
    assert r["ok"]  # the current god's own approval (FG-C4)


async def test_fga3_a_delegate_keeps_its_standing_through_its_key_line(net, settings):
    sphinx, nxt, after = Identity.generate(), Identity.generate(), Identity.generate()
    assert (await delegation(net, "delegate", sphinx))["ok"]
    p, sigs = commit_entry(sphinx, nxt, "public", net.ledger_id)
    assert (await net.svc.record("key_commit", p, sigs))["ok"]
    p, sigs = rotate_entry(sphinx.pub, nxt, after, "public", net.ledger_id)
    assert (await net.svc.record("peer_rotate", p, sigs))["ok"]
    assert delegates_view(net.svc.ledger.chain)[0]["current"] == nxt.pub
    god1, god2 = Identity.generate(), Identity.generate()
    _, r = await branch(settings, net, pass_doc=a_pass(nxt, god1), god=god1)
    assert r["ok"], r  # the new key of the delegated line
    _, r = await branch(settings, net, pass_doc=a_pass(sphinx, god2), god=god2)
    assert "rotated away" in r["error"]  # the old key (say, stolen) signs nothing that counts


async def test_fgf1_the_recorder_lists_its_delegates(net, settings):
    s1 = Identity.generate()
    assert (await delegation(net, "delegate", s1))["ok"]
    d = await InMemoryRecorderClient(net.svc).delegates()
    assert d["ok"] and [(x["delegate"], x["scope"], x["current"]) for x in d["delegates"]] == [(s1.pub, "found_branch", s1.pub)]
    child = await Child(settings, net).boot()
    assert (await InMemoryRecorderClient(child.svc).delegates())["delegates"] == []
