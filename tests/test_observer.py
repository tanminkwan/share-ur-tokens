"""The observer window's backend (user 2026-11-05: the god peer's screen, read-only, kept fresh by polling): the token,
the snapshot with a pen name for every key it mentions, the latest entries, the settings."""
import dataclasses

import httpx

from arena.bundled.observer import ObserverApp
from arena.bundled.observer.api import build_observer_api
from arena.peer.god_role import recent_entries
from tests.test_god_role import setup  # noqa: F401  (a fixture)

TOKEN = "obs-t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def window(s, **over):
    role, ov = s["role"], s["ov"]
    role.settings = dataclasses.replace(ov.settings, **over)  # the role reads god_*, the window observer_*: one Settings for both
    app = ObserverApp(role, role.settings, "127.0.0.1", 0, TOKEN)
    app._ctx = ov.ctx(role)  # the god role's own context: the same key, brokers and recorders
    return app


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_observer_api(app, TOKEN)), base_url="http://observer")


async def test_every_api_path_needs_the_token(setup):
    async with client(window(setup)) as c:
        for path in ("/api/config", "/api/state", "/api/snapshot"):
            assert (await c.get(path)).status_code == 401
            assert (await c.get(path, headers={"Authorization": "Bearer nope"})).status_code == 401
            assert (await c.get(path, headers=AUTH)).status_code == 200
        assert (await c.get("/")).status_code == 200  # the page itself is open; what it shows needs the token


async def test_the_window_is_the_observer_kind_and_asks_again_at_the_set_pace(setup):
    app = window(setup, observer_poll_ms=1234)
    async with client(app) as c:
        me = (await c.get("/api/state", headers=AUTH)).json()["me"]
        assert (me["kind"], me["kind_label"], me["operator"], me["llm"]) == ("observer", "관전 peer", "observer", False)
        assert me["pen"] == setup["ov"].pen and me["pub"] == setup["ov"].identity.pub
        assert (await c.get("/api/config", headers=AUTH)).json() == {"poll_ms": 1234}


async def test_the_snapshot_names_every_key_it_mentions(setup):
    async with client(window(setup)) as c:
        v = (await c.get("/api/snapshot", headers=AUTH)).json()
    snap = v["snapshot"]
    assert v["ok"] and snap["integrity"]["agree"] and snap["stats"]["entries"] >= 5 and v["as_of"] > 0
    mentioned = {p["pub"] for p in snap["peers"]} | {e["issuer"] for e in snap["stats"]["events"]} | {a["reader"] for a in snap["access"]}
    assert mentioned and mentioned <= set(v["names"])  # the window shows names, never raw keys
    assert all(n.startswith("필명-") for n in v["names"].values())


async def test_the_latest_entries_come_newest_first_and_never_carry_content(setup):
    async with client(window(setup, god_recent=3)) as c:
        recent = (await c.get("/api/snapshot", headers=AUTH)).json()["snapshot"]["recent"]
    assert len(recent) == 3 and [e["seq"] for e in recent] == sorted((e["seq"] for e in recent), reverse=True)
    assert set(recent[0]) == {"seq", "type", "ts", "hash", "event_id", "who"} and all(w.startswith("필명-") for e in recent for w in e["who"])
    assert recent_entries([], 5, str) == [] and recent_entries([{"type": "x", "ts": 1.0, "hash": "h", "payload": {}, "sigs": {}}], 0, str) == []


async def test_a_world_nobody_can_read_says_so_instead_of_failing(setup):
    app = window(setup)
    app.god.recorders = []  # no recorder found, and none will be: the broker's answer is empty
    app.god.locate = _none
    async with client(app) as c:
        v = (await c.get("/api/snapshot", headers=AUTH)).json()
    assert v["ok"] is False and v["error"] and v["as_of"] > 0


async def _none(ctx):
    return []
