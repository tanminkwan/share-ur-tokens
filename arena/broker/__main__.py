"""python -m arena.broker  (settings: ARENA_BROKER_* in the environment or .env)"""
from ..config import Settings
from ..serve import run
from .api import build_broker_app
from .service import BrokerService


def main():
    s = Settings.load()
    svc = BrokerService.from_settings(s)
    run(build_broker_app(svc), s.host, s.broker_port, svc.health())


if __name__ == "__main__":
    main()
