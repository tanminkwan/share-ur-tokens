"""Directory: who is out there, read from the broker's posted profiles (one responsibility: looking peers up)."""
from __future__ import annotations


class Directory:
    def __init__(self, group: str):
        self.group = group
        self.nicks: dict[str, str] = {}  # public key -> the nickname its owner posted (the latest profile seen); P9-C2
        self.read_at = float("-inf")  # when the broker's list was last read

    async def profiles(self, ctx) -> list[dict]:
        try:
            found = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return []
        for p in found:
            if p.get("nick"):
                self.nicks[p["pub"]] = p["nick"]
        self.read_at = ctx.clock()
        return found

    async def refresh(self, ctx) -> None:
        """before a person is shown who spoke: read the broker's list again unless it was read a moment ago, so a nickname the
        speaker has just changed shows at once (P9-A7)"""
        if ctx.clock() - self.read_at >= ctx.settings.nick_refresh_sec:
            await self.profiles(ctx)

    async def offers_role(self, ctx, pub: str, role: str) -> bool:
        """does this peer's posted profile offer the role (a service peer takes roles it advertises, without applying)?"""
        return any(p["pub"] == pub and role in p.get("offers", []) for p in await self.profiles(ctx))

    async def offering_op(self, ctx, op: str) -> list[str]:
        """public keys of the peers whose posted profile offers the service op (P6-A5)"""
        return [p["pub"] for p in await self.profiles(ctx) if op in ((p.get("service") or {}).get("ops") or {})]
