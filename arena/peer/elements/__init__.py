"""Built-in elements, peer side (P6-02): what a peer does for an element an event switched on. Each element registers
its basic-assistant tools (shown only for events that declared the element) and, when it needs one, a built-in app
factory (its ops). The ledger side of the same element lives in arena/ledger/elements.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PeerElement:
    name: str
    tools: tuple = ()                    # Tool objects, each with element=name
    app: Callable | None = None          # app(settings) -> a built-in app the platform assembles into every peer


PEER_ELEMENTS: dict[str, PeerElement] = {}


def register_peer_element(el: PeerElement) -> None:
    if el.name in PEER_ELEMENTS:
        raise ValueError(f"element {el.name!r} registered twice")
    PEER_ELEMENTS[el.name] = el


def element_tools() -> list:
    return [t for el in PEER_ELEMENTS.values() for t in el.tools]


from . import intake  # noqa: E402,F401  (the built-in elements register themselves)
