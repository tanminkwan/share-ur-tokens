"""The platform's built-in elements, ledger side (phase 6). Each is registered once; events switch them on."""
from __future__ import annotations

import numbers

from .elements import LedgerElement, register_ledger_element
from .types import assignments, events, roles_of


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
    if e["type"] != "share" or p.get("purpose") != "submission":
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
    n = sum(1 for x in chain if x["type"] == "share" and x["payload"].get("event_id") == ev and x["payload"].get("purpose") == "submission"
            and x["payload"]["provider"] == p["provider"])
    if n >= cfg["max_per_author"]:
        return f"intake: at most {cfg['max_per_author']} submissions per author"
    return None


register_ledger_element(LedgerElement("intake", _intake_cfg, (_intake_rule,)))


# ---------------- evaluation: evaluation requests and verdict records (P6-C) ----------------
def _evaluation_cfg(cfg: dict) -> str | None:
    if not set(cfg) <= {"evaluator_role", "verdict", "per_item"}:
        return "allowed keys: evaluator_role, verdict, per_item"
    if not isinstance(cfg.get("evaluator_role"), str) or not cfg["evaluator_role"]:
        return "evaluator_role must be a role"
    if not isinstance(cfg.get("verdict"), str) or not cfg["verdict"]:
        return "verdict must be a verdict kind"
    if not isinstance(cfg.get("per_item"), int) or cfg["per_item"] < 1:
        return "per_item must be at least 1"
    return None


def _handed_over(chain, ev, content_hash, consumer=None) -> list:
    return [x for x in chain if x["type"] == "share" and x["payload"].get("event_id") == ev and x["payload"].get("purpose") == "evaluation"
            and x["payload"]["content_hash"] == content_hash and (consumer is None or x["payload"]["consumer"] == consumer)]


def _evaluation_rule(chain, e, cfg, s) -> str | None:
    p = e["payload"]
    ev = p["event_id"]
    if e["type"] == "share" and p.get("purpose") == "evaluation":
        if p["provider"] != events(chain)[ev]["issuer"]:
            return "evaluation: only the event issuer hands items over"
        if cfg["evaluator_role"] not in roles_of(chain, ev, p["consumer"]):
            return f"evaluation: items go only to a contracted {cfg['evaluator_role']}"
        if len(_handed_over(chain, ev, p["content_hash"])) >= cfg["per_item"]:
            return f"evaluation: at most {cfg['per_item']} evaluators per item"
    if e["type"] == "feedback" and p.get("verdict") == cfg["verdict"] and not _handed_over(chain, ev, p["content_hash"], p["evaluator"]):
        return "evaluation: the evaluator was never handed this item in this event"
    return None


register_ledger_element(LedgerElement("evaluation", _evaluation_cfg, (_evaluation_rule,)))


# ---------------- sealed: register everything first, then open (P6-D) ----------------
def sealed_subject(chain, ev, label) -> str | None:
    """the assigned subject a label belongs to: the subject itself, or subject-<number>; None when not sealed"""
    asg = assignments(chain, ev)
    if not isinstance(label, str):
        return None
    if label in asg:
        return label
    head, _, tail = label.rpartition("-")
    return head if tail.isdigit() and head in asg else None


def _sealed_cfg(cfg: dict) -> str | None:
    return None if cfg == {} else "the sealed element takes no setting ({}): every assigned subject's labels are sealed"


def _labelled(chain, ev, kind, label) -> list:
    return [x for x in chain if x["type"] == kind and x["payload"].get("event_id") == ev and x["payload"].get("label") == label]


def _sealed_rule(chain, e, cfg, s) -> str | None:
    p = e["payload"]
    if e["type"] not in ("publish", "reveal"):
        return None
    ev, label = p["event_id"], p.get("label")
    subject = sealed_subject(chain, ev, label)
    if subject is None:
        # in a sealed event only labels of an assigned subject open; otherwise a label opened early would be found
        # already open once its subject is assigned, and the other parties could never register it
        return f"sealed: {label} is not a label of an assigned subject, so it cannot open yet" if e["type"] == "reveal" else None
    parties = assignments(chain, ev)[subject]
    if e["type"] == "publish":
        if p["author"] not in parties:
            return f"sealed: only the parties assigned to {subject} register {label}"
        if _labelled(chain, ev, "reveal", label):
            return f"sealed: {label} is already open; no new registration"
    else:
        registered = {x["payload"]["author"] for x in _labelled(chain, ev, "publish", label)}
        if not set(parties) <= registered:
            return f"sealed: {label} opens only after every party assigned to {subject} registered it ({len(registered & set(parties))}/{len(parties)})"
    return None


register_ledger_element(LedgerElement("sealed", _sealed_cfg, (_sealed_rule,)))
