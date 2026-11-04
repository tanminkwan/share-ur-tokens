"""GroupModes: does a broker group of mine keep a ledger? (P6-N1..N3). One responsibility: reading a group's declaration
from its broker and checking it, by code.

- the genesis group has its ledger from the beginning
- a declaration signed by the founder the broker names: `ledger: null` = a group without a ledger; an attached ledger is
  checked (the recorder is proven, the ledger id matches, `entry` is that founder's `group` entry for this group)
- no declaration, or one that does not check out: a ledger group, as before (the stricter way: every notice must then be
  declared on a ledger)"""
from __future__ import annotations

from typing import Awaitable, Callable

from ..crypto import verify
from ..groups.decl import declaration_error


def ledger_mode(why: str, declaration: dict | None = None, ledger: dict | None = None, proven: bool = False) -> dict:
    return {"ledger": True, "why": why, "declaration": declaration, "attached": ledger, "proven": proven}


def no_ledger_mode(declaration: dict) -> dict:
    return {"ledger": False, "why": "the founder declared this group without a ledger", "declaration": declaration, "attached": None,
            "proven": False}


class GroupModes:
    def __init__(self, brokers, group_id: Callable[[str], Awaitable[str]], recorder, recorder_trust, ledger_id,
                 settings: Callable, clock: Callable[[], float]):
        self.brokers, self.group_id, self.recorder, self.recorder_trust, self.ledger_id = brokers, group_id, recorder, recorder_trust, ledger_id
        self.settings, self.clock = settings, clock
        self.cache: dict[str, tuple[float, dict]] = {}

    async def mode(self, group: str, fresh: bool = False) -> dict:
        """{ledger, why, declaration, attached, proven}, remembered for ARENA_GROUP_MODE_TTL_SEC"""
        hit = self.cache.get(group)
        if hit and not fresh and self.clock() - hit[0] < self.settings().group_mode_ttl_sec:
            return hit[1]
        out = await self._read(group)
        self.cache[group] = (self.clock(), out)
        return out

    async def _read(self, group: str) -> dict:
        try:
            info = await self.brokers[group].group()
        except Exception as e:
            return ledger_mode(f"the broker did not say ({type(e).__name__})")
        if info.get("genesis"):
            return ledger_mode("the genesis group keeps the ledger from the beginning")
        decl, sig = info.get("declaration"), info.get("sig")
        if decl is None:
            return ledger_mode("no declaration at the broker: events say their own ledger")
        gid = await self.group_id(group)
        if declaration_error(decl) or decl["group_id"] != gid or decl["founder"] != info.get("founder") or not verify(decl["founder"], decl, sig or ""):
            return ledger_mode("the declaration at the broker does not check out (not the founder's, or another group's)")
        if decl["ledger"] is None:
            return no_ledger_mode(decl)
        why = await self._attached_error(decl)
        return ledger_mode(why or "a ledger is attached and proven", decl, decl["ledger"], proven=why is None)

    async def _attached_error(self, decl: dict) -> str | None:
        """the attached ledger is real: a proven recorder, that ledger, and the founder's `group` entry for this group"""
        at = decl["ledger"]
        try:
            trust = await self.recorder_trust(at["recorder_url"])
            if not trust.get("ok") or (trust.get("anchored") and trust.get("recorder") != at["recorder"]):
                return "the attached ledger's recorder is not proven by my root of trust"
            if await self.ledger_id(at["recorder_url"]) != at["ledger_id"]:
                return "the recorder keeps another ledger than the declaration names"
            v = await self.recorder(at["recorder_url"]).verify(at["entry"])
        except Exception as e:
            return f"the attached ledger did not answer ({type(e).__name__})"
        if not (v.get("exists") and v.get("type") == "group" and v.get("group_id") == decl["group_id"] and v.get("founder") == decl["founder"]):
            return "the attached ledger has no group entry of this founder for this group"
        return None
