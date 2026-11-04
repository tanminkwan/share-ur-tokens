"""Which kind of peer a window belongs to (user 2026-11-04: "각 peer(주로 api 서빙)는 바탕색상을 달리해서 구분하자. 예를
들어 관전 peer는 녹색 바탕이라던지"). The window sets <html data-peer="kind"> and shows the label as a tag, so the kind is
never told by color alone. The colors are in common_static/arena.css; the rules in .claude/skills/arena-ui/SKILL.md."""
from __future__ import annotations

PEER_KINDS: dict[str, str] = {
    "personal": "개인 peer",
    "sphinx": "스핑크스",
    "observer": "관전 peer",
    "key": "키 peer",
    "link": "link peer",
    "foundation": "재단 peer",
    "app-store": "앱 배포 peer",
    "search": "검색 peer",
    "service": "서비스 peer",
}


def kind_view(kind: str | None) -> dict:
    k = kind if kind in PEER_KINDS else "personal"
    return {"kind": k, "kind_label": PEER_KINDS[k]}
