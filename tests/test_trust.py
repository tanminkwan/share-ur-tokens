"""P5-G1 ~ G7: telling the real ledger from a whole fake one. A forger can make fresh god and recorder keys and build a
chain that agrees with itself, and can copy real signed payloads into it. The root of trust (genesis hash and god's first
key, published outside the ledger), key succession (key_rotate signed by the old key, and by god for the recorder) and the
ledger id inside every signed payload make the real chain provable from its first key."""
import dataclasses

import pytest

from arena.crypto import Identity
from arena.genesis import record_genesis
from arena.ledger import MemoryStore, audit_chain
from arena.ledger.trust import anchor_block, current_keys, verify_trust
from arena.recorder.client import InMemoryRecorderClient
from arena.recorder.service import RecorderService


class Net:
    """one community's ledger: god, a recorder and its genesis"""

    def __init__(self, settings):
        self.s = dataclasses.replace(settings, recorder_require_group=True)
        self.god, self.rec = Identity.generate(), Identity.generate()
        self.svc = RecorderService.build(self.s, self.rec, MemoryStore(), readers=[])

    async def boot(self):
        assert (await record_genesis(self.svc, self.god, self.s, Identity.generate().pub, self.rec.pub))["ok"]
        return self

    @property
    def ledger_id(self):
        return self.svc.ledger.chain[0]["hash"]

    @property
    def anchor(self):
        return {"genesis_hash": self.ledger_id, "god_pub": self.god.pub}

    async def publish(self, who, text, ledger_id=None):
        p = {"author": who.pub, "content_hash": text * 8, "group_id": "public", "ledger_id": ledger_id or self.ledger_id}
        return await self.svc.record("publish", p, {who.pub: who.sign(p)})

    async def rotate_recorder(self, god=None):
        new = Identity.generate()
        p = self.svc.rotation_request("recorder", new.pub)
        r = await self.svc.rotate_key(new, p, (god or self.god).sign(p))
        return new, r


@pytest.fixture
async def net(settings):
    return await Net(settings).boot()


async def test_p5g1_a_whole_fake_chain_passes_its_own_audit_but_not_the_root_of_trust(net, settings):
    alice = Identity.generate()
    assert (await net.publish(alice, "a"))["ok"]
    assert audit_chain(net.svc.ledger.chain, anchor=net.anchor) == "ok"
    fake = await Net(settings).boot()  # fresh god and recorder keys: a self-consistent fake
    assert (await fake.publish(alice, "a"))["ok"]
    assert audit_chain(fake.svc.ledger.chain) == "ok"  # without the root of trust nothing tells them apart
    assert "root" in audit_chain(fake.svc.ledger.chain, anchor=net.anchor)
    assert "root" in audit_chain(net.svc.ledger.chain, anchor={"genesis_hash": net.ledger_id, "god_pub": Identity.generate().pub})


async def test_p5g4_a_real_signed_payload_cannot_be_moved_into_another_ledger(net, settings):
    alice = Identity.generate()
    real = await net.publish(alice, "b")
    entry = net.svc.ledger.find(real["hash"])
    other = await Net(settings).boot()
    moved = await other.svc.record("publish", entry["payload"], entry["sigs"])  # alice's real signature, wrong ledger
    assert not moved["ok"] and "ledger_id" in moved["error"]
    p = {"author": alice.pub, "content_hash": "c" * 64, "group_id": "public"}
    assert "ledger_id" in (await net.svc.record("publish", p, {alice.pub: alice.sign(p)}))["error"]  # missing
    # a forged copy that slips an entry of another ledger in is caught by the audit
    chain = [dict(e) for e in other.svc.ledger.chain]
    assert audit_chain(chain) == "ok"
    from arena.crypto import canon, h
    body = {"type": "publish", "payload": entry["payload"], "sigs": entry["sigs"], "prev": chain[-1]["hash"], "ts": chain[-1]["ts"] + 1}
    forged = dict(body, seq=len(chain), hash=h(canon(body)))
    forged["seal"] = {"pub": other.rec.pub, "sig": other.rec.sign(forged["hash"])}
    assert "ledger" in audit_chain(chain + [forged])


async def test_p5g2_g3_recorder_key_succession_with_gods_approval(net):
    alice = Identity.generate()
    new, r = await net.rotate_recorder()
    assert r["ok"] and net.svc.identity.pub == new.pub
    assert (await net.publish(alice, "d"))["ok"]
    chain = net.svc.ledger.chain
    assert chain[-1]["seal"]["pub"] == new.pub and chain[-2]["seal"]["pub"] == net.rec.pub  # the rotation itself: old key
    assert audit_chain(chain, anchor=net.anchor) == "ok"
    assert current_keys(chain) == {"recorder": new.pub, "god": net.god.pub}
    # a later entry sealed with the old key is caught, though the seal itself is a valid signature
    bad = [dict(e) for e in chain]
    bad[-1] = dict(bad[-1], seal={"pub": net.rec.pub, "sig": net.rec.sign(bad[-1]["hash"])})
    assert "seal" in audit_chain(bad)
    # without god's signature, or by someone else's god key, no rotation
    other = Identity.generate()
    p = net.svc.rotation_request("recorder", other.pub)
    assert not (await net.svc.rotate_key(other, p, Identity.generate().sign(p)))["ok"]
    assert net.svc.identity.pub == new.pub


async def test_p5g2_god_key_succession_then_the_new_god_approves(net):
    new_god = Identity.generate()
    p = net.svc.rotation_request("god", new_god.pub)
    assert (await net.svc.record("key_rotate", p, {net.god.pub: net.god.sign(p), new_god.pub: new_god.sign(p)}))["ok"]
    assert current_keys(net.svc.ledger.chain)["god"] == new_god.pub
    _, refused = await net.rotate_recorder(god=net.god)  # the old god no longer approves
    assert not refused["ok"]
    _, ok = await net.rotate_recorder(god=new_god)
    assert ok["ok"] and audit_chain(net.svc.ledger.chain, anchor=net.anchor) == "ok"  # the first god key still anchors it


async def test_p5g5_the_trust_document_proves_the_current_recorder_key(net, settings):
    c = InMemoryRecorderClient(net.svc)
    doc = await c.trust()
    ok, why, keys = verify_trust(doc, **net.anchor)
    assert ok and keys == {"recorder": net.rec.pub, "god": net.god.pub} and doc["ledger_id"] == net.ledger_id
    new, _ = await net.rotate_recorder()
    ok, why, keys = verify_trust(await c.trust(), **net.anchor)
    assert ok and keys["recorder"] == new.pub
    fake = await Net(settings).boot()
    ok, why, _ = verify_trust(await InMemoryRecorderClient(fake.svc).trust(), **net.anchor)
    assert not ok and "root" in why
    tampered = await c.trust()
    tampered["rotations"][0]["payload"] = dict(tampered["rotations"][0]["payload"], new=Identity.generate().pub)
    assert not verify_trust(tampered, **net.anchor)[0]


async def test_p5g7_the_genesis_prints_the_root_values_to_publish(net):
    text = anchor_block(net.svc.ledger.chain)
    assert f"ARENA_TRUST_GENESIS_HASH={net.ledger_id}" in text and f"ARENA_TRUST_GOD_PUB={net.god.pub}" in text and net.rec.pub in text


async def test_p5g6_peers_put_the_ledger_id_in_everything_they_record(tmp_path, settings):
    from tests.test_assistant import Eco, asst, ctx, joined, settle
    from tests.test_reveal_carry import _commit
    eco = Eco(tmp_path, settings)
    eco.host, eco.a, eco.b = eco.peer("host"), eco.peer("a"), eco.peer("b")
    await eco.boot()
    ev = await joined(eco)
    await _commit(eco.a, ev, "x-1", "v")
    chain = eco.svc.ledger.chain
    assert len(chain) > 3 and all(e["payload"].get("ledger_id") == chain[0]["hash"] for e in chain[1:])
    assert audit_chain(chain, anchor={"genesis_hash": chain[0]["hash"], "god_pub": eco.god.pub}) == "ok"


async def test_p5g6_a_peer_with_a_root_of_trust_ignores_events_of_an_unproven_recorder(tmp_path, settings):
    from tests.test_event_apps import RULES, Runner, World, announce, route
    w = World(tmp_path, settings)
    host, player = w.peer("host", []), w.peer("player", [Runner()])
    await w.boot(host, player)
    real_anchor = {"trust_genesis_hash": w.svc.ledger.chain[0]["hash"], "trust_god_pub": w.god.pub}
    player.settings = dataclasses.replace(player.settings, trust_genesis_hash=Identity.generate().pub, trust_god_pub=w.god.pub)
    out = await announce(host, "app", [{"id": Runner.app_id, "name": "runner", "version": "1.0"}])
    await route(player)
    assert player.app(Runner).got == []  # the recorder is not the one this peer's root of trust names
    player.settings = dataclasses.replace(player.settings, **real_anchor)
    player.events.seen.discard(out["event_id"])
    player.events.since.clear()  # read the board again from the start
    player._trust.clear()
    await route(player)
    assert player.app(Runner).got == [(out["event_id"], "new")]


# ---------------- P5-G9: every community chain links its start into the original chain ----------------
class Child(Net):
    """a community that starts its own ledger, linked into the original (parent) ledger"""

    def __init__(self, settings, parent: Net, parent_url="mem://root"):
        super().__init__(settings)
        self.parent, self.parent_url = parent, parent_url

    async def boot(self, finish=True):
        """the genesis program's steps: genesis naming the parent (ledger, recorder key, branch point), chain_link in the
        parent, then entry 1 parent_link holding that sealed chain_link (CP-1, CP-2)"""
        from arena.ledger.trust import branch_parent, link_to_parent, record_parent_link
        parent = InMemoryRecorderClient(self.parent.svc)
        ptrust = await parent.trust()
        par = branch_parent(ptrust, self.parent_url) if "parent" not in ptrust["genesis"]["payload"] else \
            {"ledger_id": ptrust["ledger_id"], "recorder_url": self.parent_url, "recorder": ptrust["recorder"], "branch_point": ptrust["head"]}
        p = {"group_id": self.s.genesis_group_id, "god": self.god.pub, "broker": Identity.generate().pub, "recorder": self.rec.pub,
             "parent": par}
        assert (await self.svc.record("genesis", p, {self.god.pub: self.god.sign(p)}))["ok"]
        self.link = await link_to_parent(parent, self.god, self.rec, self.svc.ledger.chain, "child community")
        if finish and self.link.get("ok"):
            entry = (await parent.link(self.ledger_id))["link"]
            assert (await record_parent_link(self.svc, self.god, self.svc.ledger.chain, entry))["ok"]
        return self


async def test_p5g9_a_community_chain_is_proven_through_its_link_in_the_original_chain(net, settings):
    from arena.ledger.trust import verify_linked
    child = await Child(settings, net).boot()
    assert child.link["ok"]
    link = await InMemoryRecorderClient(net.svc).link(child.ledger_id)
    e = link["link"]
    assert e["type"] == "chain_link" and e["payload"]["child_ledger_id"] == child.ledger_id
    assert set(e["sigs"]) == {child.god.pub, child.rec.pub}  # signed with the new chain's private keys, not just named
    parent_doc, child_doc = await InMemoryRecorderClient(net.svc).trust(), await InMemoryRecorderClient(child.svc).trust()
    ok, why, keys = verify_linked(child_doc, parent_doc, e, **net.anchor)
    assert ok and keys == {"recorder": child.rec.pub, "god": child.god.pub}
    # a copy of the community's chain made with other keys has no link in the original chain
    fake = await Child(settings, await Net(settings).boot()).boot()  # linked into some other "original"
    ok, why, _ = verify_linked(await InMemoryRecorderClient(fake.svc).trust(), parent_doc, e, **net.anchor)
    assert not ok
    # naming the new chain's keys without their signatures is refused by the original ledger
    p = {"child_ledger_id": "0" * 64, "child_god": child.god.pub, "child_recorder": child.rec.pub, "name": "x", "group_id": "public",
         "ledger_id": net.ledger_id, "nonce": "n", "branch_point": e["payload"]["branch_point"]}
    assert "signature" in (await net.svc.record("chain_link", p, {child.god.pub: child.god.sign(p)}))["error"]
    # one link per community chain
    again = dict(e["payload"], nonce="other")
    assert "already" in (await net.svc.record("chain_link", again, {child.god.pub: child.god.sign(again), child.rec.pub: child.rec.sign(again)}))["error"]


async def test_p5g9_a_peer_anchored_at_the_original_trusts_a_linked_community_recorder(tmp_path, settings, net):
    from tests.test_event_apps import World
    child = await Child(settings, net).boot()
    stranger = await Child(settings, await Net(settings).boot(), parent_url="mem://elsewhere").boot()
    w = World(tmp_path, settings)
    peer = w.peer("p", [])
    clients = {"mem://root": InMemoryRecorderClient(net.svc), "mem://child": InMemoryRecorderClient(child.svc),
               "mem://stranger": InMemoryRecorderClient(stranger.svc)}
    peer.recorder_factory = lambda url: clients[url]
    peer.settings = dataclasses.replace(peer.settings, trust_genesis_hash=net.ledger_id, trust_god_pub=net.god.pub)
    t = await peer.recorder_trust("mem://child")
    assert t["ok"] and t["recorder"] == child.rec.pub and t["ledger_id"] == child.ledger_id
    assert not (await peer.recorder_trust("mem://stranger"))["ok"]  # linked, but not into this peer's original chain
    root = await peer.recorder_trust("mem://root")
    assert root["ok"] and root["ledger_id"] == net.ledger_id


async def test_p5g10_only_the_trunk_takes_branch_links(net, settings):
    """user 2026-11-02: branches grow only from the trunk (the root chain). A community chain cannot start a branch of its
    own: its ledger refuses chain_link, and a peer anchored at the trunk does not follow a branch of a branch. A community
    divides itself with broker groups inside its chain instead."""
    child = await Child(settings, net).boot()
    grandchild = await Child(settings, child, parent_url="mem://child").boot()
    assert not grandchild.link["ok"] and "trunk" in grandchild.link["error"]
    # even a link entry written by hand into a branch chain is refused by its ledger
    g = Identity.generate()
    p = {"child_ledger_id": "1" * 64, "child_god": g.pub, "child_recorder": g.pub, "name": "x", "group_id": "public",
         "ledger_id": child.ledger_id, "nonce": "n", "branch_point": {"seq": 0, "hash": child.ledger_id}}
    assert "trunk" in (await child.svc.record("chain_link", p, {g.pub: g.sign(p)}))["error"]


async def test_p5g11_every_entry_carries_the_recorder_time_and_the_audit_checks_its_order(net):
    """user 2026-11-02: the ledger always stamps the time. The recorder sets ts on every entry, inside the hash and the
    seal; the ledger refuses a time earlier than the last entry, and the audit of any copy now checks the order too."""
    import copy
    from arena.crypto import canon, h
    from arena.ledger import BODY
    who = Identity.generate()
    assert (await net.publish(who, "a"))["ok"] and (await net.publish(who, "b"))["ok"]
    chain = net.svc.ledger.chain
    assert all(isinstance(e["ts"], float) for e in chain) and audit_chain(chain) == "ok"
    forged = copy.deepcopy(chain)  # a recorder that put a later entry before an earlier one in time, sealing it again
    forged[-1]["ts"] = forged[-2]["ts"] - 60
    forged[-1]["hash"] = h(canon({k: forged[-1][k] for k in BODY}))
    forged[-1]["seal"] = {"pub": net.rec.pub, "sig": net.rec.sign(forged[-1]["hash"])}
    assert "time" in audit_chain(forged)


async def test_codebook_a_branch_chain_may_add_its_own_purpose_codes(net, settings):
    """user 2026-11-02: "가지 체인 자체 코드는 허용하자". A branch community declares x-<community>.<code> purposes in an
    edition on its own chain; the trunk's codes come only with the platform's table, and meanings never change."""
    from arena.codebook import builtin_document, document_hash
    child = await Child(settings, net).boot()
    pub = Identity.generate()

    async def edition(svc, ledger_id, version, local):
        d = builtin_document(name="acme", version=version)
        p = {"publisher": pub.pub, "name": "acme", "version": version, "content_hash": document_hash(d), "codes": d["codes"],
             "local": local, "group_id": "public", "ledger_id": ledger_id}
        return await svc.record("codebook", p, {pub.pub: pub.sign(p)})
    minutes = {"purposes": {"x-acme.minutes": {"types": ["publish"], "description": "회의록 원문의 시점 증명"}}}
    assert "branch chain" in (await edition(net.svc, net.ledger_id, "1.0", minutes))["error"]  # not on the trunk
    assert "x-<community>" in (await edition(child.svc, child.ledger_id, "1.0", {"purposes": {"minutes": minutes["purposes"]["x-acme.minutes"]}}))["error"]
    assert (await edition(child.svc, child.ledger_id, "1.0", minutes))["ok"]
    assert "already defined" in (await edition(child.svc, child.ledger_id, "1.1", minutes))["error"]  # meanings never change
    who = Identity.generate()

    async def publish(svc, ledger_id, text, purpose):
        p = {"author": who.pub, "content_hash": text * 8, "group_id": "public", "ledger_id": ledger_id, "purpose": purpose}
        return await svc.record("publish", p, {who.pub: who.sign(p)})
    assert (await publish(child.svc, child.ledger_id, "a", "x-acme.minutes"))["ok"]
    assert "not declared" in (await publish(child.svc, child.ledger_id, "b", "x-acme.poems"))["error"]
    assert "not declared" in (await publish(net.svc, net.ledger_id, "c", "x-acme.minutes"))["error"]  # local to its chain


async def test_codebook_a_branch_follows_a_trunk_edition_by_copying_it(net, settings):
    """user 2026-11-02: "뿌리 체인의 판도 따를 수 있게 하자". A branch copies the trunk's edition entry as it is; its ledger
    checks the copy (hash, publisher's signature, seal, the trunk named in its genesis) without the network, and an event
    on the branch names the trunk edition the same way as on the trunk."""
    import copy
    from arena.codebook import builtin_document, document_hash
    from arena.ledger.codebook import check_event_codebook
    child = await Child(settings, net).boot()
    pub = Identity.generate()
    d = builtin_document()
    p = {"publisher": pub.pub, "name": d["name"], "version": "1.0", "content_hash": document_hash(d), "codes": d["codes"],
         "group_id": "public", "ledger_id": net.ledger_id}
    trunk_ed = await net.svc.record("codebook", p, {pub.pub: pub.sign(p)})
    whole = next(e for e in net.svc.codebooks()["codebooks"] if e["hash"] == trunk_ed["hash"])
    copier = Identity.generate()

    async def copy_into(svc, ledger_id, entry):
        q = {"copier": copier.pub, "copied": {k: entry[k] for k in ("type", "payload", "sigs", "prev", "ts", "hash", "seal")},
             "group_id": "public", "ledger_id": ledger_id}
        return await svc.record("codebook", q, {copier.pub: copier.sign(q)})
    forged = copy.deepcopy(whole)
    forged["payload"]["version"] = "9.9"
    assert "hash" in (await copy_into(child.svc, child.ledger_id, forged))["error"]
    assert "branch chain" in (await copy_into(net.svc, net.ledger_id, whole))["error"]  # the trunk copies nothing
    got = await copy_into(child.svc, child.ledger_id, whole)
    assert got["ok"] and child.svc.verify(got["hash"])["copied_from"] == {"ledger_id": net.ledger_id, "entry": whole["hash"]}
    assert "already copied" in (await copy_into(child.svc, child.ledger_id, whole))["error"]
    ref = {"entry": whole["hash"], "publisher": pub.pub, "version": "1.0"}
    assert check_event_codebook(child.svc.ledger.chain, {"codebook": ref}) is None  # the branch follows the trunk edition
    stranger = await Child(settings, await Net(settings).boot()).boot()  # a branch of another trunk
    assert "not of the trunk" in (await copy_into(stranger.svc, stranger.ledger_id, whole))["error"]


async def test_codebook_any_branch_peer_copies_a_trunk_edition_with_the_helper(tmp_path, settings, net):
    from arena.codebook import builtin_document, document_hash
    from arena.peer.foundation_role import FoundationRole
    from tests.test_event_apps import World
    child = await Child(settings, net).boot()
    pub = Identity.generate()
    d = builtin_document()
    p = {"publisher": pub.pub, "name": d["name"], "version": "1.0", "content_hash": document_hash(d), "codes": d["codes"],
         "group_id": "public", "ledger_id": net.ledger_id}
    ed = await net.svc.record("codebook", p, {pub.pub: pub.sign(p)})
    from arena.ledger.codebook import editions
    w = World(tmp_path, settings)
    role = FoundationRole(settings, documents=[])
    peer = w.peer("p", [role])
    clients = {"mem://root": InMemoryRecorderClient(net.svc), "mem://child": InMemoryRecorderClient(child.svc)}
    peer.recorder_factory = lambda url: clients[url]
    r = await FoundationRole.copy_edition(peer.ctx(role), "mem://root", ed["hash"], "mem://child")
    assert r["ok"] and ed["hash"] in editions(child.svc.ledger.chain)
