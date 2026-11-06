"""The protocol spec (dev/protocol.md) ships test vectors (dev/protocol-vectors.json) so a peer written in another
language can check its encoding, hashing and signing byte for byte. This keeps the vectors equal to what the code does."""
import dataclasses
import json
import pathlib

from arena.crypto import Identity, canon, commit_hash, h, pen_name, verify
from arena.signing import sign_request, verify_request

V = json.loads((pathlib.Path(__file__).resolve().parents[1] / "dev" / "protocol-vectors.json").read_text(encoding="utf-8"))


def test_protocol_vectors_match_the_code(settings):
    me = Identity.from_hex(V["private_key_hex"])
    assert me.pub == V["public_key_hex"]
    assert pen_name(me.pub, settings.pen_name_default_nick, settings.pen_name_len) == V["pen_name"]
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


def test_key_backup_and_commitment_vectors(settings):
    """P6-K2, K3: the encrypted key backup and the promised-next-key hash, byte for byte"""
    from arena.keys.backup import open_backup, seal_backup
    from arena.ledger.peer_keys import key_commitment
    x = V["key_backup"]
    b = x["backup"]
    me, nxt = Identity.from_hex(V["private_key_hex"]), Identity.from_hex(x["next_private_key_hex"])
    fixed = dataclasses.replace(settings, key_backup_scrypt_n=b["kdf"]["n"], key_backup_scrypt_r=b["kdf"]["r"], key_backup_scrypt_p=b["kdf"]["p"])
    assert seal_backup(me, x["passphrase"], fixed, nxt, salt=bytes.fromhex(b["kdf"]["salt"]), nonce=bytes.fromhex(b["cipher"]["nonce"])) == b
    keys = open_backup(b, x["passphrase"], settings)
    assert keys["current"].pub == me.pub and keys["next"].pub == nxt.pub
    assert key_commitment(V["key_commitment"]["pub"]) == V["key_commitment"]["hash"] and V["key_commitment"]["pub"] == nxt.pub


def test_content_form_vector():
    """CP-9: a text made into the bytes that are hashed, byte for byte (BOM, CRLF, CR, decomposed Hangul)"""
    from arena.ledger.refs import content_hash_of, form_bytes
    x = V["content_form"]
    raw = bytes.fromhex(x["input_hex"])
    assert form_bytes(x["form"], raw).hex() == x["bytes_hex"] and content_hash_of(raw, x["form"]) == x["hash"]


def test_p8_ceremony_vectors_match_the_code():
    """dev/phase8 design 3: a signing request, its hash and the god's signature; a retirement declaration, its hash and a witness's signature"""
    from arena.ceremony import formats as F
    me = Identity.from_hex(V["private_key_hex"])
    c = V["ceremony_request"]
    assert F.request_hash(c["request"]) == c["request_hash"] and F.sign(c["request"], me) == c["signatures"]
    assert F.collect(c["request"], [c["signatures"]])[1] is None
    r = V["key_retirement"]
    assert F.declaration_hash(r["declaration"]) == r["declaration_hash"]
    assert verify(me.pub, r["declaration"]["body"], r["declaration"]["sigs"][me.pub])
