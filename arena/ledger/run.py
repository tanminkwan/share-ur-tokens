"""The run block of an event declaration (how it runs, which apps): part of what the ledger notarizes, so it lives with
the ledger. The peer layer re-exports these (arena.peer.plugin) for apps."""
from __future__ import annotations

import uuid

MODES = ("assistant", "app", "app_or_assistant")
ASSISTANT_RUN = {"mode": "assistant", "apps": []}  # the primordial way: no app, the basic assistant reads the rules


def is_uuid(x) -> bool:
    try:
        return str(uuid.UUID(str(x))) == str(x).lower()
    except ValueError:
        return False


def version_parts(text: str) -> tuple:
    return tuple(int(p) for p in str(text).split(".") if p.isdigit())


def version_ok(installed: str, required: str) -> bool:
    """same major version, and at least the required one"""
    a, b = version_parts(installed), version_parts(required)
    return bool(a) and bool(b) and a[0] == b[0] and a >= b


def valid_app_ref(ref) -> bool:
    return (isinstance(ref, dict) and is_uuid(ref.get("id")) and bool(version_parts(ref.get("version", "")))
            and set(ref) <= {"id", "name", "version", "hash", "required"} and isinstance(ref.get("required", True), bool))


def valid_run(mode, apps) -> bool:
    """the execution block (mode) and the app list block (apps) of an event"""
    if mode not in MODES or not isinstance(apps, list) or not all(valid_app_ref(r) for r in apps):
        return False
    if len({r["id"] for r in apps}) != len(apps):
        return False
    return mode == "assistant" or bool(apps)
