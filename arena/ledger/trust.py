"""Proving the real ledger (P5-G): the root of trust is published outside the ledger (genesis hash, god's first key);
from it, key succession (key_rotate) proves every later recorder and god key. A recorder's trust document (GET /trust)
holds the genesis entry and every key_rotate entry, enough to check the current keys without the whole chain."""
from __future__ import annotations

from ..crypto import canon, h, verify
from .envelope import BODY, hash_body
from .rules import signers
from .types import branch_point_error, current_keys


def _entry_ok(e: dict, sealer: str) -> str | None:
    if e.get("hash") != h(canon(hash_body(e))):
        return "hash"
    if any(not s or not verify(s, e["payload"], e["sigs"].get(s, "")) for s in signers(e)):
        return "signature"
    if e.get("seal", {}).get("pub") != sealer or not verify(sealer, e["hash"], e["seal"]["sig"]):
        return "recorder seal"
    return None


def verify_trust(doc: dict, genesis_hash: str, god_pub: str) -> tuple[bool, str, dict]:
    """(ok, why, current keys {recorder, god}) for a recorder's trust document, from the root of trust"""
    g = (doc or {}).get("genesis")
    if not g or g.get("type") != "genesis" or g.get("hash") != genesis_hash or g["payload"].get("god") != god_pub:
        return False, "root of trust: genesis hash or god key differs", {}
    bad = _entry_ok(g, g["payload"]["recorder"])
    if bad:
        return False, f"genesis entry: {bad}", {}
    chain = [g]
    for e in sorted(doc.get("rotations", []), key=lambda x: x.get("seq", 0)):
        keys = current_keys(chain)
        p = e.get("payload", {})
        if e.get("type") != "key_rotate" or p.get("old") != keys.get(p.get("role")) or \
                (p.get("role") == "recorder" and p.get("god") != keys["god"]) or p.get("ledger_id") != genesis_hash:
            return False, f"key succession broken at seq {e.get('seq')}", {}
        bad = _entry_ok(e, keys["recorder"])  # a rotation is sealed by the recorder key valid before it
        if bad:
            return False, f"key_rotate at seq {e.get('seq')}: {bad}", {}
        chain.append(e)
    keys = current_keys(chain)
    if doc.get("recorder") and doc["recorder"] != keys["recorder"]:
        return False, "the recorder's key is not the one key succession proves", {}
    return True, "", keys


def keys_at(doc: dict, seq: int) -> dict:
    """the recorder and god keys valid at position seq of the chain a trust document describes"""
    chain = [doc["genesis"]] + [e for e in sorted(doc.get("rotations", []), key=lambda x: x["seq"]) if e["seq"] < seq]
    return current_keys(chain)


def verify_link_entry(link: dict, parent_doc: dict, child_genesis: dict) -> str | None:
    """None when `link` (in the parent chain) links exactly this child genesis, signed with the child's god and recorder
    private keys, sealed by the parent's recorder key valid at that point, naming the parent ledger, and both sides name
    the same branch point and the parent recorder key valid there (CP-1)"""
    if not link or link.get("type") != "chain_link":
        return "no chain_link entry"
    p, g = link["payload"], child_genesis["payload"]
    if p.get("child_ledger_id") != child_genesis["hash"] or p.get("child_god") != g["god"] or p.get("child_recorder") != g["recorder"]:
        return "the link names another chain or other keys"
    par = g.get("parent", {})
    if p.get("ledger_id") != parent_doc["ledger_id"] or par.get("ledger_id") != parent_doc["ledger_id"]:
        return "the link and the new genesis do not name the same parent ledger"
    bp = par.get("branch_point")
    if branch_point_error(bp) or p.get("branch_point") != bp:
        return "the link and the new genesis do not name the same branch point"
    if not bp["seq"] < link.get("seq", -1):
        return "the link was recorded before its branch point"
    if par.get("recorder") != keys_at(parent_doc, bp["seq"] + 1)["recorder"]:
        return "the new genesis names a parent recorder key that was not valid at the branch point"
    bad = _entry_ok(link, keys_at(parent_doc, link["seq"])["recorder"])
    return f"chain_link: {bad}" if bad else None


def verify_parent_link(child_doc: dict, link: dict) -> str | None:
    """None when the branch's entry 1 is its parent_link holding exactly this chain_link, signed by the branch's god and
    sealed by its recorder key then (CP-2)"""
    e = (child_doc or {}).get("parent_link")
    if not e or e.get("type") != "parent_link" or e.get("seq") != 1:
        return "the branch chain's entry 1 is not its parent_link"
    if e["payload"].get("link", {}).get("hash") != link.get("hash"):
        return "the branch's parent_link holds another chain_link"
    bad = _entry_ok(e, keys_at(child_doc, 1)["recorder"])
    return f"parent_link: {bad}" if bad else None


def verify_linked(child_doc: dict, parent_doc: dict, link: dict, genesis_hash: str, god_pub: str) -> tuple[bool, str, dict]:
    """a community chain proven from the original chain's root of trust (one link). Returns the child's current keys"""
    ok, why, _ = verify_trust(parent_doc, genesis_hash, god_pub)
    if not ok:
        return False, f"parent: {why}", {}
    g = (child_doc or {}).get("genesis")
    if not g:
        return False, "no genesis in the child's trust document", {}
    bad = verify_link_entry(link, parent_doc, g) or verify_parent_link(child_doc, link)
    if bad:
        return False, bad, {}
    return verify_trust(child_doc, g["hash"], g["payload"]["god"])


def branch_parent(parent_doc: dict, parent_url: str) -> dict:
    """the `parent` block of a branch's genesis, from the trunk's trust document: where it came from (CP-1)"""
    if "parent" in parent_doc["genesis"]["payload"]:
        raise ValueError("only the trunk (the root chain) takes branch links; a branch chain cannot start a branch")
    return {"ledger_id": parent_doc["ledger_id"], "recorder_url": parent_url, "recorder": current_keys_of(parent_doc)["recorder"],
            "branch_point": dict(parent_doc["head"])}


def current_keys_of(doc: dict) -> dict:
    return keys_at(doc, doc["head"]["seq"] + 1)


async def link_to_parent(parent, god, recorder_identity, chain: list[dict], name: str) -> dict:
    """the new community's god and first recorder sign a chain_link into the parent chain (P5-G9), repeating the branch
    point their genesis names (CP-1)"""
    pt = await parent.trust()
    if not pt.get("ok"):
        return {"ok": False, "error": f"parent recorder: {pt.get('error')}"}
    if "parent" in pt["genesis"]["payload"]:
        return {"ok": False, "error": "only the trunk (the root chain) takes branch links; a branch chain cannot start a branch"}
    g = chain[0]
    p = {"child_ledger_id": g["hash"], "child_god": god.pub, "child_recorder": recorder_identity.pub, "name": name,
         "branch_point": (g["payload"].get("parent") or {}).get("branch_point"),
         "group_id": pt["genesis"]["payload"]["group_id"], "ledger_id": pt["ledger_id"], "nonce": g["hash"][:16]}
    return await parent.record("chain_link", p, {god.pub: god.sign(p), recorder_identity.pub: recorder_identity.sign(p)})


async def record_parent_link(recorder, god, chain: list[dict], link: dict) -> dict:
    """entry 1 of a branch chain: the chain_link the trunk sealed (CP-2). Before it the branch takes nothing else"""
    g = chain[0]
    p = {"group_id": g["payload"]["group_id"], "ledger_id": g["hash"], "god": god.pub, "link": link}
    return await recorder.record("parent_link", p, {god.pub: god.sign(p)})


def anchor_block(chain: list[dict]) -> str:
    """the root values a community publishes outside its ledger (the reference network: in the white paper)"""
    g = chain[0]
    return "\n".join([
        "# 뿌리 신뢰 값 (원장 밖에 공개)",
        f"- 제네시스 해시(원장 식별자): `{g['hash']}`",
        f"- god 첫 공개키: `{g['payload']['god']}`",
        f"- 첫 기록자 공개키: `{g['payload']['recorder']}`",
        f"- 만민 그룹: `{g['payload']['group_id']}`",
        *([f"- 연결된 원래 체인: `{g['payload']['parent']['ledger_id']}` (기록자 `{g['payload']['parent']['recorder_url']}`), "
            f"갈라진 지점: {g['payload']['parent']['branch_point']['seq']}번 기록 `{g['payload']['parent']['branch_point']['hash']}`"]
          if "parent" in g["payload"] else ["- 원래 체인(뿌리): 이 제네시스가 뿌리다"]),
        "",
        "peer 설정(.env):",
        "```",
        f"ARENA_TRUST_GENESIS_HASH={g['hash']}",
        f"ARENA_TRUST_GOD_PUB={g['payload']['god']}",
        "```",
        ""])
