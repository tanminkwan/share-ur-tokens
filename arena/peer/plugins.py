"""Load apps named in settings: "package.module:factory" where factory(settings) returns an app."""
from __future__ import annotations

import importlib

from ..config import ConfigError, Settings
from .plugin import App, capabilities_of


def load_app(spec: str, settings: Settings):
    if ":" not in spec:
        raise ConfigError(f"app spec must be module:factory: {spec!r}")
    mod, attr = spec.split(":", 1)
    try:
        factory = getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as e:
        raise ConfigError(f"cannot load app {spec!r}: {e}") from e
    app = factory(settings)
    if not isinstance(app, App) or not capabilities_of(app):
        raise ConfigError(f"{spec!r} did not produce an app (needs name, version and at least one capability)")
    return app


def load_apps(specs: list[str], settings: Settings) -> list:
    return [load_app(s, settings) for s in specs]
