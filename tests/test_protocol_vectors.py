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
