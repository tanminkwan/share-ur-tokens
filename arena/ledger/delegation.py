"""god's delegates on the trunk (dev/founding/requirements.md FG-A, FG-C3, C4, FG-F1..F3; design.md 1).

- delegate {god, delegate, scope}: the current god names a key that may let others found branch groups (a sphinx). Only
  on the trunk; once per key until it is taken back.
- undelegate {god, delegate}: the current god takes it back. Passes the delegate signs afterwards are refused.
- chain_link carries exactly one of: `pass`, a founding pass a delegate signed for that child god (arena/ledger/founding.py),
  or `approver`, the trunk's current god signing the link itself (the exception while the god key exists).

A delegate keeps its standing through its own key line (6-K: key_commit, peer_rotate): the ledger follows the line of the
key that signed a pass back to its first key, which must be delegated, and takes passes only from the line's current key.
How many passes a delegate may give, and for how long a pass holds, is not the ledger's business (FG-A5): the foundation
sets it, the sphinx enforces it; the ledger reads the pass's own `until`."""
from __future__ import annotations

from .founding import pass_error
from .peer_keys import lineage, succession
from .types import LINK_CHECKS, EntryType, _is_hex64, current_keys, is_branch, register_entry_type

DELEGATE_SCOPES = {"found_branch": "가지 그룹을 만드는 통과 증명서를 낸다(뿌리 원장이 chain_link에서 그 증명서를 받는다)"}


def active_delegates(chain) -> dict:
    """{delegated first key: {scope, entry, seq}} as the chain stands"""
    out: dict = {}
    for i, e in enumerate(chain):
        p = e["payload"]
        if e["type"] == "delegate":
            out[p["delegate"]] = {"scope": p["scope"], "entry": e.get("hash"), "seq": e.get("seq", i)}
        elif e["type"] == "undelegate":
            out.pop(p["delegate"], None)
    return out


def delegates_view(chain) -> list[dict]:
    """what GET /delegates shows: each active delegate with the current key of its line"""
    st = succession(chain)
    return [{"delegate": k, **v, "current": lineage(chain, k, st)[-1]} for k, v in sorted(active_delegates(chain).items(), key=lambda x: x[1]["seq"])]


def _delegate_shape(chain, e, now, s):
    p = e["payload"]
    if not _is_hex64(p.get("god")) or not _is_hex64(p.get("delegate")) or p["god"] == p["delegate"]:
        return f"{e['type']} needs god (the current god key) and delegate (another key)"
    if e["type"] == "delegate" and p.get("scope") not in DELEGATE_SCOPES:
        return f"scope must be one of {', '.join(DELEGATE_SCOPES)}"


def _god_on_trunk(chain, e):
    if is_branch(chain):
        return "god's delegates live on the trunk only"
    if e["payload"]["god"] != current_keys(chain)["god"]:
        return "signed by a key that is not the current god key"


def _delegate_rule(chain, e, now, s):
    err = _god_on_trunk(chain, e)
    if err:
        return err
    if e["payload"]["delegate"] in active_delegates(chain):
        return "this key is already delegated"


def _undelegate_rule(chain, e, now, s):
    err = _god_on_trunk(chain, e)
    if err:
        return err
    if e["payload"]["delegate"] not in active_delegates(chain):
        return "this key is not delegated"


def link_founding_error(chain, e, now, s) -> str | None:
    """a chain_link is allowed by a delegate's pass for its child god, or by the current god's own signature"""
    p = e["payload"]
    if ("pass" in p) == ("approver" in p):
        return "a chain_link needs exactly one of a founding pass (pass) or the current god's approval (approver)"
    if "approver" in p:
        return None if p["approver"] == current_keys(chain)["god"] else "approver is not the trunk's current god key"
    err = pass_error(p["pass"], founder=p.get("child_god"), now=now)
    if err:
        return f"founding pass: {err}"
    body = p["pass"]["body"]
    st = succession(chain)
    if body["sphinx"] in st["retired"]:
        return "founding pass: signed by a key its owner has rotated away from"
    first = lineage(chain, body["sphinx"], st)[0]
    d = active_delegates(chain).get(first)
    if d is None or d["scope"] != "found_branch":
        return "founding pass: not signed by a key god delegated to found branches"
    if any(x["type"] == "chain_link" and isinstance(x["payload"].get("pass"), dict)
           and x["payload"]["pass"].get("body", {}).get("nonce") == body["nonce"] for x in chain):
        return "founding pass: already used"
    return None


LINK_CHECKS.append(link_founding_error)
register_entry_type(EntryType("delegate", fields=frozenset({"god", "delegate", "scope"}), signers=lambda p: [p.get("god")], unique_nonce=True,
                              shape=_delegate_shape, rules=(_delegate_rule,),
                              public=lambda p, c: {"god": p["god"], "delegate": p["delegate"], "scope": p.get("scope")}))
register_entry_type(EntryType("undelegate", fields=frozenset({"god", "delegate"}), signers=lambda p: [p.get("god")], unique_nonce=True,
                              shape=_delegate_shape, rules=(_undelegate_rule,),
                              public=lambda p, c: {"god": p["god"], "delegate": p["delegate"]}))
