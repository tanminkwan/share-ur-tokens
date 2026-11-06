import os
import stat

import pytest

from arena.crypto import Identity, canon, h, pen_name, verify
from arena.signing import SignatureError, sign_request, verify_request


def test_r1_3_identity_signs_and_verifies(identity):
    payload = {"b": 1, "a": [1, 2]}
    sig = identity.sign(payload)
    assert verify(identity.pub, payload, sig)
    assert not verify(identity.pub, {"b": 2, "a": [1, 2]}, sig)
    assert not verify(Identity.generate().pub, payload, sig)
    assert not verify("zz", payload, sig)  # malformed key never raises


def test_r1_3_identity_survives_save_and_load(tmp_path, identity):
    p = tmp_path / "k" / "me.key"
    identity.save(str(p))
    again = Identity.load(str(p))
    assert again.pub == identity.pub
    assert verify(identity.pub, {"x": 1}, again.sign({"x": 1}))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_r1_3_load_or_create_makes_a_key_once(tmp_path):
    p = str(tmp_path / "svc.key")
    a = Identity.load_or_create(p)
    b = Identity.load_or_create(p)
    assert a.pub == b.pub


def test_r1_3_pen_name_uses_prefix_and_length():
    pub = "abcdef0123456789"
    assert pen_name(pub, nick="필명", n=6) == "필명-abcdef"
    assert pen_name(pub, nick="비단길", n=4) == "비단길-abcd"


def test_r1_4_canon_and_hash_are_order_independent():
    a = {"x": 1, "y": {"b": 2, "a": 1}}
    b = {"y": {"a": 1, "b": 2}, "x": 1}
    assert canon(a) == canon(b)
    assert h(canon(a)) == h(canon(b))
    assert len(h(b"")) == 64
    assert "한글" in canon({"k": "한글"}).decode()  # not escaped


def test_r1_5_signed_request_roundtrip(identity):
    now = 1_800_000_000.0
    headers = sign_request(identity, "GET", "/chain", now=now)
    assert set(headers) == {"X-Arena-Pub", "X-Arena-Ts", "X-Arena-Sig"}
    assert verify_request(headers, "GET", "/chain", now=now + 10, window=60) == identity.pub


@pytest.mark.parametrize("method,path,skew", [("POST", "/chain", 0), ("GET", "/other", 0), ("GET", "/chain", 61), ("GET", "/chain", -61)])
def test_r1_5_signed_request_rejects_wrong_target_or_stale(identity, method, path, skew):
    now = 1_800_000_000.0
    headers = sign_request(identity, "GET", "/chain", now=now)
    with pytest.raises(SignatureError):
        verify_request(headers, method, path, now=now + skew, window=60)


def test_r1_5_signed_request_rejects_missing_or_garbage_headers():
    with pytest.raises(SignatureError):
        verify_request({}, "GET", "/chain", now=0, window=60)
    with pytest.raises(SignatureError):
        verify_request({"X-Arena-Pub": "zz", "X-Arena-Ts": "nope", "X-Arena-Sig": "00"}, "GET", "/chain", now=0, window=60)
