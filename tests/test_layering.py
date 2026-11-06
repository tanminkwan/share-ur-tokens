"""P2-A1 and the layering rule: the platform knows nothing about any app or the demo."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLATFORM = sorted((ROOT / "arena").rglob("*.py"))
APP_WORDS = re.compile(r"call_id|공모|아이디어|\bidea|\breview|\badopt|심사|채택|대표이사|사장")


def test_pa1_platform_has_no_app_vocabulary():
    bad = []
    for f in PLATFORM:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if APP_WORDS.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert not bad, "\n".join(bad)


def test_layers_platform_does_not_import_apps_or_demo():
    bad = [str(f.relative_to(ROOT)) for f in PLATFORM
           if re.search(r"^\s*(from|import)\s+(apps|demo)\b", f.read_text(encoding="utf-8"), re.M)]
    assert not bad, bad


def test_layers_lower_layers_do_not_import_upper_ones():
    """SOLID re-check (2026-11-03): the ledger, recorder and broker never depend on the peer layer or the bundled apps;
    the peer core never depends on the bundled apps (dependencies point down)"""
    upper = {"ledger": r"peer|bundled|peers", "recorder": r"peer|bundled|peers", "broker": r"peer|bundled|peers", "peer": r"bundled|peers"}
    bad = []
    for layer, forbidden in upper.items():
        for f in sorted((ROOT / "arena" / layer).rglob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(rf"^\s*from\s+(\.\.+|arena\.)({forbidden})\b", line):
                    bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_p10_connectivity_is_a_service_of_its_own():
    """user 2026-11-06: "connectivity는 agent arena와 상관없는 보편 서비스". It imports nothing of this repository but itself,
    and speaks of no agent, peer, ledger or event"""
    bad = []
    for f in sorted((ROOT / "connectivity").rglob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^\s*(from|import)\s+(arena|apps|demo|tests)\b", line) or re.search(r"\b(peer|agent|ledger|arena|a2a)\b", line, re.I):
                bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert not bad, "\n".join(bad)
