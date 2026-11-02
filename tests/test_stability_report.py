"""P5-B4 (redefined 2026-11-02): repeated live runs are judged on the platform's guarantees. The harness audits every
run's ledger whether or not the LLM finished the event; this checks its report logic without running anything live."""
import json

from arena.crypto import Identity
from arena.ledger import MemoryStore, Ledger
from scripts.rps_stability import judge_run, summarize


def _ledger_file(tmp_path, settings, tamper=False):
    led = Ledger(Identity.generate(), MemoryStore(), settings)
    god = Identity.generate()
    p = {"god": god.pub, "broker": "b", "recorder": led.identity.pub, "group_id": "public"}
    entry, err = led.propose("genesis", p, {god.pub: god.sign(p)})
    assert not err
    chain = [dict(e) for e in led.chain]
    if tamper:
        chain[0]["payload"] = dict(chain[0]["payload"], broker="x")
    f = tmp_path / "genesis" / "ledger.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text("\n".join(json.dumps(e) for e in chain) + "\n", encoding="utf-8")
    return tmp_path


def test_p5b4_a_run_is_judged_on_the_platform_not_on_the_llm(tmp_path, settings):
    ok = judge_run(1, 1, "elapsed 18.2s, entries: [...]\nexit=1", _ledger_file(tmp_path / "a", settings))
    assert ok["audit"] == "ok" and ok["platform_ok"] and not ok["llm_finished"] and ok["elapsed"] == 18.2
    bad = judge_run(2, 0, "elapsed 20.0s\nexit=0", _ledger_file(tmp_path / "b", settings, tamper=True))
    assert bad["audit"] != "ok" and not bad["platform_ok"] and bad["llm_finished"]
    none = judge_run(3, 2, "Traceback ... genesis did not start", tmp_path / "c")
    assert none["audit"] == "no ledger" and not none["platform_ok"]
    text = summarize([ok, bad, none])
    assert "플랫폼 보장 지켜짐: 1/3" in text and "LLM이 끝까지 해냄(참고): 1/3" in text and "| 2 |" in text
