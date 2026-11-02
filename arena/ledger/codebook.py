"""Code table editions (user 2026-11-02). Any peer may publish an edition of the code table as a `codebook` entry; the
one many events and profiles follow gains standing by itself, counted from the ledger (no one appoints it). Following an
edition is optional: the basics are defined in advance to make the ecosystem sturdy, not to bind anyone.

An event may name the edition it follows in its `codebook` column {entry, publisher, version}. The ledger checks that the
entry is an edition on this ledger, that the column matches it, that the event's elements are codes of that edition, and
that this recorder's software implements every ledger code the edition lists (a recorder cannot enforce codes it does
not have)."""
from __future__ import annotations

import re

from ..crypto import canon, h, verify
from .elements import LEDGER_ELEMENTS
from .purposes import PURPOSES
from .types import ENTRY_TYPES, EntryType, _inc, register_entry_type

VERSION = re.compile(r"^\d+\.\d+$")
LOCAL = re.compile(r"^x-[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9_-]*$")  # a branch community's own code: x-<community>.<code>
CODE_KINDS = ("entry_types", "purposes", "elements", "connections")  # connections are the brokers' codes, listed for peers


def implemented_codes() -> dict:
    """the ledger codes this software checks (the recorder's GET /codes)"""
    return {"entry_types": sorted(ENTRY_TYPES), "purposes": sorted(PURPOSES), "elements": sorted(LEDGER_ELEMENTS)}


def _v(version: str) -> tuple:
    return tuple(int(x) for x in version.split("."))


def editions(chain) -> dict:
    """the editions known on this chain: its own, and the trunk's it copied (keyed by the trunk entry's hash, so an event
    names a trunk edition the same way on the trunk and on a branch)"""
    out = {}
    for x in chain:
        if x["type"] == "codebook":
            a = x["payload"].get("adopted")
            out.update({a["hash"]: a["payload"]} if a else {x["hash"]: x["payload"]})
    return out


def _signers(p):
    return [p.get("adopter")] if "adopted" in p else [p.get("publisher")]


BODY = ("type", "payload", "sigs", "prev", "ts")


def _adopted_ok(chain, p) -> str | None:
    """user 2026-11-02: a branch may follow the trunk's editions. The branch copies the trunk's edition entry as it is; its
    ledger checks, without the network, that the copy hashes to its hash, carries the publisher's signature, was sealed,
    and belongs to the trunk named in this branch's genesis. Peers may also look the entry up on the trunk itself."""
    a = p["adopted"]
    if not isinstance(a, dict) or a.get("type") != "codebook" or not isinstance(a.get("payload"), dict) or not all(k in a for k in (*BODY, "hash", "seal")):
        return "adopted must be a whole codebook entry of the trunk"
    if not is_branch(chain):
        return "only a branch chain copies the trunk's editions"
    if a["hash"] != h(canon({k: a[k] for k in BODY})):
        return "the copied edition does not hash to its hash"
    ap = a["payload"]
    if "adopted" in ap or "local" in ap:
        return "only the trunk's own editions are copied"
    if ap.get("ledger_id") != chain[0]["payload"]["parent"].get("ledger_id"):
        return "the copied edition is not of the trunk this branch came from"
    if not verify(ap.get("publisher", ""), ap, a["sigs"].get(ap.get("publisher", ""), "")):
        return "the copied edition lacks its publisher's signature"
    seal = a.get("seal") or {}
    if not seal.get("pub") or not verify(seal["pub"], a["hash"], seal.get("sig", "")):
        return "the copied edition lacks the trunk recorder's seal"
    if a["hash"] in editions(chain):
        return "this edition is already copied"


def _shape(chain, e, now, s):
    p = e["payload"]
    if "adopted" in p:
        return None if p.get("adopter") else "a copied edition needs the adopter who records it"
    if not p.get("publisher") or not isinstance(p.get("name"), str) or not p["name"] or not isinstance(p.get("version"), str) \
            or not VERSION.match(p["version"]) or not isinstance(p.get("content_hash"), str) or len(p["content_hash"]) != 64:
        return "codebook needs publisher, name, version x.y and the content_hash of the code table document"
    codes = p.get("codes")
    if not isinstance(codes, dict) or not set(codes) <= set(CODE_KINDS) or \
            not all(isinstance(v, list) and all(isinstance(c, str) and c for c in v) for v in codes.values()):
        return f"codebook codes must map {', '.join(CODE_KINDS)} to lists of code names"


def is_branch(chain) -> bool:
    return bool(chain) and chain[0]["type"] == "genesis" and "parent" in chain[0]["payload"]


def local_purposes(chain) -> dict:
    """a branch chain's own purpose codes, declared in its editions: code -> {types, description}"""
    out = {}
    for x in editions(chain).values():
        out.update((x.get("local") or {}).get("purposes", {}))  # copied trunk editions carry no local codes
    return out


def _check_local(chain, local) -> str | None:
    """user 2026-11-02: a branch chain may add its own codes. Only purposes (a name and the types it is for): elements and
    entry types need ledger software, so they come only in the platform's table"""
    if not isinstance(local, dict) or not set(local) <= {"purposes"}:
        return "local codes: only purposes may be added by a community"
    if not is_branch(chain):
        return "local codes belong to a branch chain; the trunk's codes come with the platform's table"
    for code, d in (local.get("purposes") or {}).items():
        if not LOCAL.match(code):
            return f"local code {code!r} must be named x-<community>.<code>"
        if not isinstance(d, dict) or not isinstance(d.get("types"), list) or not d["types"] or any(t not in ENTRY_TYPES for t in d["types"]):
            return f"local code {code!r} needs the entry types it is for"
        if not isinstance(d.get("description"), str) or not d["description"]:
            return f"local code {code!r} needs a description"
        if code in local_purposes(chain):
            return f"local code {code!r} is already defined on this chain (meanings never change; use a new name)"


def _rule(chain, e, now, s):
    p = e["payload"]
    if "adopted" in p:
        return _adopted_ok(chain, p)
    if "local" in p:
        bad = _check_local(chain, p["local"])
        if bad:
            return bad
    for x in editions(chain).values():
        if (x["publisher"], x["name"], x["version"]) == (p["publisher"], p["name"], p["version"]):
            return "this edition is already published"
    sup = p.get("supersedes")
    if sup is not None:
        prev = editions(chain).get(sup)
        if prev is None:
            return "supersedes must name a codebook edition on this ledger"
        if prev["publisher"] == p["publisher"] and prev["name"] == p["name"] and _v(p["version"]) <= _v(prev["version"]):
            return "a new edition of the same table needs a higher version"


def check_event_codebook(chain, p) -> str | None:
    """the event's codebook column, if any"""
    ref = p.get("codebook")
    if ref is None:
        return None
    if not isinstance(ref, dict) or set(ref) != {"entry", "publisher", "version"}:
        return "codebook must be {entry, publisher, version}"
    ed = editions(chain).get(ref["entry"])
    if ed is None:
        return "codebook: no such edition on this ledger"
    if (ed["publisher"], ed["version"]) != (ref["publisher"], ref["version"]):
        return "codebook: publisher or version does not match the edition"
    missing = [c for k, have in implemented_codes().items() for c in ed["codes"].get(k, []) if c not in have]
    if missing:
        return f"codebook: this recorder does not implement {', '.join(missing)} of that edition"
    outside = [el for el in p.get("elements", {}) if el not in ed["codes"].get("elements", [])]
    if outside:
        return f"codebook: elements {', '.join(outside)} are not codes of that edition"


def _public(p, chain):
    if "adopted" in p:
        a = p["adopted"]
        return {"adopter": p["adopter"], "adopted_from": {"ledger_id": a["payload"].get("ledger_id"), "entry": a["hash"]},
                **{k: a["payload"][k] for k in ("publisher", "name", "version", "content_hash", "codes") if k in a["payload"]}}
    return {k: p[k] for k in ("publisher", "name", "version", "content_hash", "codes", "supersedes", "local") if k in p}


def _contribute(rec, p, index):
    if "adopted" not in p:  # a copy is not a new edition
        _inc(rec, p["publisher"], "codebooks")


register_entry_type(EntryType("codebook", _signers, shape=_shape, rules=(_rule,), public=_public,
                              counters={"codebooks": 0, "codebook_followers": 0}, contribute=_contribute))
