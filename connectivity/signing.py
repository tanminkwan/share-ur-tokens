"""Who is asking: an ed25519 key signs "<METHOD> <path> <ts>" (headers X-Conn-Key, X-Conn-Ts, X-Conn-Sig, hex). The key is
the only identity the service knows; it never makes or keeps one. Independent of any other signing scheme in the repo.
A request whose body matters (POST /out) signs the body too: "<METHOD> <path> <ts> <sha256 of the body>"."""
from __future__ import annotations

import hashlib
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

H_KEY, H_TS, H_SIG = "X-Conn-Key", "X-Conn-Ts", "X-Conn-Sig"
_last_ts = 0.0  # no two signatures made by this process carry the same time, so a server that takes each signature once never meets a twin


class SignatureError(Exception):
    pass


def _target(method: str, path: str, ts: str, body: bytes | None = None) -> bytes:
    tail = "" if body is None else " " + hashlib.sha256(body).hexdigest()
    return f"{method.upper()} {path} {ts}{tail}".encode()


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def sign_headers(signer, key_hex: str, method: str, path: str, now: float | None = None, body: bytes | None = None) -> dict:
    """signer: bytes -> ed25519 signature bytes (whoever holds the key signs; the key itself never has to be handed over).
    body: given when the body must not be changed on the way (the signature then holds its sha256)"""
    global _last_ts
    if now is None:
        now = _last_ts = max(time.time(), _last_ts + 1e-6)
    ts = repr(float(now))
    return {H_KEY: key_hex, H_TS: ts, H_SIG: signer(_target(method, path, ts, body)).hex()}


def verify_headers(headers, method: str, path: str, now: float, window: float, body: bytes | None = None) -> str:
    """the caller's public key (hex), or raise SignatureError"""
    get = lambda h: headers.get(h) or headers.get(h.lower())
    pub, ts, sig = get(H_KEY), get(H_TS), get(H_SIG)
    if not pub or not ts or not sig:
        raise SignatureError(f"signed request required ({H_KEY}, {H_TS}, {H_SIG})")
    try:
        when = float(ts)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(sig), _target(method, path, ts, body))
    except (ValueError, InvalidSignature):
        raise SignatureError("bad request signature") from None
    if abs(now - when) > window:
        raise SignatureError("request timestamp outside the allowed window")
    return pub.lower()
