"""The key peer's role (6-K, user 2026-11-03: "key 백업 서비스도 특수 peer가 하면 되겠다", "키 발급은 peer의 보안 영역에서
스스로 만드는 거지").

A key peer never makes or sees a private key. It keeps encrypted backups (arena/keys/backup.py) and, only for an identity
that named it for recovery on the ledger in advance, signs a recovery after its own check of the person. This sample's
check is a recovery secret the owner gave with the backup (kept as a scrypt hash, attempts limited); a real key peer may
check differently (an HR record, an existing DID, a face-to-face visit). It is optional, and anyone may run one.

    key.info                         -> {pub}: name this key peer for recovery with this key
    key.backup.put {pub, backup, secret, ts, sig}   the owner's signed request (sig over op, pub, backup hash, ts)
    key.backup.get {pub, secret}     -> {backup}
    key.recover {payload, secret}    -> {sig}: this key peer's signature on a peer_rotate by recovery (arena/keys/lineage.py)"""
from __future__ import annotations

import hmac
import os

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..crypto import verify
from ..keys.backup import put_signed
from .plugin import BaseApp


class KeyRole(BaseApp):
    name, version, app_id = "platform.keys", "1.0", "9a41c6d2-3e7b-4f15-8c0a-6d2b9e4f1a73"

    def __init__(self, settings):
        self.s = settings

    def offers(self):
        return ["키 백업 보관", "키 복구"]

    def profile_extra(self):
        return {"key_peer": {"backup": True, "recovery": True}}

    def ops(self):
        return {"key.info": self._info, "key.backup.put": self._put, "key.backup.get": self._get, "key.recover": self._recover}

    # ---- the secret ----
    def _hash(self, secret: str, salt: bytes) -> str:
        return Scrypt(salt=salt, length=32, n=self.s.key_backup_scrypt_n, r=self.s.key_backup_scrypt_r,
                      p=self.s.key_backup_scrypt_p).derive(secret.encode("utf-8")).hex()

    def _check(self, ctx, pub: str, secret) -> tuple[dict, str | None]:
        """(state, error): the secret of `pub`'s record, counting wrong attempts; locked after too many"""
        state = ctx.state.load()
        rec = state.get("backups", {}).get(pub)
        if rec is None:
            return state, "no backup kept here for this key"
        if rec.get("failures", 0) >= self.s.key_peer_max_attempts:
            return state, "locked: too many wrong recovery secrets for this key"
        if not isinstance(secret, str) or not hmac.compare_digest(self._hash(secret, bytes.fromhex(rec["salt"])), rec["secret"]):
            rec["failures"] = rec.get("failures", 0) + 1
            ctx.state.save(state)
            return state, "wrong recovery secret"
        if rec.get("failures"):
            rec["failures"] = 0
            ctx.state.save(state)
        return state, None

    # ---- ops ----
    async def _info(self, ctx, msg, head):
        return {"ok": True, "pub": ctx.pub}

    async def _put(self, ctx, msg, head):
        pub, backup, secret, ts, sig = (msg.get(k) for k in ("pub", "backup", "secret", "ts", "sig"))
        if not isinstance(backup, dict) or backup.get("pub") != pub or not pub:
            return {"ok": False, "error": "a backup of the key that signs the request is needed"}
        if not isinstance(ts, (int, float)) or abs(ctx.clock() - ts) > self.s.sig_window_sec or \
                not verify(pub, put_signed(pub, backup, ts), sig or ""):
            return {"ok": False, "error": "the request must be signed now by the key the backup is of"}
        if not isinstance(secret, str) or len(secret) < self.s.key_peer_min_secret:
            return {"ok": False, "error": f"a recovery secret of at least {self.s.key_peer_min_secret} characters is needed"}
        state = ctx.state.load()
        salt = os.urandom(16)
        state.setdefault("backups", {})[pub] = {"backup": backup, "salt": salt.hex(), "secret": self._hash(secret, salt), "failures": 0}
        ctx.state.save(state)
        return {"ok": True, "pub": pub}

    async def _get(self, ctx, msg, head):
        state, err = self._check(ctx, msg.get("pub"), msg.get("secret"))
        return {"ok": False, "error": err} if err else {"ok": True, "backup": state["backups"][msg["pub"]]["backup"]}

    async def _recover(self, ctx, msg, head):
        p = msg.get("payload")
        if not isinstance(p, dict) or p.get("by") != "recovery" or p.get("recoverer") != ctx.pub:
            return {"ok": False, "error": "a peer_rotate payload by recovery naming this key peer as the recoverer is needed"}
        _, err = self._check(ctx, p.get("old"), msg.get("secret"))
        if err:
            return {"ok": False, "error": err}
        ctx.log.emit("keys", ctx.pen, f"키 복구 서명: {str(p.get('old'))[:8]} -> {str(p.get('new'))[:8]}")
        return {"ok": True, "sig": ctx.sign(p)}
