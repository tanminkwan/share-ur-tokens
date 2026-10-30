"""P4-A: open a public area by address; URL areas are read-only with local notes; new schemes plug in."""
import httpx
import pytest

from arena.config import Settings
from arena.peer.area import LocalFolderArea, open_area, register_area
from arena.peer.url_area import UrlArea
from tests.conftest import make_env


def site(files, seen, fail=False):
    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        if fail:
            return httpx.Response(503)
        path = request.url.path
        if path in files:
            body = files[path]
            return httpx.Response(200, json=body) if isinstance(body, dict) else httpx.Response(200, text=body)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


FILES = {"/area/index.json": {"documents": [{"name": "notes.md", "url": "notes.md"}, {"name": "_owner_rules.md", "url": "/area/_owner_rules.md"},
                                            {"name": "cloud.md", "url": "http://cdn/cloud.md"}]},
         "/area/notes.md": "- 클라우드 비용 최적화 5년\n", "/area/_owner_rules.md": "- 먼저 물어볼 것\n", "/cloud.md": "# 사례\nFinOps 도입\n",
         "/one/profile.md": "- 단일 문서 공개 영역\n"}


def test_p4a1_address_picks_the_implementation(tmp_path, settings):
    assert isinstance(open_area(str(tmp_path / "a"), settings), LocalFolderArea)
    assert isinstance(open_area(f"file://{tmp_path}/b", settings), LocalFolderArea)
    assert isinstance(open_area("https://x/area/", settings), UrlArea)
    with pytest.raises(ValueError):
        open_area("ftp://x/area", settings)


def test_p4a2_new_schemes_register_without_platform_changes(settings):
    made = []
    register_area("s3", lambda address, s, **kw: made.append(address) or LocalFolderArea("/nonexistent", s))
    open_area("s3://bucket/me", settings)
    assert made == ["s3://bucket/me"]


async def test_p4a3_index_documents_owner_only_and_token(tmp_path):
    s = Settings.load(env=make_env(tmp_path, ARENA_AREA_HTTP_TOKEN="tok", ARENA_AREA_LOCAL_NOTES_DIR=str(tmp_path / "notes")), dotenv_path=None)
    seen = []
    a = UrlArea("http://host/area/", s, http=site(FILES, seen))
    await a.refresh()
    assert [d.name for d in a.documents()] == ["cloud.md", "notes.md"]
    assert a.lines() == ["사례", "FinOps 도입", "클라우드 비용 최적화 5년"]
    assert "먼저 물어볼 것" in a.lines(include_owner_only=True)
    assert all(auth == "Bearer tok" for _, auth in seen)
    one = UrlArea("http://host/one/profile.md", s, http=site(FILES, []))
    await one.refresh()
    assert one.lines() == ["단일 문서 공개 영역"]


async def test_p4a3_cache_and_p4a5_failure_keeps_last_copy(tmp_path, clock):
    s = Settings.load(env=make_env(tmp_path, ARENA_AREA_CACHE_SEC="60", ARENA_AREA_LOCAL_NOTES_DIR=str(tmp_path / "n")), dotenv_path=None)
    seen = []
    a = UrlArea("http://host/area/", s, http=site(FILES, seen), clock=clock)
    await a.refresh()
    n = len(seen)
    await a.refresh()
    assert len(seen) == n  # cached
    clock.tick(61)
    a._http = site(FILES, seen, fail=True)
    assert await a.refresh() is False  # could not fetch: keep the last copy
    assert "클라우드 비용 최적화 5년" in a.lines()


async def test_p4a4_notes_go_to_the_local_folder(tmp_path):
    s = Settings.load(env=make_env(tmp_path, ARENA_AREA_LOCAL_NOTES_DIR=str(tmp_path / "n")), dotenv_path=None)
    a = UrlArea("http://host/area/", s, http=site(FILES, []))
    await a.refresh()
    a.add_note("심사 경험이 생겼다")
    a.add_note("비서의 판단", doc="_journal.md")
    assert a.lines()[-1] == "심사 경험이 생겼다" and "비서의 판단" not in a.lines()
    assert (tmp_path / "n" / s.area_notes_file).exists()


async def test_p4a5_local_refresh_is_a_no_op(tmp_path, settings):
    a = LocalFolderArea(str(tmp_path), settings)
    assert await a.refresh() is True
