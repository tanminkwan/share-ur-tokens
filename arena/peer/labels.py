"""Capability labels the agent attaches itself. Two kinds of evidence, never anything else:
  ledger  -> "역할:<role>" when the recorders' track records show enough contracts in that role
  area    -> "분야:<field>" when the model names a field AND quotes a sentence that really is in the public area"""
from __future__ import annotations

from ..llm import ask_json
from .track import track_of

FIELDS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fields"], "properties": {"fields": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["field", "evidence"],
                               "properties": {"field": {"type": "string"}, "evidence": {"type": "string"}}}}}}


def _flat(text: str) -> str:
    return " ".join(text.split())


class CapabilityLabeler:
    def __init__(self, settings):
        self.s = settings

    def system(self) -> str:
        vocab = (f" 분야 이름은 반드시 다음 목록 안에서만 고르세요: {', '.join(self.s.label_field_vocab)}." if self.s.label_field_vocab else "")
        return (f"당신은 한 구성원의 비서 에이전트입니다. 구성원의 공개 영역을 읽고, 이 구성원이 잘 아는 분야를 최대 {self.s.label_field_max}개 "
                "짧은 이름으로 고르세요. 분야 이름은 공개 영역에 쓰인 말로 짓습니다(공개 영역이 한국어면 한국어로, 번역하지 말 것). 분야마다 근거가 된 문장을 공개 영역에서 **글자 그대로** 인용하세요. 공개 영역에 없는 분야는 고르지 마세요." + vocab)

    async def compute(self, peer) -> list[dict]:
        s, person = self.s, set(peer.config.labels)
        caps, seen = [], set(person)
        if peer.known_recorders:
            t = await track_of(peer, peer.identity.pub, peer.known_recorders)
            for role, n in sorted(t["roles"].items()):
                label = s.label_role_prefix + role
                if n >= s.label_role_min and label not in seen:
                    seen.add(label)
                    caps.append({"label": label, "basis": "ledger",
                                 "evidence": {u: tr["roles"].get(role, 0) for u, tr in t["by_source"].items() if tr["roles"].get(role)}})
        lines = peer.area.lines()
        if lines:
            flat = _flat(" ".join(lines))
            d = await ask_json(peer.llm, peer.log, peer.pen, fallback=lambda: {"fields": []}, system=self.system(),
                               schema=FIELDS_SCHEMA, user="[공개 영역]\n" + "\n".join(f"- {x}" for x in lines))
            n = 0
            for f in d.get("fields", []):
                ev, label = _flat(str(f.get("evidence", ""))).strip("'\" "), s.label_field_prefix + _flat(str(f.get("field", "")))
                name = label[len(s.label_field_prefix):]
                if s.label_field_vocab and name not in s.label_field_vocab:
                    continue
                if n >= s.label_field_max or label in seen or len(ev) < s.label_evidence_min_len or ev not in flat:
                    continue
                seen.add(label)
                caps.append({"label": label, "basis": "area", "evidence": ev})
                n += 1
        return caps
