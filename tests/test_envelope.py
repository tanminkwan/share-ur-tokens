"""Protocol 3: public body and private envelope (user 2026-11-03: "비공개 칸은 공개 본체와 비공개 봉투 방식으로 해").
Anyone may copy the public form and check it; who handed what to whom and a hidden role's contractor stay in the
envelope, kept by the recorder and read only by allowed readers."""
import json

import httpx

from arena.crypto import Identity, canon
from arena.ledger import audit_chain, private_hash, public_form, split_payload, with_private
from arena.recorder.api import build_recorder_app
from tests.test_ledger import Cast
from tests.test_assistant import eco  # noqa: F401  (fixture)
from tests.test_recorder_service import svc, reader  # noqa: F401  (fixtures)


async def built(svc):
    cast = Cast()
    for e in (cast.event(), cast.publish(), cast.share(), cast.contract(role="judge"), cast.contract(role="keeper", contractor=cast.keeper, nonce="c2")):
        r = await svc.record(*e)
        assert r["ok"], r
    return cast


async def test_the_public_log_hides_the_envelope_and_still_audits(svc, reader):
    cast = await built(svc)
    log = svc.log(0)["entries"]
    text = json.dumps(log)
    assert all("envelope" not in e for e in log)
    share, hidden, shown = log[2], log[3], log[4]
    assert cast.author.pub not in json.dumps(share) and "provider" not in share["payload"] and "private" in share["payload"]
    assert cast.judge.pub not in json.dumps(hidden) and "contractor" not in hidden["payload"]  # a hidden role's contractor
    assert shown["payload"]["contractor"] == cast.keeper.pub  # a role not hidden stays public
    assert cast.judge.pub not in text
    assert audit_chain(log) == "ok"  # anyone checks hash chain, seals, public signatures
    full = svc.read_chain(reader.pub)["chain"]
    assert full[2]["envelope"]["fields"]["provider"] == cast.author.pub and audit_chain(full) == "ok"  # an allowed reader sees all
    assert svc.verify(log[2]["hash"])["type"] == "share" and "provider" not in svc.verify(log[2]["hash"])


async def test_the_ledger_refuses_envelopes_that_do_not_match(svc):
    cast = Cast()
    await svc.record(*cast.event())
    await svc.record(*cast.publish())
    kind, p, sigs, private = cast.share()
    assert "hash of the private fields" in (await svc.record(kind, p, sigs, dict(private, terms="other")))["error"]
    assert "missing" in (await svc.record(kind, p, sigs))["error"]
    full = {**{k: v for k, v in p.items() if k != "private"}, **private}
    exposed = await svc.record(kind, full, {k.pub: k.sign(full) for k in (cast.author, cast.issuer)})
    assert "private envelope" in exposed["error"]  # who handed what to whom may not be put in the public body
    both = with_private(dict(full), {"provider": full["provider"]})
    assert "either in the body or in the envelope" in (await svc.record(kind, both, {}, {"provider": full["provider"]}))["error"]


async def test_the_public_log_over_http_pages_and_needs_no_key(svc):
    await built(svc)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=build_recorder_app(svc)), base_url="http://r")
    first = (await http.get("/log?from=0&limit=2")).json()
    assert [e["seq"] for e in first["entries"]] == [0, 1] and first["next"] == 2 and first["size"] == 5
    rest = (await http.get(f"/log?from={first['next']}")).json()
    assert [e["seq"] for e in rest["entries"]] == [2, 3, 4] and all("envelope" not in e for e in rest["entries"])
    assert (await http.get("/log?from=x")).status_code == 400
    await http.aclose()


async def test_a_co_signer_signs_only_a_body_that_commits_to_what_it_was_shown(eco):
    """engage: the contractor checks that the body it signs commits (by the private hash) to the full contract"""
    from tests.test_assistant import asst, ctx, open_event, settle  # noqa: F401
    ev = await open_event(eco)
    a = eco.a
    a.llm.push("join_event")
    await a.events.watch_once(a.ctx(a.events))
    await settle(a, eco.host)
    st = asst(eco.host).events[ev]
    full = {"event_id": ev, "role": "member", "issuer": eco.host.identity.pub, "contractor": a.identity.pub, "nonce": "n",
            "group_id": st.group_id, "rules_hash": st.rules_hash}
    body = with_private({k: v for k, v in full.items() if k != "contractor"}, {"contractor": Identity.generate().pub})  # lies
    r = await a.handle({"op": "engage", "role": "member", "contract": full, "body": body, "request": {"event_id": ev, "rules_hash": st.rules_hash}})
    assert not r["ok"] and "does not match" in r["error"]
    good, _ = split_payload("contract", full, {"hidden_roles": ["member"]})
    r = await a.handle({"op": "engage", "role": "member", "contract": full, "body": good, "request": {"event_id": ev, "rules_hash": st.rules_hash}})
    assert r["ok"] and a.identity.pub not in json.dumps(good) and good["private"] == private_hash({"contractor": a.identity.pub})


def test_split_follows_the_types_rule():
    full = {"provider": "a" * 64, "consumer": "b" * 64, "content_hash": "c" * 64, "purpose": "delivery", "nonce": "n", "group_id": "g"}
    body, private = split_payload("share", full)
    assert set(private) == {"provider", "consumer", "content_hash"} and body["private"] == private_hash(private)
    body2, none = split_payload("publish", {"author": "a" * 64, "content_hash": "c" * 64, "group_id": "g"})
    assert none is None and "private" not in body2
    assert canon(body) == canon(with_private({k: v for k, v in full.items() if k not in private}, private))
