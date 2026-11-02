"""python -m arena.recorder  (settings: ARENA_RECORDER_* in the environment or .env)"""
from ..config import Settings
from ..serve import run
from .api import build_recorder_app
from .service import RecorderService


def main():
    s = Settings.load()
    svc = RecorderService.from_settings(s)
    run(build_recorder_app(svc), s.host, s.recorder_port, svc.health())


if __name__ == "__main__":
    main()
