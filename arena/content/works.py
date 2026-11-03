"""Register a work (CP-9, CP-4): the author's peer hashes the body in a content form and records `publish` with
purpose `authorship`. Where the work is kept (`ref`) is optional; it goes in the public body, or in the private
envelope when the places should not spread (`hide_storage`; whether a recorder shows places publicly is CP-5, undecided).

With link peers (user 2026-11-03: "원장은 변하지 않고 물리적인 link만 변할 수 있도록"), the ref names only permanent links
({kind: link, peer, link_id}); the places live at the link peers, and the author moves them later (LinkPeers.move)
without touching the ledger (arena/content/link_peers.py)."""
from __future__ import annotations

from ..crypto import Identity
from ..ledger.envelope import with_private
from ..ledger.refs import content_hash_of, proof_target
from .link_peers import LinkPeers
from .reference import colophon, make_reference, to_uri

PROOF_HOW = "dev/protocol.md 4.7"


def ref_block(me: Identity, content_hash: str, storage: list[dict], size: int | None = None, media_type: str | None = None,
              sign: bool = True) -> dict:
    ref = {"content_hash": content_hash, "storage": list(storage), **({"size": size} if size is not None else {}),
           **({"media_type": media_type} if media_type else {})}
    ref["proof"] = {"method": "ed25519", "signer": me.pub, "sig": me.sign(proof_target(ref)), "how": PROOF_HOW} if sign else \
        {"method": "sha256", "how": PROOF_HOW}
    return ref


async def register_work(me: Identity, data: bytes, recorder, recorder_url: str, group_id: str, form: str = "utf8-nfc-lf",
                        storage: list[dict] | None = None, media_type: str | None = None, sign_storage: bool = True,
                        hide_storage: bool = False, did: str | None = None, links: LinkPeers | None = None) -> dict:
    """-> {ok, reference, uri, colophon} or the refusal. With link peers, the places go to them and the ledger names only
    the permanent links"""
    try:
        ch = content_hash_of(data, form)
    except (ValueError, UnicodeDecodeError) as e:
        return {"ok": False, "error": f"the body is not in form {form}: {e}"}
    made = None
    if links and storage:
        made = await links.create(me, ch, storage, ch)
        if not made.get("ok"):
            return {"ok": False, "error": f"link peer: {made['error']}"}
        storage = made["places"]
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
    ref = make_reference(v["ledger_id"], r["hash"], v["seq"], v["ts"], ch, form, me.pub, recorder_url, did, made["links"] if made else None)
    return {"ok": True, "reference": ref, "uri": to_uri(ref), "colophon": colophon(ref), "receipt": r}
