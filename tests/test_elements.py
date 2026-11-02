"""P6-01 ~ P6-02: an event switches built-in elements on in an `elements` block of its declaration and notice. The ledger
accepts only registered elements with a valid setting, notarizes the block, and adds each declared element's rules to
the entries of that event. Elements are registered (ledger side and peer side under one name), never wired in."""
import dataclasses

from arena.ledger.elements import LedgerElement, register_ledger_element
from arena.peer.assistant.tools import Tool, _obj
from arena.peer.elements import PeerElement, register_peer_element
from arena.peer.events import announce_event
from tests.test_assistant import asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)
from tests.test_event_apps import RULES, Runner, World, route


def _limit_cfg(cfg):
    return None if isinstance(cfg.get("limit"), int) and cfg["limit"] > 0 else "limit must be a positive number"


def _limit_rule(chain, e, cfg, s):
    p = e["payload"]
    if e["type"] == "publish":
        n = sum(1 for x in chain if x["type"] == "publish" and x["payload"].get("event_id") == p["event_id"] and x["payload"]["author"] == p["author"])
        if n >= cfg["limit"]:
            return f"demo-limit: at most {cfg['limit']} registrations per author in this event"


async def _demo_tool(A, ctx, st):
    return {"ok": True, "demo": True}


register_ledger_element(LedgerElement("demo-limit", _limit_cfg, (_limit_rule,)))
register_peer_element(PeerElement("demo-limit", tools=(Tool("demo_tool", "{}: 시험용 요소 도구", None, _demo_tool, element="demo-limit"),)))


async def _publish(eco, who, ev, text):
    lid = eco.svc.ledger.chain[0]["hash"]
    p = {"author": who.identity.pub, "content_hash": text * 8, "event_id": ev, "group_id": "public", "ledger_id": lid}
    return await eco.svc.record("publish", p, {who.identity.pub: who.identity.sign(p)})


async def _declare(eco, elements):
    host = eco.host
    rec = (await host.brokers["public"].find("기록", role="record", identity=host.identity))["peers"][0]
    return await announce_event(host.ctx(host.events), group="public", title="t", kind="k", rules=RULES, policy={}, mode="assistant",
                                elements=elements, recorder=rec)


async def test_p6_01_the_ledger_accepts_only_registered_elements_with_valid_settings(eco):
    import pytest
    with pytest.raises(RuntimeError, match="element"):
        await _declare(eco, {"no-such-element": {}})
    with pytest.raises(RuntimeError, match="limit"):
        await _declare(eco, {"demo-limit": {"limit": 0}})
    out = await _declare(eco, {"demo-limit": {"limit": 1}})
    v = eco.svc.verify(out["event_hash"])
    assert v["elements"] == {"demo-limit": {"limit": 1}} and out["notice"]["elements"] == {"demo-limit": {"limit": 1}}


async def test_p6_02_a_declared_elements_rules_apply_to_that_events_entries_only(eco):
    on = (await _declare(eco, {"demo-limit": {"limit": 1}}))["event_id"]
    off = (await _declare(eco, {}))["event_id"]
    a = eco.a
    assert (await _publish(eco, a, on, "a"))["ok"]
    assert "demo-limit" in (await _publish(eco, a, on, "b"))["error"]
    assert (await _publish(eco, a, off, "c"))["ok"] and (await _publish(eco, a, off, "d"))["ok"]


async def test_p6_01_the_router_needs_the_notices_elements_to_match_the_ledger(tmp_path, settings):
    w = World(tmp_path, settings)
    host, player = w.peer("host", []), w.peer("player", [Runner()])
    await w.boot(host, player)
    rec = (await host.brokers["public"].find("기록", role="record", identity=host.identity))["peers"][0]
    ref = {"id": Runner.app_id, "name": "runner", "version": "1.0"}

    async def declare():
        return await announce_event(host.ctx(host.events), group="public", title="t", kind="k", rules=RULES, policy={}, mode="app",
                                    apps=[ref], elements={"demo-limit": {"limit": 2}}, recorder=rec)
    good, forged = await declare(), await declare()
    # the issuer's notice for the second event now claims other elements than the ledger notarized
    bad = dict(forged["notice"], ver=2, elements={"demo-limit": {"limit": 99}})
    assert (await w.public.post_notice(bad, host.identity.sign(bad)))["ok"]
    await route(player)
    assert player.app(Runner).got == [(good["event_id"], "new")]


async def test_p6_02_the_assistant_offers_an_elements_tools_only_where_the_event_turned_it_on(eco):
    host = eco.host
    on = await asst(host).host_event(ctx(host), title="on", kind="k", rules=RULES, policy={}, instruction="기다려라",
                                     elements={"demo-limit": {"limit": 1}})
    off = await asst(host).host_event(ctx(host), title="off", kind="k", rules=RULES, policy={}, instruction="기다려라")
    await settle(host)
    assert asst(host).events[on].elements == {"demo-limit": {"limit": 1}}
    assert "demo_tool" in asst(host)._tools_for(asst(host).events[on])
    assert "demo_tool" not in asst(host)._tools_for(asst(host).events[off])
