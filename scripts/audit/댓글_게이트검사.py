# -*- coding: utf-8 -*-
"""
댓글 게이트 검사 스크립트 (2026-07-22 신설)

목적: 사장님 코어 12칸 + Tier1 고정문구 + 수치 불변식을 **기계로** 검사한다.
     LLM 자기승인 금지 — 이 스크립트를 통과하지 못한 세트는 시트에 기입하지 않는다.

정본 = 댓글_고정문구_사전.md  (충돌 시 그 파일이 이긴다)

사용법:
  python 댓글_게이트검사.py --file 댓글세트.txt --keyword "약국샴푸" --disease "지루성 두피염" --product 샴푸
  python 댓글_게이트검사.py --file 세트.md --keyword "가슴여드름" --disease "가슴 여드름" --product 바디 --json

반환: 통과=exit 0, 실패=exit 1 (실패 항목을 stdout에 나열)
"""
import argparse
import json
import re
import sys

# 콘솔 코드페이지(cp949)에서 한글·기호 출력 시 UnicodeEncodeError로 헛failure가 나는 것 방지
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 사장님 원문 Tier1 고정문구 (한 글자도 바꾸지 않는다) ───────────────────────
T1_C = "쪽지 보냈는데 저도 어떤 제품인지 알 수 있을까요 ㅠ 혹시 병원서 처방 받아야만 살 수 있는 건가요.."
T1_B2_OPEN = "혹시 모르니까 몇시간 뒤에 삭제할게요."
T1_F = "{kw} 검색해도 정보가 찾기가 쉽지가 않네요"
T1_F_REPLY = "{kw} 검색하는 사람들이 요새 늘어난 것 같아요"
T1_G = "저도 {disease} 때문에 고민이 많네요 ㅠㅠ"

# 12칸 순서 (라벨, 답글여부)
CORE = [
    ("A", False), ("글쓴이", True), ("B", False), ("글쓴이", True),
    ("C", True), ("B", True), ("D", True), ("E", False),
    ("글쓴이", True), ("F", False), ("글쓴이", True), ("G", False),
]

# 금칙어 (하나라도 걸리면 폐기)
# ★2026-07-22 v2: 사장님 샘플 반려에서 확정된 부자연 표현·이탈구멍 표현 추가
FORBIDDEN = {
    "치료용(D13 위반)": re.compile(r"치료용"),
    "극적 염증 수식(D4 위반)": re.compile(r"(끓는|들끓|끓어)"),
    "박 어근(D-019)": re.compile(r"박(아|아둠|아서|아라|자|는다|고)"),
    "성분·약리 단정": re.compile(r"케토코나졸|항진균|살리실|벤조일|BHA|설페이트프리|나이아신|판테놀|스테로이드\s*성분"),
    "링크·상호": re.compile(r"https?://|www\.|\.com|쿠팡|올리브영|네이버쇼핑"),
    "권위 수치 단정": re.compile(r"\d+\s*%\s*(개선|감소|효과)|임상\s*\d|특허\s*\d"),
    # v2 추가 — 자연스러움
    "대학병원+피부과 붙여쓰기": re.compile(r"대학병원\s*피부과"),
    "'~쪽' 어정쩡 표현": re.compile(r"(완화|진정|케어)\s*쪽\s*(샴푸|바디워시)|쪽이더라고요|쪽이에요"),
    "자기소개형 도입": re.compile(r"저\s*[^.。\n]{0,20}(사람인데요|갈아탄 사람|바꾼 사람인데)"),
    # v2 추가 — 이탈 구멍(D6): 대안과 비교하지 않는다
    "대안 비교(이탈구멍)": re.compile(r"(약이랑|약하고|약보다|약과)\s*(는)?\s*(아예\s*)?(다른|달리|차이)|일반\s*(샴푸|바디워시)(랑|이랑|하고)\s*다르게|(랑|이랑)\s*다르게\s*(피부|두피)\s*속"),
    "E칸 마감 상투구": re.compile(r"어디까지나\s*거드는"),
}

# 대안을 '위력 있게' 그리는 문형 (D6 위반)
D6_VIOLATION = re.compile(r"(확\s*죽이|강력하게\s*잡|세게\s*잡|효과는\s*확실|잘\s*듣긴\s*(하|해))")

SYMBOLS = {
    "대학병원": re.compile(r"대학병원"),
    "동네약국": re.compile(r"(동네\s*약국|약국에서\s*(추천|알려))"),
    "지인": re.compile(r"(피부과\s*(다니는|일하는)?\s*친구|약사\s*친구|친구가\s*약사)"),
    "연구자료": re.compile(r"(국립피부과학연구원|국제\s*피부면역학회지)"),
}


def split_blocks(text):
    """댓글 세트를 12칸 블록으로 자른다. 'ㄴ '로 시작하면 답글."""
    blocks = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        m = re.match(r"^(ㄴ\s*)?(글쓴이|[A-H])\s*[:：]\s*(.*)$", line)
        if m:
            blocks.append({
                "reply": bool(m.group(1)),
                "label": m.group(2),
                "text": m.group(3).strip(),
            })
        elif blocks:
            blocks[-1]["text"] += " " + line
    return blocks


def check(text, keyword, disease, product):
    fails, warns = [], []
    blocks = split_blocks(text)

    # 1. 12칸 개수·순서
    if len(blocks) != 12:
        fails.append(f"[1] 댓글 칸 수 {len(blocks)}개 — 정확히 12개여야 함 (보강 댓글 추가 금지)")
    else:
        for i, ((exp_label, exp_reply), got) in enumerate(zip(CORE, blocks), 1):
            if got["label"] != exp_label or got["reply"] != exp_reply:
                fails.append(
                    f"[1] {i}번 칸 불일치 — 기대 {'ㄴ' if exp_reply else ''}{exp_label} / 실제 {'ㄴ' if got['reply'] else ''}{got['label']}"
                )

    joined = "\n".join(b["text"] for b in blocks)

    # 2. Tier1 완전일치
    t1 = [
        ("ㄴC 쪽지+처방", T1_C),
        ("ㄴB 삭제예고", T1_B2_OPEN),
        ("F SEO", T1_F.format(kw=keyword)),
        ("ㄴ글쓴이 SEO", T1_F_REPLY.format(kw=keyword)),
        ("G 질병 마무리", T1_G.format(disease=disease)),
    ]
    for name, phrase in t1:
        if phrase not in text:
            fails.append(f"[2] Tier1 고정문구 불일치 — {name}: `{phrase}` 가 그대로 들어있지 않음 (각색 금지)")

    # 3. 키워드 정확히 5회
    kwc = joined.count(keyword)
    if kwc != 5:
        fails.append(f"[3] 키워드 '{keyword}' {kwc}회 — 정확히 5회여야 함 (A·B·ㄴD·F·ㄴ글쓴이)")

    # 4. [제품명] — 사장님 메뉴얼대로 ㄴB·ㄴD 2회 (1회도 허용)
    pc = joined.count("[제품명]")
    if pc not in (1, 2):
        fails.append(f"[4] [제품명] {pc}회 — 메뉴얼대로 ㄴB·ㄴD 2회(또는 1회)여야 함")

    # 5. 상징재 — B에 1개, ㄴD에 1개, 서로 다르게. 한 칸에 2개 겹침 금지
    #    (사장님 2026-07-22 확정: "왜 교차해서 동시에 써?" / "3 3 겹치는 것만 방지")
    found = [n for n, rx in SYMBOLS.items() if rx.search(joined)]
    if len(found) < 2:
        fails.append(f"[5] 상징재(권위) {len(found)}종 — B·ㄴD에 서로 다른 2종이 필요 (검출: {found or '없음'})")
    if len(blocks) == 12:
        b_syms = [n for n, rx in SYMBOLS.items() if rx.search(blocks[2]["text"])]
        d_syms = [n for n, rx in SYMBOLS.items() if rx.search(blocks[6]["text"])]
        if len(b_syms) > 1:
            fails.append(f"[5] B칸에 상징재 {len(b_syms)}개 겹침({b_syms}) — 한 자리엔 하나만")
        if len(d_syms) > 1:
            fails.append(f"[5] ㄴD칸에 상징재 {len(d_syms)}개 겹침({d_syms}) — 한 자리엔 하나만")
        if b_syms and d_syms and b_syms[0] == d_syms[0]:
            fails.append(f"[5] B와 ㄴD 상징재가 같음({b_syms[0]}) — 서로 달라야 함")
        if "연구자료" in d_syms:
            fails.append("[5] ㄴD에 연구원·학회지 — 자료는 간증에 쓰지 않는다(B에서만 인용)")

    # 6. 금칙어
    # ★G04 게이트 결함 교정(2026-07-22): 메인 키워드 자체가 성분어인 경우
    #   (항진균샴푸·케토코나졸샴푸·살리실산샴푸·설페이트프리샴푸·벤조일퍼옥사이드바디워시 등 배치 내 15개)
    #   [3]이 "정확히 5회" 넣으라고 요구하는 그 문자열을 [6]이 금칙으로 잡아
    #   **어떤 세트도 통과할 수 없었다** = 규칙끼리 충돌하는 검사기 결함.
    #   사장님 지정 키워드는 상위노출 전제조건(원문: "노출이 이 글의 목적이므로 키워드 정확 표기는
    #   자연스러움보다 우선이며 바꾸지 않습니다")이므로, 성분·약리 스캔에서만 키워드를 마스킹한다.
    #   → 키워드 **밖**의 성분·약리 단정은 종전대로 전부 잡힌다.
    #   ★G05 동일 결함(2026-07-22): 메인 키워드에 상호가 들어간 경우
    #   (올리브영지루성두피염샴푸·올리브영비듬샴푸·올리브영두피팩 등 배치 내 7개)
    #   [3]이 5회 넣으라는 그 문자열을 [6] '링크·상호'가 잡아 역시 통과 불가였다.
    #   → 상호 스캔에서도 키워드만 마스킹한다(키워드 밖의 상호 언급은 종전대로 전부 잡힘).
    masked = joined.replace(keyword, "○")
    MASK_KW = ("성분·약리", "링크·상호")
    for name, rx in FORBIDDEN.items():
        m = rx.search(masked if name.startswith(MASK_KW) else joined)
        if m:
            fails.append(f"[6] 금칙어 — {name}: '{m.group(0)}'")

    # 7. D6 — 대안을 위력 있게 그리기
    m = D6_VIOLATION.search(joined)
    if m:
        fails.append(f"[7] D6 위반(대안을 위력 있게 묘사) — '{m.group(0)}'")

    # 8. 글쓴이 규칙 — ㄴ답글로만 4회, 결과후기 금지
    author = [b for b in blocks if b["label"] == "글쓴이"]
    if len(author) != 4:
        fails.append(f"[8] 글쓴이 {len(author)}회 — 정확히 4회(ㄴ답글)여야 함")
    if any(not b["reply"] for b in author):
        fails.append("[8] 글쓴이가 독립 댓글로 등장 — 항상 ㄴ답글이어야 함")
    result_rx = re.compile(r"(써봤더니|쓰고\s*나서|바꾸고\s*나서|나았어요|좋아졌어요|괜찮아졌어요)")
    for b in author:
        m = result_rx.search(b["text"])
        if m:
            fails.append(f"[8] 글쓴이 결과후기 금지(D8) — '{m.group(0)}'")

    # 9. E칸 — 디테일 하나만. 제품·메리트 언급 0 (코어 준수, 2026-07-22 사장님 지적)
    if len(blocks) == 12:
        e = blocks[7]["text"]
        if re.search(r"\[제품명\]|매일\s*쓰는\s*걸\s*바꾸|진짜\s*잡힌\s*건|위에\s*그거", e):
            fails.append("[9] E칸에 제품·메리트 전달이 들어감 — E는 디테일 하나만(코어)")
        if len(e) > 120:
            warns.append(f"[9] E칸 {len(e)}자 — 메뉴얼 예시 수준(~80자)보다 김. 짧게")

    # 9-1. A칸 — 첫인상 단점 금지. "실제로 써봐야만 아는 것"만 (사장님 2026-07-22 반려)
    #      냄새·향·색·제형·용기·가격 = 뚜껑만 열어도 아는 것 → 리얼한 단점 아님
    if blocks:
        a = blocks[0]["text"]
        m = re.search(r"(냄새|향이|향은|향\s*때문|색이|색깔|제형|용기|펌핑|가격|비싸)", a)
        if m:
            fails.append(f"[9-1] A칸이 첫인상 단점('{m.group(0)}') — 실제로 써봐야 아는 단점만(효과 저하·재발 등)")

    # 10. ㄴB — 대안과 비교하는 문장이 없어야 한다 (이탈 구멍 차단)
    if len(blocks) == 12:
        nb = blocks[5]["text"]
        if re.search(r"다르게|다른\s*쪽|보다\s*순|비해", nb):
            fails.append("[10] ㄴB에 대안 비교 문장 — 이탈 구멍(D6). 원인 규정만 쓴다")

    # 11. 빈 줄 구분 (D9)
    if "\n\n" not in text:
        warns.append("[11] 댓글 사이 빈 줄이 없음 — 직원 복붙 편의(D9)")

    return fails, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--disease", required=True)
    ap.add_argument("--product", default="샴푸", choices=["샴푸", "바디"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    text = open(a.file, encoding="utf-8").read()
    fails, warns = check(text, a.keyword, a.disease, a.product)

    if a.json:
        print(json.dumps({"pass": not fails, "fails": fails, "warns": warns}, ensure_ascii=False, indent=1))
    else:
        print(f"=== 댓글 게이트: {a.file} (키워드={a.keyword})")
        if fails:
            print(f"[FAIL] {len(fails)}건")
            for f in fails:
                print("  ✗", f)
        else:
            print("[PASS] 필수 항목 전부 통과")
        for w in warns:
            print("  ⚠", w)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
