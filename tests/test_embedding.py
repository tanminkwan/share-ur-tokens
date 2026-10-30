"""P3-A1: the HTTP embedder against a mocked bge-m3 service."""
import json

import httpx
import pytest

from arena.config import ConfigError, Settings
from arena.embedding import EmbedError, HttpEmbedder
from tests.conftest import make_env


def es(tmp_path, **over):
    return Settings.load(env=make_env(tmp_path, **{"ARENA_EMBED_URL": "http://emb", "ARENA_EMBED_BATCH": "2", "ARENA_EMBED_RETRIES": "1", **over}),
                         dotenv_path=None)


def service(seen, fail_first=0, dim=4, wrong_count=False):
    state = {"n": 0}

    def handler(request):
        body = json.loads(request.content)
        seen.append(body["texts"])
        state["n"] += 1
        if state["n"] <= fail_first:
            return httpx.Response(503, json={"detail": "busy"})
        n = len(body["texts"]) - (1 if wrong_count else 0)
        return httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * (dim - 1)] * n, "dim": dim, "count": n})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_p3a1_batches_and_keeps_order(tmp_path):
    seen = []
    e = HttpEmbedder(es(tmp_path), http=service(seen))
    out = await e.embed(["a", "b", "c", "d", "e"])
    assert seen == [["a", "b"], ["c", "d"], ["e"]] and len(out) == 5 and e.dim == 4
    assert await e.embed([]) == []


async def test_p3a1_retries_then_fails(tmp_path):
    seen = []
    assert len(await HttpEmbedder(es(tmp_path), http=service(seen, fail_first=1)).embed(["a"])) == 1
    with pytest.raises(EmbedError):
        await HttpEmbedder(es(tmp_path), http=service([], fail_first=5)).embed(["a"])


async def test_p3a1_wrong_count_or_dimension_is_an_error(tmp_path):
    with pytest.raises(EmbedError):
        await HttpEmbedder(es(tmp_path, ARENA_EMBED_RETRIES="0"), http=service([], wrong_count=True)).embed(["a", "b"])
    e = HttpEmbedder(es(tmp_path), http=service([], dim=4))
    await e.embed(["a"])
    e._http = service([], dim=8)
    with pytest.raises(EmbedError):
        await e.embed(["b"])


def test_p3a1_needs_url(tmp_path):
    with pytest.raises(ConfigError) as x:
        HttpEmbedder(Settings.load(env=make_env(tmp_path), dotenv_path=None))
    assert "ARENA_EMBED_URL" in str(x.value)
