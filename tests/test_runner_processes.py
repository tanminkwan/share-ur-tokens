"""The runners as real processes on a real genesis (2026-11-03: "test 철저히"): the sample personal peer in human mode
opens its owner desk window, the service peer answers over its api binding with a receipt, the foundation peer records
the built-in code table edition, and the key peer keeps a backup while a peer's owner registers, rotates and checks its
keys with `python -m arena.keys`. No LLM."""
import json
import os
import subprocess
import sys
import time

import httpx

from arena.broker.client import BrokerClient
from arena.config import Settings
from arena.recorder.client import RecorderClient
from tests.conftest import make_env
from tests.test_processes import ROOT, Proc, free_port, procs  # noqa: F401  (procs is a fixture)
from tests.test_service_peer import spec


def wait_file(path, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.1)
    raise TimeoutError(str(path))


async def test_runner_processes_on_a_real_genesis(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "me", "desk", "svc", "svc_api", "fnd", "keys", "link", "link_api")}
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

    # the sample personal peer, human mode: its window (the console by default) answers with the token it wrote in its home
    me = Proc("arena.peers.personal", dict(env, ARENA_PERSONAL_MODE="human", ARENA_PERSONAL_PEER_HOME=str(tmp_path / "me"),
                                          ARENA_PERSONAL_PEER_PORT=str(ports["me"]), ARENA_PERSONAL_CONSOLE_PORT=str(ports["desk"]),
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

    # the key peer keeps the backup; the owner registers, rotates and checks keys from the command line (6-K)
    kp = Proc("arena.peers.key_peer", dict(env, ARENA_KEY_PEER_PORT=str(ports["keys"]), ARENA_KEY_PEER_AREA=str(tmp_path / "kp"),
                                           ARENA_KEY_PEER_KEY_FILE=str(tmp_path / "kp.key"), ARENA_KEY_PEER_BROKERS=brokers), tmp_path)
    procs.append(kp)
    kp_url = f"http://127.0.0.1:{ports['keys']}"
    kp.wait_up(kp_url, path="/.well-known/agent-card.json")

    def keys(*args):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env, MY_PASS="correct horse battery", MY_SECRET="my recovery secret")
        r = subprocess.run([sys.executable, "-m", "arena.keys", *args, "--home", str(tmp_path / "owner"), "--passphrase-env", "MY_PASS"],
                           env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout or "{}"), r.stdout + r.stderr
    code, reg, out = keys("register", "--recorder", rec_url, "--key-peer", kp_url, "--key-peer-recovers", "--secret-env", "MY_SECRET",
                          "--backup-file", str(tmp_path / "backup.json"))
    assert code == 0 and reg["key_peer"]["ok"], out
    assert "correct horse" not in out and "my recovery secret" not in out  # never printed
    assert json.loads((tmp_path / "backup.json").read_text())["pub"] == reg["pub"]
    code, rot, out = keys("rotate", "--recorder", rec_url, "--key-peer", kp_url, "--secret-env", "MY_SECRET")
    assert code == 0 and rot["pub"] != reg["pub"], out
    st = (await R.key(reg["pub"]))
    assert st["status"] == "retired" and st["current"] == rot["pub"]
    code, where, _ = keys("where")
    assert code == 0 and "0600" in where["where"]  # ARENA_KEY_STORE=file in tests
    code, bad, _ = keys("rotate", "--recorder", rec_url, "--backup-file", str(tmp_path / "backup.json"))
    assert code == 1 and "already rotated" in bad["error"]  # the first backup's promise is used up

    # works registry: the author registers a text, a reader checks a copy and finds it by its hash (CP-9, CP-10)
    (tmp_path / "poem.txt").write_bytes("시 한 편\r\n".encode("utf-8"))
    (tmp_path / "copy.txt").write_bytes("시 한 편\n".encode("utf-8"))

    def content(*args):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env)
        r = subprocess.run([sys.executable, "-m", "arena.content", *args], env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout or "{}"), r.stdout + r.stderr
    code, reg, out = content("register", "--home", str(tmp_path / "author"), "--recorder", rec_url, "--file", str(tmp_path / "poem.txt"),
                             "--out", str(tmp_path / "poem-ref.json"))
    assert code == 0 and reg["reference"]["ledger_id"] == (await R.trust())["ledger_id"], out
    code, chk, out = content("check", "--file", str(tmp_path / "copy.txt"), "--ref", str(tmp_path / "poem-ref.json"))
    assert code == 0 and chk["steps"][0]["ok"] and chk["steps"][1]["ok"], out
    code, found, out = content("find", "--file", str(tmp_path / "copy.txt"), "--recorder", rec_url)
    assert code == 0 and found["entry"] == reg["reference"]["entry"], out

    # a link peer (api only): the ledger names a permanent link, the author moves the work later (user 2026-11-03)
    lp = Proc("arena.peers.link_peer", dict(env, ARENA_LINK_PEER_PORT=str(ports["link"]), ARENA_LINK_PEER_API_PORT=str(ports["link_api"]),
                                            ARENA_LINK_PEER_AREA=str(tmp_path / "lp"), ARENA_LINK_PEER_KEY_FILE=str(tmp_path / "lp.key"),
                                            ARENA_LINK_PEER_BROKERS=brokers, ARENA_LINK_PEER_RECORDER_URL=rec_url), tmp_path)
    procs.append(lp)
    link_url = f"http://127.0.0.1:{ports['link_api']}"
    end = time.time() + 20
    while time.time() < end:
        try:
            if httpx.post(link_url + "/ops/link.info", json={}, timeout=1).json().get("ok"):
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    (tmp_path / "story.txt").write_bytes("이야기 하나\n".encode("utf-8"))
    code, reg, out = content("register", "--home", str(tmp_path / "author"), "--recorder", rec_url, "--file", str(tmp_path / "story.txt"),
                             "--storage", "https=https://old.example/story.txt", "--link-peer", link_url, "--out", str(tmp_path / "story-ref.json"))
    assert code == 0 and reg["reference"]["links"][0]["via"] == link_url, out
    code, moved, out = content("relink", "--home", str(tmp_path / "author"), "--ref", str(tmp_path / "story-ref.json"),
                               "--storage", "https=https://new.example/story.txt")
    assert code == 0 and moved["peers"][0]["ver"] == 2, out
    code, now, out = content("resolve", "--ref", str(tmp_path / "story-ref.json"))
    assert code == 0 and now["targets"] == [{"kind": "https", "location": "https://new.example/story.txt"}], out

