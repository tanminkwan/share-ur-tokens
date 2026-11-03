"""What an owner does with its own keys (6-K). The recorder and the key peer are injected (RecorderAPI, and `ask`: one
message to a key peer), so the flows run the same from the command line, a screen, or a test.

    register   promise the next key on the ledger (key_commit), seal the backup {current, next}, optionally hand it to
               a key peer and name that key peer for recovery
    rotate     move to the promised next key (stolen key): from the backup; the new key promises the one after it
    recover    lost key and lost backup: a key peer named in advance signs; new keys are made on this device
    restore    a new device, same key: put the backup's current key into this peer's key store"""
from __future__ import annotations

import time
from typing import Awaitable, Callable

from ..crypto import Identity
from .backup import BackupError, open_backup, put_request, seal_backup
from .lineage import commit_entry, recovery_entry, rotate_entry
from .store import KeyStore, load_or_create

Ask = Callable[[dict], Awaitable[dict]]


class KeyFlows:
    def __init__(self, settings, store: KeyStore, name: str, recorder, ask: Ask | None = None, clock=None):
        self.s, self.store, self.name, self.recorder, self.ask = settings, store, name, recorder, ask
        self.clock = clock or time.time

    async def _ledger_id(self) -> str | None:
        t = await self.recorder.trust()
        return t.get("ledger_id") if t.get("ok") else None

    async def _key_peer(self) -> str:
        if self.ask is None:
            raise BackupError("no key peer given")
        r = await self.ask({"op": "key.info"})
        if not r.get("ok"):
            raise BackupError(f"key peer: {r.get('error')}")
        return r["pub"]

    async def _hand_over(self, me: Identity, backup: dict, secret: str | None) -> dict | None:
        if self.ask is None or secret is None:
            return None
        return await self.ask(put_request(me, backup, secret, self.clock()))

    @staticmethod
    def _fail(e) -> dict:
        return {"ok": False, "error": str(e)}

    async def register(self, passphrase: str, recovery: list[str] = (), secret: str | None = None, key_peer_recovers: bool = False) -> dict:
        try:
            me, nxt = load_or_create(self.store, self.name), Identity.generate()
            recovery = list(recovery) + ([await self._key_peer()] if key_peer_recovers else [])
            backup = seal_backup(me, passphrase, self.s, nxt)  # before the promise: a short passphrase stops here
        except BackupError as e:
            return self._fail(e)
        p, sigs = commit_entry(me, nxt, self.s.genesis_group_id, await self._ledger_id(), recovery)
        r = await self.recorder.record("key_commit", p, sigs)
        if not r.get("ok"):
            return r
        kept = await self._hand_over(me, backup, secret)
        return {"ok": True, "pub": me.pub, "recovery": recovery, "backup": backup, "entry": r["hash"], **({"key_peer": kept} if kept else {})}

    async def fetch(self, pub: str, secret: str) -> dict:
        if self.ask is None:
            return self._fail("no key peer given")
        return await self.ask({"op": "key.backup.get", "pub": pub, "secret": secret})

    async def rotate(self, passphrase: str, backup: dict | None = None, secret: str | None = None) -> dict:
        try:
            if backup is None:
                me = self.store.load(self.name)
                got = await self.fetch(me.pub if me else "", secret or "")
                if not got.get("ok"):
                    return got
                backup = got["backup"]
            keys = open_backup(backup, passphrase, self.s)
        except BackupError as e:
            return self._fail(e)
        if "next" not in keys:
            return self._fail("this backup holds no promised next key (register first)")
        old, new, following = keys["current"], keys["next"], Identity.generate()
        status = await self.recorder.key(old.pub)
        p, sigs = rotate_entry(old.pub, new, following, self.s.genesis_group_id, await self._ledger_id(), status.get("recovery", []))
        r = await self.recorder.record("peer_rotate", p, sigs)
        if not r.get("ok"):
            return r
        return await self._moved_to(new, following, passphrase, secret, r)

    async def recover(self, old_pub: str, passphrase: str, secret: str) -> dict:
        try:
            kp = await self._key_peer()
            seal_backup(Identity.generate(), passphrase, self.s)  # check the passphrase before anything is signed
        except BackupError as e:
            return self._fail(e)
        status = await self.recorder.key(old_pub)
        new, following = Identity.generate(), Identity.generate()
        p = recovery_entry(old_pub, new.pub, following.pub, kp, self.s.genesis_group_id, await self._ledger_id(), status.get("recovery", []))
        a = await self.ask({"op": "key.recover", "payload": p, "secret": secret})
        if not a.get("ok"):
            return a
        r = await self.recorder.record("peer_rotate", p, {new.pub: new.sign(p), kp: a["sig"]})
        if not r.get("ok"):
            return r
        return await self._moved_to(new, following, passphrase, secret, r)

    async def _moved_to(self, new: Identity, following: Identity, passphrase: str, secret: str | None, r: dict) -> dict:
        """the new key goes into this peer's key store; its backup promises the following key"""
        self.store.save(self.name, new)
        backup = seal_backup(new, passphrase, self.s, following)
        kept = await self._hand_over(new, backup, secret)
        return {"ok": True, "pub": new.pub, "backup": backup, "entry": r["hash"], **({"key_peer": kept} if kept else {})}

    def restore(self, backup: dict, passphrase: str, force: bool = False) -> dict:
        try:
            keys = open_backup(backup, passphrase, self.s)
        except BackupError as e:
            return self._fail(e)
        have = self.store.load(self.name)
        if have is not None and have.pub != keys["current"].pub and not force:
            return self._fail("this peer already has another key here (force to replace it)")
        self.store.save(self.name, keys["current"])
        return {"ok": True, "pub": keys["current"].pub, "where": self.store.where(self.name)}
