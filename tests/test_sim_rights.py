"""The founding-rights simulation (sim/rights.py): the controller moves the right way, and the model behaves."""
import random
from dataclasses import replace

from sim.rights import SCENARIOS, Control, Scenario, designed, next_difficulty, poisson, run, step, stock_factor, summary, main

C = Control()


def by(name):
    return next(s for s in SCENARIOS if s.name == name)


def test_the_stock_pulls_the_difficulty_the_right_way():
    assert stock_factor(C, 800) == 1.0
    assert stock_factor(C, 3000) == 2.0          # too many unspent: harder
    assert stock_factor(C, 175) == 0.5           # too few: easier
    assert stock_factor(C, 0) == 1 / 350         # none at all: as easy as the step allows
    assert stock_factor(replace(C, stock="up"), 175) == 1.0 and stock_factor(replace(C, stock="up"), 3000) == 2.0
    assert stock_factor(replace(C, stock="none"), 3000) == 1.0


def test_the_difficulty_follows_the_mints_within_the_step():
    assert next_difficulty(C, 10.0, [50, 50, 50], 800) == 10.0
    assert next_difficulty(C, 10.0, [100, 100, 100], 800) == 20.0
    assert next_difficulty(C, 10.0, [5000] * 3, 800) == 40.0     # at most x4 a day
    assert next_difficulty(C, 10.0, [0, 0, 0], 800) == 2.5       # at most /4 a day
    assert next_difficulty(C, 10.0, [], 800) == 10.0
    assert next_difficulty(replace(C, window=1), 10.0, [0, 0, 100], 800) == 20.0  # only the window counts


def test_poisson_has_the_right_mean():
    rng = random.Random(3)
    for lam in (0.5, 7, 300):
        xs = [poisson(rng, lam) for _ in range(4000)]
        assert abs(sum(xs) / len(xs) - lam) < max(0.1, lam * 0.03)
    assert poisson(rng, 0) == 0


def test_steady_mints_near_the_target_and_serves_everyone():
    s = summary(by("steady"), run(by("steady")))
    assert 45 <= s["mints/day (after settling)"] <= 55
    assert s["honest founders served"] > 0.98 and s["attacker branches"] == 0


def test_d1_easing_on_a_low_stock_lets_a_spammer_inflate_the_flow():
    """finding: a spammer spends at once, the stock stays low, the first design eases and mints run far above R"""
    s = summary(by("spam-10x"), run(designed(by("spam-10x"), "D1 처음 설계")))
    assert s["mints/day (after settling)"] > 3 * C.R


def test_d2_the_flow_alone_holds_the_target_but_a_richer_attacker_takes_most():
    days = run(designed(by("spam-10x"), "D2 흐름만"))
    late = days[60:]
    assert 40 <= sum(x.mints_h + x.mints_a for x in late) / len(late) <= 60
    s = summary(by("spam-10x"), days)
    assert s["attacker share of mints"] > 0.7 and s["honest founders served"] < 0.5


def test_d3_a_daily_cap_closes_the_gap_before_the_controller_catches_up():
    d2 = summary(by("flash-50x"), run(designed(by("flash-50x"), "D2 흐름만")))
    d3 = summary(by("flash-50x"), run(designed(by("flash-50x"), "D3 흐름만 + 하루 상한")))
    assert d2["max mints in a day"] > 1000 and d3["max mints in a day"] <= 100
    assert d3["attacker branches"] < d2["attacker branches"] / 5


def test_d5_an_endorsement_path_bound_to_founders_serves_the_honest_whatever_the_gpus():
    for name in ("spam-10x", "hoard-10x", "flash-50x", "demand-surge"):
        for seed in (1, 2, 3):
            s = summary(by(name), run(designed(by(name), "D5 D4, 보증 권리는 양도 불가"), seed))
            assert s["honest founders served"] > 0.99, (name, seed)


def test_with_a_cap_the_branches_a_day_stay_bounded_in_every_scenario():
    for name in ("D3 흐름만 + 하루 상한", "D5 D4, 보증 권리는 양도 불가"):
        for sc in SCENARIOS:
            days = run(designed(sc, name))
            assert max(x.mints_h + x.mints_a for x in days) <= 100 + 60, (name, sc.name)  # the cap plus the endorsement path


def test_runs_are_repeatable_and_rights_expire():
    sc = Scenario("t", "", honest_hash=step(0, 100, 100), demand=lambda d: 0.0, days=200)
    a, b = run(sc, seed=5), run(sc, seed=5)
    assert a == b
    assert sum(x.expired for x in a) > 0 and max(x.stock_h for x in a) <= C.R * C.T * 1.3


def test_the_command_writes_the_tables(tmp_path, capsys):
    out = tmp_path / "r.md"
    main(["--days", "60", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "| 지표 |" in text and all(s.name in text for s in SCENARIOS)


def test_d7_a_shrinking_schedule_starves_a_growing_ecosystem():
    g = by("growth-2y")
    d5 = summary(g, run(designed(g, "D5 D4, 보증 권리는 양도 불가")))
    d7 = summary(g, run(designed(g, "D7 일정형(반감 360일) + 따라가는 상한")))
    assert d7["honest founders served"] < d5["honest founders served"] < 0.9


def test_d8_following_all_issuance_compounds_and_the_attacker_feeds_it():
    st = summary(by("steady"), run(designed(by("steady"), "D8 비례형(누적의 1%) + 따라가는 상한")))
    assert st["target R at the end"] > 2 * C.R  # grows by itself though demand stays the same
    g, gs = by("growth-2y"), by("growth-2y-spam")
    honest = summary(g, run(designed(g, "D8 비례형(누적의 1%) + 따라가는 상한")))
    spam = summary(gs, run(designed(gs, "D8 비례형(누적의 1%) + 따라가는 상한")))
    assert spam["attacker branches"] > 100_000 and spam["all issued"] >= honest["all issued"] * 0.9


def test_d9_following_the_endorsement_path_grows_with_the_honest_and_ignores_the_gpus():
    g, gs = by("growth-2y"), by("growth-2y-spam")
    honest = summary(g, run(designed(g, "D9 보증 쓰임 추이형 + 따라가는 상한")))
    spam = summary(gs, run(designed(gs, "D9 보증 쓰임 추이형 + 따라가는 상한")))
    assert honest["target R at the end"] > 2 * C.R and honest["honest founders served"] > 0.99
    assert abs(spam["target R at the end"] - honest["target R at the end"]) < 0.15 * honest["target R at the end"]
    assert spam["honest founders served"] > 0.99
