"""The encrypted key backup (P6-K2). Sealed on the device with the owner's passphrase; whoever keeps it (a file, a key
peer) holds only ciphertext. Losing both the device and the passphrase is the owner's responsibility, unless the owner
named a key peer that can recover the key (lineage.py).

    {"format": "arena-key-backup", "version": 1, "pub": <current public key>,
     "kdf": {"name": "scrypt", "n", "r", "p", "salt": hex16},
     "cipher": {"name": "aes-256-gcm", "nonce": hex12},
     "ciphertext": hex}

The plaintext is canon({"current": private hex, "next": private hex or absent}): the next key, promised on the ledger
by its hash, lives only here, so a thief holding the device's current key cannot take the identity over. Everything
but the ciphertext is the AES-GCM associated data (canonical JSON), so the header cannot be changed either. Test
vector: dev/protocol-vectors.json "key_backup"."""
from __future__ import annotations

import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..crypto import Identity, canon, h

FORMAT, VERSION = "arena-key-backup", 1


class BackupError(Exception):
    pass


def _key(passphrase: str, kdf: dict) -> bytes:
    return Scrypt(salt=bytes.fromhex(kdf["salt"]), length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]).derive(passphrase.encode("utf-8"))


def _header(b: dict) -> dict:
    return {k: b[k] for k in ("format", "version", "pub", "kdf", "cipher")}


def seal_backup(current: Identity, passphrase: str, settings, next_key: Identity | None = None,
                salt: bytes | None = None, nonce: bytes | None = None) -> dict:
    """the backup of this peer's current key (and its promised next key). salt/nonce are fixed only by the test vector"""
    if len(passphrase) < settings.key_backup_min_passphrase:
        raise BackupError(f"the passphrase needs at least {settings.key_backup_min_passphrase} characters")
    kdf = {"name": "scrypt", "n": settings.key_backup_scrypt_n, "r": settings.key_backup_scrypt_r, "p": settings.key_backup_scrypt_p,
           "salt": (salt or os.urandom(16)).hex()}
    b = {"format": FORMAT, "version": VERSION, "pub": current.pub, "kdf": kdf,
         "cipher": {"name": "aes-256-gcm", "nonce": (nonce or os.urandom(12)).hex()}}
    plain = canon({"current": current.private_hex(), **({"next": next_key.private_hex()} if next_key else {})})
    b["ciphertext"] = AESGCM(_key(passphrase, kdf)).encrypt(bytes.fromhex(b["cipher"]["nonce"]), plain, canon(_header(b))).hex()
    return b


def open_backup(b: dict, passphrase: str, settings) -> dict[str, Identity]:
    """{"current": Identity, "next"?: Identity}; BackupError when it is not a backup, the passphrase is wrong, or it was changed"""
    try:
        kdf, cipher = b["kdf"], b["cipher"]
        if b["format"] != FORMAT or b["version"] != VERSION or kdf["name"] != "scrypt" or cipher["name"] != "aes-256-gcm":
            raise BackupError("not an arena key backup of a known version")
        if not (isinstance(kdf["n"], int) and 2 <= kdf["n"] <= settings.key_backup_scrypt_n_max):
            raise BackupError("the backup asks for a scrypt N outside the accepted range")
        plain = AESGCM(_key(passphrase, kdf)).decrypt(bytes.fromhex(cipher["nonce"]), bytes.fromhex(b["ciphertext"]), canon(_header(b)))
    except BackupError:
        raise
    except InvalidTag:
        raise BackupError("wrong passphrase, or the backup was changed") from None
    except (KeyError, TypeError, ValueError) as e:
        raise BackupError(f"not a readable key backup: {type(e).__name__}") from None
    keys = {k: Identity.from_hex(v) for k, v in json.loads(plain).items()}
    if keys["current"].pub != b["pub"]:
        raise BackupError("the backup's key is not the public key it names")
    return keys


def put_signed(pub: str, backup: dict, ts: float) -> dict:
    """what the owner signs to hand a backup to a key peer: the request, the backup's hash and the time"""
    return {"op": "key.backup.put", "pub": pub, "backup": h(canon(backup)), "ts": ts}


def put_request(me: Identity, backup: dict, secret: str, now: float) -> dict:
    """the message that hands this backup to a key peer, with the recovery secret the key peer will ask for"""
    return {"op": "key.backup.put", "pub": me.pub, "backup": backup, "secret": secret, "ts": now, "sig": me.sign(put_signed(me.pub, backup, now))}
