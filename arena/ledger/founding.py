"""The founding pass (dev/founding/requirements.md FG-C1, C2): what a sphinx (god's delegate, a person who met the applicant)
signs when it lets someone found a branch group. Off the ledger until it is used; bound to one founder key, so it cannot
be handed on.

    pass = {format, version, body: {founder, sphinx, issued_at, until, nonce}, sig}     sig = the sphinx's signature over body

Pure functions; the trunk's chain_link rule checks a pass with them (FG-C3, arena/ledger/delegation.py).

The founding policy (FG-F6): what the foundation says a sphinx should follow, signed by the foundation, never on a ledger
(the ledger does not enforce it, FG-A5; the sphinx does):

    policy = {format, version, body: {foundation, cap: {count, days}, pass_days, issued_at}, sig}"""
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


POLICY_FORMAT = "arena-founding-policy"
POLICY_KEYS = ("foundation", "cap", "pass_days", "issued_at")


def policy_body(foundation: str, cap_count: int, cap_days: float, pass_days: float, issued_at: float) -> dict:
    return {"foundation": foundation, "cap": {"count": int(cap_count), "days": float(cap_days)}, "pass_days": float(pass_days),
            "issued_at": float(issued_at)}


def make_policy(body: dict, sig: str) -> dict:
    return {"format": POLICY_FORMAT, "version": VERSION, "body": dict(body), "sig": sig}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def policy_error(p, foundation: str | None = None) -> str | None:
    """None when `p` is a founding policy its foundation signed (and, with foundation, that one)"""
    if not isinstance(p, dict) or p.get("format") != POLICY_FORMAT or p.get("version") != VERSION or set(p) != {"format", "version", "body", "sig"}:
        return "not a founding policy"
    b = p["body"]
    if not isinstance(b, dict) or set(b) != set(POLICY_KEYS) or not isinstance(b["foundation"], str) or not HEX64.fullmatch(b["foundation"]):
        return "a founding policy names foundation, cap, pass_days and issued_at"
    cap = b["cap"]
    if not isinstance(cap, dict) or set(cap) != {"count", "days"} or not isinstance(cap["count"], int) or isinstance(cap["count"], bool) \
            or cap["count"] < 0 or not _num(cap["days"]) or cap["days"] <= 0:
        return "cap is {count (0 or more), days (more than 0)}"
    if not _num(b["pass_days"]) or b["pass_days"] <= 0 or not _num(b["issued_at"]):
        return "pass_days is more than 0 and issued_at a time"
    if not verify(b["foundation"], b, p.get("sig") or ""):
        return "the foundation's signature does not verify"
    if foundation is not None and b["foundation"] != foundation:
        return "this policy is from another foundation"
    return None
