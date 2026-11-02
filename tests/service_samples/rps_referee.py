"""A judging API peer for the with-elements comparison (P6-V3): event-specific code lives in an API peer, not in the
platform (user 2026-11-02). It reads both players' reveals for a label from the event's ledger and computes the winner."""

BEATS = {"가위": "보", "바위": "가위", "보": "바위"}


async def judge(input, ctx, request):
    url, ev, label = request["recorder_url"], request["event_id"], input["label"]
    entries = (await ctx.recorder(url).event_entries(ev)).get("entries", [])
    asg = {s: v for e in entries if e["type"] == "assign" for s, v in e.get("subjects", {}).items()}
    subject = label if label in asg else label.rpartition("-")[0]
    a, b = asg[subject]
    moves = {e["author"]: e["value"] for e in entries if e["type"] == "reveal" and e.get("label") == label}
    if a not in moves or b not in moves:
        return {"error": "both reveals are not on the ledger yet", "winner": None}
    ma, mb = moves[a], moves[b]
    winner = "" if ma == mb else a if BEATS.get(ma) == mb else b
    return {"label": label, "a": a, "b": b, "moves": {"a": ma, "b": mb}, "winner": winner}
