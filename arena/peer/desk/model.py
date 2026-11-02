"""One thing on the owner's desk. Kinds are registered in advance (dev/peer-spec.md 2.8): a kind says whether the
person's answer is awaited, and what an answer looks like."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ItemKind:
    name: str
    label: str
    awaits: bool          # someone (the assistant, code) waits for the person's answer
    answer_keys: tuple    # what an answer carries


ITEM_KINDS: dict[str, ItemKind] = {}


def register_item_kind(k: ItemKind) -> None:
    if k.name in ITEM_KINDS:
        raise ValueError(f"desk item kind {k.name!r} registered twice")
    ITEM_KINDS[k.name] = k


for _k in (ItemKind("question", "물음", True, ("yes", "why")),
           ItemKind("write", "글 부탁", True, ("fields",)),
           ItemKind("suggestion", "제안", True, ("approve",)),
           ItemKind("notice", "공지", False, ()),
           ItemKind("timer", "시각", False, ()),
           ItemKind("ledger", "원장", False, ()),
           ItemKind("message", "메시지", False, ())):
    register_item_kind(_k)


@dataclass
class DeskItem:
    id: str
    kind: str
    title: str
    body: str = ""
    event_id: str | None = None
    fields: dict = field(default_factory=dict)   # write: {name: description}; suggestion: {"tool": .., "args": ..}
    status: str = "open"                          # open | done
    answer: dict | None = None
    created: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DeskItem":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})
