"""Containers for the API-serving peers (user 2026-11-03: "api 서버 peer들은 독립된 장소에서 따로 실행되니 실행용 디렉토리
분할하고 각각 docker compose 배치해", "broker도 test용으로 별도 디렉토리에", "build 옵션은 docker compose에 넣지 마 분리해").
deploy/<peer>/ holds one compose file and its .env.example; deploy/build.sh builds the one image.
The checks here always run; a real build and run is opt-in (ARENA_TEST_DOCKER=1), and needs docker."""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import time

import httpx
import pytest

from arena.config import Settings

DEPLOY = pathlib.Path(__file__).resolve().parents[1] / "deploy"
DIRS = ["test-broker", "link-peer", "key-peer", "foundation-peer", "app-store-peer", "search-peer", "service-peer"]
COMPOSE_ONLY = {"ARENA_IMAGE", "ARENA_SERVICE_SPEC_FILE"}  # read by compose itself, not by the platform


def keys_known() -> set:
    from dataclasses import fields
    return {f.metadata["key"] for f in fields(Settings) if "key" in f.metadata}


def test_each_peer_has_its_own_directory_compose_and_env_example():
    known = keys_known()
    for d in DIRS:
        compose = (DEPLOY / d / "docker-compose.yml").read_text(encoding="utf-8")
        assert "build:" not in compose, d  # the image is built by deploy/build.sh only
        assert "image: ${ARENA_IMAGE:-agent-arena:latest}" in compose and "network_mode: host" in compose, d
        assert "required: false" in compose and "data:/app/data" in compose, d  # .env read at run time, never baked in
        module = re.search(r'command: \["([\w.]+)"', compose).group(1)
        assert importlib.util.find_spec(module) is not None, (d, module)
        example = (DEPLOY / d / ".env.example").read_text(encoding="utf-8")
        names = {ln.split("=", 1)[0] for ln in example.splitlines() if ln and not ln.startswith("#")}
        assert names - COMPOSE_ONLY <= known, (d, names - COMPOSE_ONLY - known)  # every setting is a real one
    assert "--network host" in (DEPLOY / "build.sh").read_text(encoding="utf-8")
    assert (DEPLOY / "service-peer" / "specs" / "example-service.json").exists()


def test_the_example_service_spec_loads():
    import json
    import sys
    from arena.peer.service import ServiceApp, load_spec
    sys.path.insert(0, str(DEPLOY / "service-peer" / "specs"))
    try:
        spec = load_spec(str(DEPLOY / "service-peer" / "specs" / "example-service.json"))
        app = ServiceApp(Settings.load(env={}, dotenv_path=None), spec)
        assert set(app.ops()) == {"add", "echo"} and json.dumps(spec)
    finally:
        sys.path.remove(str(DEPLOY / "service-peer" / "specs"))


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_every_compose_file_is_valid():
    for d in DIRS:
        r = subprocess.run(["docker", "compose", "config", "-q"], cwd=DEPLOY / d, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (d, r.stderr[-300:])


@pytest.mark.skipif(os.environ.get("ARENA_TEST_DOCKER") != "1" or shutil.which("docker") is None,
                    reason="a real container build and run is opt-in: ARENA_TEST_DOCKER=1")
def test_containers_run_and_a_peer_started_before_its_broker_connects_later():
    def compose(d, *args):
        return subprocess.run(["docker", "compose", *args], cwd=DEPLOY / d, capture_output=True, text=True, timeout=300)

    def wait(check, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if check():
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(1)
        return False
    assert subprocess.run([str(DEPLOY / "build.sh")], capture_output=True, text=True, timeout=900).returncode == 0
    try:
        assert compose("link-peer", "up", "-d").returncode == 0  # before the broker exists
        assert wait(lambda: "아직 연결되지 않음" in compose("link-peer", "logs").stdout, 30)
        assert compose("test-broker", "up", "-d").returncode == 0
        no_proxy = httpx.Client(trust_env=False, timeout=2)
        assert wait(lambda: no_proxy.get("http://127.0.0.1:9100/health").status_code == 200)
        assert wait(lambda: "프로필 게시" in compose("link-peer", "logs").stdout)  # it kept connecting, then posted
        assert no_proxy.post("http://127.0.0.1:9191/ops/link.info", json={}).json()["ok"]
    finally:
        for d in ("link-peer", "test-broker"):
            compose(d, "down", "-v")
