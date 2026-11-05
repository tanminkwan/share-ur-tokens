"""The observer window on a real genesis, as real processes (user 2026-11-05): ARENA_GENESIS_GOD_WEB_PORT opens the god's
window, its token is made in the god's home, and what it shows is what the god reads from the real recorder."""
import httpx

from tests.test_processes import Proc, free_port, make_env, procs  # noqa: F401  (procs is a fixture)


async def test_the_god_s_window_on_a_real_genesis(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"],
                   ARENA_GENESIS_GOD_WEB_PORT=ports["web"], ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_GOD_CACHE_SEC="0", ARENA_OBSERVER_POLL_MS="500")
    p = Proc("arena.genesis", env, tmp_path)
    procs.append(p)
    web = f"http://127.0.0.1:{ports['web']}"
    p.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    p.wait_up(web, path="/")
    token = (tmp_path / "genesis" / "homes" / "god" / "web-token").read_text().strip()
    async with httpx.AsyncClient(base_url=web, trust_env=False, timeout=10) as c:
        assert (await c.get("/api/snapshot")).status_code == 401  # the page is open, what it shows is not
        auth = {"Authorization": f"Bearer {token}"}
        me = (await c.get("/api/state", headers=auth)).json()["me"]
        assert (me["kind"], me["kind_label"]) == ("observer", "관전 peer")
        assert (await c.get("/api/config", headers=auth)).json() == {"poll_ms": 500}
        v = (await c.get("/api/snapshot", headers=auth)).json()
    snap = v["snapshot"]
    assert v["ok"] and snap["stats"]["entries"] == 1 and snap["stats"]["by_type"] == {"genesis": 1} and snap["integrity"]["agree"]
    assert [e["type"] for e in snap["recent"]] == ["genesis"] and snap["recent"][0]["seq"] == 0
    assert snap["stats"]["genesis"]["god"] == me["pub"] and v["names"][me["pub"]] == me["pen"]  # the window is the god's own


async def test_no_window_unless_the_port_is_set(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god")}
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"])
    p = Proc("arena.genesis", env, tmp_path)
    procs.append(p)
    p.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    assert not (tmp_path / "genesis" / "homes" / "god" / "web-token").exists()  # nothing opened, no token made
