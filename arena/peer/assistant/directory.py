"""Directory: who is out there, read from the broker's posted profiles (one responsibility: looking peers up)."""
from __future__ import annotations


class Directory:
    def __init__(self, group: str):
        self.group = group
        self.nicks: dict[str, str] = {}  # public key -> the nickname its owner posted (the latest profile seen); P9-C2

    async def profiles(self, ctx) -> list[dict]:
        try:
            found = (await ctx.brokers[self.group].list_profiles(identity=ctx.identity)).get("profiles", [])
        except Exception:
            return []
        for p in found:
            if p.get("nick"):
                self.nicks[p["pub"]] = p["nick"]
        return found

    async def offers_role(self, ctx, pub: str, role: str) -> bool:
        """does this peer's posted profile offer the role (a service peer takes roles it advertises, without applying)?"""
        return any(p["pub"] == pub and role in p.get("offers", []) for p in await self.profiles(ctx))

    async def offering_op(self, ctx, op: str) -> list[str]:
        """public keys of the peers whose posted profile offers the service op (P6-A5)"""
        return [p["pub"] for p in await self.profiles(ctx) if op in ((p.get("service") or {}).get("ops") or {})]
