"""CP-4, CP-9, CP-10 (dev/chain-policy.md 6절, user 2026-11-02): "원장에 책 정보를 찍는 것이 아니라 책에 원장 정보를 찍는 거야".

The ledger keeps the body's hash and the author's signature; the book carries the ledger reference; a reader checks a
copy from the book; someone with only a copy finds the registration by the body's hash. Where the content is kept
(`ref`) is optional and vouched for by a registered proof method."""
import dataclasses
import io
import json

import pytest

from arena.content import check_work, colophon, from_uri, make_reference, register_work, to_uri
from arena.content.cli import parser, run
from arena.crypto import Identity
from arena.ledger.refs import CONTENT_FORMS, content_hash_of, form_bytes, proof_target
from arena.recorder.client import InMemoryRecorderClient
from tests.test_trust import Child, Net, net  # noqa: F401  (net is a fixture)

NOVEL = "첫 문장.\r\n둘째 문장.\n".encode("utf-8")


# ---------------- CP-9: how a work becomes bytes ----------------
def test_cp9_the_text_form_makes_one_body_of_many_copies():
    import unicodedata
    lf = "한글 소설\n둘째 줄\n"
    variants = [lf.encode(), ("﻿" + lf).encode(), lf.replace("\n", "\r\n").encode(), lf.replace("\n", "\r").encode(),
                unicodedata.normalize("NFD", lf).encode()]  # BOM, Windows and old Mac line ends, Hangul decomposed (macOS)
    assert len({content_hash_of(v, "utf8-nfc-lf") for v in variants}) == 1
    assert len({content_hash_of(v, "bytes") for v in variants}) == len(variants)  # bytes: exactly the file
    assert form_bytes("utf8-nfc-lf", variants[4]) == lf.encode()
    with pytest.raises(UnicodeDecodeError):
        content_hash_of(b"\xff\xfe not utf-8", "utf8-nfc-lf")
    with pytest.raises(ValueError, match="unknown content form"):
        content_hash_of(b"x", "pdf-text")
    assert set(CONTENT_FORMS) == {"bytes", "utf8-nfc-lf"}


def test_cp9_the_reference_round_trips_and_names_what_never_changes():
    ref = make_reference("a" * 64, "b" * 64, 7, 1761955200.0, "c" * 64, "utf8-nfc-lf", "d" * 64, "http://rec.example/api", did="did:web:author.example")
    back = from_uri(to_uri(ref))
    assert {k: back[k] for k in ("ledger_id", "entry", "content_hash", "form", "author", "recorder_url", "did")} == \
        {k: ref[k] for k in ("ledger_id", "entry", "content_hash", "form", "author", "recorder_url", "did")}
    text = colophon(ref)
    assert "원장 식별자: " + "a" * 64 in text and "7번" in text and "arena-ref:" in text and "did:web:author.example" in text
    with pytest.raises(ValueError, match="not an arena-ref"):
        from_uri("https://example.com/x")
    with pytest.raises(ValueError, match="lacks"):
        from_uri("arena-ref:" + "a" * 64 + "/" + "b" * 64 + "?form=bytes")


# ---------------- CP-4: the ref block ----------------
async def test_cp4_the_ledger_checks_the_ref_block_and_its_proof(net, settings):
    me = Identity.generate()
    ch = content_hash_of(NOVEL, "utf8-nfc-lf")

    async def publish(**extra):
        p = {"author": me.pub, "content_hash": ch, "purpose": "authorship", "group_id": "public", "ledger_id": net.ledger_id, **extra}
        return await net.svc.record("publish", p, {me.pub: me.sign(p)})
    place = [{"kind": "https", "location": "https://example.com/novel.txt"}]
    assert "own content_hash" in (await publish(ref={"content_hash": "0" * 64, "storage": place}))["error"]
    assert "1 to" in (await publish(ref={"content_hash": ch, "storage": []}))["error"]
    assert "registered kind" in (await publish(ref={"content_hash": ch, "storage": [{"kind": "ftp", "location": "x"}]}))["error"]
    assert "location of at most" in (await publish(ref={"content_hash": ch, "storage": [{"kind": "https", "location": "x" * (settings.ref_location_max + 1)}]}))["error"]
    assert "number of bytes" in (await publish(ref={"content_hash": ch, "storage": place, "size": -1}))["error"]
    assert "media_type" in (await publish(ref={"content_hash": ch, "storage": place, "media_type": ""}))["error"]
    assert "proof.method" in (await publish(ref={"content_hash": ch, "storage": place, "proof": {"method": "rsa"}}))["error"]
    assert "signer and sig" in (await publish(ref={"content_hash": ch, "storage": place, "proof": {"method": "ed25519"}}))["error"]
    other = Identity.generate()
    forged = {"content_hash": ch, "storage": place}
    forged["proof"] = {"method": "ed25519", "signer": me.pub, "sig": other.sign(proof_target(forged))}
    assert "does not verify" in (await publish(ref=forged))["error"]
    assert "how is a link" in (await publish(ref={"content_hash": ch, "storage": place, "proof": {"method": "sha256", "how": 3}}))["error"]
    assert "registered content form" in (await publish(form="docx"))["error"]
    good = {"content_hash": ch, "storage": place, "size": len(NOVEL), "media_type": "text/plain"}
    good["proof"] = {"method": "ed25519", "signer": me.pub, "sig": me.sign(proof_target(good))}
    r = await publish(ref=good, form="utf8-nfc-lf")
    assert r["ok"]
    v = net.svc.verify(r["hash"])
    assert v["form"] == "utf8-nfc-lf" and "ref" not in v  # public verify shows the form; where it is stays out of the public view


async def test_cp4_a_share_keeps_its_ref_in_the_private_envelope(net, settings):
    from arena.ledger import split_payload
    a, b = Identity.generate(), Identity.generate()
    assert (await net.publish(a, "z"))["ok"]
    ch = "z" * 8  # what Net.publish registered
    full = {"provider": a.pub, "consumer": b.pub, "content_hash": ch, "nonce": "n1", "group_id": "public", "ledger_id": net.ledger_id,
            "ref": {"content_hash": ch, "storage": [{"kind": "peer", "location": a.pub + "/notes.md"}], "proof": {"method": "sha256"}}}
    body, private = split_payload("share", full)
    assert "ref" in private and "ref" not in body
    sigs = {a.pub: a.sign(body), b.pub: b.sign(body)}
    assert (await net.svc.record("share", body, sigs, private))["ok"]
    exposed = dict(full, nonce="n2")
    assert "must go in the private envelope" in (await net.svc.record("share", exposed, {a.pub: a.sign(exposed), b.pub: b.sign(exposed)}))["error"]


# ---------------- register, check, find ----------------
async def _register(net, me, **kw):
    return await register_work(me, NOVEL, InMemoryRecorderClient(net.svc), "mem://root", "public", **kw)


async def test_cp9_a_reader_checks_a_copy_from_the_book(net, settings):
    me = Identity.generate()
    r = await _register(net, me, storage=[{"kind": "https", "location": "https://example.com/novel.txt"}], media_type="text/plain")
    assert r["ok"] and r["reference"]["author"] == me.pub and "arena-ref:" in r["uri"] and "본문 해시" in r["colophon"]
    rec, anchor = InMemoryRecorderClient(net.svc), net.anchor
    copy = "첫 문장.\n둘째 문장.\n".encode("utf-8")  # another machine's line ends: the same body
    got = await check_work(copy, r["reference"], rec, anchor)
    assert got["ok"] and [s["step"] for s in got["steps"]] == ["body", "entry", "ledger"] and got["purpose"] == "authorship"
    assert got["seq"] == r["reference"]["seq"] and got["at"] == r["reference"]["ts"]
    bad = await check_work("첫 문장 고침.\n".encode(), r["reference"], rec, anchor)
    assert not bad["ok"] and bad["steps"][0]["ok"] is False
    lied = dict(r["reference"], author=Identity.generate().pub)
    assert "author" in (await check_work(copy, lied, rec, anchor))["steps"][1]["detail"]
    assert "not in form" in (await check_work(b"\xff", r["reference"], rec, anchor))["steps"][0]["detail"]
    skipped = await check_work(copy, r["reference"], rec, None)
    assert skipped["ok"] and skipped["steps"][2]["ok"] is None and "skipped" in skipped["steps"][2]["detail"]
    wrong_root = await check_work(copy, r["reference"], rec, {"genesis_hash": "0" * 64, "god_pub": net.god.pub})
    assert not wrong_root["ok"] and "root values" in wrong_root["steps"][2]["detail"]
    # someone holding only a copy finds the registration by the body's hash (CP-10)
    found = net.svc.content(content_hash_of(copy, "utf8-nfc-lf"))
    assert found["found"] and found["entry"] == r["reference"]["entry"] and found["author"] == me.pub
    assert net.svc.content("9" * 64) == {"ok": True, "content_hash": "9" * 64, "found": False}
    assert "first publisher" in (await _register(net, Identity.generate()))["error"]  # the same body is registered once
    closed = dataclasses.replace(settings, recorder_public_content=False)
    net.svc.settings = closed
    assert "not public" in net.svc.content("9" * 64)["error"]


async def test_cp9_hidden_places_and_a_work_on_a_branch_chain(net, settings):
    me = Identity.generate()
    r = await _register(net, me, storage=[{"kind": "place", "location": "서고 3층"}], hide_storage=True, sign_storage=False)
    assert r["ok"]
    stored = net.svc.ledger.raw[r["receipt"]["seq"]]
    assert "ref" not in stored["payload"] and stored["envelope"]["fields"]["ref"]["storage"][0]["location"] == "서고 3층"
    assert "ref" not in json.dumps(net.svc.log(0)["entries"][r["receipt"]["seq"]]["payload"])  # the public log has no place
    # a work registered on a branch chain is proven through the trunk's link
    child = await Child(settings, net).boot()
    recorders = {"mem://root": InMemoryRecorderClient(net.svc), "mem://child": InMemoryRecorderClient(child.svc)}
    w = await register_work(me, "가지 체인의 시".encode(), recorders["mem://child"], "mem://child", "public")
    assert w["ok"] and w["reference"]["ledger_id"] == child.ledger_id
    got = await check_work("가지 체인의 시".encode(), w["reference"], recorders["mem://child"], net.anchor, recorders.get)
    assert got["ok"], got["steps"]
    stray = await Child(settings, await Net(settings).boot()).boot()
    recorders["mem://stray"] = InMemoryRecorderClient(stray.svc)
    s = await register_work(me, "다른 뿌리".encode(), recorders["mem://stray"], "mem://stray", "public")
    assert not (await check_work("다른 뿌리".encode(), s["reference"], recorders["mem://stray"], net.anchor, recorders.get))["ok"]
    assert "not in form" in (await register_work(me, b"\xff", recorders["mem://root"], "mem://root", "public"))["error"]


async def test_cp9_the_command_line(tmp_path, net, settings):
    rec = InMemoryRecorderClient(net.svc)
    f = tmp_path / "novel.txt"
    f.write_bytes(NOVEL)

    async def cli(*args, s=settings):
        out = io.StringIO()
        code = await run(parser().parse_args(list(args)), s, out, recorder_of=lambda url: rec)
        return code, json.loads(out.getvalue())
    code, h = await cli("hash", "--file", str(f))
    assert code == 0 and h["content_hash"] == content_hash_of(NOVEL, "utf8-nfc-lf")
    code, reg = await cli("register", "--home", str(tmp_path / "author"), "--recorder", "mem://root", "--file", str(f),
                          "--storage", "https=https://example.com/n.txt", "--did", "did:web:me.example", "--out", str(tmp_path / "ref.json"))
    assert code == 0 and reg["reference"]["did"] == "did:web:me.example" and "receipt" not in reg
    anchored = dataclasses.replace(settings, trust_genesis_hash=net.ledger_id, trust_god_pub=net.god.pub)
    code, chk = await cli("check", "--file", str(f), "--ref", str(tmp_path / "ref.json"), s=anchored)
    assert code == 0 and all(x["ok"] for x in chk["steps"])
    code, chk = await cli("check", "--file", str(f), "--uri", reg["uri"])
    assert code == 0 and chk["steps"][2]["ok"] is None  # no root values in these settings: said, not silently passed
    code, found = await cli("find", "--file", str(f), "--recorder", "mem://root")
    assert code == 0 and found["entry"] == reg["reference"]["entry"]
    code, missing = await cli("find", "--hash", "8" * 64, "--recorder", "mem://root")
    assert code == 1 and missing["found"] is False
    with pytest.raises(SystemExit, match="kind=location"):
        await cli("register", "--home", str(tmp_path / "author"), "--recorder", "mem://root", "--file", str(f), "--storage", "nowhere")
