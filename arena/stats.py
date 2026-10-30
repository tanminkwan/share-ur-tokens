"""Generic ledger statistics for spectators. No verdict or role name has a meaning here; they are only counted."""
from __future__ import annotations

from collections import Counter, defaultdict

from .ledger import contribution


def ledger_stats(chain: list[dict], top_flows: int) -> dict:
    types = Counter(e["type"] for e in chain)
    verdicts: dict = {}
    sums: dict = defaultdict(lambda: defaultdict(list))
    for e in chain:
        if e["type"] != "feedback":
            continue
        p = e["payload"]
        v = verdicts.setdefault(p.get("verdict"), {"count": 0})
        v["count"] += 1
        for k, x in p.items():
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                sums[p.get("verdict")][k].append(x)
    for name, v in verdicts.items():
        v["avg"] = {k: round(sum(xs) / len(xs), 2) for k, xs in sums[name].items()}
    flows = Counter((e["payload"]["provider"], e["payload"]["consumer"]) for e in chain if e["type"] == "share")
    return {
        "entries": len(chain), "by_type": dict(types),
        "signers": len({pub for e in chain for pub in e["sigs"]}),
        "events": [{"event_id": e["payload"]["event_id"], "kind": e["payload"].get("kind"), "issuer": e["payload"]["issuer"],
                    "approvers": list(e["payload"].get("approvers", []))} for e in chain if e["type"] == "event"],
        "verdicts": verdicts,
        "roles": dict(Counter(e["payload"]["role"] for e in chain if e["type"] == "contract")),
        "top_flows": [{"from": a, "to": b, "n": n} for (a, b), n in flows.most_common(top_flows)],
        "span_sec": round(chain[-1]["ts"] - chain[0]["ts"], 1) if chain else 0,
    }


def per_peer(chain: list[dict], profiles: list[dict], pen) -> list[dict]:
    """strengths = what the profile says (self-described); track record = what the ledger proves, joined by public key"""
    contrib = contribution(chain)
    prof = {p["pub"]: p for p in profiles}
    empty = {"published": 0, "received_by": 0, "verdicts_received": {}, "verdicts_given": {}, "roles": {}, "events": 0, "approvals": 0}
    out = []
    for pub in sorted(set(prof) | set(contrib)):
        p = prof.get(pub, {})
        out.append(dict(pub=pub, who=pen(pub), group=p.get("group"), strengths=p.get("summary"), ver=p.get("ver"),
                        offers=p.get("offers", []), labels=p.get("labels", []), **contrib.get(pub, empty)))
    return sorted(out, key=lambda x: (-sum(x["verdicts_received"].values()), -x["received_by"], -sum(x["roles"].values()), x["pub"]))
