"""Who is asking: an ed25519 key signs "<METHOD> <path> <ts>" (headers X-Conn-Key, X-Conn-Ts, X-Conn-Sig, hex). The key is
the only identity the service knows; it never makes or keeps one. Independent of any other signing scheme in the repo."""
from __future__ import annotations

import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

H_KEY, H_TS, H_SIG = "X-Conn-Key", "X-Conn-Ts", "X-Conn-Sig"


class SignatureError(Exception):
    pass


def _target(method: str, path: str, ts: str) -> bytes:
    return f"{method.upper()} {path} {ts}".encode()


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def sign_headers(signer, key_hex: str, method: str, path: str, now: float | None = None) -> dict:
    """signer: bytes -> ed25519 signature bytes (whoever holds the key signs; the key itself never has to be handed over)"""
    ts = repr(float(time.time() if now is None else now))
    return {H_KEY: key_hex, H_TS: ts, H_SIG: signer(_target(method, path, ts)).hex()}


def verify_headers(headers, method: str, path: str, now: float, window: float) -> str:
    """the caller's public key (hex), or raise SignatureError"""
    get = lambda h: headers.get(h) or headers.get(h.lower())
    pub, ts, sig = get(H_KEY), get(H_TS), get(H_SIG)
    if not pub or not ts or not sig:
        raise SignatureError(f"signed request required ({H_KEY}, {H_TS}, {H_SIG})")
    try:
        when = float(ts)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(sig), _target(method, path, ts))
    except (ValueError, InvalidSignature):
        raise SignatureError("bad request signature") from None
    if abs(now - when) > window:
        raise SignatureError("request timestamp outside the allowed window")
    return pub.lower()
