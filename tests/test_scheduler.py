"""P6-S: the peer's scheduler (user 2026-11-02: "가위바위보 game이 특정 시간에 서로 session을 맺고 경기해라라는 식의 룰을
가지고 있었다면 그 시간에 action할 수 있어야지"). An event may carry a notarized schedule; each peer's scheduler (code,
no LLM) wakes its app or assistant at those times; the assistant may set its own reminders. Timers survive a restart."""
import dataclasses
import time

from arena.ledger.schedule import check_schedule
from arena.peer.plugin import BaseApp
from arena.peer.scheduler import Scheduler, parse_when
from tests.test_assistant import RULES, asst, ctx, eco, settle  # noqa: F401  (eco is a fixture)

POL = {"roles": ["player"]}


def test_p6s1_the_schedule_is_checked_by_the_ledger():
    assert check_schedule([{"at": 1.0, "code": "session", "subject": "m1"}], 10) is None
    assert "unknown time code" in check_schedule([{"at": 1.0, "code": "teatime"}], 10)
    assert "seconds" in check_schedule([{"at": "18:00", "code": "start"}], 10)
    assert "at most" in check_schedule([{"at": 1.0, "code": "start"}] * 3, 2)
    assert parse_when("+60", 100.0) == 160.0 and parse_when("2026-11-02T18:00:00+09:00", 0) == 1793610000.0


class Alarm(BaseApp):
    name, version, app_id = "alarm", "1.0", "1f2e3d4c-5b6a-4978-8a9b-0c1d2e3f4a5b"

    def __init__(self):
        self.rang = []

    async def on_timer(self, ctx, timer):
        self.rang.append(timer["kind"])


async def test_p6s2_an_app_is_woken_once_at_its_time_and_a_missed_timer_fires_after_a_restart(eco):
    alarm = Alarm()
    p = eco.peer("clock", apps=[alarm])
    actx, sctx = p.ctx(alarm), p.ctx(p.scheduler)
    now = time.time()
    actx.schedule(now + 60, "tea")
    actx.schedule(now + 120, "dinner")
    assert await p.scheduler.fire_due(sctx, now + 61) == 1 and alarm.rang == ["tea"]
    assert await p.scheduler.fire_due(sctx, now + 62) == 0  # once only
    assert actx.cancel_timer(actx.schedule(now + 900, "x")) == 1 and [t["kind"] for t in actx.timers()] == ["dinner"]
    # the peer goes away and comes back after the time: the kept timer fires once
    again = Scheduler(eco.s)  # a fresh scheduler reading the same kept state
    await again.start(sctx)
    await again.stop(sctx)
    assert [t["kind"] for t in again.timers] == ["dinner"]
    assert await again.fire_due(sctx, now + 500) == 1 and alarm.rang == ["tea", "dinner"]


async def test_p6s3_everyone_wakes_at_the_events_notarized_time(eco):
    host, a = eco.host, eco.a
    at = time.time() + 600
    ev = await asst(host).host_event(ctx(host), title="18시 경기", kind="k", rules=RULES, policy=POL, instruction="일정대로 하라",
                                     schedule=[{"at": at, "code": "session", "subject": "m1", "note": "두 선수가 만나 경기"}])
    await settle(host)
    decl = next(e for e in eco.svc.ledger.chain if e["type"] == "event" and e["payload"]["event_id"] == ev)
    assert eco.svc.verify(decl["hash"])["schedule"][0]["code"] == "session"
    await a.events.watch_once(a.ctx(a.events))
    await settle(a)
    assert [t["data"]["code"] for t in ctx(a).timers(ev)] == ["session"] and len(ctx(host).timers(ev)) == 1
    assert "일정(원장)" in asst(a)._system(ctx(a), asst(a).events[ev]) and "지금 시각" in asst(a)._system(ctx(a), asst(a).events[ev])
    await a.scheduler.fire_due(a.ctx(a.scheduler), at + 1)
    await settle(a)
    assert any("[일정 시각]" in x and "session m1" in x for x in asst(a).events[ev].transcript)


async def test_p6s4_the_assistant_sets_its_own_reminders_within_a_limit(eco):
    host = eco.host
    host.settings = dataclasses.replace(host.settings, assistant_max_reminders=1)
    ev = await asst(host).host_event(ctx(host), title="예약", kind="k", rules=RULES, policy=POL, instruction="기다려라")
    await settle(host)
    host.llm.push("remind", when="+30", note="상대 공개 확인")
    host.llm.push("remind", when="+60", note="하나 더")
    await asst(host).feed(ctx(host), ev, "예약해 둬")
    await settle(host)
    st = asst(host).events[ev]
    assert [t["data"]["note"] for t in ctx(host).timers(ev)] == ["상대 공개 확인"]
    assert any("예약은 1개까지" in x for x in st.transcript)
    await host.scheduler.fire_due(host.ctx(host.scheduler), time.time() + 31)
    await settle(host)
    assert any("[내 예약]" in x and "상대 공개 확인" in x for x in st.transcript)
