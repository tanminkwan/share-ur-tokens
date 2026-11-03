"""Directory: who is out there, read from the broker's posted profiles (one responsibility: looking peers up)."""
from __future__ import annotations


class Directory:
    def __init__(self, group: str):
        self.group = group

    async def profiles(self, ctx) -> list[dict]:
        try:
            return (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return []

    async def offers_role(self, ctx, pub: str, role: str) -> bool:
        """does this peer's posted profile offer the role (a service peer takes roles it advertises, without applying)?"""
        return any(p["pub"] == pub and role in p.get("offers", []) for p in await self.profiles(ctx))

    async def offering_op(self, ctx, op: str) -> list[str]:
        """public keys of the peers whose posted profile offers the service op (P6-A5)"""
        return [p["pub"] for p in await self.profiles(ctx) if op in ((p.get("service") or {}).get("ops") or {})]
