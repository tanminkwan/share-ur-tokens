"""P10-I2, I4: real processes in containers. Two peers on two docker networks that share nothing (neither can open the other's
port) host, join, contract and talk through the connectivity server. Every path is TCP; UDP carries only the STUN check each
peer shows in its window (10-D). deploy/relay-test/docker-compose.yml.
The structure checks always run; the containers are opt-in (ARENA_TEST_DOCKER=1) and need docker. Human mode, no LLM."""
import json
import os
import pathlib
import shutil
import subprocess
import time
import uuid

import httpx
import pytest

from connectivity.config import ConnectivitySettings

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
TOKEN = "relay-test"
IMAGE = "agent-arena:relay-test"  # its own tag: the test never replaces the image other containers on this host run
RULES = "[relay 시험 규칙]\n1. 참가 신청을 하면 개최자가 member 역할 계약을 맺는다.\n2. 두 사람은 인사를 나눈다."
docker = pytest.mark.skipif(os.environ.get("ARENA_TEST_DOCKER") != "1" or shutil.which("docker") is None,
                            reason="a real container build and run is opt-in: ARENA_TEST_DOCKER=1")


def connectivity_keys() -> set:
    from dataclasses import fields
    return {f.metadata["key"] for f in fields(ConnectivitySettings)}


def test_the_connectivity_server_has_its_own_deploy_directory():
    compose = (DEPLOY / "connectivity" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "build:" not in compose and 'command: ["connectivity"]' in compose and "network_mode: host" in compose
    assert "required: false" in compose and "volumes:" not in compose  # it keeps no state
    example = (DEPLOY / "connectivity" / ".env.example").read_text(encoding="utf-8")
    names = {ln.split("=", 1)[0] for ln in example.splitlines() if ln and not ln.startswith("#")}
    assert names - {"ARENA_IMAGE"} == connectivity_keys()  # every setting, and only its own (it knows nothing of Arena)
    assert "CONNECTIVITY_PATHS=/.well-known/agent-card.json,/rpc,/a2a/notify" in example
    assert "!connectivity" in (DEPLOY / "image" / "Dockerfile.dockerignore").read_text(encoding="utf-8")  # it is in the image


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_the_new_compose_files_are_valid_and_the_two_peers_share_no_network():
    for d in ("connectivity", "relay-test"):
        r = subprocess.run(["docker", "compose", "config", "-q"], cwd=DEPLOY / d, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (d, r.stderr[-300:])
    r = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=DEPLOY / "relay-test", capture_output=True, text=True, timeout=60)
    sv = json.loads(r.stdout)["services"]
    assert set(sv["peer-a"]["networks"]) & set(sv["peer-b"]["networks"]) == set()
    assert set(sv["genesis"]["networks"]) == set(sv["connectivity"]["networks"]) == {"net-a", "net-b"}
    for p in ("peer-a", "peer-b"):
        assert sv[p]["environment"]["ARENA_PERSONAL_PEER_CONNECTIVITY"] == "http://connectivity:9200"
        assert all(port["host_ip"] == "127.0.0.1" for port in sv[p]["ports"])  # only the owner's window, only on this machine
    assert "CONNECTIVITY_PROBE_ALLOW" not in sv["connectivity"]["environment"]  # private sources are never probed: relay


def wait(check, timeout=60.0, step=0.5):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            got = check()
            if got:
                return got
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            last = e
        time.sleep(step)
    raise AssertionError(f"timed out ({last!r})")


@docker
def test_p10_i2_two_peers_that_cannot_reach_each_other_take_part_in_an_event_through_the_relay():
    project = f"relay-test-{uuid.uuid4().hex[:6]}"
    env = dict(os.environ, ARENA_IMAGE=IMAGE, RELAY_TEST_A_CONSOLE="19183", RELAY_TEST_B_CONSOLE="19283", RELAY_TEST_TOKEN=TOKEN)

    def compose(*args, timeout=300):
        return subprocess.run(["docker", "compose", "-p", project, *args], cwd=DEPLOY / "relay-test", env=env,
                              capture_output=True, text=True, timeout=timeout)

    def inside(service, code):
        """run python in a container: what that container (and only it) can reach"""
        r = compose("exec", "-T", service, "python", "-c", code, timeout=60)
        return r.stdout.strip()

    build = subprocess.run([str(DEPLOY / "build.sh"), IMAGE], capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stderr[-500:]
    H = {"Authorization": f"Bearer {TOKEN}"}
    A = httpx.Client(base_url="http://127.0.0.1:19183", headers=H, trust_env=False, timeout=60)
    B = httpx.Client(base_url="http://127.0.0.1:19283", headers=H, trust_env=False, timeout=60)
    try:
        assert compose("up", "-d").returncode == 0
        a = wait(lambda: A.get("/api/state").json()["me"], 90)
        assert a["reach"] in ("checking", "relay")  # the window knows from the start that the peer is finding its way
        # each checks itself and finds it cannot be reached from outside
        a = wait(lambda: (lambda me: me if me["reach"] == "relay" else None)(A.get("/api/state").json()["me"]))
        b = wait(lambda: (lambda me: me if me["reach"] == "relay" else None)(B.get("/api/state").json()["me"]), 90)
        # STUN (P10-C7): UDP gets out between these containers; shown in the window, the path stays the relay over TCP
        assert wait(lambda: A.get("/api/state").json()["me"]["udp"] is True) and wait(lambda: B.get("/api/state").json()["me"]["udp"] is True)

        # the two cannot open each other: no network in common
        probe = "import httpx\ntry:\n httpx.get('http://peer-b:9180/.well-known/agent-card.json', trust_env=False, timeout=3); print('open')\n" \
                "except Exception: print('closed')"
        assert inside("peer-a", probe) == "closed"
        # the broker lists each at its relay address, from the very first post (no earlier version at its own address)
        def listed():
            got = json.loads(inside("peer-a", "import httpx,json; print(json.dumps({p['nick']: [p['url'], p['ver']] for p in "
                                              "httpx.get('http://genesis:9100/profiles', trust_env=False).json()['profiles']}))"))
            return got if {"가람", "나래"} <= set(got) else None
        got = wait(listed)
        assert got["가람"] == [f"http://connectivity:9200/r/{a['pub']}", 1] and got["나래"] == [f"http://connectivity:9200/r/{b['pub']}", 1]

        ev = A.post("/api/events", json={"title": "relay 시험", "kind": "놀이", "rules": RULES, "policy": {"roles": ["member"]}}).json()
        assert ev["ok"], ev
        ev = ev["event_id"]
        wait(lambda: any(e["event_id"] == ev for e in B.get("/api/state").json()["events"]))
        assert B.post(f"/api/events/{ev}/tools/join_event", json={"args": {}}).json()["ok"]  # B → A, through A's relay
        wait(lambda: any(t["kind"] == "join" for t in A.get(f"/api/events/{ev}").json()["timeline"]))
        c = A.post(f"/api/events/{ev}/tools/contract", json={"args": {"role": "member", "peer": "나래"}}).json()  # A → B
        assert c["ok"] and c["contracts_so_far"] == 1, c
        # ok means B's signature came back through B's relay and the contract is on the ledger
        assert "member=나래-" in A.get(f"/api/events/{ev}").json()["state_line"]
        assert A.post(f"/api/events/{ev}/say", json={"to": "나래", "text": "relay로 갑니다"}).json()["ok"]
        wait(lambda: any(t["dir"] == "in" and t["text"] == "relay로 갑니다" for t in B.get(f"/api/events/{ev}").json()["timeline"]))
        assert B.post(f"/api/events/{ev}/say", json={"to": "가람", "text": "잘 받았어요"}).json()["ok"]
        wait(lambda: any(t["dir"] == "in" and t["text"] == "잘 받았어요" for t in A.get(f"/api/events/{ev}").json()["timeline"]))

        # the relay restarts (P10-C4): both peers attach again, and a message sent at once is not lost
        assert compose("restart", "connectivity").returncode == 0
        assert A.post(f"/api/events/{ev}/say", json={"to": "나래", "text": "다시 붙었나요"}).json()["ok"]
        wait(lambda: any(t["dir"] == "in" and t["text"] == "다시 붙었나요" for t in B.get(f"/api/events/{ev}").json()["timeline"]))

        health = json.loads(inside("peer-a", "import httpx,json; print(json.dumps(httpx.get('http://connectivity:9200/health', trust_env=False).json()))"))
        assert health["attached"] == 2 and health["relayed_bytes"] > 0  # counted since the restart
    finally:
        A.close()
        B.close()
        compose("down", "-v")


# ---- 10-F: a peer on a company network that can open only the connectivity server (deploy/intranet-test) ----
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_the_intranet_compose_lets_the_company_peer_reach_only_the_connectivity_server():
    d = DEPLOY / "intranet-test"
    r = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=d, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    c = json.loads(r.stdout)
    sv, nets = c["services"], c["networks"]
    assert nets["intranet"].get("internal") is True  # no way out of it, as a company network with a firewall
    assert set(sv["peer-b"]["networks"]) == {"intranet"} and set(sv["connectivity"]["networks"]) == {"intranet", "internet"}
    assert set(sv["genesis"]["networks"]) == set(sv["peer-a"]["networks"]) == {"internet"}
    on_intranet = {name for name, s in sv.items() if "intranet" in s["networks"]}
    assert on_intranet == {"peer-b", "connectivity"}  # the only thing the company peer can open is the connectivity server
    env = sv["connectivity"]["environment"]
    assert env["CONNECTIVITY_OUT"] == "true" and not env.get("CONNECTIVITY_PUBLIC_URL")
    assert sv["peer-b"]["environment"]["ARENA_PERSONAL_PEER_CONNECTIVITY"] == "http://connectivity:9200"
    assert sv["peer-b"]["environment"]["ARENA_PERSONAL_PEER_BROKERS"] == "public=http://genesis:9100"  # the broker's own address
    assert "ports" not in sv["peer-b"]


@docker
def test_p10_f_a_company_peer_that_can_open_only_the_connectivity_server_takes_part_in_an_event():
    project = f"intranet-test-{uuid.uuid4().hex[:6]}"
    token = "intranet-test"
    env = dict(os.environ, ARENA_IMAGE=IMAGE, INTRANET_TEST_A_CONSOLE="19383", INTRANET_TEST_TOKEN=token)

    def compose(*args, timeout=300):
        return subprocess.run(["docker", "compose", "-p", project, *args], cwd=DEPLOY / "intranet-test", env=env,
                              capture_output=True, text=True, timeout=timeout)

    def inside(service, code):
        r = compose("exec", "-T", service, "python", "-c", code, timeout=60)
        return r.stdout.strip()

    def can_open(service, url):
        return inside(service, f"import httpx\ntry:\n httpx.get({url!r}, trust_env=False, timeout=3); print('open')\nexcept Exception: print('closed')")

    class InPeerB:
        """peer-b's window API, called inside its container (a network with no way out cannot publish a port)"""
        def _call(self, method, path, body=None):
            code = ("import httpx,json,sys; r=httpx.request(sys.argv[1], 'http://127.0.0.1:9183'+sys.argv[2], "
                    f"headers={{'Authorization': 'Bearer {token}'}}, json=json.loads(sys.argv[3]), trust_env=False, timeout=60); print(r.text)")
            r = compose("exec", "-T", "peer-b", "python", "-c", code, method, path, json.dumps(body), timeout=90)
            return json.loads(r.stdout)

        def get(self, path):
            return self._call("GET", path)

        def post(self, path, body):
            return self._call("POST", path, body)

    build = subprocess.run([str(DEPLOY / "build.sh"), IMAGE], capture_output=True, text=True, timeout=900)
    assert build.returncode == 0, build.stderr[-500:]
    A = httpx.Client(base_url="http://127.0.0.1:19383", headers={"Authorization": f"Bearer {token}"}, trust_env=False, timeout=60)
    B = InPeerB()
    try:
        up = compose("up", "-d")
        assert up.returncode == 0, up.stderr[-500:]
        a = wait(lambda: A.get("/api/state").json()["me"], 90)
        b = wait(lambda: (lambda me: me if me["reach"] == "relay" else None)(B.get("/api/state")["me"]), 120)

        # the company network: peer-b opens the connectivity server and nothing else
        assert can_open("peer-b", "http://connectivity:9200/health") == "open"
        assert can_open("peer-b", "http://genesis:9100/health") == "closed"
        assert can_open("peer-b", "http://peer-a:9180/.well-known/agent-card.json") == "closed"
        assert can_open("peer-b", "https://www.google.com/") == "closed"

        # peer-b's profile reached the broker (through the way out) at its relay address; peer-a at its own
        def listed():
            got = json.loads(inside("peer-a", "import httpx,json; print(json.dumps({p['nick']: p['url'] for p in "
                                              "httpx.get('http://genesis:9100/profiles', trust_env=False).json()['profiles']}))"))
            return got if {"가람", "나래"} <= set(got) else None
        got = wait(listed, 90)
        assert got["나래"] == f"http://connectivity:9200/r/{b['pub']}" and got["가람"] == "http://peer-a:9180"

        # an event between them: peer-a hosts on the internet, peer-b takes part from the company network
        ev = A.post("/api/events", json={"title": "사내망 시험", "kind": "놀이", "rules": RULES, "policy": {"roles": ["member"]}}).json()
        assert ev["ok"], ev
        ev = ev["event_id"]
        wait(lambda: any(e["event_id"] == ev for e in B.get("/api/state")["events"]), 90)  # the notice reached the company peer
        assert B.post(f"/api/events/{ev}/tools/join_event", {"args": {}})["ok"]  # B → A: through the way out
        wait(lambda: any(t["kind"] == "join" for t in A.get(f"/api/events/{ev}").json()["timeline"]))
        c = A.post(f"/api/events/{ev}/tools/contract", json={"args": {"role": "member", "peer": "나래"}}).json()  # A → B: through B's relay
        assert c["ok"] and c["contracts_so_far"] == 1, c
        assert "member=나래-" in A.get(f"/api/events/{ev}").json()["state_line"]  # on the ledger, which peer-b cannot open itself
        assert A.post(f"/api/events/{ev}/say", json={"to": "나래", "text": "인터넷에서 보냅니다"}).json()["ok"]
        wait(lambda: any(t["dir"] == "in" and t["text"] == "인터넷에서 보냅니다" for t in B.get(f"/api/events/{ev}")["timeline"]))
        assert B.post(f"/api/events/{ev}/say", {"to": "가람", "text": "사내망에서 답합니다"})["ok"]
        wait(lambda: any(t["dir"] == "in" and t["text"] == "사내망에서 답합니다" for t in A.get(f"/api/events/{ev}").json()["timeline"]))

        health = json.loads(inside("peer-a", "import httpx,json; print(json.dumps(httpx.get('http://connectivity:9200/health', trust_env=False).json()))"))
        assert health["attached"] == 1 and health["relayed_bytes"] > 0  # peer-b is reached through the relay
        assert health["out_calls"] > 0 and "bad_target" not in health["refused"]  # and calls out through the server
    finally:
        A.close()
        compose("down", "-v")
