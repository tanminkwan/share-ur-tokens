"""Register a work (CP-9, CP-4): the author's peer hashes the body in a content form and records `publish` with
purpose `authorship`. Where the work is kept (`ref`) is optional; it goes in the public body, or in the private
envelope when the places should not spread (`hide_storage`; whether a recorder shows places publicly is CP-5, undecided).

With a link peer (user 2026-11-03: "원장은 변하지 않고 물리적인 link만 변할 수 있도록"), the ref names only a permanent
link (<link peer>/<link id>); the places live at the link peer, and the author changes them later (relink) without
touching the ledger. `Ask` is one message to a link peer (its api or a2a binding)."""
from __future__ import annotations

import time
from typing import Awaitable, Callable

from ..crypto import Identity
from ..ledger.envelope import with_private
from ..ledger.refs import content_hash_of, proof_target
from .links import KeyOf, link_id, make_link, verify_link
from .reference import colophon, make_reference, to_uri

Ask = Callable[[dict], Awaitable[dict]]

PROOF_HOW = "dev/protocol.md 4.7"


def ref_block(me: Identity, content_hash: str, storage: list[dict], size: int | None = None, media_type: str | None = None,
              sign: bool = True) -> dict:
    ref = {"content_hash": content_hash, "storage": list(storage), **({"size": size} if size is not None else {}),
           **({"media_type": media_type} if media_type else {})}
    ref["proof"] = {"method": "ed25519", "signer": me.pub, "sig": me.sign(proof_target(ref)), "how": PROOF_HOW} if sign else \
        {"method": "sha256", "how": PROOF_HOW}
    return ref


async def set_link(me: Identity, ask: Ask, owner: str, name: str, targets: list[dict], content_hash: str | None = None,
                   now: float | None = None) -> dict:
    """a new version of a link at a link peer (the first, or the last + 1), signed by me"""
    cur = await ask({"op": "link.get", "id": link_id(owner, name)})
    ver = cur["link"]["ver"] + 1 if cur.get("ok") else 1
    rec = make_link(me, owner, name, ver, targets, time.time() if now is None else now, content_hash)
    r = await ask({"op": "link.set", "link": rec})
    return dict(r, link=rec) if r.get("ok") else r


async def relink(me: Identity, ask: Ask, the_link_id: str, targets: list[dict], settings, now: float | None = None) -> dict:
    """the author moves the work: the link keeps its id, owner and content hash; only where it points changes"""
    cur = await ask({"op": "link.get", "id": the_link_id})
    if not cur.get("ok"):
        return cur
    bad = await verify_link(cur["link"], settings)
    if bad and "signed by its owner" not in bad:
        return {"ok": False, "error": f"the link peer's copy does not check: {bad}"}
    c = cur["link"]
    return await set_link(me, ask, c["owner"], c["name"], targets, c.get("content_hash"), now)


async def resolve_link(ask: Ask, the_link_id: str, settings, expected_owner: str | None = None, key_of: KeyOf | None = None) -> dict:
    """where the work is now: the newest version, checked against its owner's signature (a link peer cannot forge it)"""
    cur = await ask({"op": "link.get", "id": the_link_id})
    if not cur.get("ok"):
        return cur
    bad = await verify_link(cur["link"], settings, expected_owner, key_of)
    if bad:
        return {"ok": False, "error": f"the link does not check: {bad}"}
    c = cur["link"]
    return {"ok": True, "targets": c["targets"], "ver": c["ver"], "owner": c["owner"], "signer": c["signer"], "ts": c["ts"]}


async def register_work(me: Identity, data: bytes, recorder, recorder_url: str, group_id: str, form: str = "utf8-nfc-lf",
                        storage: list[dict] | None = None, media_type: str | None = None, sign_storage: bool = True,
                        hide_storage: bool = False, did: str | None = None, link_ask: Ask | None = None, link_via: str | None = None) -> dict:
    """-> {ok, reference, uri, colophon} or the refusal. With link_ask, the places go to that link peer and the ledger
    names only the permanent link"""
    try:
        ch = content_hash_of(data, form)
    except (ValueError, UnicodeDecodeError) as e:
        return {"ok": False, "error": f"the body is not in form {form}: {e}"}
    link = None
    if link_ask and storage:
        info = await link_ask({"op": "link.info"})
        if not info.get("ok"):
            return {"ok": False, "error": f"link peer: {info.get('error')}"}
        made = await set_link(me, link_ask, me.pub, ch, storage, ch)
        if not made.get("ok"):
            return {"ok": False, "error": f"link peer: {made.get('error')}"}
        link = {"peer": info["pub"], "id": made["id"], **({"via": link_via} if link_via else {})}
        storage = [{"kind": "link", "peer": info["pub"], "link_id": made["id"], **({"via": link_via} if link_via else {})}]
    t = await recorder.trust()
    lid = t.get("ledger_id") if t.get("ok") else None
    p = {"author": me.pub, "content_hash": ch, "purpose": "authorship", "form": form, "group_id": group_id, **({"ledger_id": lid} if lid else {})}
    private = None
    if storage:
        ref = ref_block(me, ch, storage, len(data), media_type, sign_storage)
        if hide_storage:
            private, p = {"ref": ref}, with_private(p, {"ref": ref})
        else:
            p["ref"] = ref
    r = await recorder.record("publish", p, {me.pub: me.sign(p)}, private)
    if not r.get("ok"):
        return r
    v = await recorder.verify(r["hash"])
    ref = make_reference(v["ledger_id"], r["hash"], v["seq"], v["ts"], ch, form, me.pub, recorder_url, did, link)
    return {"ok": True, "reference": ref, "uri": to_uri(ref), "colophon": colophon(ref), "receipt": r}
