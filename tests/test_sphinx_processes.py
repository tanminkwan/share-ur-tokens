"""The sphinx on a real genesis, as real processes: the genesis, the sphinx peer (python -m arena.peers.sphinx, a person's
peer in human mode with its window), an applicant running python -m arena.groups apply / pass over a2a, and the person
answering in the window's API after meeting the applicant. No LLM."""
import json
import os
import subprocess
import sys
import time

import httpx

from arena.broker.client import BrokerClient
from arena.config import Settings
from arena.ledger.founding import pass_error
from arena.peer.home import PeerHome
from tests.conftest import make_env
from tests.test_processes import ROOT, Proc, free_port, procs  # noqa: F401  (procs is a fixture)
from tests.test_runner_processes import wait_file


async def test_the_sphinx_gives_a_pass_after_the_person_says_yes(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "sphinx", "window")}
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"],
                   ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_LLM_BACKEND="none")
    g = Proc("arena.genesis", env, tmp_path)
    procs.append(g)
    burl = f"http://127.0.0.1:{ports['broker']}"
    g.wait_up(burl)
    s = Settings.load(env=env, dotenv_path=None)

    sp = Proc("arena.peers.sphinx", dict(env, ARENA_PERSONAL_MODE="human", ARENA_PERSONAL_PEER_HOME=str(tmp_path / "sphinx"),
                                         ARENA_PERSONAL_PEER_PORT=str(ports["sphinx"]), ARENA_PERSONAL_CONSOLE_PORT=str(ports["window"]),
                                         ARENA_PERSONAL_PEER_BROKERS=f"public={burl}"), tmp_path)
    procs.append(sp)
    token = wait_file(tmp_path / "sphinx" / "web-token")
    sphinx_url = f"http://127.0.0.1:{ports['sphinx']}"
    sp.wait_up(sphinx_url, path="/.well-known/agent-card.json")
    window, auth = f"http://127.0.0.1:{ports['window']}", {"Authorization": f"Bearer {token}"}
    sp.wait_up(window, path="/")

    # the sphinx shows itself on the board: anyone finds who lets groups be founded
    end, found = time.time() + 20, []
    while time.time() < end and not found:
        found = (await BrokerClient(burl, s).find("그룹 생성 허락", role="그룹 생성 허락")).get("peers", [])
        time.sleep(0.2)
    assert found and found[0].get("operator") == "human"

    def groups(*args):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env)
        r = subprocess.run([sys.executable, "-m", "arena.groups", *args], env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout or "{}"), r.stdout + r.stderr
    home = ("--home", str(tmp_path / "founder"))
    code, r, out = groups("apply", *home, "--sphinx", sphinx_url, "--purpose", "동네 독서 모임의 가지 그룹", "--contact", "mailto:reader@example.org")
    assert code == 0 and r["status"] == "waiting", out
    founder = PeerHome(str(tmp_path / "founder"), s).identity().pub

    # the person sees the application in the window, meets the applicant (outside the platform) and says yes
    end, item = time.time() + 20, None
    while time.time() < end and item is None:
        items = httpx.get(f"{window}/api/items", headers=auth).json()
        item = next((x for x in items.get("items", []) if founder in x.get("body", "")), None)
        time.sleep(0.2)
    assert item and "mailto:reader@example.org" in item["body"]
    code, waiting, _ = groups("pass", "--sphinx", sphinx_url, "--application", r["application_id"])
    assert code == 0 and waiting["status"] == "waiting"
    assert httpx.post(f"{window}/api/items/{item['id']}/answer", headers=auth, json={"yes": True, "why": "영상 통화로 만남"}).json()["ok"]

    end, got = time.time() + 20, {}
    while time.time() < end and got.get("status") != "passed":
        code, got, out = groups("pass", *home, "--sphinx", sphinx_url, "--application", r["application_id"], "--out", str(tmp_path / "pass.json"))
        time.sleep(0.3)
    assert got["status"] == "passed", out
    p = json.loads((tmp_path / "pass.json").read_text())
    assert pass_error(p, founder=founder, now=time.time()) is None
    assert p["body"]["sphinx"] == found[0]["pub"]
