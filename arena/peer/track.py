"""Track records across recorders, and a mechanical check against a requirement (e.g. before a role contract)."""
from __future__ import annotations

NUMBERS = ("published", "received_by", "events", "approvals", "closed", "groups")
MAPS = ("verdicts_received", "verdicts_given", "roles", "attested")


def empty_track() -> dict:
    return {**{k: 0 for k in NUMBERS}, **{k: {} for k in MAPS}}


def add_tracks(a: dict, b: dict) -> dict:
    out = empty_track()
    for k in NUMBERS:
        out[k] = a.get(k, 0) + b.get(k, 0)
    for k in MAPS:
        for src in (a.get(k, {}), b.get(k, {})):
            for name, n in src.items():
                out[k][name] = out[k].get(name, 0) + n
    return out


async def track_of(peer, pub: str, recorder_urls) -> dict:
    """sum of the public track records of `pub` on each recorder; `sources` says which answered, `by_source` keeps each"""
    total, sources, by_source = empty_track(), {}, {}
    for url in recorder_urls:
        try:
            r = await peer.recorder(url).track(pub)
            if not r.get("ok"):
                raise RuntimeError(r.get("error", "no track"))
            by_source[url] = r["track"]
            total = add_tracks(total, r["track"])
            sources[url] = "ok"
        except Exception as e:
            sources[url] = f"{type(e).__name__}: {e}"
    return dict(total, sources=sources, by_source=by_source)


def meets(track: dict, need: dict) -> tuple[bool, list[str]]:
    """need: {"roles": {"judge": 1}, "approvals": 1, ...} -> (ok, ["roles.judge 0/1", ...])"""
    missing = []
    for k, want in need.items():
        if isinstance(want, dict):
            for name, n in want.items():
                have = track.get(k, {}).get(name, 0)
                if have < n:
                    missing.append(f"{k}.{name} {have}/{n}")
        elif track.get(k, 0) < want:
            missing.append(f"{k} {track.get(k, 0)}/{want}")
    return (not missing, missing)
