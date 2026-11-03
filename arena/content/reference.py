"""The ledger reference a book carries (CP-9). The reference is not part of the hashed body (the entry's hash depends
on the body's hash, so the body cannot contain it): it goes on the colophon, outside the body.

    {"format": "arena-ledger-ref", "version": 1, "ledger_id", "entry", "seq", "ts", "content_hash", "form",
     "author", "recorder_url", "did"?}

`links` ([{peer, id, via?}], optional) name a permanent link at one or more link peers: where the work is kept now, which its author
may change without touching the ledger. `ledger_id`, `entry`, `content_hash`, `form`, `author` and the link never change.
`recorder_url` (and the link's `via`) are where to look today and may change (finding the recorder by ledger_id alone is CP-11, undecided). `did` is the author's existing DID if any: the
platform does not issue or check DIDs (6-K4)."""
from __future__ import annotations

import datetime
from urllib.parse import parse_qs, quote, urlsplit

FORMAT, VERSION, SCHEME = "arena-ledger-ref", 1, "arena-ref"
FIXED = ("ledger_id", "entry", "content_hash", "form", "author")


def make_reference(ledger_id: str, entry: str, seq: int, ts: float, content_hash: str, form: str, author: str,
                   recorder_url: str, did: str | None = None, links: list[dict] | None = None) -> dict:
    return {"format": FORMAT, "version": VERSION, "ledger_id": ledger_id, "entry": entry, "seq": seq, "ts": ts,
            "content_hash": content_hash, "form": form, "author": author, "recorder_url": recorder_url, **({"did": did} if did else {}),
            **({"links": [dict(x) for x in links]} if links else {})}


def to_uri(ref: dict) -> str:
    """one line for a QR code: arena-ref:<ledger_id>/<entry>?content=..&form=..&author=..&recorder=..[&did=..]"""
    q = [("content", ref["content_hash"]), ("form", ref["form"]), ("author", ref["author"]), ("recorder", ref["recorder_url"])]
    q += [("did", ref["did"])] if ref.get("did") else []
    q += [("link", f"{x['peer']}/{x['id']}" + (f"|{x['via']}" if x.get("via") else "")) for x in ref.get("links", [])]
    return f"{SCHEME}:{ref['ledger_id']}/{ref['entry']}?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in q)


def from_uri(uri: str) -> dict:
    u = urlsplit(uri)
    if u.scheme != SCHEME or "/" not in u.path:
        raise ValueError(f"not an {SCHEME}: address")
    ledger_id, entry = u.path.split("/", 1)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    missing = [k for k in ("content", "form", "author", "recorder") if k not in q]
    if missing:
        raise ValueError(f"the address lacks {', '.join(missing)}")
    links = []
    for v in parse_qs(u.query).get("link", []):
        where, _, via = v.partition("|")
        peer, _, lid = where.partition("/")
        links.append({"peer": peer, "id": lid, **({"via": via} if via else {})})
    return {"format": FORMAT, "version": VERSION, "ledger_id": ledger_id, "entry": entry, "content_hash": q["content"], "form": q["form"],
            "author": q["author"], "recorder_url": q["recorder"], **({"did": q["did"]} if "did" in q else {}), **({"links": links} if links else {})}


def colophon(ref: dict) -> str:
    """the lines for the colophon (판권면)"""
    when = datetime.datetime.fromtimestamp(ref["ts"], datetime.timezone.utc).isoformat(timespec="seconds") if "ts" in ref else "-"
    return "\n".join([
        "이 책의 본문은 에이전트 아레나 원장에 등록되어 있습니다.",
        f"원장 식별자: {ref['ledger_id']}",
        f"등록 기록: {ref['entry']}" + (f" ({ref['seq']}번, {when})" if "seq" in ref else ""),
        f"본문 해시: {ref['content_hash']} (방식 {ref['form']})",
        f"작가 공개키: {ref['author']}" + (f" / DID {ref['did']}" if ref.get("did") else ""),
        f"확인할 곳: {ref['recorder_url']}",
        *[f"영구 link: {x['peer']}/{x['id']}" + (f" (지금 주소 {x['via']})" if x.get("via") else "") for x in ref.get("links", [])],
        f"주소: {to_uri(ref)}",
    ])
