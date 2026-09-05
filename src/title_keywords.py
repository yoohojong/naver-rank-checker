# -*- coding: utf-8 -*-
"""카페 글 제목 → 사람들이 네이버에 검색할 법한 **검색 키워드**.

왜 이 모듈이 생겼나 (2026-09-06)
--------------------------------
경쟁사 배치는 로그인 없이 상위노출 남의 글의 **제목**을 이미 손에 쥔다. 그 제목에서
'우리한테 없는 검색 키워드'를 뽑아 키워드 후보로 쓰려고 했는데, 전에는 브랜드 추출기
(comment_brand.extract_candidates)를 그대로 썼다. 그건 브랜드 조각을 뽑는 도구라
제목에 넣으면 게시판 이름('육아,커뮤니티')·조사·문장 조각('뻣뻣한'·'계세요')이
그대로 후보가 돼 잡음이 심했다(실물 416줄 대부분 쓰레기).

사장님 프로세스 정본(cafe-external/경쟁사_키워드_역추적_프로세스.md):
  "제목만으로 애매하면 본문과 댓글을 보면 키워드를 여러 번 반복했을 것"
  → 제목에서 뽑아야 하는 건 **검색 키워드**지 브랜드 조각이 아니다.
    예: "지루성 두피염 약국 가서 겨우 해결했네요 ㅠㅠ" → "지루성 두피염"

그래서 사람은 한 줄만 봐도 아는 판단을 언어모델에 맡긴다 — 브랜드 판정과 똑같이.

LLM 통로는 새로 만들지 않는다
------------------------------
comment_brand_llm 의 _call(무료 Groq → 유료 OpenAI → Anthropic 순)·_extract_json·
_salvage·available 을 그대로 쓴다. 여기서는 '제목 → 키워드' 규칙(system 프롬프트)과
응답 읽기만 얹는다.

안전
- 열쇠(LLM)가 없으면 빈 dict 로 물러난다 — 지어내지 않는다(그때는 시트에 아무것도 안 씀).
- 확실하지 않으면 안 뽑는다(사장님 원칙: 확실하지 않으면 빼라).
- 세는 쪽(collect_comment_brands.제목_키워드후보)이 이 판정을 **인자로 주입**받아,
  가짜 판정으로 검사한다.
"""
from __future__ import annotations

import time

from . import comment_brand_llm as _llm

# 한 번에 물어볼 제목 수. 답이 길어지면 잘려 묶음이 통째로 미판정이 되므로 크게 잡지 않는다.
BATCH = 25

# 제목당 뽑는 키워드 최대 개수 — 하나의 검색 의도에 초점을 맞춘다.
최대_키워드 = 2

_SYSTEM = (
    "너는 네이버 카페 글 제목에서 **사람들이 네이버에 검색할 법한 키워드**만 뽑는다.\n"
    "키워드 = 제품 고민·증상·부위 중심의 명사형 검색어다.\n"
    "각 항목은 '번호. 제목' 형식이다.\n"
    "규칙:\n"
    "1. 사람이 네이버 검색창에 칠 만한 명사형 키워드만 뽑는다. 제목당 0~2개.\n"
    "   예: '지루성 두피염 약국 가서 겨우 해결했네요 ㅠㅠ' → ['지루성 두피염']\n"
    "       '등에 여드름 올라와서 미스트 뿌리는 중' → ['등 여드름']\n"
    "2. 다음은 버린다(뽑지 않는다):\n"
    "   · 게시판·카페 이름: 육아, 요리, 인테리어, 커뮤니티, 자유게시판\n"
    "   · 조사·부사·문장 조각: 계세요, 뻣뻣한, 뭔가, 관리하나, 있는데, 어떡해\n"
    "   · 감탄사·이모지: ㅠㅠ, ㅋㅋ, 헐, !!!\n"
    "3. 브랜드명 하나만 있는 제목은 버린다(그건 경쟁사에서 이미 다룬다 — 여기선 키워드다).\n"
    "   예: '안티트로 샴푸 진짜 좋아요' → []   (브랜드뿐)\n"
    "4. 확실하지 않으면 뽑지 않는다. 빈 목록으로 둔다. 지어내지 마라.\n"
    "5. 받은 번호 전부에 답한다. '제목' 칸에는 받은 제목을 **그대로 옮겨 적는다**.\n"
    '출력은 JSON 만: {"제목별": [{"n":1,"제목":"지루성 두피염 약국...","키워드":["지루성 두피염"]},'
    ' {"n":2,"제목":"육아,커뮤니티","키워드":[]}]}\n'
    "다른 말은 절대 하지 않는다."
)


def _one_batch(titles: list, call, *, timeout: int, sleep, errors: list | None = None) -> dict:
    """제목 묶음 하나 판정 → {원제목: [키워드,...]}. 실패하면 빈 dict."""
    lines = [f"{n}. {t}" for n, t in enumerate(titles, 1)]
    content, truncated = call(
        _SYSTEM, "제목마다 검색 키워드를 뽑아줘.\n" + "\n".join(lines),
        max_tokens=2000, timeout=timeout, sleep=sleep, errors=errors)
    if not content:
        return {}
    obj = _llm._extract_json(content)
    rows = obj.get("제목별") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        rows = _llm._salvage(content)       # 잘린 답에서도 읽히는 줄은 건진다
        if not rows:
            return {}

    # 번호가 한 칸 밀리면 키워드가 옆 제목에 붙는다 — 되돌려받은 '제목' 글자로 대조한다.
    by_echo = {_llm._key(t): t for t in titles}
    out: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(titles):
            continue
        t = titles[n - 1]
        echo = _llm._key(r.get("제목"))
        if echo and echo != _llm._key(t):
            t = by_echo.get(echo)
            if t is None:                   # 누구 제목인지 모르겠으면 넣지 않는다
                continue
        kws: list = []
        for k in (r.get("키워드") or []):
            k = str(k).strip()
            if k and k not in kws:
                kws.append(k)
        out[t] = kws[:최대_키워드]
    return out


def extract_keywords(titles: list, *, call=None, timeout: int = 30,
                     sleep=time.sleep, batch: int = BATCH,
                     errors: list | None = None) -> dict:
    """제목 목록 → {제목: [검색 키워드 0~2개]}.

    call = comment_brand_llm._call 모양의 호출기. 검사에서 가짜로 주입한다.
    안 주면 진짜 통로를 쓰되, 열쇠가 하나도 없으면 빈 dict 로 물러난다(지어내지 않음).
    """
    titles = [str(t).strip() for t in (titles or []) if str(t).strip()]
    # 같은 제목은 한 번만 묻는다(중복 제목은 묶음만 축낸다).
    본것: set = set()
    uniq: list = []
    for t in titles:
        k = _llm._key(t)
        if k and k not in 본것:
            본것.add(k)
            uniq.append(t)
    if not uniq:
        return {}

    if call is None:
        if not _llm.available():
            return {}
        call = _llm._call

    out: dict = {}
    for start in range(0, len(uniq), batch):
        chunk = uniq[start:start + batch]
        got = _one_batch(chunk, call, timeout=timeout, sleep=sleep, errors=errors)
        if got:
            out.update(got)
    return out
