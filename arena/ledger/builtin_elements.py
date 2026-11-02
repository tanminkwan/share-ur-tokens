"""The platform's built-in elements, ledger side (phase 6). Each is registered once; events switch them on."""
from __future__ import annotations

import numbers

from .elements import LedgerElement, register_ledger_element
from .types import events, roles_of


# ---------------- intake: accepting submissions (P6-B) ----------------
def _intake_cfg(cfg: dict) -> str | None:
    if not set(cfg) <= {"deadline", "max_per_author", "receiver", "audience"}:
        return "allowed keys: deadline, max_per_author, receiver, audience"
    if "deadline" in cfg and not isinstance(cfg["deadline"], numbers.Real):
        return "deadline must be a time in seconds"
    if not isinstance(cfg.get("max_per_author"), int) or cfg["max_per_author"] < 1:
        return "max_per_author must be at least 1"
    if not isinstance(cfg.get("receiver"), str) or not cfg["receiver"]:
        return "receiver must be 'issuer' or a role"
    if "audience" in cfg and (not isinstance(cfg["audience"], list) or not all(isinstance(x, str) for x in cfg["audience"])):
        return "audience must be a list of labels"
    return None


def _intake_rule(chain, e, cfg, s) -> str | None:
    p = e["payload"]
    if e["type"] != "share" or p.get("terms") != "submission":
        return None
    ev = p["event_id"]
    decl = events(chain)[ev]
    receiver = cfg["receiver"]
    if (receiver == "issuer" and p["consumer"] != decl["issuer"]) or (receiver != "issuer" and receiver not in roles_of(chain, ev, p["consumer"])):
        return f"intake: the receiver of submissions is {receiver}"
    if "deadline" in cfg and e["ts"] > cfg["deadline"]:
        return "intake: after the deadline"
    if set(decl.get("policy", {}).get("conflict_roles", [])) & roles_of(chain, ev, p["provider"]):
        return "intake: a contractor in a conflicting role cannot submit"
    n = sum(1 for x in chain if x["type"] == "share" and x["payload"].get("event_id") == ev and x["payload"].get("terms") == "submission"
            and x["payload"]["provider"] == p["provider"])
    if n >= cfg["max_per_author"]:
        return f"intake: at most {cfg['max_per_author']} submissions per author"
    return None


register_ledger_element(LedgerElement("intake", _intake_cfg, (_intake_rule,)))
