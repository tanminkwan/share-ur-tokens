"""The founding pass (dev/founding/requirements.md FG-C1, C2): what a sphinx (god's delegate, a person who met the applicant)
signs when it lets someone found a branch group. Off the ledger until it is used; bound to one founder key, so it cannot
be handed on.

    pass = {format, version, body: {founder, sphinx, issued_at, until, nonce}, sig}     sig = the sphinx's signature over body

Pure functions; the trunk's chain_link rule will check a pass with them (FG-C3, not yet)."""
from __future__ import annotations

import re

from ..crypto import verify

FORMAT, VERSION = "arena-founding-pass", 1
HEX64 = re.compile(r"[0-9a-f]{64}")
BODY_KEYS = ("founder", "sphinx", "issued_at", "until", "nonce")


def pass_body(founder: str, sphinx: str, issued_at: float, until: float, nonce: str) -> dict:
    return {"founder": founder, "sphinx": sphinx, "issued_at": float(issued_at), "until": float(until), "nonce": nonce}


def make_pass(body: dict, sig: str) -> dict:
    return {"format": FORMAT, "version": VERSION, "body": dict(body), "sig": sig}


def pass_error(p, founder: str | None = None, now: float | None = None, sphinxes: set | None = None) -> str | None:
    """None when `p` is a pass its sphinx signed; with founder: for that founder only; with now: not expired; with
    sphinxes: signed by one of those keys"""
    if not isinstance(p, dict) or p.get("format") != FORMAT or p.get("version") != VERSION or set(p) != {"format", "version", "body", "sig"}:
        return "not a founding pass"
    b = p["body"]
    if not isinstance(b, dict) or set(b) != set(BODY_KEYS):
        return "a founding pass names founder, sphinx, issued_at, until and nonce"
    if not all(isinstance(b[k], str) and HEX64.fullmatch(b[k]) for k in ("founder", "sphinx")):
        return "founder and sphinx are public keys"
    if not all(isinstance(b[k], (int, float)) and not isinstance(b[k], bool) for k in ("issued_at", "until")) or b["until"] <= b["issued_at"]:
        return "issued_at and until are times, until after issued_at"
    if not isinstance(b["nonce"], str) or not b["nonce"]:
        return "a nonce makes each pass one of a kind"
    if not verify(b["sphinx"], b, p.get("sig") or ""):
        return "the sphinx's signature does not verify"
    if sphinxes is not None and b["sphinx"] not in sphinxes:
        return "signed by a key that is not a sphinx here"
    if founder is not None and b["founder"] != founder:
        return "this pass is for another founder (it cannot be handed on)"
    if now is not None and not (b["issued_at"] <= now < b["until"]):
        return "this pass is not valid now"
    return None
