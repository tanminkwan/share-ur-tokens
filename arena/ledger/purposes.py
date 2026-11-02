"""Purpose codes: the column `purpose` inside the payload (user 2026-11-02: "payload 영역은 자율성을 보장하되, code화할
가치가 있는 것들은 payload 밖 또는 payload 내 독립적인 column을 부여해").

The payload stays free: the ledger does not read fields it has no column for. What is worth a code gets a column. The kind
of act is the entry `type`, outside the payload (set by the recorder's rules, sealed). Why an entry was made, when one type
serves several ends, is `purpose`: a registered code inside the payload, so the signers sign it. The ledger accepts only
registered codes, only on the types each code is for, and runs the code's own check. An entry without a purpose is fine
(autonomy): it simply makes no coded claim."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

PurposeCheck = Callable[[list, dict], "str | None"]   # (chain, entry) -> why refused, or None


@dataclass(frozen=True)
class Purpose:
    code: str
    types: tuple            # the entry types this purpose may be declared on
    description: str        # plain words, shown in the protocol and to agents
    check: PurposeCheck | None = None


PURPOSES: dict[str, Purpose] = {}


def register_purpose(p: Purpose) -> None:
    if p.code in PURPOSES:
        raise ValueError(f"purpose {p.code!r} registered twice")
    PURPOSES[p.code] = p


def check_purpose(chain, e) -> str | None:
    code = e["payload"].get("purpose")
    if code is None:
        return None
    p = PURPOSES.get(code)
    if p is None:
        return f"unknown purpose {code!r}"
    if e["type"] not in p.types:
        return f"purpose {code!r} is not for {e['type']} entries"
    return p.check(chain, e) if p.check else None


# ---------------- built-in purposes ----------------
def _no_label(chain, e):
    if e["payload"].get("label") is not None:
        return "authorship: a work is registered as it is, not sealed under a label (use purpose commit)"


def _label(chain, e):
    if e["payload"].get("label") is None:
        return "commit: a sealed registration needs a label to open it later"


register_purpose(Purpose("authorship", ("publish",), "저작 내용과 그 시점의 증명: 이 사람이 이 내용을 이 시각에 이미 가지고 있었다. "
                         "책에 원장 정보를 찍어 거꾸로 찾게 한다(dev/chain-policy.md 6.1)", _no_label))
register_purpose(Purpose("commit", ("publish",), "나중에 공개할 값의 봉인 등록(먼저 등록하고 나중에 공개)", _label))
