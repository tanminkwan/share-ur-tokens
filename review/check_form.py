"""신청서의 문항 글이 주최 측 양식 원문(docs/form-original.txt)과 한 글자도 다르지 않은지 검사한다.

원문을 문항별 블록(문항 번호로 시작하는 줄부터 다음 문항 전까지, 끝의 빈 줄 제외)으로 나누고,
각 블록이 신청서 안에 그대로(줄 끝 공백 포함) 순서대로 들어 있는지 확인한다. 어긋나면 0이 아닌 값으로 끝난다.
    python3 review/check_form.py                                   # 신청서 원본
    python3 review/check_form.py docs/hackathon-proposal-submit.md # 제출용 압축본
"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
original = (root / "docs/form-original.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs/hackathon-proposal.md"
proposal = (target if target.is_absolute() else Path.cwd() / target).read_text(encoding="utf-8")

starts = [i for i, line in enumerate(original) if re.match(r"^[1-7]\. ", line)]
blocks = []
for k, i in enumerate(starts):
    end = starts[k + 1] if k + 1 < len(starts) else len(original)
    body = original[i:end]
    while body and body[-1].strip() == "":
        body.pop()
    blocks.append("\n".join(body))

pos, ok = 0, True
for n, block in enumerate(blocks, 1):
    found = proposal.find(block, pos)
    if found < 0:
        ok = False
        print(f"문항 {n}: 원문과 다릅니다(또는 순서가 바뀌었습니다)")
    else:
        pos = found + len(block)
        print(f"문항 {n}: 원문 그대로")
sys.exit(0 if ok and len(blocks) == 7 else 1)
