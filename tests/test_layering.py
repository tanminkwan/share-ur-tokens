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
