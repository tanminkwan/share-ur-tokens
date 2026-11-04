"""P6-N on a real genesis, as real processes: the genesis (broker, recorder, god), two brokers of a team group that know
each other, and the founder running `python -m arena.groups`. The group first lives on its brokers alone; then the
founder attaches the genesis ledger: the `group` entry is on the ledger and both brokers name it, also after a restart.
No LLM."""
import json
import os
import subprocess
import sys

from arena.broker.client import BrokerClient
from arena.config import Settings
from arena.peer.groups import GroupModes
from arena.peer.home import PeerHome
from arena.peer.trust_check import RecorderTrust
from arena.recorder.client import RecorderClient
from tests.conftest import make_env
from tests.test_processes import ROOT, Proc, free_port, procs  # noqa: F401  (procs is a fixture)


async def test_a_team_group_without_a_ledger_then_attached_on_a_real_genesis(tmp_path, procs):
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "a", "b")}
    env = make_env(tmp_path, ARENA_GENESIS_DIR=str(tmp_path / "genesis"), ARENA_GENESIS_BROKER_PORT=ports["broker"],
                   ARENA_GENESIS_RECORDER_PORT=ports["rec"], ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"],
                   ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_LLM_BACKEND="none")
    s = Settings.load(env=env, dotenv_path=None)
    founder = PeerHome(str(tmp_path / "founder"), s).identity()
    g = Proc("arena.genesis", env, tmp_path)
    procs.append(g)
    burl = f"http://127.0.0.1:{ports['broker']}"
    g.wait_up(burl)
    g.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    rec_url = (await BrokerClient(burl, s).find("기록", role="record"))["peers"][0]["recorder_url"]

    ua, ub = f"http://127.0.0.1:{ports['a']}", f"http://127.0.0.1:{ports['b']}"

    def team_broker(name, port, neighbor):
        p = Proc("arena.broker", dict(env, ARENA_BROKER_PORT=str(port), ARENA_BROKER_NAME=name, ARENA_BROKER_NEIGHBORS=neighbor,
                                      ARENA_BROKER_GROUP_ID="g-team", ARENA_BROKER_FOUNDER_PUB=founder.pub,
                                      ARENA_BROKER_KEY_FILE=str(tmp_path / f"{name}.key"), ARENA_BROKER_STATE_FILE=str(tmp_path / f"{name}.json")),
                 tmp_path)
        procs.append(p)
        p.wait_up(f"http://127.0.0.1:{port}")
        return p
    team_broker("A", ports["a"], ub)
    pb = team_broker("B", ports["b"], ua)
    A, B = BrokerClient(ua, s), BrokerClient(ub, s)
    pubs = [(await A.health())["pub"], (await B.health())["pub"]]

    def groups(*args):
        full = dict(os.environ, PYTHONPATH=str(ROOT), **env)
        r = subprocess.run([sys.executable, "-m", "arena.groups", *args], env=full, cwd=tmp_path, capture_output=True, text=True, timeout=60)
        return r.returncode, json.loads(r.stdout or "{}"), r.stdout + r.stderr
    home = ("--home", str(tmp_path / "founder"))

    # the genesis group has its ledger from the beginning: nothing to declare there
    code, shown, out = groups("show", "--broker", burl)
    assert code == 0 and shown["genesis"] is True and shown["declaration"] is None, out
    code, bad, out = groups("declare", *home, "--broker", burl)
    assert code == 1 and "genesis group" in bad["error"], out

    # P6-N1: the team group on its brokers alone; one broker shares it with the other
    code, d, out = groups("declare", *home, "--broker", ua, "--group-broker", pubs[0], "--group-broker", pubs[1])
    assert code == 0 and d["declaration"]["ledger"] is None and d["declaration"]["ver"] == 1, out
    assert (await B.group())["declaration"] == d["declaration"]

    R = RecorderClient(rec_url, s)
    recorder = lambda url: RecorderClient(url, s)
    trust = RecorderTrust(lambda: s, recorder)

    async def group_id(_):
        return "g-team"

    async def ledger_id(url):
        return (await trust.check(url)).get("ledger_id")
    modes = GroupModes({"team": B}, group_id, recorder, trust.check, ledger_id, lambda: s, lambda: 0.0)
    assert (await modes.mode("team", fresh=True))["ledger"] is False

    # P6-N3: attach the genesis ledger; the group entry is the founder's, and both brokers name it
    code, at, out = groups("attach", *home, "--broker", ub, "--recorder", rec_url)
    assert code == 0 and at["declaration"]["ver"] == 2, out
    v = await R.verify(at["entry"])
    assert v["exists"] and v["type"] == "group" and v["group_id"] == "g-team" and v["founder"] == founder.pub
    assert (await A.group())["declaration"]["ledger"]["entry"] == at["entry"]
    m = await modes.mode("team", fresh=True)
    assert m["ledger"] and m["proven"] and m["attached"]["ledger_id"] == (await R.trust())["ledger_id"]
    code, again, out = groups("attach", *home, "--broker", ua, "--recorder", rec_url)
    assert code == 1 and "already keeps a ledger" in again["error"], out

    # the broker keeps it across a restart
    pb.stop()
    team_broker("B", ports["b"], ua)
    assert (await B.group())["declaration"]["ledger"]["entry"] == at["entry"]
