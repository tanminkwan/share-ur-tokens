"""Handles: what the LLM sees instead of 64-hex values (public keys -> 필명-xxxxxx, other hashes -> #short refs), and the
way back, done by code (P5-C25, C37). One responsibility: naming."""
from __future__ import annotations

import re

from ...crypto import pen_name
from .directory import Directory

HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


class Handles:
    def __init__(self, settings, directory: Directory):
        self.s, self.directory = settings, directory

    def known_pubs(self, ctx, st) -> set:
        pubs = {ctx.pub, st.issuer_pub, *st.peers, *(c[1] for c in st.contracts), *st.roster}
        for req in st.pending.values():
            pubs |= set(req["payload"].get("parties", []))
        return pubs

    def handle(self, ctx, st, pub: str) -> str:
        name = pen_name(pub, ctx.settings.pen_name_prefix, ctx.settings.pen_name_len)
        st.aliases[name] = pub
        return name

    def shorten(self, ctx, st, text: str) -> str:
        """public keys become 필명-xxxxxx, other 64-hex values become #xxxxxxxxxx; the code remembers what they stand for"""
        pubs = self.known_pubs(ctx, st)

        def one(m):
            full = m.group(0)
            if full in pubs:
                return self.handle(ctx, st, full)
            ref = "#" + full[:self.s.assistant_ref_len]
            st.aliases[ref] = full
            return ref
        return HEX64.sub(one, text)

    def expand(self, st, obj):
        """the reverse, on what the LLM hands to a tool: exact handles and short refs become the real values"""
        if isinstance(obj, str):
            return st.aliases.get(obj.strip(), obj)
        if isinstance(obj, list):
            return [self.expand(st, x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.expand(st, v) for k, v in obj.items()}
        return obj

    async def resolve_peer(self, ctx, st, ref: str, need_url: bool = True) -> tuple[str | None, str | None]:
        """a peer named by handle, public key or address -> (public key, address); unknown handles are looked up on the broker"""
        ref = self.expand(st, str(ref))
        if ref in (ctx.pub, ctx.pen):
            return ctx.pub, ctx.url
        if ref.startswith(("http://", "https://", "mem://")):
            return next((p for p, u in st.peers.items() if u == ref), None), ref
        pub = ref if HEX64.fullmatch(ref) else None
        if pub and (pub in st.peers or not need_url):
            return pub, st.peers.get(pub)
        for p in await self.directory.profiles(ctx):
            if p["pub"] == pub or pen_name(p["pub"], ctx.settings.pen_name_prefix, ctx.settings.pen_name_len) == ref:
                st.peers.setdefault(p["pub"], p.get("url"))
                return p["pub"], st.peers[p["pub"]]
        return pub, None

    async def check_handles(self, ctx, st, obj):
        """a whole string that looks like a handle but names nobody known (event, broker) is refused; known ones become keys"""
        pre, n = ctx.settings.pen_name_prefix, ctx.settings.pen_name_len
        bad = []

        async def one(x):
            if isinstance(x, dict):
                return {k: await one(v) for k, v in x.items()}
            if isinstance(x, list):
                return [await one(v) for v in x]
            if isinstance(x, str) and x.strip().startswith(pre) and len(x.strip()) == len(pre) + n:
                pub, _ = await self.resolve_peer(ctx, st, x.strip(), need_url=False)
                if not pub:
                    bad.append(x.strip())
                    return x
                return pub
            return x
        return await one(obj), bad

    async def learn_keys(self, ctx, st, text: str, ledger) -> None:
        """64-hex values in an input that may be public keys I do not know yet: look them up in the event's ledger and on
        the broker, so the LLM sees one name (the handle) for one person from the start"""
        unknown = set(HEX64.findall(text)) - self.known_pubs(ctx, st) - set(st.aliases.values())
        if not unknown:
            return
        await ledger.progress_entries(ctx, st)  # adds everyone named in this event's ledger to the roster
        unknown -= set(st.roster)
        if not unknown:
            return
        for p in await self.directory.profiles(ctx):
            if p["pub"] in unknown:
                st.roster.append(p["pub"])
                st.peers.setdefault(p["pub"], p.get("url"))
