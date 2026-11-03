"""Every refusal the ledger and its checks can give, one by one (coverage of the branches the flows rarely take).
A refusal that never runs in a test is a refusal nobody knows works."""
import copy

from arena.codebook import builtin_document, document_hash
from arena.crypto import Identity, canon, h
from arena.ledger import body_of, hash_body, private_hash, with_private
from arena.ledger.run import is_uuid, valid_app_ref, valid_run, version_ok
from arena.ledger.schedule import check_schedule
from arena.ledger.trust import verify_link_entry, verify_linked, verify_trust
from arena.recorder.client import InMemoryRecorderClient
from tests.test_trust import Child, Net, net  # noqa: F401  (net is a fixture)


def test_schedule_refusals():
    assert "non-empty" in check_schedule([], 5) and "non-empty" in check_schedule("x", 5)
    assert "items are" in check_schedule([{"at": 1, "code": "start", "x": 1}], 5)
    assert "seconds" in check_schedule([{"at": True, "code": "start"}], 5)
    assert "text" in check_schedule([{"at": 1, "code": "start", "note": 3}], 5)


def test_run_block_refusals():
    ok = {"id": "938604c1-2964-4bfc-96c4-91677f128508", "version": "1.0"}
    assert valid_run("assistant", []) and valid_run("app", [ok]) and not valid_run("app", [])
    assert not valid_run("turbo", []) and not valid_run("app", [ok, ok]) and not valid_run("app", "x")
    assert not valid_app_ref(dict(ok, extra=1)) and not valid_app_ref(dict(ok, required="yes")) and not valid_app_ref({"id": "x", "version": "1"})
    assert is_uuid(ok["id"]) and not is_uuid("nope") and version_ok("1.2", "1.1") and not version_ok("2.0", "1.0") and not version_ok("x", "1")


def test_body_of_refuses_a_body_that_does_not_commit_to_the_full_payload():
    full = {"a": 1, "secret": 2}
    body = with_private({"a": 1}, {"secret": 2})
    assert body_of(full, body) == {"secret": 2}
    assert body_of(full, dict(body, a=9)) is None                               # a public field differs
    assert body_of(full, with_private({"a": 1}, {"secret": 3})) is None         # the hash names other private fields
    assert body_of({"a": 1}, {"a": 1}) == {} and body_of({"a": 1}, with_private({"a": 1}, {"z": 1})) is None


async def test_trust_refusals(net, settings):
    doc = net.svc.trust()
    assert verify_trust(doc, net.ledger_id, net.god.pub)[0]
    assert "differs" in verify_trust(doc, "0" * 64, net.god.pub)[1]
    bent = copy.deepcopy(doc)
    bent["genesis"]["payload"]["broker"] = "x" * 64
    assert not verify_trust(bent, net.ledger_id, net.god.pub)[0]                  # the genesis entry itself was changed
    _, r = await net.rotate_recorder()
    rotated = net.svc.trust()
    broken = copy.deepcopy(rotated)
    broken["rotations"][0]["payload"]["old"] = "y" * 64
    assert "succession" in verify_trust(broken, net.ledger_id, net.god.pub)[1]
    lied = dict(rotated, recorder="z" * 64)
    assert "key succession proves" in verify_trust(lied, net.ledger_id, net.god.pub)[1]
    child = await Child(settings, net).boot()
    link = (await InMemoryRecorderClient(net.svc).link(child.ledger_id))["link"]
    cdoc = child.svc.trust()
    assert verify_link_entry(None, rotated, cdoc["genesis"]) == "no chain_link entry"
    other = copy.deepcopy(link)
    other["payload"]["child_god"] = "q" * 64
    assert "another chain" in verify_link_entry(other, net.svc.trust(), cdoc["genesis"])
    assert "parent: " in verify_linked(cdoc, net.svc.trust(), link, "0" * 64, net.god.pub)[1]
    assert "no genesis" in verify_linked({}, net.svc.trust(), link, net.ledger_id, net.god.pub)[1]


async def test_codebook_refusals(net, settings):
    pub = Identity.generate()
    d = builtin_document()

    async def edition(**over):
        p = {"publisher": pub.pub, "name": d["name"], "version": "1.0", "content_hash": document_hash(d), "codes": d["codes"],
             "group_id": "public", "ledger_id": net.ledger_id, **over}
        p = {k: v for k, v in p.items() if v is not None}
        return await net.svc.record("codebook", p, {pub.pub: pub.sign(p)})
    assert "needs publisher" in (await edition(version="v1"))["error"]
    assert "codes must map" in (await edition(codes={"weird": []}))["error"]
    assert "supersedes must name" in (await edition(supersedes="0" * 64))["error"]
    assert "only purposes" in (await edition(local={"elements": {}}))["error"]
    assert (await edition())["ok"]
    child = await Child(settings, net).boot()
    copier = Identity.generate()
    q = {"copier": copier.pub, "copied": {"type": "codebook"}, "group_id": "public", "ledger_id": child.ledger_id}
    assert "whole codebook entry" in (await child.svc.record("codebook", q, {copier.pub: copier.sign(q)}))["error"]
    q2 = {"copied": {"type": "codebook"}, "group_id": "public", "ledger_id": child.ledger_id}
    assert "copier" in (await child.svc.record("codebook", q2, {}))["error"]
    whole = next(e for e in net.svc.codebooks()["codebooks"])
    unsigned = copy.deepcopy(whole)
    unsigned["sigs"] = {}
    unsigned["hash"] = h(canon(hash_body(unsigned)))
    q3 = {"copier": copier.pub, "copied": {k: unsigned[k] for k in ("type", "payload", "sigs", "prev", "ts", "hash", "seal")},
          "group_id": "public", "ledger_id": child.ledger_id}
    assert "publisher's signature" in (await child.svc.record("codebook", q3, {copier.pub: copier.sign(q3)}))["error"]
    resealed = copy.deepcopy(whole)
    resealed["seal"] = {"pub": copier.pub, "sig": "00" * 64}
    q4 = {"copier": copier.pub, "copied": {k: resealed[k] for k in ("type", "payload", "sigs", "prev", "ts", "hash", "seal")},
          "group_id": "public", "ledger_id": child.ledger_id}
    assert "seal" in (await child.svc.record("codebook", q4, {copier.pub: copier.sign(q4)}))["error"]


def test_private_hash_is_canonical():
    assert private_hash({"b": 1, "a": 2}) == private_hash({"a": 2, "b": 1})
