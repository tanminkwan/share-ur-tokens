"""P8-A1, P8-A3: the offline machine's commands. The god key is made and kept only encrypted, the module loads no
networking code, and nothing is signed before the person has read the request and said yes."""
import io
import json
import os
import subprocess
import sys

import pytest

from arena.ceremony import cli
from arena.ceremony import formats as F
from arena.ceremony.offline import describe, make_god_key, open_god_key
from arena.crypto import Identity
from tests.test_processes import ROOT

PASS = "correct horse battery staple"


def test_p8a1_the_offline_commands_load_no_networking_code():
    code = ("import sys, arena.ceremony.cli as c, arena.ceremony.offline; "
            "c.parser().parse_args(['sign','--key','k','--request','r','--out','o']); "
            "print(sorted(m for m in ('httpx', 'uvicorn', 'starlette', 'a2a', 'arena.recorder.client') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT)))
    assert r.stdout.strip() == "[]", r.stdout + r.stderr


def test_p8a1_the_god_key_is_made_once_and_only_encrypted(settings, tmp_path):
    pub = make_god_key(str(tmp_path), PASS, settings)
    assert sorted(os.listdir(tmp_path)) == ["god-key.json", "god.pub"]
    sealed = (tmp_path / "god-key.json").read_text()
    god = open_god_key(str(tmp_path / "god-key.json"), PASS, settings)
    assert god.pub == pub and god.private_hex() not in sealed and oct(os.stat(tmp_path / "god-key.json").st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        make_god_key(str(tmp_path), PASS, settings)  # never overwritten: a god key is made once


def args(*a):
    return cli.parser().parse_args(list(a))


def test_p8a3_the_request_is_shown_and_nothing_is_signed_without_a_yes(settings, tmp_path, monkeypatch):
    make_god_key(str(tmp_path), PASS, settings)
    god = open_god_key(str(tmp_path / "god-key.json"), PASS, settings)
    p = {"group_id": "public", "god": god.pub, "broker": "b" * 64, "recorder": "c" * 64}
    req = F.request(1, "trunk", None, god.pub, [F.item("genesis", "genesis", p, [god.pub])], 1.0)
    (tmp_path / "r.json").write_text(json.dumps(req))
    monkeypatch.setenv("P", PASS)
    a = args("sign", "--key", str(tmp_path / "god-key.json"), "--request", str(tmp_path / "r.json"), "--out", str(tmp_path / "s.json"),
             "--passphrase-env", "P")
    shown = io.StringIO()
    assert cli.command(a, settings, out=shown, ask=lambda q: "n") == {"ok": False, "error": "not signed"}
    assert not (tmp_path / "s.json").exists()
    text = shown.getvalue()
    assert "round 1 · chain trunk" in text and "genesis (genesis) [sign]" in text and god.pub[:16] in text
    assert cli.command(a, settings, out=io.StringIO(), ask=lambda q: "y")["signed"] == ["genesis"]
    assert F.collect(req, [json.loads((tmp_path / "s.json").read_text())])[1] is None


def test_describe_marks_the_items_another_key_signs(settings):
    god, new = Identity.generate(), Identity.generate()
    req = F.request(2, "trunk", "a" * 64, god.pub, [F.item("key_rotate", "key_rotate", {"role": "god", "old": god.pub, "new": new.pub},
                                                          [god.pub, new.pub]), F.item("x", "x", {"a": 1}, [new.pub])], 1.0)
    lines = describe(req, god.pub)
    assert "- key_rotate (key_rotate) [sign]" in lines and "- x (x) [other key signs]" in lines
