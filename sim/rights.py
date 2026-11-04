"""Group-founding rights earned by proof of work, transferable, with a supply controller (user 2026-11-04: "GPU를
소모하게 해서 그룹생성 권리를 득하고 그 권리는 양도도 가능. 그 권리가 너무 많아지거나 부족하지 않도록 logic으로 조절").

A day-by-day model, no real hashing: a miner with hash power h finds on average h / D rights a day at difficulty D.
The controller sees only what the ledger would show (mints, spends, expiries, the unspent stock) and sets the next
day's difficulty:

    next D = D * clamp( (mints over the window / (R * window)) * stock_factor(U), 1 / max_step, max_step )
    stock_factor(U) = (U / U_max) ** k   if U > U_max      (too many unspent: harder)
                      (U / U_min) ** k   if U < U_min      (too few: easier)
                      1                  otherwise
    a right not spent within T days expires

Run: python -m sim.rights [--days N] [--seed S] [--out FILE]   (writes the scenario tables as markdown)"""
from __future__ import annotations

import argparse
import math
import random
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable


# ---------------- the controller (what would go into the ledger rules) ----------------
@dataclass(frozen=True)
class Control:
    R: float = 50.0          # target mints a day
    T: int = 90              # days a right lives unspent
    U_min: float = 350.0     # unspent stock below this: easier (about a week of target mints)
    U_max: float = 1500.0    # unspent stock above this: harder (about a month)
    k: float = 1.0           # how strongly the stock pulls
    max_step: float = 4.0    # the difficulty changes at most this factor a day
    window: int = 3          # days of mints the controller averages
    stock: str = "both"      # how the unspent stock pulls: both (harder when many, easier when few) | up (only harder) | none
    daily_cap: float | None = None  # the ledger takes at most this many mints a day (None: no cap)
    target: str = "fixed"    # the target R over time: fixed | schedule (halves every half_life days) | relative (growth x all issued so far)
    half_life: float = 360.0
    growth: float = 0.01
    R_min: float = 10.0
    R_max: float = 500.0
    cap_ratio: float | None = None  # a daily cap that follows the target: cap_ratio x that day's R (instead of daily_cap)
    alpha: float = 1.0       # endorsed: R = alpha x the mean daily branches founded through the endorsement path
    trend_window: int = 30


def target_rate(c: Control, day: int, issued: int, endorsed_use: list[int] | None = None) -> float:
    """that day's target mints, from the published schedule, the trend of all rights issued so far, or the trend of the
    branches founded through the endorsement path (a signal GPUs cannot inflate)"""
    if c.target == "endorsed":
        w = (endorsed_use or [])[-c.trend_window:]
        return min(max(c.alpha * (sum(w) / len(w) if w else 0.0), c.R_min), c.R_max)
    if c.target == "schedule":
        return max(c.R_min, c.R * 0.5 ** (day / c.half_life))
    if c.target == "relative":
        return min(max(c.growth * issued, c.R_min), c.R_max)
    return c.R


def cap_of(c: Control, R: float) -> float | None:
    return c.cap_ratio * R if c.cap_ratio is not None else c.daily_cap


def stock_factor(c: Control, unspent: float) -> float:
    if c.stock == "none":
        return 1.0
    if unspent > c.U_max:
        return (unspent / c.U_max) ** c.k
    if unspent < c.U_min and c.stock == "both":
        return (max(unspent, 1.0) / c.U_min) ** c.k
    return 1.0


def next_difficulty(c: Control, d: float, recent_mints: list[int], unspent: float, R: float | None = None) -> float:
    """the next day's difficulty from the last `window` days of mints and today's unspent stock (R: the day's target)"""
    w = recent_mints[-c.window:]
    flow = (sum(w) / len(w)) / (R or c.R) if w else 1.0
    factor = flow * stock_factor(c, unspent)
    factor = min(max(factor, 1.0 / c.max_step), c.max_step)
    return d * factor


# ---------------- the world ----------------
def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 60:  # normal approximation for large means
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


@dataclass(frozen=True)
class Scenario:
    name: str
    about: str
    honest_hash: Callable[[int], float] = lambda day: 100.0      # GPUs of honest miners on that day
    attacker_hash: Callable[[int], float] = lambda day: 0.0
    demand: Callable[[int], float] = lambda day: 40.0            # honest founders wanting a group that day
    attacker: str = "none"                                       # none | spam (spends at once) | hoard (never spends)
    buys: float = 0.0                                            # share of the honest surplus the attacker buys each day (rights are transferable)
    endorsed: float = 0.0                                        # rights a day given to honest founders by endorsement (a second path, no GPU)
    endorsed_transferable: bool = True                           # may an endorsed right be sold (False: bound to the founder it was given to)
    endorsed_q: float = 0.0                                      # more endorsements a day per branch founded through the path (its founders sponsor too)
    endorsed_on_request: bool = False                            # endorsed rights only for founders waiting (none left to expire or sell)
    control: Control = field(default_factory=Control)
    days: int = 180


@dataclass
class Day:
    day: int
    difficulty: float
    mints_h: int
    mints_a: int
    stock_h: int
    stock_a: int
    branches_h: int
    branches_a: int
    queue: int
    expired: int
    target: float = 0.0
    waited: int = 0          # days the founders served today had waited, summed


def run(sc: Scenario, seed: int = 1) -> list[Day]:
    rng, c = random.Random(seed), sc.control
    issued, e_branches, endorsed_use = 0, 0, []
    R = target_rate(c, 0, issued, endorsed_use)
    d = (sc.honest_hash(0) + sc.attacker_hash(0)) / R  # start where today's power gives R a day
    held = {"h": deque(), "a": deque(), "e": deque()}  # mint days of unspent rights, oldest first (e: endorsed, bound to its founder)
    queue: deque[int] = deque()          # days honest founders started waiting
    mints: list[int] = []
    out: list[Day] = []
    for day in range(sc.days):
        mh, ma = poisson(rng, sc.honest_hash(day) / d), poisson(rng, sc.attacker_hash(day) / d)
        cap = cap_of(c, R)
        if cap is not None and mh + ma > cap:  # the ledger takes the first `cap` valid answers of the day
            take = int(cap)
            mh = sum(1 for _ in range(take) if rng.random() < mh / (mh + ma))
            ma = take - mh
        pow_mints = mh + ma
        queue.extend([day] * poisson(rng, sc.demand(day)))
        me = poisson(rng, sc.endorsed + sc.endorsed_q * e_branches)  # the endorsement path: no GPU, honest founders only (not counted by the controller)
        if sc.endorsed_on_request:
            me = min(me, max(0, len(queue) - len(held["e"])))
        held["h"].extend([day] * mh)
        held["a"].extend([day] * ma)
        held["h" if sc.endorsed_transferable else "e"].extend([day] * me)
        mh += me
        # honest founders: those who waited first get the oldest rights (spend before they expire)
        bh, waited, be = 0, 0, 0
        while queue and (held["e"] or held["h"]):
            waited += day - queue.popleft()
            src = "e" if held["e"] else "h"  # a founder spends the right given to them first
            held[src].popleft()
            be += src == "e"
            bh += 1
        e_branches += be
        endorsed_use.append(be)
        # transfer: the attacker buys part of what honest miners hold beyond the founders waiting
        bought = int(len(held["h"]) * sc.buys)
        for _ in range(bought):
            held["a"].append(held["h"].pop())  # the newest ones
        ba = 0
        if sc.attacker == "spam":
            ba, held["a"] = len(held["a"]), deque()
        expired = 0
        for who in ("h", "a", "e"):
            while held[who] and held[who][0] <= day - c.T:
                held[who].popleft()
                expired += 1
        mints.append(pow_mints)
        issued += pow_mints + me
        unspent = len(held["h"]) + len(held["a"]) + len(held["e"])
        out.append(Day(day, d, mh, ma, len(held["h"]) + len(held["e"]), len(held["a"]), bh, ba, len(queue), expired, R, waited))
        R = target_rate(c, day + 1, issued, endorsed_use)
        d = next_difficulty(c, d, mints, unspent, R)
    return out


# ---------------- what a run says ----------------
def summary(sc: Scenario, days: list[Day], settle: int = 14) -> dict:
    after = days[settle:]
    total_a = sum(x.mints_a for x in days)
    total = sum(x.mints_h + x.mints_a for x in days)
    attack_hash_days = sum(sc.attacker_hash(x.day) for x in days)
    honest_hash_days = sum(sc.honest_hash(x.day) for x in days)
    served = sum(x.branches_h for x in days)
    wanted = served + days[-1].queue
    return {
        "mints/day (after settling)": round(sum(x.mints_h + x.mints_a for x in after) / len(after), 1),
        "max mints in a day": max(x.mints_h + x.mints_a for x in days),
        "max branches in a day": max(x.branches_h + x.branches_a for x in days),
        "attacker share of mints": round(total_a / total, 3) if total else 0.0,
        "attacker branches": sum(x.branches_a for x in days),
        "honest branches": served,
        "honest founders served": round(served / wanted, 3) if wanted else 1.0,
        "honest queue at the end": days[-1].queue,
        "mean wait (days)": round(sum(x.waited for x in days) / served, 2) if served else None,
        "all issued": total,
        "target R at the end": round(days[-1].target, 1),
        "max unspent stock": max(x.stock_h + x.stock_a for x in days),
        "expired": sum(x.expired for x in days),
        "difficulty end / start": round(days[-1].difficulty / days[0].difficulty, 2),
        "GPU-days per attacker right": round(attack_hash_days / total_a, 2) if total_a else None,
        "GPU-days per honest right": round(honest_hash_days / (total - total_a), 2) if total - total_a else None,
    }


def step(at: int, before: float, after: float) -> Callable[[int], float]:
    return lambda day: before if day < at else after


def ramp(days: int, start: float, end: float) -> Callable[[int], float]:
    return lambda day: start + (end - start) * min(day, days) / days


def window(start: int, end: int, base: float, high: float) -> Callable[[int], float]:
    return lambda day: high if start <= day < end else base


SCENARIOS = [
    Scenario("steady", "정직한 GPU 100대, 하루 40명이 그룹을 원함(목표 발행 50보다 적음)"),
    Scenario("spam-10x", "30일째 공격자가 GPU 1,000대(정직한 쪽의 10배)를 붙이고, 얻는 대로 가지를 만듦", attacker_hash=step(30, 0, 1000), attacker="spam"),
    Scenario("hoard-10x", "같은 공격자가 권리를 쓰지 않고 쌓아 둠(시장 독점, 재고 부풀리기)", attacker_hash=step(30, 0, 1000), attacker="hoard"),
    Scenario("buy-surplus", "GPU 없는 공격자가 정직한 채굴자의 남는 권리를 매일 절반씩 사서 가지를 만듦(양도 가능)", buys=0.5, attacker="spam"),
    Scenario("flash-50x", "30~32일 사흘만 GPU 5,000대(50배)를 붙였다가 뺌: 조절이 따라오기 전의 틈", attacker_hash=window(30, 33, 0, 5000), attacker="spam"),
    Scenario("miners-leave", "60일째 정직한 GPU가 90% 빠짐", honest_hash=step(60, 100, 10)),
    Scenario("demand-surge", "60~90일 그룹을 원하는 사람이 하루 120명으로 늘어남", demand=window(60, 90, 40, 120)),
    Scenario("growth-2y", "2년 동안 생태계가 자람: 정직한 GPU 50→400대, 그룹을 원하는 사람 하루 10→160명", honest_hash=ramp(720, 50, 400),
             demand=ramp(720, 10, 160), days=720),
    Scenario("growth-2y-spam", "같은 2년, 30일째부터 공격자 GPU 1,000대가 계속 마구 씀", honest_hash=ramp(720, 50, 400), demand=ramp(720, 10, 160),
             attacker_hash=step(30, 0, 1000), attacker="spam", days=720),
]


DESIGNS = {
    "D1 처음 설계": Control(),
    "D2 흐름만": Control(stock="none"),
    "D3 흐름만 + 하루 상한": Control(stock="none", daily_cap=100),
    "D4 D3 + 보증 길": Control(stock="none", daily_cap=100),
    "D5 D4, 보증 권리는 양도 불가": Control(stock="none", daily_cap=100),
    "D6 D5 + 남으면 어렵게": Control(stock="up", daily_cap=100, U_max=500),
    "D7 일정형(반감 360일) + 따라가는 상한": Control(stock="none", target="schedule", half_life=360, cap_ratio=2),
    "D8 비례형(누적의 1%) + 따라가는 상한": Control(stock="none", target="relative", growth=0.01, R_min=10, R_max=500, cap_ratio=2),
    "D9 보증 쓰임 추이형 + 따라가는 상한": Control(stock="none", target="endorsed", alpha=1.0, R_min=10, R_max=500, cap_ratio=2),
}
GROWING_PATH = {"D9 보증 쓰임 추이형 + 따라가는 상한"}  # the endorsement path grows with its own branches, on request
ENDORSED = {"D4 D3 + 보증 길": (30.0, True), "D5 D4, 보증 권리는 양도 불가": (30.0, False), "D6 D5 + 남으면 어렵게": (30.0, False),
            "D7 일정형(반감 360일) + 따라가는 상한": (30.0, False), "D8 비례형(누적의 1%) + 따라가는 상한": (30.0, False),
            "D9 보증 쓰임 추이형 + 따라가는 상한": (10.0, False)}  # rights a day by endorsement, transferable?


def designed(sc: Scenario, name: str) -> Scenario:
    e, tr = ENDORSED.get(name, (sc.endorsed, sc.endorsed_transferable))
    grow = name in GROWING_PATH
    return replace(sc, control=DESIGNS[name], endorsed=e, endorsed_transferable=tr, endorsed_q=1 / 30 if grow else sc.endorsed_q,
                   endorsed_on_request=grow or sc.endorsed_on_request)


def table(rows: list[tuple[str, dict]]) -> str:
    keys = list(rows[0][1])
    head = "| 지표 | " + " | ".join(n for n, _ in rows) + " |\n|---|" + "---|" * len(rows) + "\n"
    return head + "".join(f"| {k} | " + " | ".join(str(r[k]) for _, r in rows) + " |\n" for k in keys)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m sim.rights")
    ap.add_argument("--days", type=int, default=None, help="days to run (default: each scenario's own)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = "\n".join(f"- `{sc.name}`: {sc.about}" for sc in SCENARIOS) + "\n"
    for name in DESIGNS:
        rows = [(sc.name, summary(sc, run(replace(designed(sc, name), days=a.days or sc.days), a.seed))) for sc in SCENARIOS]
        text += f"\n### {name}\n\n" + table(rows)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
