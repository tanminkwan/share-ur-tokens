"""Write .env.example from every settings class (platform, apps, demo). Run after adding a setting:
    .venv/bin/python scripts/gen_env_example.py"""
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CLASSES = [("arena.config", "Settings", "플랫폼"), ("apps.idea_contest.config", "ContestSettings", "아이디어 경연 앱"),
           ("demo.config", "DemoSettings", "시연 장치")]


def main():
    lines = ["# 에이전트 아레나 설정. 이 파일을 .env로 복사해 값을 채운다. 비워 두면 기본값.", ""]
    for mod, name, title in CLASSES:
        try:
            cls = getattr(importlib.import_module(mod), name)
        except ModuleNotFoundError:
            continue
        lines += [f"# ===== {title} ({name}) =====", ""]
        for key, default, doc in cls.describe():
            d = ",".join(default) if isinstance(default, list) else ("" if default is None else default)
            lines += [f"# {doc}", f"{key}={d}", ""]
    (ROOT / ".env.example").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
