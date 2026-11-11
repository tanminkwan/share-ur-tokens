"""python -m connectivity  (settings: CONNECTIVITY_* in the environment)"""
import asyncio
import json
import logging

import uvicorn

from . import stun
from .api import build_connectivity_app
from .config import ConnectivitySettings
from .service import ConnectivityService, load_allow_keys


async def run(s: ConnectivitySettings) -> None:
    svc = ConnectivityService(s, allow_keys=load_allow_keys(s.allow_keys_file))
    log = logging.getLogger("connectivity")
    udp = await stun.serve(s.host, s.stun_port) if s.stun_port else None  # STUN on UDP only when the operator opens it
    log.info("starting %s", json.dumps(dict(svc.health(), base=s.base_url or None, stun_port=s.stun_port or None)))
    try:
        await uvicorn.Server(uvicorn.Config(build_connectivity_app(svc), host=s.host, port=s.port, log_level="warning")).serve()
    finally:
        if udp:
            udp.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run(ConnectivitySettings.from_env()))


if __name__ == "__main__":
    main()
