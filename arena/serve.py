"""Run a Starlette app with uvicorn using Settings (shared by the broker and recorder entry points)."""
from __future__ import annotations

import json
import logging

import uvicorn


def run(app, host: str, port: int, banner: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("arena").info("starting %s", json.dumps(banner, ensure_ascii=False))
    uvicorn.run(app, host=host, port=port, log_level="warning")


async def serve_background(app, host: str, port: int):
    """start uvicorn inside the running event loop and wait until it listens (used to host many apps in one process)"""
    import asyncio
    srv = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="off"))
    asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    return srv
