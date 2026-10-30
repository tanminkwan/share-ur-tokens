"""python -m arena.collector  (settings: ARENA_COLLECTOR_* in the environment or .env)"""
from ..config import Settings
from ..serve import run
from .api import build_collector_app
from .service import CollectorService


def main():
    s = Settings.load()
    svc = CollectorService.from_settings(s)
    run(build_collector_app(svc), s.host, s.collector_port, svc.health())


if __name__ == "__main__":
    main()
