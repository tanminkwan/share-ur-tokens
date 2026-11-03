"""The protocol spec (dev/protocol.md) ships test vectors (dev/protocol-vectors.json) so a peer written in another
language can check its encoding, hashing and signing byte for byte. This keeps the vectors equal to what the code does."""
import json
import pathlib

from arena.crypto import Identity, canon, commit_hash, h, pen_name, verify
from arena.signing import sign_request, verify_request

V = json.loads((pathlib.Path(__file__).resolve().parents[1] / "dev" / "protocol-vectors.json").read_text(encoding="utf-8"))


def test_protocol_vectors_match_the_code(settings):
    me = Identity.from_hex(V["private_key_hex"])
    assert me.pub == V["public_key_hex"]
    assert pen_name(me.pub, settings.pen_name_prefix, settings.pen_name_len) == V["pen_name"]
    assert canon(V["canonical_json"]["input"]).decode() == V["canonical_json"]["bytes_utf8"]
    assert me.sign(V["signature"]["payload"]) == V["signature"]["sig_hex"]  # ed25519 signatures are deterministic
    assert verify(me.pub, V["signature"]["payload"], V["signature"]["sig_hex"])
    assert h(b"hello") == V["sha256_of_hello"]
    c = V["commit_hash"]
    assert commit_hash(c["label"], c["value"], c["salt"], c["pub"]) == c["hash"]
    r = V["signed_request"]
    assert sign_request(me, r["method"], r["path"], now=r["ts"]) == r["headers"]
    assert verify_request(r["headers"], r["method"], r["path"], now=r["ts"], window=60) == me.pub
    e = V["ledger_entry_hash"]
    assert h(canon(e["body"])) == e["hash"]
    assert all(verify(pub, e["body"]["payload"], sig) for pub, sig in e["body"]["sigs"].items())


def test_protocol_3_vector_with_an_envelope():
    """protocol 3: the private hash, the hash of the private signatures and the entry hash, byte for byte"""
    from arena.ledger import hash_body, private_hash
    x = V["ledger_entry_with_envelope"]
    e, env = x["entry"], x["envelope"]
    assert e["payload"]["private"] == private_hash(env["fields"]) and e["private_sigs"] == private_hash(env["sigs"])
    assert h(canon(hash_body(e))) == x["hash"]
    assert all(verify(pub, e["payload"], sig) for pub, sig in env["sigs"].items())
    assert "provider" not in e["payload"] and env["fields"]["provider"] == V["public_key_hex"]
