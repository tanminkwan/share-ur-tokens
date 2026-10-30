"""Run a Starlette app with uvicorn using Settings (shared by the broker and recorder entry points)."""
from __future__ import annotations

import json
import logging

import uvicorn


def run(app, host: str, port: int, banner: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("arena").info("starting %s", json.dumps(banner, ensure_ascii=False))
    uvicorn.run(app, host=host, port=port, log_level="warning")
