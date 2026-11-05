"""P8-E4: the root-key ceremony rehearsed as real processes, start to end (user principle: new features also on a real
genesis as real processes). The offline machine is its own folder and its own processes (god-key, sign); the ceremony
machine runs ceremony run; arena.genesis takes the folder over; witnesses sign; one records; anyone verifies."""
import json
import os
import subprocess
import sys
import time

import httpx

from arena.crypto import Identity
from arena.ledger.trust import verify_trust
from arena.recorder.client import RecorderClient
from arena.config import Settings
from tests.conftest import make_env
from tests.test_processes import ROOT, Proc, free_port, procs  # noqa: F401  (procs is a fixture)

PASS = "correct horse battery staple"


def cli(env, cwd, *args, ok=True) -> dict:
    full = dict(os.environ, PYTHONPATH=str(ROOT), CEREMONY_PASS=PASS, **env)
    r = subprocess.run([sys.executable, "-m", "arena.ceremony", *args], env=full, cwd=cwd, capture_output=True, text=True, timeout=120)
    out = json.loads(r.stdout[r.stdout.index("{\n"):]) if "{\n" in r.stdout else {"ok": False, "raw": r.stdout + r.stderr}
    assert out.get("ok") is ok, (args, out, r.stderr)
    return out


def sign_round(env, tmp, offline, folder, n, key="god-key.json", suffix=""):
    req = os.path.join(folder, "rounds", f"round-{n}.request.json")
    end = time.time() + 30
    while not os.path.exists(req):
        assert time.time() < end, f"round {n} request never appeared"
        time.sleep(0.05)
    return cli(env, tmp, "sign", "--key", os.path.join(offline, key), "--request", req, "--out",
               req.replace("request", "signatures" + suffix), "--yes", "--passphrase-env", "CEREMONY_PASS")


def genesis_env(tmp, folder, ports):
    return make_env(tmp, ARENA_GENESIS_DIR=folder, ARENA_GENESIS_BROKER_PORT=ports["broker"], ARENA_GENESIS_RECORDER_PORT=ports["rec"],
                    ARENA_GENESIS_RECORDER_API_PORT=ports["api"], ARENA_GENESIS_GOD_PORT=ports["god"], ARENA_GENESIS_GOD_WEB_PORT=ports["web"],
                    ARENA_RECORDER_REQUIRE_GROUP="true", ARENA_GOD_CACHE_SEC="0")


def start_genesis(procs, env, tmp, ports):
    g = Proc("arena.genesis", env, tmp)
    procs.append(g)
    g.wait_up(f"http://127.0.0.1:{ports['god']}", path="/.well-known/agent-card.json")
    return g


async def test_p8e4_rehearsal_of_the_trunk_ceremony_as_real_processes(tmp_path, procs):
    env = make_env(tmp_path, ARENA_CEREMONY_POLL_SEC="0.05", ARENA_CEREMONY_TIMEOUT_SEC="60")
    offline, folder = str(tmp_path / "offline"), str(tmp_path / "ceremony")
    god = cli(env, tmp_path, "god-key", "--out", offline, "--passphrase-env", "CEREMONY_PASS")["god"]
    assert sorted(os.listdir(offline)) == ["god-key.json", "god.pub"]  # no plaintext god key file anywhere
    assert json.load(open(os.path.join(offline, "god-key.json")))["format"] == "arena-key-backup"
    w = [Identity.generate() for _ in range(2)]
    for i, k in enumerate(w):
        k.save(str(tmp_path / f"w{i}.key"))

    run = Proc("arena.ceremony", env, tmp_path, args=["run", "--god-pub", os.path.join(offline, "god.pub"), "--out", folder,
                                                      "--witness", w[0].pub, "--witness", w[1].pub, "--note", "rehearsal"])
    procs.append(run)
    assert sign_round(env, tmp_path, offline, folder, 1)["signed"] == ["genesis"]
    assert sign_round(env, tmp_path, offline, folder, 2)["signed"] == ["key_rotate"]
    assert run.p.wait(60) == 0, run.p.stdout.read().decode()
    assert not os.path.exists(os.path.join(folder, "god.key"))

    # arena.genesis takes the folder over: god.pub only, the observer key reads, the operating key seals
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    genv = genesis_env(tmp_path, folder, ports)
    g = start_genesis(procs, genv, tmp_path, ports)
    s = Settings.load(env=genv, dotenv_path=None)
    R = RecorderClient(f"http://127.0.0.1:{ports['api']}", s)
    doc = await R.trust()
    anchor = open(os.path.join(folder, "trust-anchor.md")).read()
    ledger_id = next(x.split("=", 1)[1] for x in anchor.splitlines() if x.startswith("ARENA_TRUST_GENESIS_HASH="))
    ok, why, keys = verify_trust(doc, ledger_id, god)  # what a peer with ARENA_TRUST_* does
    assert ok, why
    assert keys["god"] == god and keys["recorder"] == Identity.load(os.path.join(folder, "recorder.key")).pub
    me = Identity.generate()
    p = {"author": me.pub, "content_hash": "ab" * 32, "purpose": "authorship", "group_id": "public", "ledger_id": ledger_id, "nonce": "x1"}
    r = await R.record("publish", p, {me.pub: me.sign(p)})
    assert r["ok"] and r["seal"]["pub"] == keys["recorder"]  # life goes on, sealed by the operating key

    # the witnesses sign, one records, anyone verifies
    decl = os.path.join(folder, "retirement.json")
    assert cli(env, tmp_path, "verify", "--declaration", decl, "--recorder", f"http://127.0.0.1:{ports['api']}", ok=False)["checks"][0]["ok"] is False
    for i in range(2):
        cli(env, tmp_path, "witness", "--declaration", decl, "--key-file", str(tmp_path / f"w{i}.key"), "--yes")
    pub = cli(env, tmp_path, "publish", "--declaration", decl, "--key-file", str(tmp_path / "w0.key"), "--recorder", f"http://127.0.0.1:{ports['api']}")
    v = cli(env, tmp_path, "verify", "--declaration", decl, "--recorder", f"http://127.0.0.1:{ports['api']}")
    assert v["anchored"] and all(c["ok"] for c in v["checks"]) and (await R.verify(pub["entry"]))["purpose"] == "retirement"

    # the observer window reads as the observer key, not god
    token = open(os.path.join(folder, "homes", "god", "web-token")).read().strip()
    st = httpx.get(f"http://127.0.0.1:{ports['web']}/api/state", headers={"Authorization": f"Bearer {token}"}, timeout=5, trust_env=False).json()
    assert st["me"]["reads_as"] == "observer" and st["me"]["god"]["pub"] == god
    assert st["me"]["pub"] == Identity.load(os.path.join(folder, "observer.key")).pub

    # later: stop, hand the operating key to the next one (god signs offline again), start, the same ledger goes on
    g.stop()
    req = cli(env, tmp_path, "rotate-request", "--dir", folder)
    sig = req["request"].replace("request", "signatures")
    cli(env, tmp_path, "sign", "--key", os.path.join(offline, "god-key.json"), "--request", req["request"], "--out", sig, "--yes",
        "--passphrase-env", "CEREMONY_PASS")
    rot = cli(env, tmp_path, "rotate", "--dir", folder, "--request", req["request"], "--signatures", sig)
    assert rot["new"] == req["new"] and not os.path.exists(os.path.join(folder, "recorder.next.key"))
    assert not [f for f in os.listdir(folder) if "retired" in f]
    start_genesis(procs, genv, tmp_path, ports)
    doc2 = await R.trust()
    assert doc2["ledger_id"] == ledger_id and verify_trust(doc2, ledger_id, god)[2]["recorder"] == req["new"]
    me2 = Identity.generate()
    p2 = dict(p, author=me2.pub, content_hash="cd" * 32, nonce="x2")
    assert (await R.record("publish", p2, {me2.pub: me2.sign(p2)}))["seal"]["pub"] == req["new"]


async def test_p8e2_a_folder_with_god_pub_and_no_ledger_does_not_start(tmp_path, procs):
    folder = tmp_path / "g"
    folder.mkdir()
    (folder / "god.pub").write_text(Identity.generate().pub + "\n")
    ports = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    g = Proc("arena.genesis", genesis_env(tmp_path, str(folder), ports), tmp_path)
    procs.append(g)
    assert g.p.wait(30) != 0
    assert "ceremony run first" in g.p.stdout.read().decode()


async def test_p8e4_branch_ceremony_links_into_a_running_trunk(tmp_path, procs):
    """three rounds: genesis (with parent); chain_link + key_rotate; parent_link. The trunk keeps the chain_link, the branch
    holds parent_link at 1 and the handover at 2; arena.genesis takes the branch folder over with the trunk named"""
    trunk_dir = tmp_path / "trunk"
    tp = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    start_genesis(procs, genesis_env(tmp_path, str(trunk_dir), tp), tmp_path, tp)  # the trunk, the rehearsal way
    trunk = f"http://127.0.0.1:{tp['api']}"
    env = make_env(tmp_path, ARENA_CEREMONY_POLL_SEC="0.05", ARENA_CEREMONY_TIMEOUT_SEC="60", ARENA_RECORDER_REQUIRE_GROUP="true")
    offline, folder = str(tmp_path / "offline"), str(tmp_path / "branch")
    god = cli(env, tmp_path, "god-key", "--out", offline, "--passphrase-env", "CEREMONY_PASS")["god"]
    w = [Identity.generate().pub for _ in range(2)]
    # the trunk god approves this branch offline too (FG-C4): its key sealed into a backup on the offline side
    from arena.keys.backup import seal_backup
    trunk_god = Identity.load(str(trunk_dir / "god.key"))
    json.dump(seal_backup(trunk_god, PASS, s := Settings.load(env=env, dotenv_path=None)), open(os.path.join(offline, "trunk-god-key.json"), "w"))
    run = Proc("arena.ceremony", env, tmp_path, args=["run", "--god-pub", os.path.join(offline, "god.pub"), "--out", folder, "--witness", w[0],
                                                      "--witness", w[1], "--parent", trunk, "--name", "team-a", "--approver", trunk_god.pub])
    procs.append(run)
    for n, items in ((1, ["genesis"]), (2, ["chain_link", "key_rotate"]), (3, ["parent_link"])):
        assert sign_round(env, tmp_path, offline, folder, n)["signed"] == items
        if n == 2:
            assert sign_round(env, tmp_path, offline, folder, n, key="trunk-god-key.json", suffix="-trunk")["signed"] == ["chain_link"]
    assert run.p.wait(60) == 0, run.p.stdout.read().decode()

    from arena.ledger import JsonlStore
    raw = JsonlStore(os.path.join(folder, "ledger.jsonl")).load()
    assert [e["type"] for e in raw] == ["genesis", "parent_link", "key_rotate"]
    T = RecorderClient(trunk, s)
    link = (await T.link(raw[0]["hash"]))["link"]
    assert link["payload"]["child_god"] == god and link["payload"]["name"] == "team-a" and link["payload"]["approver"] == trunk_god.pub
    assert link["payload"]["child_recorder"] == raw[0]["payload"]["recorder"] != raw[2]["payload"]["new"]  # the first key signed it, then went

    bp = {k: free_port() for k in ("broker", "rec", "api", "god", "web")}
    benv = dict(genesis_env(tmp_path, folder, bp), ARENA_GENESIS_PARENT_RECORDER_URL=trunk)
    start_genesis(procs, benv, tmp_path, bp)
    B = RecorderClient(f"http://127.0.0.1:{bp['api']}", s)
    assert (await B.health())["ledger_id"] == raw[0]["hash"] and (await B.audit())["status"] == "ok"
