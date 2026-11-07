"""P10-I2, I4: real processes in containers. Two peers on two docker networks that share nothing (neither can open the other's
port) host, join, contract and talk through the connectivity server. No UDP anywhere. deploy/relay-test/docker-compose.yml.
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

        health = json.loads(inside("peer-a", "import httpx,json; print(json.dumps(httpx.get('http://connectivity:9200/health', trust_env=False).json()))"))
        assert health["attached"] == 2 and health["relayed_bytes"] > 0 and not health["refused"]
    finally:
        A.close()
        B.close()
        compose("down", "-v")
