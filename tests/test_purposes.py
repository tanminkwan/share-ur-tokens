"""Coded columns (user 2026-11-02): the payload stays free, but what is worth a code gets its own column. The kind of act
is the entry type (outside the payload); why the entry was made is `purpose`, a registered code inside the payload."""
from arena.ledger import PURPOSES
from tests.test_ledger import Cast
from tests.test_recorder_service import svc, reader  # noqa: F401  (fixtures)


def _publish(cast, **extra):
    kind, p, _ = cast.publish(ev=None)
    p.update(extra)
    return kind, p, {cast.author.pub: cast.author.sign(p)}


async def test_purpose_codes_are_registered_and_checked(svc):
    cast = Cast()
    assert {"authorship", "commit"} <= set(PURPOSES)
    assert "unknown purpose" in (await svc.record(*_publish(cast, purpose="poem")))["error"]
    assert "label" in (await svc.record(*_publish(cast, purpose="authorship", label="m1")))["error"]
    assert "label" in (await svc.record(*_publish(cast, purpose="commit")))["error"]
    ok = await svc.record(*_publish(cast, purpose="authorship", note="자유 영역: 원장은 읽지 않는다"))
    assert ok["ok"]
    v = svc.verify(ok["hash"])
    assert v["purpose"] == "authorship" and "note" not in v  # the column is public, the free area is not


async def test_a_purpose_belongs_to_its_types_and_no_purpose_is_fine(svc):
    cast = Cast()
    kind, p, sigs = cast.share()
    p["purpose"] = "authorship"  # the purpose column is checked before signatures
    assert "not for share" in (await svc.record(kind, p, sigs))["error"]
    assert (await svc.record(*cast.publish(content="free", ev=None)))["ok"]  # autonomy: no coded claim, still recorded
