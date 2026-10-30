"""The assistant summarizes the public area (never owner-only documents) into the profile it signs and posts."""
from __future__ import annotations

from ..llm import ask_json

SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}}
SUMMARY_SYSTEM = ("당신은 한 구성원의 비서 에이전트입니다. 구성원의 공개 영역(지식과 경험 노트)을 읽고, 다른 peer들이 검색해서 "
                  "연락할 수 있도록 이 구성원이 누구이고 무엇을 할 수 있는지 3문장 이내로 요약하세요. 노트에 없는 경력이나 능력은 "
                  "만들지 말고, 실명은 쓰지 마세요. 일하는 원칙이 노트에 있으면 포함하세요.")


class ProfileBuilder:
    def __init__(self):
        self.version = 0

    async def build(self, peer) -> dict:
        lines = peer.area.lines()[-peer.settings.profile_lines_max:]
        d = await ask_json(peer.llm, peer.log, peer.pen, fallback=lambda: {"summary": lines[0] if lines else ""},
                           system=SUMMARY_SYSTEM, schema=SUMMARY_SCHEMA, user="[공개 영역]\n" + "\n".join(f"- {x}" for x in lines))
        self.version += 1
        profile = {"url": peer.config.url, "summary": d["summary"], "offers": peer.offers(), "labels": list(peer.config.labels),
                   "until": peer.clock() + peer.settings.profile_ttl_sec, "ver": self.version}
        for app in peer.apps:
            profile.update(app.profile_extra())
        return profile
