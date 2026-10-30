"""P3-A3, P3-A4: signed A2A messages; parts for peers without a person."""
import pytest

from arena.crypto import Identity
from arena.llm import LLMError, NoLLM
from arena.peer.owner import NoOwner
from arena.signing import SignatureError, sign_message, verify_message


def test_p3a3_signed_message_roundtrip_and_rejects(identity):
    m = dict({"op": "search_notices", "q": "x"}, **sign_message(identity, "search_notices", now=100.0))
    assert verify_message(m, now=120.0, window=60) == identity.pub
    with pytest.raises(SignatureError):
        verify_message(dict(m, op="other"), now=120.0, window=60)
    with pytest.raises(SignatureError):
        verify_message(m, now=200.0, window=60)
    with pytest.raises(SignatureError):
        verify_message({"op": "x"}, now=0, window=60)
    with pytest.raises(SignatureError):
        verify_message(dict(m, pub=Identity.generate().pub), now=120.0, window=60)


async def test_p3a4_no_owner_and_no_llm():
    a = await NoOwner().ask("결재할까요?")
    assert a.yes is False and a.why
    with pytest.raises(PermissionError):
        await NoOwner().write("t", "c", {})
    with pytest.raises(LLMError):
        await NoLLM().ask_json(system="s", schema={}, user="u")
