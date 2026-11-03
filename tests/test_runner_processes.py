"""The runners as real processes on a real genesis (2026-11-03: "test 철저히"): the sample personal peer in human mode
opens its owner desk window, the service peer answers over its api binding with a receipt, the foundation peer records
the built-in code table edition. No LLM."""
import json
import time

import httpx

from arena.broker.client import BrokerClient
from arena.config import Settings
from arena.recorder.client import RecorderClient
from tests.conftest import make_env
from tests.test_processes import Proc, free_port, procs  # noqa: F401  (procs is a fixture)
from tests.test_service_peer import spec


def wait_file(path, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.1)
    raise TimeoutError(str(path))


async def test_runner_processes_on_a_real_genesis(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "me", "desk", "svc", "svc_api", "fnd")}
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"],
                   ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_LLM_BACKEND="none")
    burl = f"http://127.0.0.1:{ports['broker']}"
    g = Proc("arena.genesis", env, tmp_path)
    procs.append(g)
    g.wait_up(burl)
    g.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    s = Settings.load(env=env, dotenv_path=None)
    rec_url = (await BrokerClient(burl, s).find("기록", role="record"))["peers"][0]["recorder_url"]
    brokers = f"public={burl}"

    # the sample personal peer, human mode: its desk window answers with the token it wrote in its home
    me = Proc("arena.peers.personal", dict(env, ARENA_PERSONAL_MODE="human", ARENA_PERSONAL_PEER_HOME=str(tmp_path / "me"),
                                          ARENA_PERSONAL_PEER_PORT=str(ports["me"]), ARENA_PERSONAL_DESK_PORT=str(ports["desk"]),
                                          ARENA_PERSONAL_PEER_BROKERS=brokers), tmp_path)
    procs.append(me)
    token = wait_file(tmp_path / "me" / "web-token")
    me.wait_up(f"http://127.0.0.1:{ports['desk']}", path="/")
    state = httpx.get(f"http://127.0.0.1:{ports['desk']}/api/state", headers={"Authorization": f"Bearer {token}"}).json()
    assert state["me"]["operator"] == "human" and state["me"]["llm"] is False
    assert httpx.get(f"http://127.0.0.1:{ports['desk']}/api/state").status_code == 401

    # the service peer from a spec file, api binding: an answer with a signed receipt
    (tmp_path / "calc.json").write_text(json.dumps(spec()), encoding="utf-8")
    svc = Proc("arena.peers.service", dict(env, ARENA_SERVICE_PEER_PORT=str(ports["svc"]), ARENA_SERVICE_PEER_API_PORT=str(ports["svc_api"]),
                                           ARENA_SERVICE_PEER_CONNECTIONS="api", ARENA_SERVICE_PEER_AREA=str(tmp_path / "svc"),
                                           ARENA_SERVICE_PEER_KEY_FILE=str(tmp_path / "svc.key"), ARENA_SERVICE_PEER_BROKERS=brokers,
                                           ), tmp_path, args=("--spec", str(tmp_path / "calc.json")))
    procs.append(svc)
    end, r = time.time() + 20, None
    while time.time() < end:
        try:
            r = httpx.post(f"http://127.0.0.1:{ports['svc_api']}/ops/add", json={"input": {"a": 2, "b": 3}}, timeout=2).json()
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    assert r and r["ok"] and r["result"] == {"sum": 5} and r["receipt"]["op"] == "add"

    # the foundation peer records the built-in code table edition on the ledger
    fnd = Proc("arena.peers.foundation", dict(env, ARENA_FOUNDATION_PEER_PORT=str(ports["fnd"]), ARENA_FOUNDATION_PEER_AREA=str(tmp_path / "fnd"),
                                              ARENA_FOUNDATION_PEER_KEY_FILE=str(tmp_path / "fnd.key"), ARENA_FOUNDATION_PEER_BROKERS=brokers,
                                              ARENA_FOUNDATION_PEER_RECORDER_URL=rec_url), tmp_path)
    procs.append(fnd)
    R, end, books = RecorderClient(rec_url, s), time.time() + 20, []
    while time.time() < end and not books:
        books = (await R.codebooks()).get("codebooks", [])
        time.sleep(0.2)
    assert books and books[0]["payload"]["name"] == "agent-arena"
