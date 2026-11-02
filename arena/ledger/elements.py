"""Built-in elements, ledger side (P6-01, P6-02). An event switches elements on in the `elements` block of its declaration
({name: setting}); the ledger accepts only registered names with a valid setting, and adds each declared element's rules
to the entries that point at that event. The peer side of an element (its ops and assistant tools) is registered under
the same name in arena/peer/elements; the ledger never imports the peer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

ConfigCheck = Callable[[dict], "str | None"]           # setting -> why it is not valid, or None
ElementRule = Callable[[list, dict, dict, object], "str | None"]  # (chain, entry, setting, settings) -> why refused, or None


@dataclass(frozen=True)
class LedgerElement:
    name: str
    check_config: ConfigCheck
    rules: tuple = ()


LEDGER_ELEMENTS: dict[str, LedgerElement] = {}


def register_ledger_element(el: LedgerElement) -> None:
    if el.name in LEDGER_ELEMENTS:
        raise ValueError(f"element {el.name!r} registered twice")
    LEDGER_ELEMENTS[el.name] = el


def check_elements(elements) -> str | None:
    """None when an event's elements block is acceptable"""
    if not isinstance(elements, dict):
        return "elements must map element names to settings"
    for name, cfg in elements.items():
        el = LEDGER_ELEMENTS.get(name)
        if el is None:
            return f"unknown element {name!r}"
        if not isinstance(cfg, dict):
            return f"element {name!r}: setting must be an object"
        bad = el.check_config(cfg)
        if bad:
            return f"element {name!r}: {bad}"
    return None


def element_rules(chain, e, decl: dict, settings) -> str | None:
    """the rules of every element the entry's event declared"""
    for name, cfg in (decl.get("elements") or {}).items():
        el = LEDGER_ELEMENTS.get(name)
        for rule in el.rules if el else ():
            err = rule(chain, e, cfg, settings)
            if err:
                return err
    return None
