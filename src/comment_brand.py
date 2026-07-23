# -*- coding: utf-8 -*-
"""댓글에서 경쟁 제품명 뽑기.

사장님 정의 (2026-07-23 원문):
    "경쟁사는 카페이름이 아니라 키워드 검색해서 상위노출된 카페에서 들어가면 달리는 댓글
     (우리 글 말고 다른 글) 에서 두 번째 댓글 티키타카에서 나오는 제품명을 추출해달라"

즉 경쟁사 = 남의 글 댓글에서 팔리고 있는 **제품**. 카페는 무대일 뿐이다.

실물에서 확인한 것 (2026-07-23 직접 수집):
  "혹시 어떤제품 쓰시는지 알 수 있을까요?"  ← 묻는 댓글
  "모zi젠 펩ㅋㅏ놀 탈모앰플 쓰고 있어요"     ← 여기서 제품명이 나온다
  "맥단ㅂI 탈모샴푸 쓰고 있어요~"
경쟁사들은 카페 정책·검색을 피하려고 **글자를 일부러 흐트러뜨린다**(모zi젠, 맥단ㅂI, ㅃ얀).
그대로 세면 같은 제품이 다른 이름으로 흩어지므로 글자를 정리한 뒤 센다.

원칙(이 프로젝트 확정): **적게 세는 오류 > 지어내는 오류.**
  애매하면 세지 않는다. 없는 경쟁 제품을 만들어내지 않는다.
"""
from __future__ import annotations

import re

# 제품을 가리키는 꼬리말. 이 앞에 붙는 말이 제품 이름이다.
PRODUCT_SUFFIXES = (
    "샴푸", "앰플", "토닉", "세럼", "크림", "비누", "바디워시", "워시",
    "트리트먼트", "에센스", "로션", "연고", "스프레이", "필링",
)

# 이름이 아니라 '무엇'을 가리키는 말 — 이게 앞에 붙으면 브랜드가 아니다.
# (검색 키워드·증상·일반 표현. 실물 댓글에서 그대로 확인한 것들.)
GENERIC_WORDS = {
    "비듬", "탈모", "지루성", "두피", "각질", "기름", "건성", "지성", "민감",
    "약용", "저자극", "약산성", "천연", "한방", "쿨링", "멘톨", "단백질",
    "여드름", "트러블", "등드름", "모공", "각화증", "아기", "유아", "어린이",
    "남성", "여성", "임산부", "새치", "염색", "볼륨", "손상", "곱슬",
    "그", "이", "저", "무슨", "어떤", "다른", "같은", "제", "저희", "우리",
    "인생", "최고", "국민", "요즘", "그냥", "진짜", "완전", "제일",
    "일반", "아무", "무슨", "건선", "지루", "각질제거", "두피각질",
    "대충", "계속", "바꿔가며", "가끔", "매일", "한번", "그런", "이런", "저런",
    "쓰던", "쓰는", "좋은", "괜찮은", "유명한", "비싼", "싼", "새",
}

# 앞말이 조사·어미로 끝나면 이름이 아니라 문장 조각이다.
# 실물에서 "받은 샴푸"·"맞는 샴푸"·"저는 샴푸"·"끊고 샴푸" 가 이렇게 잡혔다(2026-07-23).
_JOSA_TAIL = (
    "은", "는", "이", "가", "을", "를", "도", "만", "의", "에", "로", "서",
    "고", "며", "나", "랑", "과", "와", "듯", "던", "면", "게", "지", "네",
)

# 이름 길이 한계 — 너무 짧으면 조사·감탄사, 너무 길면 문장을 통째로 집는다.
MIN_NAME, MAX_NAME = 2, 12

_TOKEN_RE = re.compile(
    r"([가-힣A-Za-z0-9ㄱ-ㅎㅏ-ㅣ][가-힣A-Za-z0-9ㄱ-ㅎㅏ-ㅣ ]{0,28})(%s)" % "|".join(PRODUCT_SUFFIXES)
)

# 꼬리말이 없어도 제품을 가리키는 말투 — "헤드앤숄더 써보세요", "○○ 쓰고 있어요".
_USE_RE = re.compile(
    r"([가-힣A-Za-z0-9ㄱ-ㅎㅏ-ㅣ]{2,12})\s*(?:이거\s*|그거\s*)?"
    r"(?:써보|쓰고|쓰는|썼|사용|추천|주문|구매|바꿨|바꾸고)"
)

# 이름에 이런 조각이 섞여 있으면 사람 말이지 제품 이름이 아니다.
_NOT_NAME_PARTS = ("한테", "에게", "까지", "부터", "보다", "처럼", "라고", "하고", "인데", "이라")

# 검열 피하려 끼워 넣는 글자: 영문·숫자·홑자모.
# 이것들을 걷어내면 "모zi젠"→"모젠", "맥단ㅂI"→"맥단", "뽀ㅇ얀"→"뽀얀" 으로 모인다.
_NOISE_CHARS_RE = re.compile(r"[A-Za-z0-9ㄱ-ㅎㅏ-ㅣ]")

# 꼬리말 없이 이름만 던지는 경우가 많다("니조랄은요?"). 조사만 떼고 후보로 본다.
_BARE_RE = re.compile(r"([가-힣]{2,10}?)(?:은요|는요|이요|요\?|은\?|는\?)")

# 묻는 댓글 = 이 뒤에 제품명이 나온다(티키타카). 사장님이 말한 '두 번째 댓글'.
ASKING_PATTERNS = (
    "어떤제품", "어떤 제품", "뭔데요", "뭐에요", "뭐예요", "알 수 있을까요",
    "알려주", "제품명", "어디꺼", "어디 꺼", "무슨 제품", "어떤거", "어떤 거",
    "링크", "정보 좀", "추천 좀", "궁금",
)


def normalize_name(text: str) -> str:
    """흐트러뜨린 글자를 정리해 같은 제품이 한 이름으로 모이게 한다.

    "모zi젠" → "모젠" / "맥단ㅂI" → "맥단" / "뽀ㅇ얀" → "뽀얀"
    (완벽하진 않다. 'ㅃ얀' 처럼 첫 글자를 자모로 바꾼 것은 따로 잡힌다 —
     못 묶어 적게 세는 쪽이 엉뚱한 걸 묶는 쪽보다 안전하다.)
    """
    return _NOISE_CHARS_RE.sub("", str(text or "")).replace(" ", "").strip()


def is_asking(text: str) -> bool:
    """제품을 묻는 댓글인지 — 이 다음 댓글에 제품명이 나온다."""
    t = str(text or "")
    return any(p in t for p in ASKING_PATTERNS)


def _looks_like_name(key: str) -> bool:
    """이 말이 제품 이름일 만한가 — 사람 말 조각이면 버린다."""
    if len(key) < MIN_NAME or len(key) > MAX_NAME:
        return False
    if any(key.endswith(g) or key == g for g in GENERIC_WORDS):
        return False
    if any(part in key for part in _NOT_NAME_PARTS):
        return False
    if key[-1] in _JOSA_TAIL and len(key) <= 3:
        return False
    # 종류 이름 자체는 브랜드가 아니다 ("샴푸", "탈모샴푸")
    if key in PRODUCT_SUFFIXES:
        return False
    for suf in PRODUCT_SUFFIXES:
        if key.endswith(suf):
            stem = key[: -len(suf)]
            if not stem or stem in GENERIC_WORDS:
                return False
    return True


def extract_products(text: str) -> list[tuple]:
    """댓글 한 줄 → [(보이는 이름, 묶음 키, 제품종류)] · 순수함수.

    두 갈래로 잡는다.
      ① 이름 + 꼬리말      "맥단ㅂI 탈모샴푸" → 맥단ㅂI (사이의 '탈모' 같은 일반어는 벗겨냄)
      ② 이름 + 쓰는 말투   "헤드앤숄더 써보세요" → 헤드앤숄더 (꼬리말이 없어도 잡는다)
    """
    text = str(text or "")
    out: list[tuple] = []
    seen: set = set()

    def add(name_raw: str, suffix: str):
        key = normalize_name(name_raw)
        if not _looks_like_name(key):
            return
        full = key + suffix
        if full in seen:
            return
        seen.add(full)
        out.append((name_raw.strip() + (" " + suffix if suffix else ""), full, suffix or "제품"))

    # ① 꼬리말 앞에서 이름 찾기
    for m in _TOKEN_RE.finditer(text):
        head, suffix = m.group(1), m.group(2)
        tokens = [t for t in head.split() if t]
        while tokens and normalize_name(tokens[-1]) in GENERIC_WORDS:
            tokens.pop()                      # '탈모샴푸' 의 '탈모' 처럼 일반어는 벗겨낸다
        if not tokens:
            continue
        add(tokens[-1], suffix)   # 바로 앞 한 덩어리만 이름 후보로 (여러 개 이으면 문장이 섞인다)

    # ② 쓰는 말투로 찾기 (꼬리말이 없는 브랜드)
    for m in _USE_RE.finditer(text):
        add(m.group(1), "")

    # ③ 이름만 툭 던지는 경우 ("니조랄은요?")
    for m in _BARE_RE.finditer(text):
        add(m.group(1), "")

    return out


def products_from_comments(comments: list, *, only_after_question: bool = True,
                           window: int = 2) -> list[dict]:
    """댓글 목록 → 제품 언급 목록 · 순수함수.

    only_after_question=True 면 **묻는 댓글 바로 다음 window 개**만 본다.
    사장님이 말한 티키타카가 정확히 이 자리다 — "그게 뭔데요?" → "○○샴푸 쓰고 있어요".
    질문 이후 전부를 보면 한참 뒤 잡담까지 딸려 들어온다(실측으로 확인).
    """
    out: list[dict] = []
    left = 10 ** 6 if not only_after_question else 0
    for c in comments or []:
        text = str((c or {}).get("content") or "")
        if only_after_question and is_asking(text):
            left = window
            continue
        if left <= 0:
            continue
        for shown, key, suffix in extract_products(text):
            out.append({"표시": shown, "키": key, "종류": suffix, "댓글": text[:120]})
        if only_after_question:
            left -= 1
    return out


def tally(mentions: list[dict], *, exclude_keys: set | None = None) -> list[dict]:
    """제품 언급 → 제품별 횟수 · 순수함수. exclude_keys = 자사 제품(빼고 센다)."""
    skip = {normalize_name(k) for k in (exclude_keys or set())}
    acc: dict = {}
    for m in mentions or []:
        key = m["키"]
        if any(s and s in key for s in skip):
            continue
        entry = acc.setdefault(key, {"표시": m["표시"], "종류": m["종류"], "횟수": 0, "예시": m["댓글"]})
        entry["횟수"] += 1
    out = [{"제품": v["표시"], "키": k, "종류": v["종류"], "횟수": v["횟수"], "댓글 예시": v["예시"]}
           for k, v in acc.items()]
    out.sort(key=lambda r: (-r["횟수"], r["제품"]))
    return out
