"""SOLID re-check, part 3: the app context is offered as small interfaces; the platform's context provides every one of
them, and the SDK declares everything the platform's context gives (so the two never drift apart again: before this
test the SDK's Context lacked six members the context had)."""
import inspect

from arena.peer.context import AppContext, PlatformContext
from arena.sdk import Context
from arena.sdk.context import PARTS
from tests.test_assistant import asst, ctx, eco  # noqa: F401  (eco is a fixture)


def declared(proto) -> set:
    out = set()
    for k in proto.__mro__:
        if k in (object,) or k.__module__ == "typing":
            continue
        out |= {n for n in vars(k) if not n.startswith("_")} | set(getattr(k, "__annotations__", {}))
    return out


def test_the_sdk_declares_exactly_what_the_platform_context_gives():
    given = {n for n, _ in inspect.getmembers(AppContext) if not n.startswith("_")} | {"app_name", "state"}
    assert declared(Context) == given  # nothing missing from the SDK, nothing promised that the context lacks
    parts = [declared(p) for p in PARTS]
    assert set().union(*parts) == given and sum(len(p) for p in parts) == len(given)  # each member in exactly one interface


def test_the_platform_context_is_every_small_interface(eco):
    c = ctx(eco.a)
    assert isinstance(c, Context) and all(isinstance(c, p) for p in PARTS)
    platform_only = {n for n, _ in inspect.getmembers(PlatformContext) if not n.startswith("_")} - set(declared(Context))
    assert platform_only == {"apps_with", "app_by_id", "ctx_of", "install_app", "inbox"}  # built-in apps only, never in the SDK
