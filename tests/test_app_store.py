"""P5-F1 ~ F7: the optional app distribution peer. An event names an app this peer does not have; the event router asks
the configured distribution peers, checks the package by code only (source hash, publisher signature, trusted publishers,
size, id and version), asks the owner, loads it, checks id, version and the event's code hash again, installs it and
routes the event. Installed packages survive a restart."""
import dataclasses
import json

from arena.crypto import Identity
from arena.peer.app_store import AppStoreRole
from arena.peer.plugin import app_fingerprint, app_ref
from arena.sdk import check_package, load_app_file, package_app
from tests.fakes import FakeOwner
from tests.test_event_apps import World, announce, route

APP_ID = "6b3f0c2e-5a7d-4e19-9c41-2d8f7a1b3e55"
SRC = '''"""an app shipped through an app distribution peer (test sample)"""
from arena.peer.plugin import BaseApp


class Shipped(BaseApp):
    name, version, app_id = "shipped", "1.0", "6b3f0c2e-5a7d-4e19-9c41-2d8f7a1b3e55"

    def __init__(self, settings):
        self.s, self.got = settings, []

    async def on_event(self, ctx, notice, change):
        self.got.append((notice["notice_id"], change))


def make(settings):
    return Shipped(settings)
'''


def pkg(publisher, source=SRC, version="1.0", url=None):
    return package_app(publisher, app_id=APP_ID, name="shipped", version=version, module="shipped", factory="make", source=source, url=url)


def test_p5f1_f2_a_package_is_checked_by_code_only(settings):
    pub = Identity.generate()
    p = pkg(pub)
    assert p["manifest"]["publisher"] == pub.pub and check_package(p, settings, APP_ID, "1.0") is None
    assert "hash" in check_package(dict(p, source=SRC + "\n# changed"), settings)
    forged = dict(p, manifest=dict(p["manifest"], version="9.9"))
    assert "서명" in check_package(forged, settings)
    assert "배포자" in check_package(p, dataclasses.replace(settings, app_trusted_publishers=[Identity.generate().pub]))
    assert check_package(p, dataclasses.replace(settings, app_trusted_publishers=[pub.pub])) is None
    assert "크기" in check_package(p, dataclasses.replace(settings, app_max_source_bytes=10))
    assert "app_id" in check_package(p, settings, "00000000-0000-4000-8000-000000000000", "1.0")
    assert "버전" in check_package(p, settings, APP_ID, "2.0")


async def test_p5f3_the_store_publishes_lists_and_serves_and_keeps_packages(tmp_path, settings):
    w = World(tmp_path, settings)
    store = w.peer("store", [AppStoreRole(w.s, str(tmp_path / "store-dir"))])
    pub = Identity.generate()
    assert (await store.handle({"op": "app_publish", "package": pkg(pub)}))["ok"]
    bad = pkg(pub)
    bad["manifest"]["name"] = "renamed"
    assert not (await store.handle({"op": "app_publish", "package": bad}))["ok"]
    got = await store.handle({"op": "app_get", "app_id": APP_ID, "version": "1.0"})
    assert got["ok"] and got["package"]["source"] == SRC
    assert not (await store.handle({"op": "app_get", "app_id": "00000000-0000-4000-8000-000000000000"}))["ok"]
    lst = await store.handle({"op": "app_list"})
    assert [(x["app_id"], x["version"]) for x in lst["apps"]] == [(APP_ID, "1.0")]
    again = AppStoreRole(w.s, str(tmp_path / "store-dir"))  # a restarted store still has it
    assert (await again.ops()["app_get"](None, {"app_id": APP_ID}, None))["ok"]


async def _world(tmp_path, settings, owner_yes=True, owner=None, store_package=None, pin=True):
    s = dataclasses.replace(settings, app_store_urls=["mem://store"])
    w = World(tmp_path, s)
    store = w.peer("store", [AppStoreRole(w.s, str(tmp_path / "store-dir"))])
    publisher = Identity.generate()
    assert (await store.handle({"op": "app_publish", "package": store_package or pkg(publisher)}))["ok"]
    host = w.peer("host", [])
    player = w.peer("player", [])
    player.owner = owner if owner is not None else FakeOwner(yes=owner_yes, why="쓰겠다" if owner_yes else "남의 코드는 싫다")
    await w.boot(host, player, store)
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref" / "shipped.py").write_text(SRC, encoding="utf-8")
    sample = load_app_file(str(tmp_path / "ref" / "shipped.py"), "ref_shipped", "make", s)
    out = await announce(host, "app", [app_ref(sample, pin_code=pin)])
    return w, host, player, out["event_id"], sample


async def test_p5f4_f5_f6_a_missing_app_is_fetched_checked_approved_installed_and_routed(tmp_path, settings):
    w, host, player, ev, sample = await _world(tmp_path, settings)
    await route(player)
    app = player.app_by_id(APP_ID)
    assert app is not None and app.got == [(ev, "new")]
    assert app_fingerprint(app) == app_fingerprint(sample)
    asked = " ".join(player.owner.asked[-1])
    assert "shipped" in asked and "격리" in asked  # the owner is told what will run and that it runs inside the peer


async def test_p5f5_no_install_without_the_owners_yes(tmp_path, settings):
    w, host, player, ev, _ = await _world(tmp_path, settings, owner_yes=False)
    await route(player)
    assert player.app_by_id(APP_ID) is None


async def test_p5f5_an_autonomous_peer_installs_nothing(tmp_path, settings):
    from arena.peer.owner import NoOwner
    w, host, player, ev, _ = await _world(tmp_path, settings, owner=NoOwner())
    await route(player)
    assert player.app_by_id(APP_ID) is None


async def test_p5f6_code_that_differs_from_the_events_pinned_hash_is_not_installed(tmp_path, settings):
    other = SRC.replace("self.got.append((notice[\"notice_id\"], change))", "self.got.append(('x', change))")
    w, host, player, ev, _ = await _world(tmp_path, settings, store_package=pkg(Identity.generate(), source=other))
    await route(player)
    assert player.app_by_id(APP_ID) is None
    leftovers = list((tmp_path / "events").rglob("shipped.py"))
    assert not leftovers  # what was fetched and refused is removed


async def test_p5f4_a_store_may_answer_with_a_download_link(tmp_path, settings):
    linked = pkg(Identity.generate(), url="https://apps.example/shipped-1.0.py")
    linked["source"] = None
    fetched = []

    async def fake_fetch(url):
        fetched.append(url)
        return SRC
    w, host, player, ev, _ = await _world(tmp_path, settings, store_package=linked)
    player.events.installer.fetch_url = fake_fetch
    await route(player)
    assert fetched == ["https://apps.example/shipped-1.0.py"] and player.app_by_id(APP_ID) is not None


async def test_p5f7_installed_packages_are_checked_and_loaded_again_after_a_restart(tmp_path, settings):
    w, host, player, ev, _ = await _world(tmp_path, settings)
    await route(player)
    assert player.app_by_id(APP_ID) is not None
    from arena.peer.node import Peer, PeerConfig
    again = Peer(player.identity, w.s, PeerConfig(url="mem://player2"), player.area, player.owner, player.llm, w.t, w.log,
                 brokers=player.brokers, apps=[])
    await again.events.installer.reload(again.ctx(again.events))
    assert again.app_by_id(APP_ID) is not None
    # a package changed on disk while the peer was down is not loaded
    f = next((tmp_path / "events").rglob("package.json"))
    p = json.loads(f.read_text(encoding="utf-8"))
    p["source"] += "\n# changed on disk"
    f.write_text(json.dumps(p), encoding="utf-8")
    third = Peer(player.identity, w.s, PeerConfig(url="mem://player3"), player.area, player.owner, player.llm, w.t, w.log,
                 brokers=player.brokers, apps=[])
    await third.events.installer.reload(third.ctx(third.events))
    assert third.app_by_id(APP_ID) is None
