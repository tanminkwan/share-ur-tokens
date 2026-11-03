"""The built-in code table (user 2026-11-02): the basics defined in advance so the ecosystem is sturdy. Not binding: an
event or profile may say it follows an edition (by its ledger entry), and an edition gains standing by being followed.
The foundation peer (arena/peer/foundation_role.py) publishes this document as an edition; anyone may publish another."""
from __future__ import annotations

from .connections import CONNECTION_KINDS
from .crypto import canon, h
from .ledger.codebook import implemented_codes
from .ledger.purposes import PURPOSES
from .ledger.refs import CONTENT_FORMS, PROOF_METHODS, STORAGE_KINDS
from .ledger.schedule import TIME_CODES

NAME, VERSION = "agent-arena", "1.0"


def builtin_document(name: str = NAME, version: str = VERSION) -> dict:
    """the code table this software implements, with the meaning of each code (what an edition's content_hash covers)"""
    codes = {**implemented_codes(), "connections": sorted(CONNECTION_KINDS)}
    return {"name": name, "version": version, "codes": codes,
            "meanings": {"purposes": {c: {"types": list(p.types), "description": p.description} for c, p in sorted(PURPOSES.items())},
                         "time_codes": {c: {"description": t.description} for c, t in sorted(TIME_CODES.items())},
                         "connections": {k: {"label": c.label, "fields": list(c.fields), "automatic": c.automatic}
                                         for k, c in sorted(CONNECTION_KINDS.items())},
                         **{kind: {c: {"description": x.description} for c, x in sorted(table.items())}
                            for kind, table in (("storage_kinds", STORAGE_KINDS), ("proof_methods", PROOF_METHODS),
                                                ("content_forms", CONTENT_FORMS))}}}


def document_hash(doc: dict) -> str:
    return h(canon(doc))
