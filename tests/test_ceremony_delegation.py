"""FG-F4, F5 (dev/founding/design.md 4, 5): god's delegates in the ceremony and after it; a branch ceremony allowed by a
founding pass or by the trunk god's approval (signed offline like everything god signs)."""
import asyncio
import json
import os

import pytest

from arena.ceremony import formats as F
from arena.ceremony import rotate
from arena.ceremony import run as R
from arena.crypto import Identity
from arena.ledger import JsonlStore
from arena.ledger.delegation import active_delegates
from arena.recorder.client import InMemoryRecorderClient
from tests.test_ceremony_run import captured, fast  # noqa: F401  (captured is a fixture)
from tests.test_delegation import a_pass, delegation
from tests.test_trust import Net, net  # noqa: F401  (net is a fixture)


async def offline(folder, keys, rounds):
    """sign each round's request with every given key that is a signer there"""
    done = 0
    while done < rounds:
        path = os.path.join(folder, R.ROUNDS, f"round-{done + 1}.request.json")
        if os.path.exists(path):
            req = json.load(open(path, encoding="utf-8"))
            for i, k in enumerate(keys):
                if any(k.pub in x["signers"] for x in req["items"]):
                    json.dump(F.sign(req, k), open(path.replace("request", f"signatures-{i}"), "w"))
            done += 1
        await asyncio.sleep(0.01)


def witnesses():
    return [Identity.generate().pub, Identity.generate().pub]


async def ceremony(settings, folder, god, keys, rounds, **kw):
    signer = asyncio.create_task(offline(folder, keys, rounds))
    out = await R.run(fast(settings), god.pub, folder, witnesses(), say=lambda _: None, **kw)
    await signer
    return out


async def test_fgf5_the_trunk_ceremony_records_god_s_delegates_after_the_handover(settings, tmp_path, captured):
    god, d1, d2 = Identity.generate(), Identity.generate(), Identity.generate()
    folder = str(tmp_path / "c")
    out = await ceremony(settings, folder, god, [god], 2, delegates=[d1.pub, d2.pub])
    raw = JsonlStore(os.path.join(folder, R.LEDGER)).load()
    assert [e["type"] for e in raw] == ["genesis", "key_rotate", "delegate", "delegate"]
    assert set(active_delegates(raw)) == {d1.pub, d2.pub} and out["delegates"] == [d1.pub, d2.pub]
    req = json.load(open(os.path.join(folder, R.ROUNDS, "round-2.request.json")))
    assert [x["name"] for x in req["items"]] == ["key_rotate", "delegate-1", "delegate-2"]  # one offline session signs all three
    d = json.load(open(os.path.join(folder, R.DECLARATION)))
    assert d["body"]["head"] == {"seq": 3, "hash": raw[3]["hash"]} and d["body"]["handover"] == raw[1]["hash"]
    steps = [json.loads(x)["step"] for x in open(os.path.join(folder, R.LOG))]
    assert steps.count("delegated") == 2 and steps.index("rotated") < steps.index("delegated") < steps.index("first-key-gone")


async def test_fgf5_after_the_ceremony_god_delegates_and_takes_back_offline(settings, tmp_path, captured):
    god, d1 = Identity.generate(), Identity.generate()
    folder = str(tmp_path / "c")
    await ceremony(settings, folder, god, [god], 2)
    r = rotate.delegate_request(fast(settings), folder, d1.pub)
    req = json.load(open(r["request"]))
    assert req["items"][0]["type"] == "delegate" and req["round"] == 3
    assert (await rotate.delegate_apply(fast(settings), folder, req, [F.sign(req, god)]))["ok"]
    raw = JsonlStore(os.path.join(folder, R.LEDGER)).load()
    assert set(active_delegates(raw)) == {d1.pub}
    r = rotate.delegate_request(fast(settings), folder, d1.pub, undo=True)
    req = json.load(open(r["request"]))
    done = await rotate.delegate_apply(fast(settings), folder, req, [F.sign(req, god)])
    assert done["ok"] and done["kind"] == "undelegate"
    assert active_delegates(JsonlStore(os.path.join(folder, R.LEDGER)).load()) == {}
    assert "still needs" in (await rotate.delegate_apply(fast(settings), folder, req, []))["error"]


async def test_fgf4_the_ceremony_checks_the_allowance_before_any_key_is_made(settings, tmp_path):
    god = Identity.generate()
    pass_other = a_pass(Identity.generate(), Identity.generate())
    cases = [("for a branch ceremony", dict(pass_doc=a_pass(Identity.generate(), god))),
             ("exactly one of", dict(parent=object())),
             ("exactly one of", dict(parent=object(), pass_doc=a_pass(Identity.generate(), god), approver=Identity.generate().pub)),
             ("another founder", dict(parent=object(), pass_doc=pass_other)),
             ("trunk ceremony", dict(parent=object(), approver=Identity.generate().pub, delegates=[Identity.generate().pub])),
             ("not the god key", dict(delegates=[god.pub]))]
    for i, (why, kw) in enumerate(cases):
        folder = tmp_path / f"c{i}"
        with pytest.raises(R.Aborted, match=why):
            await R.run(fast(settings), god.pub, str(folder), witnesses(), say=lambda _: None, **kw)
        assert not (folder / R.BROKER_KEY).exists()


async def test_fgf4_a_branch_ceremony_with_a_delegate_s_pass(settings, tmp_path, captured, net):
    sphinx, god = Identity.generate(), Identity.generate()
    assert (await delegation(net, "delegate", sphinx))["ok"]
    folder = str(tmp_path / "b")
    out = await ceremony(settings, folder, god, [god], 3, parent=InMemoryRecorderClient(net.svc), parent_url="mem://root",
                         name="team-a", pass_doc=a_pass(sphinx, god))
    link = net.svc.link(out["ledger_id"])["link"]
    assert link["payload"]["pass"]["body"]["founder"] == god.pub and "approver" not in link["payload"]
    assert [e["type"] for e in JsonlStore(os.path.join(folder, R.LEDGER)).load()] == ["genesis", "parent_link", "key_rotate"]


async def test_fgf4_a_branch_ceremony_the_trunk_god_approves_offline(settings, tmp_path, captured, net):
    god = Identity.generate()
    folder = str(tmp_path / "b")
    out = await ceremony(settings, folder, god, [god, net.god], 3, parent=InMemoryRecorderClient(net.svc), parent_url="mem://root",
                         name="team-b", approver=net.god.pub)
    req = json.load(open(os.path.join(folder, R.ROUNDS, "round-2.request.json")))
    assert next(x for x in req["items"] if x["name"] == "chain_link")["signers"] == [god.pub, net.god.pub]
    link = net.svc.link(out["ledger_id"])["link"]
    assert link["payload"]["approver"] == net.god.pub and net.god.pub in link["sigs"]
