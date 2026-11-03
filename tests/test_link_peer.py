"""Permanent links (user 2026-11-03: "영구적인 api 서비스 특수 peer를 만들어서 여기에 link를 달고, 실제 url 등은 향후 바뀔
수 있으니 게시자가 변경할 수 있도록 해. 원장은 변하지 않고 물리적인 link만 변할 수 있도록"; "link peer 또한 다른 누군가가
스스로 공신력을 얻어서 만들 수 있음"). The ledger names <link peer>/<link id>; the link peer keeps where the work is now;
only its owner's current key changes it; a reader checks the owner's signature, so a link peer cannot forge it."""
import dataclasses
import io
import json

from arena.content import register_work, relink, resolve_link
from arena.content.cli import parser, run
from arena.content.links import link_id, make_link
from arena.crypto import Identity
from arena.keys.lineage import commit_entry, rotate_entry
from arena.peer.link_role import LinkRole
from arena.recorder.client import InMemoryRecorderClient
from tests.test_event_apps import World

PLACE = [{"kind": "https", "location": "https://old.example/novel.txt"}]
MOVED = [{"kind": "https", "location": "https://new.example/novel.txt"}, {"kind": "ipfs", "location": "bafy-novel"}]


async def world(tmp_path, settings, **over):
    s = dataclasses.replace(settings, link_peer_recorder_url="mem://rec", **over)
    w = World(tmp_path, s)
    await w.boot()
    lp = w.peer("links", [LinkRole(s)])
    return w, s, lp, lp.handle


async def test_the_link_peer_keeps_versions_only_the_owner_may_add(tmp_path, settings):
    w, s, lp, ask = await world(tmp_path, settings)
    me = Identity.generate()
    v1 = make_link(me, me.pub, "novel", 1, PLACE, 1.0)
    r = await ask({"op": "link.set", "link": v1})
    assert r["ok"] and (r["peer"], r["id"]) == (lp.identity.pub, link_id(me.pub, "novel"))
    assert "ver must be 2" in (await ask({"op": "link.set", "link": make_link(me, me.pub, "novel", 3, MOVED, 2.0)}))["error"]
    assert (await ask({"op": "link.set", "link": make_link(me, me.pub, "novel", 2, MOVED, 2.0)}))["ok"]
    got = await ask({"op": "link.get", "id": v1["id"]})
    assert got["link"]["ver"] == 2 and got["link"]["targets"] == MOVED
    assert [x["ver"] for x in (await ask({"op": "link.history", "id": v1["id"]}))["versions"]] == [1, 2]
    thief = Identity.generate()
    forged = make_link(thief, me.pub, "novel", 3, [{"kind": "https", "location": "https://evil.example"}], 3.0)
    assert "only the link's owner" in (await ask({"op": "link.set", "link": forged}))["error"]
    bent = dict(make_link(me, me.pub, "novel", 3, MOVED, 3.0), targets=PLACE)
    assert "signature" in (await ask({"op": "link.set", "link": bent}))["error"]
    other = make_link(me, me.pub, "novel", 3, MOVED, 3.0, content_hash="c" * 64)
    assert "keeps its owner, name and content hash" in (await ask({"op": "link.set", "link": other}))["error"]
    assert "registered kind" in (await ask({"op": "link.set", "link": make_link(me, me.pub, "x", 1, [{"kind": "link", "peer": "a" * 64, "link_id": "b" * 32}], 1.0)}))["error"]
    assert "1 to" in (await ask({"op": "link.set", "link": make_link(me, me.pub, "y", 1, [], 1.0)}))["error"]
    assert "registered kind" in (await ask({"op": "link.set", "link": make_link(me, me.pub, "z", 1, [{"kind": "ftp", "location": "x"}], 1.0)}))["error"]
    assert "id is not the one" in (await ask({"op": "link.set", "link": dict(v1, id="0" * 32)}))["error"]
    assert "needs id, owner" in (await ask({"op": "link.set", "link": {"id": "x"}}))["error"]
    assert "no such link" in (await ask({"op": "link.get", "id": "nothing"}))["error"]
    assert "no such link" in (await ask({"op": "link.history", "id": "nothing"}))["error"]
    assert (await ask({"op": "link.info"}))["pub"] == lp.identity.pub
    assert "영구 link" in (await lp.advertise())["offers"]


async def test_after_key_rotation_the_new_key_moves_links_and_the_old_one_cannot(tmp_path, settings):
    w, s, lp, ask = await world(tmp_path, settings)
    me, nxt, after = Identity.generate(), Identity.generate(), Identity.generate()
    assert (await ask({"op": "link.set", "link": make_link(me, me.pub, "novel", 1, PLACE, 1.0)}))["ok"]
    p, sigs = commit_entry(me, nxt, "public", w.svc.ledger.chain[0]["hash"])
    assert (await w.svc.record("key_commit", p, sigs))["ok"]
    p, sigs = rotate_entry(me.pub, nxt, after, "public", w.svc.ledger.chain[0]["hash"])
    assert (await w.svc.record("peer_rotate", p, sigs))["ok"]
    stolen = make_link(me, me.pub, "novel", 2, [{"kind": "https", "location": "https://evil.example"}], 2.0)
    assert "only the link's owner" in (await ask({"op": "link.set", "link": stolen}))["error"]  # the old key was rotated away
    assert (await ask({"op": "link.set", "link": make_link(nxt, me.pub, "novel", 2, MOVED, 2.0)}))["ok"]
    rec = InMemoryRecorderClient(w.svc)
    got = await resolve_link(ask, link_id(me.pub, "novel"), s, me.pub, rec.key)
    assert got["ok"] and got["targets"] == MOVED and got["signer"] == nxt.pub
    assert "not signed by its owner" in (await resolve_link(ask, link_id(me.pub, "novel"), s, me.pub, None))["error"]  # without asking a recorder


async def test_a_work_names_only_the_link_and_its_author_moves_it(tmp_path, settings):
    w, s, lp, ask = await world(tmp_path, settings)
    me = Identity.generate()
    rec = InMemoryRecorderClient(w.svc)
    r = await register_work(me, "소설 본문".encode(), rec, "mem://rec", "public", storage=PLACE, link_ask=ask, link_via="http://links.example")
    assert r["ok"]
    ref = r["reference"]
    lid = ref["link"]["id"]
    entry = w.svc.ledger.chain[r["receipt"]["seq"]]["payload"]
    assert entry["ref"]["storage"] == [{"kind": "link", "peer": lp.identity.pub, "link_id": lid, "via": "http://links.example"}]  # no URL on the ledger
    assert "영구 link" in r["colophon"] and "link=" in r["uri"]
    assert (await resolve_link(ask, lid, s, me.pub, rec.key))["targets"] == PLACE
    moved = await relink(me, ask, lid, MOVED, s)
    assert moved["ok"] and moved["ver"] == 2
    assert (await resolve_link(ask, lid, s, me.pub, rec.key))["targets"] == MOVED
    assert w.svc.ledger.chain[r["receipt"]["seq"]]["payload"] == entry  # the ledger did not change
    assert "someone other than the work's author" in (await resolve_link(ask, lid, s, Identity.generate().pub))["error"]
    # a link peer that lies (changes the places it keeps) is caught by the owner's signature
    state = lp.ctx(lp.app(LinkRole)).state
    st = state.load()
    st["links"][lid][-1]["targets"] = [{"kind": "https", "location": "https://evil.example"}]
    state.save(st)
    assert "does not check" in (await resolve_link(ask, lid, s, me.pub, rec.key))["error"]
    assert "does not check" in (await relink(me, ask, lid, MOVED, s))["error"]
    assert "no such link" in (await relink(me, ask, "nothing", MOVED, s))["error"]
    assert "no such link" in (await resolve_link(ask, "nothing", s))["error"]


async def test_the_ledger_checks_a_link_place_by_its_own_fields(tmp_path, settings):
    """the link's identifiers are fields of their own (code reads them; nothing is parsed out of a text)"""
    w, s, lp, ask = await world(tmp_path, settings)
    me = Identity.generate()
    n = iter(range(100))

    async def publish(place):
        ch = f"{next(n):064x}"
        p = {"author": me.pub, "content_hash": ch, "group_id": "public", "ledger_id": w.svc.ledger.chain[0]["hash"],
             "ref": {"content_hash": ch, "storage": [place]}}
        return await w.svc.record("publish", p, {me.pub: me.sign(p)})
    good = {"kind": "link", "peer": "a" * 64, "link_id": "b" * 32}
    assert "names peer" in (await publish(dict(good, peer="not-a-key")))["error"]
    assert "needs link_id" in (await publish({"kind": "link", "peer": "a" * 64}))["error"]
    assert "not location" in (await publish(dict(good, location="a" * 64 + "/" + "b" * 32)))["error"]  # no packed text
    assert "via" in (await publish(dict(good, via="")))["error"]
    assert "needs location" in (await publish({"kind": "https"}))["error"]
    assert (await publish(dict(good, via="http://links.example")))["ok"]


async def test_the_command_line_registers_relinks_and_resolves(tmp_path, settings):
    w, s, lp, ask = await world(tmp_path, settings)
    rec = InMemoryRecorderClient(w.svc)
    f = tmp_path / "poem.txt"
    f.write_text("시 한 편\n", encoding="utf-8")

    async def cli(*args):
        out = io.StringIO()
        code = await run(parser().parse_args(list(args)), s, out, recorder_of=lambda url: rec, link_of=lambda url: ask)
        return code, json.loads(out.getvalue())
    home = str(tmp_path / "author")
    code, reg = await cli("register", "--home", home, "--recorder", "mem://rec", "--file", str(f), "--storage", "https=https://a.example/p",
                          "--link-peer", "http://links.example", "--out", str(tmp_path / "ref.json"))
    assert code == 0 and reg["reference"]["link"]["via"] == "http://links.example"
    code, moved = await cli("relink", "--home", home, "--ref", str(tmp_path / "ref.json"), "--storage", "https=https://b.example/p")
    assert code == 0 and moved["ver"] == 2
    code, now = await cli("resolve", "--ref", str(tmp_path / "ref.json"))
    assert code == 0 and now["targets"] == [{"kind": "https", "location": "https://b.example/p"}]
    code, by_id = await cli("resolve", "--link-id", reg["reference"]["link"]["id"], "--owner", reg["reference"]["author"],
                            "--link-peer", "http://links.example")
    assert code == 0 and by_id["ver"] == 2
    try:
        await cli("resolve", "--link-id", "x")
        raise AssertionError("needs the link peer")
    except SystemExit as e:
        assert "--link-peer" in str(e)
