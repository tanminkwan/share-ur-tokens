"""Content kept off the ledger (CP-4) and how a text becomes the bytes that are hashed (CP-9). The ledger keeps only
the hash; these are codes, registered like the connection methods, so every implementation reads them the same way.

- storage kinds: where the content may be found (`ref.storage`). Many places may hold it; the hash is the same.
- proof methods: how the one who names the places vouches for them (`ref.proof`): `sha256` (compare the hash only),
  `ed25519` (a key signs canon({content_hash, storage})).
- content forms: how a work becomes bytes before hashing (`publish.form`). The same novel typed on another machine
  differs in line ends, a byte order mark, or how Hangul is composed (NFC or NFD); `utf8-nfc-lf` makes them one.

What the ledger checks: shape, registered names, a signature if there is one. It never fetches the content: whoever
gets it hashes it. Policy: dev/chain-policy.md 6절."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Callable

from ..crypto import canon, h, verify


@dataclass(frozen=True)
class StorageKind:
    name: str
    description: str


@dataclass(frozen=True)
class ProofMethod:
    name: str
    description: str
    check: Callable[[dict], "str | None"]   # the ref block -> error or None


@dataclass(frozen=True)
class ContentForm:
    name: str
    description: str
    to_bytes: Callable[[bytes], bytes]


STORAGE_KINDS: dict[str, StorageKind] = {}
PROOF_METHODS: dict[str, ProofMethod] = {}
CONTENT_FORMS: dict[str, ContentForm] = {}


def _register(table: dict, item) -> None:
    if item.name in table:
        raise ValueError(f"{item.name!r} registered twice")
    table[item.name] = item


register_storage_kind = lambda k: _register(STORAGE_KINDS, k)  # noqa: E731
register_proof_method = lambda m: _register(PROOF_METHODS, m)  # noqa: E731
register_content_form = lambda f: _register(CONTENT_FORMS, f)  # noqa: E731


# ---------------- content forms (CP-9) ----------------
def _utf8_nfc_lf(data: bytes) -> bytes:
    text = data.decode("utf-8")  # strict: a text that is not UTF-8 is not this form
    if text.startswith("﻿"):
        text = text[1:]
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).encode("utf-8")


def form_bytes(form: str, data: bytes) -> bytes:
    if form not in CONTENT_FORMS:
        raise ValueError(f"unknown content form {form!r} (known: {', '.join(sorted(CONTENT_FORMS))})")
    return CONTENT_FORMS[form].to_bytes(data)


def content_hash_of(data: bytes, form: str) -> str:
    """the hash a work is registered by: SHA-256 of its bytes in that form"""
    return h(form_bytes(form, data))


# ---------------- proof methods (CP-4) ----------------
def proof_target(ref: dict) -> dict:
    """what an ed25519 proof signs: the content hash and the places, as canonical JSON"""
    return {"content_hash": ref["content_hash"], "storage": ref["storage"]}


def _sha256_proof(ref: dict) -> str | None:
    return None  # nothing to sign: the receiver hashes what it got


def _ed25519_proof(ref: dict) -> str | None:
    pr = ref["proof"]
    if not isinstance(pr.get("signer"), str) or not pr["signer"] or not isinstance(pr.get("sig"), str):
        return "an ed25519 proof needs signer and sig"
    if not verify(pr["signer"], proof_target(ref), pr["sig"]):
        return "the ed25519 proof does not verify (signer over {content_hash, storage})"
    return None


# ---------------- the ref block ----------------
def ref_error(p: dict, settings) -> str | None:
    """the `ref` block of a publish or share: where the content is and how that is vouched for"""
    ref = p.get("ref")
    if ref is None:
        return None
    if not isinstance(ref, dict) or ref.get("content_hash") != p.get("content_hash"):
        return "ref must be an object naming the entry's own content_hash"
    st = ref.get("storage")
    if not isinstance(st, list) or not st or len(st) > settings.ref_storage_max:
        return f"ref.storage must list 1 to {settings.ref_storage_max} places"
    for x in st:
        if not isinstance(x, dict) or x.get("kind") not in STORAGE_KINDS:
            return f"each place needs a registered kind ({', '.join(sorted(STORAGE_KINDS))})"
        if not isinstance(x.get("location"), str) or not x["location"] or len(x["location"]) > settings.ref_location_max:
            return f"each place needs a location of at most {settings.ref_location_max} characters"
    if "size" in ref and (not isinstance(ref["size"], int) or isinstance(ref["size"], bool) or ref["size"] < 0):
        return "ref.size is a number of bytes"
    if "media_type" in ref and (not isinstance(ref["media_type"], str) or not ref["media_type"]):
        return "ref.media_type is a text such as text/plain"
    pr = ref.get("proof")
    if pr is not None:
        if not isinstance(pr, dict) or pr.get("method") not in PROOF_METHODS:
            return f"ref.proof.method must be one of {', '.join(sorted(PROOF_METHODS))}"
        if "how" in pr and not isinstance(pr["how"], str):
            return "ref.proof.how is a link to how to check it"
        return PROOF_METHODS[pr["method"]].check(ref)
    return None


def form_error(p: dict) -> str | None:
    f = p.get("form")
    if f is not None and f not in CONTENT_FORMS:
        return f"form must be a registered content form ({', '.join(sorted(CONTENT_FORMS))})"
    return None


for _k in (StorageKind("https", "웹 주소(https://...)"), StorageKind("peer", "어떤 peer의 공개 영역(공개키와 그 안의 이름)"),
           StorageKind("ipfs", "IPFS 내용 주소(cid)"), StorageKind("git", "git 저장소와 커밋"),
           StorageKind("place", "실물의 소재 설명(보관 장소, 등기, 위치)")):
    register_storage_kind(_k)
register_proof_method(ProofMethod("sha256", "해시 대조만: 받은 내용을 해시해 content_hash와 같은지 본다", _sha256_proof))
register_proof_method(ProofMethod("ed25519", "서명자가 정규 JSON {content_hash, storage}에 서명했다: 이 위치들을 그 키가 밝혔다", _ed25519_proof))
register_content_form(ContentForm("bytes", "파일의 바이트 그대로", lambda b: b))
register_content_form(ContentForm("utf8-nfc-lf", "UTF-8 글: 앞의 BOM을 빼고, 줄바꿈을 LF로, 유니코드 NFC(한글 조합형을 완성형으로)", _utf8_nfc_lf))
