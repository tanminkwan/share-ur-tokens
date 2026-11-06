"""python -m connectivity  (settings: CONNECTIVITY_* in the environment)"""
import json
import logging

import uvicorn

from .api import build_connectivity_app
from .config import ConnectivitySettings
from .service import ConnectivityService, load_allow_keys


def main():
    s = ConnectivitySettings.from_env()
    svc = ConnectivityService(s, allow_keys=load_allow_keys(s.allow_keys_file))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("connectivity").info("starting %s", json.dumps(dict(svc.health(), base=s.base_url)))
    uvicorn.run(build_connectivity_app(svc), host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
