"""Connection methods (P6-A6): how one reaches a peer, defined in advance by the platform. A profile lists the peer's
connections; broker and peers check them against this registry. New methods are added by registration.

    human  people talk directly (chat, text). The platform only tells an owner the contact; it never sends for them.
    a2a    agents talk over A2A 1.0 (agent card + JSON-RPC, one JSON message each way).
    api    request and response over the platform's REST binding: POST {url}/ops/{op} with {"input": ...} (arena/rest.py)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionKind:
    name: str
    label: str
    fields: tuple          # required fields besides "kind"
    automatic: bool        # may code use it without a person?


CONNECTION_KINDS: dict[str, ConnectionKind] = {}


def register_connection_kind(k: ConnectionKind) -> None:
    if k.name in CONNECTION_KINDS:
        raise ValueError(f"connection method {k.name!r} registered twice")
    CONNECTION_KINDS[k.name] = k


for _k in (ConnectionKind("human", "사람끼리(채팅·문자)", ("contact",), automatic=False),
           ConnectionKind("a2a", "에이전트끼리(A2A)", ("url",), automatic=True),
           ConnectionKind("api", "요청과 응답(REST)", ("url",), automatic=True)):
    register_connection_kind(_k)


def check_connections(conns) -> str | None:
    """None when a profile's connections list only registered methods with their required fields"""
    if not isinstance(conns, list):
        return "connections must be a list"
    for c in conns:
        k = CONNECTION_KINDS.get(c.get("kind")) if isinstance(c, dict) else None
        if k is None:
            return f"unknown connection method {c.get('kind') if isinstance(c, dict) else c!r}"
        missing = [f for f in k.fields if not isinstance(c.get(f), str) or not c.get(f)]
        if missing:
            return f"connection {k.name} needs {', '.join(missing)}"
    return None


def pick(conns: list, usable=("a2a", "api")) -> dict | None:
    """the first connection code may use, in the caller's order of preference"""
    for kind in usable:
        for c in conns or []:
            if c.get("kind") == kind and CONNECTION_KINDS[kind].automatic:
                return c
    return None
