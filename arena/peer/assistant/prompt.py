"""Prompt: the code-made state line (shown to the LLM, and to the owner on the desk) and the system prompt of a turn.
One responsibility: what the LLM is told."""
from __future__ import annotations

from ..scheduler import fmt_time
from .handles import Handles
from .waiting_calls import WaitingCalls


class Prompt:
    def __init__(self, handles: Handles):
        self.handles = handles

    def state_line(self, ctx, st) -> str:
        """where this event stands, as the code sees it"""
        h = lambda pub: self.handles.handle(ctx, st, pub)
        revealed = [k for k, v in st.secrets.items() if v.get("reveal_hash")]
        sent = [f"{k}→{'·'.join(h(p) for p in v)}" for k, v in st.sent_reveals.items()]
        mine = [k for k, v in st.assignments.items() if ctx.pub in v]
        assigned = (f"배정(원장): {'; '.join(f'{k}=' + '·'.join(h(p) for p in v) for k, v in st.assignments.items())} / "
                    f"내 배정: {', '.join(mine) or '없음'} / ") if st.assignments else ""
        sealed = (" / ".join(st.sealed_view) + " / ") if st.sealed_view else ""
        held = {c[0] for c in st.contracts}
        open_roles = {r: v for r, v in st.role_offers.items() if r not in held}  # a role contracted since the last look is not open
        now = f"지금 시각: {fmt_time(ctx.clock())} / "
        plan = (f"일정({'원장' if st.on_ledger else '공지'}): " + "; ".join(f"{fmt_time(x['at'])} {x['code']}{' ' + x['subject'] if x.get('subject') else ''}" for x in st.schedule) + " / "
                if st.schedule else "")
        mine_t = [t for t in ctx.timers(st.event_id) if t["kind"] == "remind"]
        reminders = ("내 예약: " + "; ".join(f"{fmt_time(t['at'])} {t['data'].get('note', '')}" for t in mine_t) + " / ") if mine_t else ""
        endorsed = ("공동 서명: " + ", ".join(f"{h(e['endorser'])}({e['how']})" for e in st.endorsements) + " / ") if st.endorsements else ""
        return now + plan + reminders + WaitingCalls.line(st) + endorsed + assigned + sealed + (
            f"내 먼저 등록 라벨: {', '.join(st.secrets) or '없음'} / 원장에 공개한 내 라벨: {', '.join(revealed) or '없음'} / "
            f"내가 보낸 공개값: {', '.join(sent) or '없음'} / 내가 받은 서명 요청: {', '.join(st.pending) or '없음'} / "
            f"내가 제안한 공동 확인: {', '.join(st.proposals) or '없음'} / 참가 신청: {'함' if st.joined else '안 함'} / 닫힘: {st.closed} / "
            f"아는 peer: {', '.join(h(p) for p in st.peers) or '없음'} / "
            f"이 이벤트에서 맺은 역할 계약 {len(st.contracts)}건: {', '.join(f'{c[0]}={h(c[1])}' for c in st.contracts) or '없음'}"
            + ((f" / 참가 신청자(코드 확인) {len(st.applicants)}명: {', '.join(h(p) for p in st.applicants) or '없음'}"
                f" / 아직 계약하지 않은 신청자: {', '.join(h(p) for p in st.applicants if p not in {c[1] for c in st.contracts}) or '없음'}"
                + (" / 아직 계약 없는 역할: " + "; ".join(f"{r}(프로필에 내건 peer: {', '.join(h(p) for p in v) or '없음'})"
                                                    for r, v in open_roles.items()) if open_roles else "")
                + " / 나는 개최자다(참가 신청은 참가자가 하는 일이고, 개최자는 신청자와 계약한다)") if st.role == "host" else ""))

    def system(self, ctx, st, tool_lines: str) -> str:
        """the system prompt of one turn: who I am, the rules, the owner's standing instruction, where things stand, the tools"""
        h = lambda pub: self.handles.handle(ctx, st, pub)
        return (f"당신은 peer '{ctx.pen}'의 비서 에이전트입니다. 이벤트 '{st.title}'(event_id {st.event_id}, broker 그룹 {st.group_id})에 "
                f"{'개최자' if st.role == 'host' else '참가자'}로 참여합니다. 아래 이벤트 규칙을 정확히 따르세요. 규칙에 없는 일은 하지 말고, "
                "확실하지 않으면 note로 적은 뒤 wait 하세요. 소유자(사람)에게 묻는 말은 한국어로 씁니다. "
                "peer는 필명(필명-xxxxxx)으로, 해시는 #로 시작하는 짧은 참조로 부르며, 도구에도 그대로 넣으면 됩니다.\n\n[이벤트 규칙]\n" + st.rules
                + (f"\n\n[소유자의 지시] {self.handles.shorten(ctx, st, st.instruction)}" if st.instruction else "")
                + ("" if st.on_ledger else "\n[원장 없음] 이 broker 그룹에는 원장이 없다. 계약·등록·공개·공동 확인·배정 같은 기록은 할 수 없고, "
                   "메시지와 서비스 호출로만 진행한다. 개최자는 끝낼 때 close_notice로 공지를 마감한다.")
                + (f"\n[등록 값] 이 이벤트에서 등록(commit)하는 값은 다음 중 하나다: {', '.join(st.policy['reveal_values'])}" if st.policy.get("reveal_values") else "") +
                f"\n\n[나] {h(ctx.pub)}\n[개최자] {h(st.issuer_pub)}\n[지금 상태] {self.state_line(ctx, st)}\n\n[쓸 수 있는 도구]\n{tool_lines}\n\n"
                "먼저 도구 하나를 고르면, 그 도구의 인자를 따로 묻습니다. 이번 입력에 대해 규칙이 정한 일을 다 했으면 wait를 고르세요.")
