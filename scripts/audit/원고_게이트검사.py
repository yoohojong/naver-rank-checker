# -*- coding: utf-8 -*-
"""
원고 게이트 검사 스크립트 (v4 측정 정의 기계 검증)

v4 프롬프트가 '산술 검증(글자수·키워드 횟수)은 LLM이 약하다 → 별도 스크립트로 외부 확인'을
권장한다. 이 스크립트가 그 외부 검증기다. 본문(그리고 선택적 댓글)을 넣으면
글자수/줄/키워드/감정자음/사진/최장줄을 v4 측정 정의 그대로 재서 게이트 통과 여부를 판정한다.

측정 정의(v4 고정):
- 글자수  = 공백·줄바꿈·(사진n) 자리표시 줄 제외, 자모(ㅠ/ㅜ)·문장부호(;;/..) 포함.
- 줄(단위) = 줄바꿈으로 나뉜 '비어있지 않은' 한 줄. (사진n) 자리표시 줄은 제외, 빈 줄도 제외.
- 키워드  = 풀스트링(정확 일치) 카운트. 자른/붙인 변형은 0회.
- 감정자음 = 'ㅠ' 또는 'ㅜ' 각 문자 총 개수(ㅠㅠ=2). 주 자음 = 더 많은 쪽.

사용법:
  # 대본 샘플 markdown 통째로 파싱해 4종 일괄 검사
  python 원고_게이트검사.py 설득축_대본_샘플_4종.md

  # 본문 파일 하나 검사(3단계 실키워드 발행 전)
  python 원고_게이트검사.py --body 본문.txt --title "제목..." --keyword "머리간지러움" --stage 3

주의: 이 스크립트는 '숫자 게이트'만 본다. 타사가드(성분·약리·권위·실명·링크)·5버튼·축정합·자연스러움
같은 질적 게이트는 사람/리뷰 에이전트 몫이다. 아래 guard_scan은 명백한 위반 후보를 흘려주는 보조 힌트일 뿐.
"""
import re
import sys

# 콘솔 코드페이지(cp949)에서 한글·기호 출력 시 UnicodeEncodeError로 헛failure가 나는 것 방지
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse

PHOTO_LINE = re.compile(r"^\(\s*사진\s*\d+.*\)\s*$")  # (사진1 — ...) 자리표시 줄

# 단계별 게이트 밴드 (v4 (b)(c)(f)(g))
# ★2026-07-22 교정: kw 밴드가 정본(원고_프롬프트_복붙용.md L21·L68 = "정확히 5~6회")과
#   반대로 잠겨 있었다(3·4단계 2~3 / 5단계 4~5). 그 결과 키워드 3회짜리 본문이 "통과"로 찍혀
#   프롬프트 미준수가 검출되지 않았다(2026-07-21 파일럿 실측). → 전 단계 (5, 6)으로 통일.
#   근거: 원장 확정 "본문 메인키워드 = 정확히 5~6회, 임의 완화 금지"(상위노출 전제조건).
BANDS = {
    3: dict(chars=(520, 870), kw=(5, 6), lines=(17, 34), emo=(12, 23), longest=90),
    4: dict(chars=(520, 870), kw=(5, 6), lines=(17, 34), emo=(12, 23), longest=90),
    5: dict(chars=(600, 870), kw=(5, 6), lines=(17, 34), emo=(12, 23), longest=90),
}

# 보조 힌트: 명백한 가드 위반 후보(정밀 아님 — 리뷰 에이전트가 최종 판정)
GUARD_HINTS = {
    "박 어근(금지)": re.compile(r"박(아|아둠|아서|아라|자|는다)"),
    "권위(약사/의사/교수/피부과)": re.compile(r"약사|의사|교수|피부과\s*\d|전문의|N위|\d+위"),
    "링크/URL": re.compile(r"https?://|www\.|\.com|쿠팡|링크"),
    "성분/약리 후보": re.compile(r"케토코나졸|항진균|살리실|BHA|설페이트프리|나이아신|판테놀|세라마이드\s*함유"),
}


def strip_body_lines(body_text):
    """본문을 줄 단위로 나누되 (사진n) 자리표시 줄과 빈 줄을 분리해 돌려준다."""
    prose, photos = [], 0
    for raw in body_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if PHOTO_LINE.match(line):
            photos += 1
            continue
        prose.append(line)
    return prose, photos


def char_count(prose_lines):
    """공백 제외 글자수(자모·문장부호 포함)."""
    joined = "".join(prose_lines)
    return len(re.sub(r"\s", "", joined))


def measure(title, body, keyword, stage=None, comments=None):
    prose, photos = strip_body_lines(body)
    chars = char_count(prose)
    lines = len(prose)
    longest = max((len(re.sub(r"\s", "", ln)) for ln in prose), default=0)

    title = title or ""
    kw_title = title.count(keyword)
    kw_body = "".join(prose).count(keyword)  # 본문만(제목 별도)
    kw_total = kw_title + kw_body

    full = title + "\n" + "\n".join(prose)
    n_tt = full.count("ㅠ")
    n_tw = full.count("ㅜ")
    main_emo = "ㅠ" if n_tt >= n_tw else "ㅜ"
    main_cnt = max(n_tt, n_tw)

    # 가드 힌트 스캔(본문+댓글)
    scan_target = full + ("\n" + comments if comments else "")
    hints = {}
    for label, pat in GUARD_HINTS.items():
        found = pat.findall(scan_target)
        if found:
            hints[label] = sorted(set(found))[:6]

    result = dict(
        title=title, keyword=keyword, stage=stage,
        chars=chars, lines=lines, longest=longest, photos=photos,
        kw_title=kw_title, kw_body=kw_body, kw_total=kw_total,
        emo_tt=n_tt, emo_tw=n_tw, main_emo=main_emo, main_cnt=main_cnt,
        guard_hints=hints,
    )
    if stage in BANDS:
        result["gate"] = _grade(result, BANDS[stage])
    return result


def _grade(r, band):
    checks = {}
    lo, hi = band["chars"];  checks["글자수"] = (lo <= r["chars"] <= hi, f'{r["chars"]} (기준 {lo}~{hi})')
    # ★2026-07-22 교정 2회차: 밴드를 kw_total(제목+본문)에 걸면 본문 4회짜리가 통과한다.
    #   정본(원고_프롬프트_복붙용.md L68) = "**본문**에 정확히 5~6회". 제목은 별도 조건.
    #   → 밴드는 kw_body 에 건다. total 은 참고 표시만.
    lo, hi = band["kw"];     checks["키워드"] = (lo <= r["kw_body"] <= hi, f'본문 {r["kw_body"]} (기준 {lo}~{hi}) · 제목 {r["kw_title"]} · 합 {r["kw_total"]}')
    lo, hi = band["lines"];  checks["줄"]    = (lo <= r["lines"] <= hi, f'{r["lines"]} (기준 {lo}~{hi})')
    lo, hi = band["emo"];    checks["감정자음"] = (lo <= r["main_cnt"] <= hi, f'{r["main_emo"]} {r["main_cnt"]} (기준 {lo}~{hi})')
    checks["최장줄"] = (r["longest"] <= band["longest"], f'{r["longest"]} (≤{band["longest"]})')
    checks["사진"]   = (r["photos"] >= 1, f'{r["photos"]}장')
    return checks


def parse_samples(md_path):
    """설득축_대본_샘플 markdown에서 ## ▶ 섹션마다 (name,title,body) 추출."""
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    blocks = re.split(r"^##\s*▶\s*", text, flags=re.M)[1:]
    out = []
    for b in blocks:
        name = b.splitlines()[0]
        name = re.sub(r"\(.*?\)", "", name).strip()
        # 제목
        mt = re.search(r"##\s*\[제목\]\s*\n(.+)", b)
        title = mt.group(1).strip() if mt else ""
        # 본문: [본문] ~ [댓글 대본]
        mb = re.search(r"##\s*\[본문\]\s*\n(.*?)(?=^##\s*\[댓글)", b, flags=re.S | re.M)
        body = mb.group(1) if mb else ""
        # 댓글: [댓글 대본] ~ [이 대본]
        mc = re.search(r"##\s*\[댓글 대본\]\s*\n(.*?)(?=^##\s*\[이 대본)", b, flags=re.S | re.M)
        comments = mc.group(1) if mc else ""
        out.append(dict(name=name, title=title, body=body, comments=comments))
    return out


_SAMPLE_STAGE = {
    "머리간지러움": 3,     # 순수 증상 하소연, 제품 안 씀 → 2~3회
    "니조랄샴푸": 5,       # 니조랄 직접 써본 실패 후기 → 4~5회
    "등드름바디워시": 5,   # '등드름바디워시' 구매·반복사용 실패 → 4~5회
    "아토피바디워시": 4,   # 3개 갈아탄 비교 → v4 규칙상 2~3회(키워드=카테고리 일반명사)
}


def _stage_of(name):
    return _SAMPLE_STAGE.get(name, 3)


def _print(r):
    """게이트 결과를 출력하고 통과 여부(bool)를 돌려준다.
    ★2026-07-22: 이전에는 아무것도 돌려주지 않아 main()이 항상 exit 0을 냈다
      → '게이트 실패'라고 찍히는데도 자동 검증은 통과로 읽혔다(검증 사슬의 구멍)."""
    print(f'  제목: {r["title"]}')
    print(f'  글자수 {r["chars"]} · 줄 {r["lines"]} · 최장줄 {r["longest"]} · 사진 {r["photos"]}장')
    print(f'  키워드 "{r["keyword"]}" 총 {r["kw_total"]}회 (제목 {r["kw_title"]} + 본문 {r["kw_body"]})')
    print(f'  감정자음 ㅠ {r["emo_tt"]} / ㅜ {r["emo_tw"]}  → 주 {r["main_emo"]} {r["main_cnt"]}회')
    if r.get("guard_hints"):
        print(f'  ⚠️ 가드 힌트: {r["guard_hints"]}')
    if "gate" in r:
        for k, (ok, msg) in r["gate"].items():
            print(f'    [{"O" if ok else "X"}] {k}: {msg}')
        allok = all(ok for ok, _ in r["gate"].values())
        print(f'    ===> {"게이트 통과" if allok else "게이트 실패"}')
        return allok
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md", nargs="?", help="대본 샘플 markdown(4종 일괄 검사)")
    ap.add_argument("--body", help="본문 텍스트 파일")
    ap.add_argument("--title", default="")
    ap.add_argument("--keyword", default="")
    ap.add_argument("--stage", type=int, default=None)
    a = ap.parse_args()

    if a.body:
        with open(a.body, encoding="utf-8") as f:
            body = f.read()
        r = measure(a.title, body, a.keyword, stage=a.stage)
        return 0 if _print(r) else 1

    if not a.md:
        ap.error("markdown 파일이나 --body 중 하나는 필요")

    allok = True
    for s in parse_samples(a.md):
        print(f'\n▶ {s["name"]}')
        r = measure(s["title"], s["body"], s["name"], stage=_stage_of(s["name"]),
                    comments=s["comments"])
        allok = _print(r) and allok
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
