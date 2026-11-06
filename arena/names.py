"""Pen names (P9): a nickname the peer chooses + the first characters of its public key (비단길-aa11ff).
Pure rules, no I/O: what a nickname may look like, how a name is shown, and how a name typed by a person (the full name, the
nickname alone, or the nickname plus the start of the key) becomes one key. Display only: protocol messages and the ledger
carry whole public keys (dev/protocol.md 2.4)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

HEX = re.compile(r"[0-9a-f]*")


def nick_error(nick: str, max_len: int) -> str | None:
    """why this nickname is not allowed, or None (P9-A4): 1..max_len characters, no space, '-', '#', control character, http address"""
    if not isinstance(nick, str) or not nick:
        return "닉네임이 비어 있다"
    if len(nick) > max_len:
        return f"닉네임은 {max_len}자까지다({len(nick)}자)"
    if any(c.isspace() or c in "-#" or unicodedata.category(c).startswith("C") for c in nick):
        return "닉네임에는 공백, '-', '#', 제어 문자를 쓸 수 없다"
    if nick.lower().startswith(("http", "mem:")):
        return "닉네임은 주소처럼 시작할 수 없다"
    return None


def display(pub: str, nick: str, n: int) -> str:
    """the pen name shown for a key: nickname-first n characters of the key"""
    return f"{nick}-{pub[:n]}"


@dataclass
class Match:
    pub: str | None = None
    error: str | None = None
    candidates: list = field(default_factory=list)  # (pub, nick) pairs still possible when the name was not enough


def resolve(ref: str, known: list[tuple[str, str]], n: int) -> Match:
    """known: (public key, nickname) pairs. `비단길-aa11ff` -> that key; `비단길` -> the only peer with that nickname;
    `비단길-aa` -> the only one whose key starts so. Several left -> nothing is chosen, the candidates are named (P9-B1..B4).
    Nicknames are compared without regard to case; keys are lower-case hex."""
    ref = (ref or "").strip()
    nick, _, start = ref.partition("-")
    start = start.lower()
    if not nick or not HEX.fullmatch(start):
        return Match(error=f"{ref}를 찾지 못했다")
    hits = [(p, k) for p, k in known if k.casefold() == nick.casefold() and p.startswith(start)]
    if not hits:
        return Match(error=f"{ref}를 찾지 못했다")
    if len(hits) == 1:
        return Match(pub=hits[0][0])
    names = ", ".join(display(p, k, n) for p, k in hits)
    return Match(error=f"{ref}는 여럿이다: {names} (키 앞부분을 더 써 달라)", candidates=hits)
