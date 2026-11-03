"""6-K (user 2026-11-02/03): a peer makes its own key in its secure area; an encrypted backup; key succession with a
promised next key; recovery only by key peers named in advance."""
import json
import os
import stat

import pytest

from arena.config import ConfigError
from arena.crypto import Identity
from arena.keys import BackupError, FileKeyStore, OsKeyStore, open_backup, open_key_store, seal_backup
from arena.keys.lineage import commit_entry, recovery_entry, rotate_entry
from arena.keys.store import AutoKeyStore, load_or_create
from arena.ledger.peer_keys import key_commitment
from arena.peer.home import PeerHome
from tests.test_trust import Net, net  # noqa: F401  (net is a fixture)


class FakeKeyring:
    """stands in for the OS key store (tests never touch the machine's own)"""
    priority = 5

    def __init__(self):
        self.items = {}

    def get_password(self, service, user):
        return self.items.get((service, user))

    def set_password(self, service, user, value):
        self.items[(service, user)] = value

    def delete_password(self, service, user):
        del self.items[(service, user)]


# ---------------- P6-K1: where the key lives ----------------
def test_p6k1_the_os_key_store_keeps_the_key_out_of_files(tmp_path, settings):
    ring = FakeKeyring()
    store = OsKeyStore("agent-arena", ring)
    name = str(tmp_path / "home" / "identity.key")
    me = load_or_create(store, name)
    assert load_or_create(store, name).pub == me.pub  # the same peer after a restart
    assert not os.path.exists(name) and list(ring.items) == [("agent-arena", os.path.abspath(name))]
    assert "OS 키 보관소" in store.where(name)
    store.remove(name)
    store.remove(name)  # nothing left to remove is not an error
    assert store.load(name) is None


def test_p6k1_file_store_is_0600_and_auto_keeps_an_existing_file(tmp_path, settings):
    f = FileKeyStore()
    name = str(tmp_path / "a.key")
    me = load_or_create(f, name)
    assert stat.S_IMODE(os.stat(name).st_mode) == 0o600 and f.load(name).pub == me.pub and "0600" in f.where(name)
    f.remove(name)
    assert f.load(name) is None
    ring = FakeKeyring()
    auto = AutoKeyStore(FileKeyStore(), OsKeyStore("s", ring))
    old = load_or_create(FileKeyStore(), str(tmp_path / "old.key"))
    assert load_or_create(auto, str(tmp_path / "old.key")).pub == old.pub and not ring.items  # an existing file stays
    load_or_create(auto, str(tmp_path / "new.key"))
    assert ring.items and not os.path.exists(tmp_path / "new.key")  # a new key goes to the OS store
    auto.remove(str(tmp_path / "new.key"))
    assert not ring.items
    no_os = AutoKeyStore(FileKeyStore(), None)
    assert "OS 키 보관소가 없어 파일" in no_os.where(str(tmp_path / "x.key"))  # said, not silent


def test_p6k1_choosing_the_store_by_settings(tmp_path, settings, monkeypatch):
    import dataclasses
    import arena.keys.store as store_module
    assert open_key_store(settings).kind == "file"
    assert open_key_store(dataclasses.replace(settings, key_store="os"), backend=FakeKeyring()).kind == "os"
    assert open_key_store(dataclasses.replace(settings, key_store="auto"), backend=FakeKeyring()).os is not None
    monkeypatch.setattr(store_module, "os_backend", lambda: None)  # a machine without an OS key store
    with pytest.raises(ConfigError, match="no OS key store"):
        open_key_store(dataclasses.replace(settings, key_store="os"))
    assert open_key_store(dataclasses.replace(settings, key_store="auto")).os is None
    with pytest.raises(ConfigError, match="auto, os or file"):
        open_key_store(dataclasses.replace(settings, key_store="vault"))
    home = PeerHome(str(tmp_path / "h"), settings)
    assert home.identity().pub == home.identity().pub and os.path.exists(home.key_name())


# ---------------- P6-K2: the encrypted backup ----------------
def test_p6k2_the_backup_holds_only_ciphertext_and_opens_with_the_passphrase(settings):
    me, nxt = Identity.generate(), Identity.generate()
    b = seal_backup(me, "correct horse battery", settings, nxt)
    text = json.dumps(b)
    assert me.private_hex() not in text and nxt.private_hex() not in text and b["pub"] == me.pub
    keys = open_backup(b, "correct horse battery", settings)
    assert keys["current"].pub == me.pub and keys["next"].pub == nxt.pub
    assert "current" in open_backup(seal_backup(me, "correct horse battery", settings), "correct horse battery", settings)
    with pytest.raises(BackupError, match="wrong passphrase"):
        open_backup(b, "wrong horse battery", settings)
    with pytest.raises(BackupError, match="wrong passphrase, or the backup was changed"):
        open_backup(dict(b, pub=Identity.generate().pub), "correct horse battery", settings)  # the header is bound too
    with pytest.raises(BackupError, match="at least"):
        seal_backup(me, "short", settings)
    with pytest.raises(BackupError, match="known version"):
        open_backup(dict(b, version=2), "correct horse battery", settings)
    with pytest.raises(BackupError, match="scrypt N"):
        open_backup(dict(b, kdf=dict(b["kdf"], n=2 ** 30)), "correct horse battery", settings)
    with pytest.raises(BackupError, match="not a readable"):
        open_backup({"format": "arena-key-backup"}, "correct horse battery", settings)


# ---------------- P6-K3: key succession on the ledger ----------------
async def _record(net, entry):
    p, sigs = entry
    return await net.svc.record(p.get("pub") and "key_commit" or "peer_rotate", p, sigs)


async def test_p6k3_rotation_needs_the_promised_key_and_retires_the_old_one(net, settings):
    me, nxt, after = Identity.generate(), Identity.generate(), Identity.generate()
    assert (await _record(net, commit_entry(me, nxt, "public", net.ledger_id)))["ok"]
    assert "already has a promise" in (await _record(net, commit_entry(me, after, "public", net.ledger_id)))["error"]
    assert (await net.publish(me, "a"))["ok"]
    thief = Identity.generate()  # holds the current key only: cannot make the promised key
    assert "not the one promised" in (await _record(net, rotate_entry(me.pub, thief, after, "public", net.ledger_id)))["error"]
    assert (await _record(net, rotate_entry(me.pub, nxt, after, "public", net.ledger_id)))["ok"]
    assert "retired key" in (await net.publish(me, "b"))["error"]  # the old key signs nothing more
    assert (await net.publish(nxt, "c"))["ok"]
    assert "already rotated" in (await _record(net, rotate_entry(me.pub, after, Identity.generate(), "public", net.ledger_id)))["error"]
    assert "part of a key line" in (await _record(net, commit_entry(nxt, after, "public", net.ledger_id)))["error"]
    k = net.svc.key(me.pub)
    assert k["status"] == "retired" and k["current"] == nxt.pub and k["lineage"] == [me.pub, nxt.pub]
    assert net.svc.key(nxt.pub)["next"] == key_commitment(after.pub)
    assert net.svc.key(Identity.generate().pub)["status"] == "unknown"
    t = net.svc.track(nxt.pub)
    assert t["track"]["published"] == 2 and t["lineage"] == [me.pub, nxt.pub]  # the record follows the identity


async def test_p6k3_recovery_only_by_a_key_peer_named_in_advance(net, settings):
    me, nxt, keeper, stranger = (Identity.generate() for _ in range(4))
    assert (await _record(net, commit_entry(me, nxt, "public", net.ledger_id, recovery=[keeper.pub])))["ok"]
    new, following = Identity.generate(), Identity.generate()  # made on the person's new device

    async def recover(by: Identity):
        p = recovery_entry(me.pub, new.pub, following.pub, by.pub, "public", net.ledger_id)
        return await net.svc.record("peer_rotate", p, {new.pub: new.sign(p), by.pub: by.sign(p)})
    assert "not named for recovery" in (await recover(stranger))["error"]
    p = recovery_entry(me.pub, new.pub, following.pub, keeper.pub, "public", net.ledger_id)
    assert "signature" in (await net.svc.record("peer_rotate", p, {new.pub: new.sign(p)}))["error"]  # the key peer must sign
    assert (await recover(keeper))["ok"]
    assert net.svc.key(me.pub)["current"] == new.pub


async def test_p6k3_shapes(net, settings):
    me, nxt = Identity.generate(), Identity.generate()

    async def commit(**over):
        p = dict(commit_entry(me, nxt, "public", net.ledger_id)[0], **over)
        return (await net.svc.record("key_commit", p, {me.pub: me.sign(p)}))["error"]
    assert "needs pub and next" in await commit(next="x")
    assert "distinct" in await commit(recovery=["a", "a"])
    assert "at most" in await commit(recovery=[Identity.generate().pub for _ in range(settings.key_recovery_max + 1)])
    assert "own recovery" in await commit(recovery=[me.pub])

    async def rotate(**over):
        p = dict(rotate_entry(me.pub, nxt, Identity.generate(), "public", net.ledger_id)[0], **over)
        return (await net.svc.record("peer_rotate", p, {nxt.pub: nxt.sign(p)}))["error"]
    assert "needs old, new" in await rotate(new=me.pub)
    assert "by must be" in await rotate(by="force")
    assert "recoverer" in await rotate(by="recovery")
    assert "key_commit first" in await rotate()


# ---------------- the key peer and the owner's flows ----------------
PASS, SECRET = "correct horse battery", "my recovery secret"


async def keyworld(tmp_path, settings):
    """a ledger, a key peer, and the owner's flows for one peer home (keys made here, in the home's key store)"""
    from arena.keys.flows import KeyFlows
    from arena.peer.key_role import KeyRole
    from arena.recorder.client import InMemoryRecorderClient
    from tests.test_event_apps import World
    w = World(tmp_path, settings)
    await w.boot()
    kp = w.peer("keys", [KeyRole(settings)])
    home = PeerHome(str(tmp_path / "me"), settings)
    rec = InMemoryRecorderClient(w.svc)
    return w, kp, home, rec, KeyFlows(settings, home.key_store(), home.key_name(), rec, kp.handle)


async def test_p6k_register_then_the_stolen_key_is_rotated_away(tmp_path, settings):
    w, kp, home, rec, flows = await keyworld(tmp_path, settings)
    r = await flows.register(PASS, secret=SECRET, key_peer_recovers=True)
    assert r["ok"] and r["recovery"] == [kp.identity.pub] and r["key_peer"]["ok"]
    old = r["pub"]
    assert old == home.identity().pub  # the key was made by the peer itself, in its own store
    st = await rec.key(old)
    assert st["status"] == "current" and st["recovery"] == [kp.identity.pub]
    assert "wrong recovery secret" in (await flows.fetch(old, "not the secret"))["error"]
    r2 = await flows.rotate(PASS, secret=SECRET)  # the backup comes back from the key peer
    assert r2["ok"] and r2["pub"] != old and home.identity().pub == r2["pub"]
    assert (await rec.key(old))["status"] == "retired" and (await rec.key(r2["pub"]))["recovery"] == [kp.identity.pub]
    assert (await flows.fetch(r2["pub"], SECRET))["ok"]  # the new key's backup is kept too
    r3 = await flows.rotate(PASS, backup=r2["backup"])  # and again, from a backup file
    assert r3["ok"] and (await rec.key(old))["current"] == r3["pub"]


async def test_p6k_recovery_by_the_named_key_peer_and_restore_on_a_new_device(tmp_path, settings):
    w, kp, home, rec, flows = await keyworld(tmp_path, settings)
    r = await flows.register(PASS, secret=SECRET, key_peer_recovers=True)
    old = r["pub"]
    home.key_store().remove(home.key_name())  # the device is gone, and the passphrase with it
    assert "wrong recovery secret" in (await flows.recover(old, PASS, "a guessed secret"))["error"]
    got = await flows.recover(old, PASS, SECRET)
    assert got["ok"] and (await rec.key(old))["current"] == got["pub"] == home.identity().pub
    # restore: a new device, the same key (the passphrase is known)
    from arena.keys.flows import KeyFlows
    other = PeerHome(str(tmp_path / "new-device"), settings)
    nf = KeyFlows(settings, other.key_store(), other.key_name(), rec, kp.handle)
    assert nf.restore(got["backup"], PASS)["pub"] == got["pub"] and other.identity().pub == got["pub"]
    assert "wrong passphrase" in nf.restore(got["backup"], "not the passphrase")["error"]
    load_or_create(PeerHome(str(tmp_path / "third"), settings).key_store(), str(tmp_path / "third" / "identity.key"))
    third = KeyFlows(settings, FileKeyStore(), str(tmp_path / "third" / "identity.key"), rec)
    assert "another key" in third.restore(got["backup"], PASS)["error"]
    assert third.restore(got["backup"], PASS, force=True)["ok"]


async def test_p6k_the_key_peer_refuses(tmp_path, settings):
    import dataclasses
    from arena.keys import put_request
    w, kp, home, rec, flows = await keyworld(tmp_path, settings)
    me = Identity.generate()
    b = seal_backup(me, PASS, settings)
    now = kp.clock()
    assert "backup of the key" in (await kp.handle(dict(put_request(me, b, SECRET, now), pub=Identity.generate().pub)))["error"]
    assert "signed now" in (await kp.handle(put_request(me, b, SECRET, now - 10 * settings.sig_window_sec)))["error"]
    assert "signed now" in (await kp.handle(put_request(Identity.generate(), dict(b), SECRET, now) | {"pub": me.pub}))["error"]
    assert "at least" in (await kp.handle(put_request(me, b, "short", now)))["error"]
    assert "no backup kept" in (await kp.handle({"op": "key.backup.get", "pub": me.pub, "secret": SECRET}))["error"]
    assert (await kp.handle(put_request(me, b, SECRET, now)))["ok"]
    for _ in range(settings.key_peer_max_attempts):
        assert "wrong" in (await kp.handle({"op": "key.backup.get", "pub": me.pub, "secret": "x" * 12}))["error"]
    assert "locked" in (await kp.handle({"op": "key.backup.get", "pub": me.pub, "secret": SECRET}))["error"]
    assert "recoverer" in (await kp.handle({"op": "key.recover", "payload": {"by": "next"}, "secret": SECRET}))["error"]
    # flows without a key peer, or with nothing promised
    from arena.keys.flows import KeyFlows
    bare = KeyFlows(settings, home.key_store(), home.key_name(), rec)
    assert "no key peer" in (await bare.register(PASS, key_peer_recovers=True))["error"]
    assert "no key peer" in (await bare.fetch(me.pub, SECRET))["error"]
    assert "at least" in (await bare.register("short"))["error"]
    assert "no promised next key" in (await bare.rotate(PASS, backup=seal_backup(me, PASS, settings)))["error"]
    assert "no key peer" in (await bare.recover(me.pub, PASS, SECRET))["error"]
    other = KeyFlows(settings, home.key_store(), home.key_name(), rec, kp.handle)
    assert "no backup kept" in (await other.rotate(PASS, secret=SECRET))["error"]
    plain = dataclasses.replace(settings)
    assert (await KeyFlows(plain, home.key_store(), home.key_name(), rec).register(PASS))["ok"]
    assert "already has a promise" in (await bare.register(PASS))["error"]


async def test_p6k_the_command_line_restores_from_a_backup_file_and_never_prints_secrets(tmp_path, settings, monkeypatch):
    import io
    from arena.keys.cli import parser, run
    me = Identity.generate()
    f = tmp_path / "backup.json"
    f.write_text(json.dumps(seal_backup(me, PASS, settings)), encoding="utf-8")
    monkeypatch.setenv("MY_PASS", PASS)
    out = io.StringIO()
    a = parser().parse_args(["restore", "--home", str(tmp_path / "h"), "--backup-file", str(f), "--passphrase-env", "MY_PASS"])
    assert await run(a, settings, out) == 0
    shown = json.loads(out.getvalue())
    assert shown["pub"] == me.pub and PASS not in out.getvalue() and me.private_hex() not in out.getvalue()
    assert PeerHome(str(tmp_path / "h"), settings).identity().pub == me.pub
    monkeypatch.delenv("MY_PASS")
    with pytest.raises(SystemExit, match="MY_PASS is not set"):
        await run(a, settings, io.StringIO())
