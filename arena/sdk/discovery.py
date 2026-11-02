"""Find apps installed as Python packages through the entry point group "arena.apps"."""
from __future__ import annotations

from importlib.metadata import entry_points

from ..config import ConfigError
from ..peer.plugin import App, capabilities_of

ENTRY_POINT_GROUP = "arena.apps"


def discover_apps(settings, names: list[str] | None = None, eps=None) -> list:
    """load every installed app (or only `names`); each entry point names a factory(settings) -> app"""
    found = []
    for ep in eps if eps is not None else entry_points(group=ENTRY_POINT_GROUP):
        if names is not None and ep.name not in names:
            continue
        app = ep.load()(settings)
        if not isinstance(app, App) or not capabilities_of(app):
            raise ConfigError(f"entry point {ep.name!r} did not produce an app")
        found.append(app)
    return found
