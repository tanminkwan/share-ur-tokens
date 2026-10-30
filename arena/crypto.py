"""Identity (ed25519), canonical JSON, SHA-256 and the display pen name. No network, no settings: pure helpers."""
from __future__ import annotations

import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pen_name(pub: str, prefix: str, n: int) -> str:
    return prefix + pub[:n]


class Identity:
    """A peer (or service) identity is just an ed25519 key pair; the public key hex is its identifier."""

    def __init__(self, key: Ed25519PrivateKey):
        self._k = key
        self.pub = key.public_key().public_bytes_raw().hex()

    @classmethod
    def generate(cls) -> "Identity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_hex(cls, priv_hex: str) -> "Identity":
        return cls(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex.strip())))

    @classmethod
    def load(cls, path: str) -> "Identity":
        with open(path, encoding="utf-8") as f:
            return cls.from_hex(f.read())

    @classmethod
    def load_or_create(cls, path: str) -> "Identity":
        if os.path.exists(path):
            return cls.load(path)
        me = cls.generate()
        me.save(path)
        return me

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self._k.private_bytes_raw().hex() + "\n")
        os.chmod(path, 0o600)

    def sign(self, payload) -> str:
        return self._k.sign(canon(payload)).hex()


def verify(pub_hex: str, payload, sig_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), canon(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
