"""P5-D1 ~ D5, D7, D8: apps plug in through small capability interfaces and an injected context."""
import pytest

from arena.config import ConfigError
from arena.crypto import Identity
from arena.peer.context import AppContext, PlatformContext
from arena.peer.plugin import Decision, MessageHead, OfferProvider, OpProvider, RoleAcceptor, capabilities_of
from arena.peer.plugins import load_app, load_apps
from tests.test_peer import broker, make_peer  # noqa: F401


class OnlyOps:
    name, version, app_id = "only-ops", "1.0", "0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b01"

    def __init__(self):
        self.seen = []

    def ops(self):
        async def ping(ctx, msg, head):
            self.seen.append((type(ctx), head))
            ctx.state.save({"pings": ctx.state.load().get("pings", 0) + 1})
            return {"ok": True}
        return {"ping": ping}


class OffersAndAccepts:
    name, version, app_id = "role-x", "1.0", "0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b02"

    def offers(self):
        return ["x"]

    async def accept_role(self, ctx, role, request):
        return Decision(True, "ok") if role == "x" else None


def test_p5d2_capabilities_are_detected_per_app():
    assert capabilities_of(OnlyOps()) == ["OpProvider"]
    assert capabilities_of(OffersAndAccepts()) == ["OfferProvider", "RoleAcceptor"]
    assert isinstance(OffersAndAccepts(), RoleAcceptor) and not isinstance(OffersAndAccepts(), OpProvider)
    assert isinstance(OffersAndAccepts(), OfferProvider)


async def test_p5d1_p5d3_apps_get_a_context_and_the_head_not_the_peer(tmp_path, settings, broker):  # noqa: F811
    app = OnlyOps()
    p = make_peer(tmp_path, settings, broker, apps=[app])
    await p.handle({"op": "ping"}, meta={"group_id": await p.group_id("main"), "event_id": "ev-1"})
    ctx_type, head = app.seen[0]
    assert ctx_type is AppContext and head == MessageHead(await p.group_id("main"), "ev-1", None)
    ctx = p.ctx(app)
    for internal in ("transport", "apps", "home", "_ops", "persist", "handle"):
        assert not hasattr(ctx, internal), internal  # an app cannot reach the peer's insides through its context
    assert ctx.state.load() == {"pings": 1}
    assert isinstance(p.ctx(p.builtins[0]), PlatformContext)


async def test_p5d4_platform_ops_are_builtin_apps_and_reserved(tmp_path, settings, broker):  # noqa: F811
    p = make_peer(tmp_path, settings, broker)
    assert {"engage", "approve", "solicit"} <= set(p.skills())
    assert [b.name for b in p.builtins] == ["platform.roles", "platform.approvals", "platform.requests", "platform.events", "platform.scheduler"]

    class Hijack:
        name, version, app_id = "hijack", "1.0", "0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b03"

        def ops(self):
            async def engage(ctx, msg, head):
                return {"ok": True}
            return {"engage": engage}
    (tmp_path / "h").mkdir()
    with pytest.raises(ValueError, match="reserved"):
        make_peer(tmp_path / "h", settings, broker, apps=[Hijack()])


def test_p5d5_assembly_rules(tmp_path, settings, broker):  # noqa: F811
    class NoVersion:
        name, app_id = "nv", "0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b04"

        def ops(self):
            return {}

    class NoCapability:
        name, version, app_id = "nc", "1.0", "0b1d3c3e-6f7a-4a43-9d1e-7a0c2f8e1b05"
    for d in ("a", "b", "c"):
        (tmp_path / d).mkdir()
    with pytest.raises(ValueError, match="needs a name, a version and an app_id"):
        make_peer(tmp_path / "a", settings, broker, apps=[NoVersion()])
    with pytest.raises(ValueError, match="no capability"):
        make_peer(tmp_path / "b", settings, broker, apps=[NoCapability()])
    with pytest.raises(ValueError, match="registered twice"):
        make_peer(tmp_path / "c", settings, broker, apps=[OnlyOps(), OnlyOps()])


async def test_p5d5_install_at_runtime_and_load_from_settings(tmp_path, settings, broker):  # noqa: F811
    p = make_peer(tmp_path, settings, broker)
    app = load_app("tests.plugin_samples.apps:make_greeter", settings)
    await p.install(app)
    assert (await p.handle({"op": "greet", "who": "you"}))["hello"] == "you"
    with pytest.raises(ValueError):
        await p.install(load_app("tests.plugin_samples.apps:make_greeter", settings))  # same name twice
    with pytest.raises(ConfigError):
        load_app("tests.plugin_samples.apps:make_nothing", settings)
    with pytest.raises(ConfigError):
        load_app("no.such.module:x", settings)
    assert [a.name for a in load_apps(["tests.plugin_samples.apps:make_greeter"], settings)] == ["greeter"]


async def test_p5d7_a_new_entry_type_registers_without_touching_the_ledger(settings, clock):
    from arena.ledger import ENTRY_TYPES, EntryType, Ledger, MemoryStore, contribution, public_view, register_entry_type
    me = Identity.generate()
    register_entry_type(EntryType("checkin", lambda p: [p.get("who")], unique_nonce=True,
                                  public=lambda p, c: {"who": p["who"]}, counters={"checkins": 0},
                                  contribute=lambda rec, p, idx: rec[p["who"]].__setitem__("checkins", rec[p["who"]]["checkins"] + 1)))
    try:
        led = Ledger(Identity.generate(), MemoryStore(), settings, clock=clock)
        p = {"who": me.pub, "nonce": "n1", "group_id": "public"}
        e, err = led.propose("checkin", p, {me.pub: me.sign(p)})
        assert err is None and public_view(e, led.chain) == {"who": me.pub}
        assert led.propose("checkin", p, {me.pub: me.sign(p)})[1] == "replay (nonce already used)"
        assert contribution(led.chain)[me.pub]["checkins"] == 1
    finally:
        ENTRY_TYPES.pop("checkin")


def test_p5d8_broker_interfaces_are_small():
    from arena.broker.client import BrokerAPI, GroupAdmin, Health, NoticeBoard, ProfileBoard
    assert {"advertise", "list_profiles", "find"} == {n for n in dir(ProfileBoard) if not n.startswith("_")}
    assert "grant" not in dir(NoticeBoard) and "advertise" not in dir(NoticeBoard)
    assert all(x in BrokerAPI.__mro__ for x in (ProfileBoard, NoticeBoard, GroupAdmin, Health))
