"""Every window's page and files carry Cache-Control: no-cache, so a plain browser refresh shows a new version at once
(user 2026-11-06: the rename button did not show after an update until a hard refresh)."""
from starlette.testclient import TestClient

from arena.bundled.web_api import screen_routes
from starlette.applications import Starlette


def test_pages_and_files_are_revalidated_every_time(tmp_path):
    (tmp_path / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (tmp_path / "app.js").write_text("export {}", encoding="utf-8")
    c = TestClient(Starlette(routes=screen_routes(str(tmp_path))))
    for path in ("/", "/static/app.js", "/common/dom.js"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    etag = c.get("/static/app.js").headers["etag"]
    again = c.get("/static/app.js", headers={"if-none-match": etag})
    assert again.status_code == 304  # unchanged: nothing is sent again
