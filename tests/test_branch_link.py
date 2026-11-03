"""CP-1, CP-2 (dev/chain-policy.md 4~5절): a branch and the trunk recognise each other at one point.

CP-1: the branch's first entry names the trunk's recorder key then and the branch point (the trunk's last entry when it
branched); the chain_link in the trunk repeats the same point, and the trunk checks the point is one of its entries.
CP-2: the branch's entry 1 is its parent_link, holding the chain_link the trunk sealed, so whoever has only the branch
knows which trunk entry to look up; before it the branch takes nothing else."""
import copy

from arena.crypto import Identity
from arena.ledger.trust import anchor_block, branch_parent, link_to_parent, record_parent_link, verify_link_entry, verify_linked, verify_parent_link
from arena.recorder.client import InMemoryRecorderClient
from tests.test_trust import Child, Net, net  # noqa: F401  (net is a fixture)


async def test_cp1_the_branch_genesis_names_the_trunk_recorder_key_and_the_branch_point(net, settings):
    head = net.svc.trust()["head"]
    child = await Child(settings, net).boot()
    par = child.svc.ledger.chain[0]["payload"]["parent"]
    assert par["recorder"] == net.rec.pub and par["branch_point"] == head  # the trunk's last entry when it branched
    link = (await InMemoryRecorderClient(net.svc).link(child.ledger_id))["link"]
    assert link["payload"]["branch_point"] == head and head["seq"] < link["seq"]
    assert "갈라진 지점: " in anchor_block(child.svc.ledger.chain)


async def test_cp1_the_ledgers_refuse_a_branch_start_without_its_point(net, settings):
    c = Net(settings)
    base = {"group_id": settings.genesis_group_id, "god": c.god.pub, "broker": Identity.generate().pub, "recorder": c.rec.pub}

    async def genesis(parent):
        p = dict(base, parent=parent)
        return await c.svc.record("genesis", p, {c.god.pub: c.god.sign(p)})
    good = branch_parent(net.svc.trust(), "mem://root")
    assert "recorder key then" in (await genesis({k: v for k, v in good.items() if k != "recorder"}))["error"]
    assert "branch_point" in (await genesis(dict(good, branch_point={"seq": -1, "hash": net.ledger_id})))["error"]
    assert "branch_point" in (await genesis(dict(good, branch_point={"seq": True, "hash": net.ledger_id})))["error"]
    assert "branch_point" in (await genesis(dict(good, branch_point="0")))["error"]
    # the trunk takes a chain_link only at a point that is one of its entries
    child = await Child(settings, net).boot(finish=False)
    g = child.svc.ledger.chain[0]
    p = {"child_ledger_id": "2" * 64, "child_god": child.god.pub, "child_recorder": child.rec.pub, "name": "x", "group_id": "public",
         "ledger_id": net.ledger_id, "nonce": "other", "branch_point": {"seq": 99, "hash": g["hash"]}}
    sigs = {child.god.pub: child.god.sign(p), child.rec.pub: child.rec.sign(p)}
    assert "not an entry of this chain" in (await net.svc.record("chain_link", p, sigs))["error"]
    p = dict(p, branch_point={"seq": 0, "hash": "3" * 64})
    assert "not an entry of this chain" in (await net.svc.record("chain_link", p, {child.god.pub: child.god.sign(p),
                                                                                    child.rec.pub: child.rec.sign(p)}))["error"]


async def test_cp2_a_branch_takes_nothing_before_its_parent_link(net, settings):
    child = await Child(settings, net).boot(finish=False)
    assert child.link["ok"]
    who = Identity.generate()
    assert "not linked yet" in (await child.publish(who, "a"))["error"]
    link = (await InMemoryRecorderClient(net.svc).link(child.ledger_id))["link"]
    assert (await record_parent_link(child.svc, child.god, child.svc.ledger.chain, link))["ok"]
    assert (await child.publish(who, "a"))["ok"]  # linked: the branch now takes entries
    assert "once" in (await record_parent_link(child.svc, child.god, child.svc.ledger.chain, link))["error"]
    assert "belongs to a branch" in (await record_parent_link(net.svc, net.god, net.svc.ledger.chain, link))["error"]


async def test_cp2_the_branch_ledger_checks_the_chain_link_it_holds(net, settings):
    child = await Child(settings, net).boot(finish=False)
    other = await Child(settings, net).boot()
    link = (await InMemoryRecorderClient(net.svc).link(child.ledger_id))["link"]
    chain = child.svc.ledger.chain

    async def holding(lk, god=None):
        return (await record_parent_link(child.svc, god or child.god, chain, lk))["error"]
    assert "signed by this chain's god" in await holding(link, god=Identity.generate())
    bent = copy.deepcopy(link)
    bent["payload"]["name"] = "changed"
    assert "hash does not match" in await holding(bent)
    forged = dict(link, seal={"pub": link["seal"]["pub"], "sig": "00" * 64})
    assert "seal does not verify" in await holding(forged)
    assert "another chain" in await holding((await InMemoryRecorderClient(net.svc).link(other.ledger_id))["link"])
    assert "needs god and link" in await holding({"type": "share"})
    assert len(child.svc.ledger.chain) == 1  # every attempt refused; the right one still goes in
    assert (await record_parent_link(child.svc, child.god, chain, link))["ok"]


async def test_cp1_cp2_a_peer_proves_both_sides_name_one_point(net, settings):
    child = await Child(settings, net).boot()
    pdoc, cdoc = net.svc.trust(), child.svc.trust()
    link = (await InMemoryRecorderClient(net.svc).link(child.ledger_id))["link"]
    assert verify_linked(cdoc, pdoc, link, **net.anchor)[0]
    no_entry = {k: v for k, v in cdoc.items() if k != "parent_link"}
    assert "not its parent_link" in verify_parent_link(no_entry, link)
    assert "another chain_link" in verify_parent_link(cdoc, dict(link, hash="4" * 64))
    lied = copy.deepcopy(cdoc)
    lied["parent_link"]["payload"]["god"] = "x"
    assert "parent_link: " in verify_parent_link(lied, link)
    # a genesis that names a trunk recorder key that was not valid at its branch point
    g = copy.deepcopy(cdoc["genesis"])
    g["payload"]["parent"]["recorder"] = Identity.generate().pub
    assert "not valid at the branch point" in verify_link_entry(link, pdoc, g)
    g2 = copy.deepcopy(cdoc["genesis"])
    g2["payload"]["parent"]["branch_point"] = {"seq": 0, "hash": "5" * 64}
    assert "same branch point" in verify_link_entry(link, pdoc, g2)


async def test_cp1_the_recorder_key_that_counts_is_the_one_valid_at_the_branch_point(net, settings):
    """the trunk rotates its recorder key after the branch grew but before the link: the genesis names the key then, the
    link is sealed by the new key, and both are right"""
    child = Child(settings, net)
    parent = InMemoryRecorderClient(net.svc)
    par = branch_parent(await parent.trust(), "mem://root")
    p = {"group_id": settings.genesis_group_id, "god": child.god.pub, "broker": Identity.generate().pub, "recorder": child.rec.pub, "parent": par}
    assert (await child.svc.record("genesis", p, {child.god.pub: child.god.sign(p)}))["ok"]
    new, r = await net.rotate_recorder()
    assert r["ok"]
    assert (await link_to_parent(parent, child.god, child.rec, child.svc.ledger.chain, "late"))["ok"]
    link = (await parent.link(child.ledger_id))["link"]
    assert link["seal"]["pub"] == new.pub and par["recorder"] == net.rec.pub
    assert (await record_parent_link(child.svc, child.god, child.svc.ledger.chain, link))["ok"]
    ok, why, _ = verify_linked(child.svc.trust(), net.svc.trust(), link, **net.anchor)
    assert ok, why
