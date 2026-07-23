# -*- coding: utf-8 -*-
"""댓글에서 경쟁 제품 **후보**를 뽑는다. (확정은 여기서 하지 않는다)

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

★이 파일의 역할은 '후보 고르기'까지다 (2026-07-23 재설계)
--------------------------------------------------------
글자 규칙만으로 제품명을 확정하려다 표가 망가졌다. 실제로 나온 것:
    약국에서(30회) · 꾸준히 · 공감 · 지금 · 있는데 · 못할정도였는데 샴푸
"샴푸/쓰고 앞의 말은 제품"이라는 규칙 때문인데, 한국어는 활용형이 끝없이 늘어나서
막을 낱말을 아무리 더 적어도 새 변주가 계속 들어온다(금지어 목록으로는 못 막는다).
→ 그래서 **여기서는 후보만 고르고, 제품이냐 아니냐는 comment_brand_llm 이 판정한다.**
   판정을 못 받은 후보는 표에 넣지 않는다(빈칸이 낫지 지어낸 이름은 안 된다).

여기 있는 걸러내기(문법 꼬리·종류 이름·흔한 낱말)는 **정답 보증이 아니라 비용 절약**이다.
뻔한 문장 조각을 미리 버려서 판정에 보낼 후보 수를 줄이는 용도.

원칙(이 프로젝트 확정): **적게 세는 오류 > 지어내는 오류.**
"""
from __future__ import annotations

import re

# 제품을 가리키는 꼬리말. 이 앞에 붙는 말이 제품 이름이다.
# ★긴 것부터 적는다 — '바디워시' 가 '워시' 보다 먼저 잡혀야
#   "다시꽃 바디워시" 에서 '다시꽃' 이 살아남는다 (짧은 게 먼저면 '바디' 가 이름이 된다).
PRODUCT_SUFFIXES = (
    "트리트먼트", "바디워시", "샴푸", "앰플", "토닉", "세럼", "크림", "비누",
    "워시", "에센스", "로션", "연고", "스프레이", "필링",
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
    "일반", "아무", "건선", "지루", "각질제거", "두피각질", "바디", "헤어",
    "대충", "계속", "바꿔가며", "가끔", "매일", "한번", "그런", "이런", "저런",
    "쓰던", "쓰는", "좋은", "괜찮은", "유명한", "비싼", "싼", "새", "치료용",
}

# 제품이 아니라 장소·행위·상태를 가리키는 흔한 말.
# 문법으로는 못 거른다(다 멀쩡한 명사·부사다) — 실물 표에 올라온 것들을 모았다(2026-07-23).
COMMON_WORDS = {
    "지금", "제품", "제품들", "공감", "신경", "추천", "예약", "라인", "가격",
    "정보", "사진", "성분", "효과", "사용", "구매", "주문", "후기", "댓글",
    "카페", "링크", "쪽지", "가장", "직접", "정도", "어느정도", "요즘", "오늘",
    "어제", "내일", "처음", "나중", "다음", "이번", "저번", "가끔", "매번",
    "약국", "병원", "피부과", "대학병원", "한의원", "올리브영", "다이소",
    "공홈", "본사", "약사", "교수", "원장", "지인", "친구", "동네", "화장품",
    "스케일러", "클렌저", "필링", "앰플", "토닉", "샴푸", "린스", "비누",
}

# 한국어 활용형·조사 꼬리. **닫힌 집합**이다 — 낱말과 달리 개수가 늘지 않는다.
# 실물에서 "못할정도였는데 샴푸"·"약국에서"·"올라와서 샴푸" 가 이렇게 잡혔다(2026-07-23).
_INFLECTED_TAILS = (
    # 연결·종결 어미
    "는데", "은데", "인데", "니까", "으니", "면서", "지만", "라서", "래서",
    "더라", "드라", "라구", "구요", "군요", "네요", "나요", "까요", "세요",
    "예요", "에요", "어요", "아요", "여요", "해요", "지요", "이요", "잖아", "거든",
    "다가", "도록", "든지", "는지", "려고", "려면", "라고", "다고", "냐고",
    "했어", "됐어", "셨어", "렸어", "났어", "왔어", "갔어", "봤어", "줬어",
    "았어", "었어", "겠어", "는거", "거에", "만한", "으세", "하게", "면요",
    # 조사
    "에서", "에게", "한테", "부터", "까지", "으로", "로서", "로써", "이나",
    "이랑", "처럼", "만큼", "보다", "마다", "조차", "밖에", "이라", "라는",
    "이란", "마저", "대로", "이든", "이며", "이자",
)

# 한 글자 꼬리 — 세 글자 이상일 때만 본다(두 글자 브랜드를 죽이지 않으려고).
_TAIL_CHARS_LONG = ("서", "면", "고", "며", "까", "히", "듯", "던", "로")

# 이름 뒤에 흔히 붙는 조사 — 떼고 나서 판단한다("바디워시를" → "바디워시").
_TRAILING_JOSA = ("으로", "이랑", "을", "를", "은", "는", "이", "가", "도",
                  "만", "의", "에", "로", "랑", "과", "와")

# 이름 길이 한계 — 너무 짧으면 조사·감탄사, 너무 길면 문장을 통째로 집는다.
MIN_NAME, MAX_NAME = 2, 12

# 앞말을 **짧게** 잡는다(?) — 그래야 '바디워시' 가 '워시' 보다 먼저 걸린다.
# 욕심껏 잡으면 "다시꽃 바디워시" 에서 앞말이 '…바디' 까지 먹고 '워시' 만 꼬리말이 된다.
_TOKEN_RE = re.compile(
    r"([가-힣A-Za-z0-9ㄱ-ㅎㅏ-ㅣ][가-힣A-Za-z0-9ㄱ-ㅎㅏ-ㅣ ]{0,28}?)(%s)" % "|".join(PRODUCT_SUFFIXES)
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


def strip_josa(word: str) -> str:
    """이름 뒤 조사를 뗀다 — "바디워시를" → "바디워시" (떼고 나면 종류 이름인 게 보인다)."""
    w = str(word or "").strip()
    for j in _TRAILING_JOSA:
        if len(w) > len(j) + 1 and w.endswith(j):
            return w[: -len(j)]
    return w


def is_inflected(word: str) -> bool:
    """이 말이 활용형·조사가 붙은 문장 조각인가 — 문법 꼬리만 본다(닫힌 집합)."""
    w = str(word or "")
    if len(w) < 2:
        return False
    if any(w.endswith(t) for t in _INFLECTED_TAILS):
        return True
    if len(w) >= 3 and w[-1] in _TAIL_CHARS_LONG:
        return True
    return any(p in w for p in _NOT_NAME_PARTS)


# 증상·용도를 가리키는 끝 글자. '지루성두피염샴푸'·'미산성 샴푸'·'치료용' 처럼
# 앞말이 이걸로 끝나면 브랜드가 아니라 무엇에 쓰는 것인지를 말한 것이다.
_SYMPTOM_TAIL_CHARS = ("염", "증", "성", "용")


def strip_generic_tail(key: str) -> str:
    """이름 뒤에 붙은 일반어를 벗긴다 — "맥단ㅂi탈모"(→맥단탈모) → "맥단".

    띄어쓰기가 없으면 '탈모샴푸' 가 이름에 들러붙는다. 글자로 벗겨야 같은 제품으로 모인다.
    """
    key = normalize_name(key)
    for _ in range(4):                       # 몇 겹 붙어도 벗기되, 끝없이 돌지는 않는다
        for g in sorted(GENERIC_WORDS, key=len, reverse=True):
            if len(g) >= 2 and key.endswith(g) and len(key) - len(g) >= MIN_NAME:
                key = key[: -len(g)]
                break
        else:
            break
    return key


def is_category_word(word: str) -> bool:
    """종류 이름 자체인가 — '샴푸'·'탈모샴푸'·'바디워시' 는 브랜드가 아니다."""
    key = normalize_name(word)
    if not key:
        return True
    if key in PRODUCT_SUFFIXES or key in GENERIC_WORDS:
        return True
    for suf in PRODUCT_SUFFIXES:
        if key.endswith(suf):
            stem = key[: -len(suf)]
            if not stem or stem in GENERIC_WORDS:
                return True
            if stem[-1] in _SYMPTOM_TAIL_CHARS:   # '지루성두피염'샴푸 · '미산'성 샴푸
                return True
    return False


def looks_like_candidate(key: str) -> bool:
    """판정에 보낼 만한 후보인가 — 뻔한 문장 조각·종류 이름·흔한 낱말은 여기서 버린다.

    ★통과 = '제품이다' 가 아니다. '사람(LLM)이 봐줄 값어치가 있다' 는 뜻일 뿐.
    """
    key = normalize_name(key)
    if len(key) < MIN_NAME or len(key) > MAX_NAME:
        return False
    if key in COMMON_WORDS or key in GENERIC_WORDS:
        return False
    if is_inflected(key):
        return False
    if is_category_word(key):
        return False
    return True


def extract_candidates(text: str) -> list[tuple]:
    """댓글 한 줄 → [(보이는 이름, 묶음 키, 제품종류)] · 순수함수. **후보일 뿐이다.**

    세 갈래로 잡는다.
      ① 이름 + 꼬리말      "맥단ㅂI 탈모샴푸" → 맥단ㅂI (사이의 '탈모' 같은 일반어는 벗겨냄)
      ② 이름 + 쓰는 말투   "헤드앤숄더 써보세요" → 헤드앤숄더 (꼬리말이 없어도 잡는다)
      ③ 이름만 툭          "니조랄은요?" → 니조랄
    """
    text = str(text or "")
    out: list[tuple] = []
    seen: set = set()

    def add(name_raw: str, suffix: str):
        shown = strip_josa(str(name_raw).strip())
        key = strip_generic_tail(shown)   # "맥단ㅂi탈모샴푸" 도 '맥단' 으로 모인다
        if not looks_like_candidate(key):
            return
        if key in seen:          # 묶음 키는 브랜드만 — '닥터이노브' 와 '닥터이노브 샴푸' 는 한 제품
            return
        seen.add(key)
        out.append((shown + (" " + suffix if suffix else ""), key, suffix or "제품"))

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


def candidates_from_comments(comments: list, *, only_after_question: bool = True,
                             window: int = 2) -> list[dict]:
    """댓글 목록 → 제품 **후보** 목록 · 순수함수.

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
        for shown, key, suffix in extract_candidates(text):
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
