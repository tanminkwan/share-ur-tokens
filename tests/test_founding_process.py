"""FG-F9: the branch-founding path from end to end as real processes, no LLM. A trunk ceremony names the sphinx as god's
delegate; arena.genesis takes the trunk over; the foundation peer publishes its founding policy; the sphinx peer takes
that policy and sees it is delegated; an applicant applies with its branch god key; the person behind the sphinx says
yes in its window; the applicant takes the pass; the branch genesis links into the trunk with that pass; the same pass
cannot found a second branch."""
import json
import os
import shutil
import subprocess
import sys
import time

import httpx

from arena.a2a import A2ATransport
from arena.config import Settings
from arena.crypto import Identity
from arena.peer.home import PeerHome
from arena.recorder.client import RecorderClient
from tests.conftest import make_env
from tests.test_ceremony_process import cli, genesis_env, sign_round, start_genesis
from tests.test_processes import ROOT, Proc, free_port, procs  # noqa: F401  (procs is a fixture)
from tests.test_runner_processes import wait_file


async def test_fgf9_a_branch_founded_through_a_delegated_sphinx_and_the_foundation_s_policy(tmp_path, procs):
    env = make_env(tmp_path, ARENA_CEREMONY_POLL_SEC="0.05", ARENA_CEREMONY_TIMEOUT_SEC="60", ARENA_LLM_BACKEND="none",
                   ARENA_RECORDER_REQUIRE_GROUP="true")
    s = Settings.load(env=env, dotenv_path=None)
    sphinx_pub = PeerHome(str(tmp_path / "sphinx"), s).identity().pub  # the person's peer key, made before the ceremony names it

    # the trunk ceremony names the sphinx as god's delegate (round 2: handover + delegate, one offline session)
    offline, trunk_dir = str(tmp_path / "offline"), str(tmp_path / "trunk")
    cli(env, tmp_path, "god-key", "--out", offline, "--passphrase-env", "CEREMONY_PASS")
    w = [Identity.generate().pub, Identity.generate().pub]
    run = Proc("arena.ceremony", env, tmp_path, args=["run", "--god-pub", os.path.join(offline, "god.pub"), "--out", trunk_dir,
                                                      "--witness", w[0], "--witness", w[1], "--delegate", sphinx_pub])
    procs.append(run)
    sign_round(env, tmp_path, offline, trunk_dir, 1)
    assert sign_round(env, tmp_path, offline, trunk_dir, 2)["signed"] == ["delegate-1", "key_rotate"]
    assert run.p.wait(60) == 0, run.p.stdout.read().decode()
    tp = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    start_genesis(procs, genesis_env(tmp_path, trunk_dir, tp), tmp_path, tp)
    trunk = f"http://127.0.0.1:{tp['api']}"
    burl = f"http://127.0.0.1:{tp['broker']}"
    T = RecorderClient(trunk, s)
    assert [d["delegate"] for d in (await T.delegates())["delegates"]] == [sphinx_pub]

    # the foundation publishes its policy; the sphinx takes it and sees it is delegated
    fport, sport, wport = free_port(), free_port(), free_port()
    fkey = tmp_path / "foundation.key"
    foundation = Identity.generate()
    foundation.save(str(fkey))
    fp = Proc("arena.peers.foundation", dict(env, ARENA_FOUNDATION_PEER_PORT=str(fport), ARENA_FOUNDATION_PEER_KEY_FILE=str(fkey),
                                             ARENA_FOUNDATION_PEER_AREA=str(tmp_path / "f-area"), ARENA_FOUNDATION_PEER_BROKERS=f"public={burl}",
                                             ARENA_FOUNDATION_FOUNDING_CAP_COUNT="3", ARENA_FOUNDATION_FOUNDING_PASS_DAYS="5"), tmp_path)
    procs.append(fp)
    furl = f"http://127.0.0.1:{fport}"
    fp.wait_up(furl, path="/.well-known/agent-card.json")
    sp = Proc("arena.peers.sphinx", dict(env, ARENA_PERSONAL_MODE="human", ARENA_PERSONAL_PEER_HOME=str(tmp_path / "sphinx"),
                                         ARENA_PERSONAL_PEER_PORT=str(sport), ARENA_PERSONAL_CONSOLE_PORT=str(wport),
                                         ARENA_PERSONAL_PEER_BROKERS=f"public={burl}", ARENA_SPHINX_FOUNDATION_URL=furl,
                                         ARENA_SPHINX_FOUNDATION_PUB=foundation.pub, ARENA_SPHINX_TRUNK_RECORDER_URL=trunk,
                                         ARENA_SPHINX_POLICY_REFRESH_SEC="0.5"), tmp_path)
    procs.append(sp)
    surl = f"http://127.0.0.1:{sport}"
    token = wait_file(tmp_path / "sphinx" / "web-token")
    sp.wait_up(surl, path="/.well-known/agent-card.json")
    window, auth = f"http://127.0.0.1:{wport}", {"Authorization": f"Bearer {token}"}
    sp.wait_up(window, path="/")
    info = await A2ATransport(s).call(surl, {"op": "sphinx.info"})
    assert info["delegated"] is True and info["pub"] == sphinx_pub
    assert info["policy"] == {"cap": {"count": 3, "days": 30.0}, "pass_days": 5.0, "source": "foundation", "foundation": foundation.pub}
    items = httpx.get(f"{window}/api/items", headers=auth, timeout=5).json()["items"]
    assert any(x["kind"] == "notice" and "위임됨" in x["title"] for x in items)  # its person is told

    # an applicant with its branch god key; the person says yes; the applicant takes the pass
    branch_dir = tmp_path / "branch"
    branch_dir.mkdir()
    founder = Identity.generate()
    founder.save(str(branch_dir / "god.key"))

    def groups(*args):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env)
        r = subprocess.run([sys.executable, "-m", "arena.groups", *args], env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout or "{}"), r.stdout + r.stderr
    key = ("--key-file", str(branch_dir / "god.key"))
    code, r, out = groups("apply", *key, "--sphinx", surl, "--purpose", "사내 연구 모임의 가지", "--contact", "mailto:lab@example.org")
    assert code == 0 and r["status"] == "waiting", out
    end, item = time.time() + 20, None
    while time.time() < end and item is None:
        item = next((x for x in httpx.get(f"{window}/api/items", headers=auth, timeout=5).json()["items"]
                     if x["kind"] == "question" and founder.pub in x.get("body", "")), None)
        time.sleep(0.2)
    assert item and httpx.post(f"{window}/api/items/{item['id']}/answer", headers=auth, json={"yes": True, "why": "영상 통화"}).json()["ok"]
    end, got = time.time() + 20, {}
    while time.time() < end and got.get("status") != "passed":
        code, got, out = groups("pass", *key, "--sphinx", surl, "--application", r["application_id"], "--out", str(tmp_path / "pass.json"))
        time.sleep(0.3)
    assert got["status"] == "passed", out
    p = json.loads((tmp_path / "pass.json").read_text())
    assert p["body"]["until"] - p["body"]["issued_at"] == 5 * 86400  # the foundation's pass_days, enforced by the sphinx

    # the branch genesis links into the trunk with that pass
    bp = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    benv = dict(genesis_env(tmp_path, str(branch_dir), bp), ARENA_GENESIS_PARENT_RECORDER_URL=trunk,
                ARENA_GENESIS_FOUNDING_PASS_FILE=str(tmp_path / "pass.json"), ARENA_GENESIS_BROKER_NAME="lab")
    start_genesis(procs, benv, tmp_path, bp)
    B = RecorderClient(f"http://127.0.0.1:{bp['api']}", s)
    bid = (await B.health())["ledger_id"]
    link = (await T.link(bid))["link"]
    assert link["payload"]["pass"]["body"]["sphinx"] == sphinx_pub and link["payload"]["child_god"] == founder.pub
    assert (await T.verify(link["hash"]))["founding"]["sphinx"] == sphinx_pub

    # the same pass cannot found a second branch, even for the same founder key
    again = tmp_path / "branch2"
    again.mkdir()
    shutil.copy(branch_dir / "god.key", again / "god.key")
    bp2 = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    g2 = Proc("arena.genesis", dict(genesis_env(tmp_path, str(again), bp2), ARENA_GENESIS_PARENT_RECORDER_URL=trunk,
                                    ARENA_GENESIS_FOUNDING_PASS_FILE=str(tmp_path / "pass.json")), tmp_path)
    procs.append(g2)
    assert g2.p.wait(30) != 0
    assert "already used" in g2.p.stdout.read().decode()
