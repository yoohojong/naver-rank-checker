# -*- coding: utf-8 -*-
"""키워드 → 상위노출된 남의 글 → 댓글 → 경쟁 제품명 · 횟수.

사장님 정의(2026-07-23): 경쟁사 = 남의 글 댓글에서 팔리는 **제품**.

흐름
  1) 키워드 검색 (순위 검사와 같은 크롤러)
  2) 상위 구좌 카페 글 중 **우리 글 제외**
  3) 각 글의 댓글 가져오기 (로그인 없이 됨 — 2026-07-23 실증)
  4) 묻는 댓글 다음에서 제품 **후보** 뽑기 + 흐트러뜨린 글자 정리
  5) 후보를 한데 모아 중복 없이 **판정**(언어모델) — 판정된 것만 제품으로 인정
  6) 제품군(시트 탭)별 · 제품별 횟수 집계

★판정 못 받은 후보는 표에 넣지 않는다 (2026-07-23 재설계)
  전에는 판정이 실패하면 글자규칙 결과를 그대로 표에 넣었다. 그래서 '약국에서'(30회)
  '꾸준히' '공감' 같은 게 경쟁 제품으로 올라갔다. 지금은 빈칸으로 둔다 —
  적게 세는 오류는 고칠 수 있지만, 지어낸 표는 사장님을 잘못된 판단으로 이끈다.

읽기만 한다. 시트에 쓰는 건 호출부(sheet_out) 가 정할 때만.

실행:
  python -m scripts.collect_comment_brands --keywords 비듬샴푸,지루성두피샴푸 --product 샴푸
  python -m scripts.collect_comment_brands --from-sheet --limit 30      (시트 키워드로)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.comment_brand import (extract_candidates, is_asking, normalize_name,  # noqa: E402
                               strip_generic_tail, tally)
from src import brand_verdicts  # noqa: E402
from src import brand_from_comments  # noqa: E402
from src import comment_reads  # noqa: E402
from src import comment_brand_llm  # noqa: E402
from src import title_keywords  # noqa: E402
from src import shop_probe  # noqa: E402
from src.crawler import Crawler  # noqa: E402
from src.parser import cafe_slug_of, is_known_url  # noqa: E402
from src.parser import collect_slot_items  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CAFE_URL = re.compile(r"cafe\.naver\.com/([^/?#]+)/(\d+)")
_CLUB_ID = re.compile(r'g_sClubId\s*=\s*"(\d+)"')
# 검색에서 온 주소에 붙어 있는 열쇠. 회원 전용 카페 글도 이게 있으면 열린다.
# 이걸 버리고 부르면 403 — 전체 실행에서 1,106개 중 548개를 그렇게 놓쳤다(2026-07-23 실측).
_ART_TOKEN = re.compile(r"[?&]art=([^&#]+)")

# 댓글 한 장에 100개. 뒷장까지 따라가되 끝없이 돌지는 않는다.
COMMENT_PAGE_SIZE, COMMENT_PAGE_CAP = 100, 20

# 우리 제품 — 세지 않는다(경쟁이 아니다). 흐트러뜨린 표기·되살린 표기 둘 다 막는다.
# 샴푸만 넣어놨다가 바디워시 표기('ㅃ얀 바디워시')가 표에 남았다(2026-07-23 실측) → 브랜드로 막는다.
# ★2026-09-05 — '뽀얀'·'얀' 둘만 적혀 있어서 **우리 제품 '두드럼' 이 두드러기 경쟁사로**
#   표에 올라 있었다(사장님: "경쟁사 추출한거 보니까 다 이상하다").
#   우리 브랜드 어근을 전부 적는다. 근거는 cafe-external/일별기록/2026-09-04.md 의
#   '브랜드 검색량' 표 — 거기 적힌 우리 키워드에서 뽑은 어근이다.
#     뽀얀(샴푸·바디워시·등드름) · 머드름(샴푸) · 몸드름(바디워시) ·
#     두드럼(세포막크림·연고·크림) · 세포막(크림) · 여리손(해여리손·핑거롤) · 핑거롤
#   ★어근으로 적는 이유: tally 가 **글자가 들어 있으면** 뺀다. '두드럼크림' 도
#     '두드럼' 하나로 걸린다. 이름을 다 적으면 새 이름이 생길 때마다 샌다.
# ★2026-09-05 독립검증: '얀'(한 글자)을 뺐다. tally 가 부분일치로 걸러서
#   '에비얀' 같은 **얀이 든 진짜 경쟁사를 조용히 지웠다**(라이브 데이터 손실).
#   '뽀얀' 은 두 글자라 안전하다. 초성 섞인 'ㅃ얀' 류는 판정기(LLM)가 '뽀얀' 으로
#   되살려 거른다(comment_brand_llm _SYSTEM). 한 글자 어근은 발굴 시스템에 독이다.
OUR_PRODUCT_HINTS = {"뽀얀", "머드름", "몸드름", "두드럼", "세포막",
                     "여리손", "핑거롤"}

# 제품이 아니라 '무엇'을 가리키는 말 — 표에 들어가면 안 된다.
# 실측에서 '지루성두피염샴푸' 가 제품처럼 올라왔다(2026-07-23).
NOT_A_BRAND = {
    "샴푸", "탈모샴푸", "비듬샴푸", "지루성샴푸", "지루성두피염샴푸", "두피샴푸",
    "바디워시", "바디로션", "트리트먼트", "린스", "크림", "앰플", "토닉",
    "약국", "병원", "피부과", "대학병원", "올리브영", "공홈", "본사",
    "스테로이드", "항생제", "소염제", "영양제", "유산균", "케토코나졸", "미녹시딜",
    # ★2026-09-05 사장님 "가게 이름이 맨 위로 온다" — 파는 곳(가게)은 경쟁 제품이 아니다.
    #   검색량이 크다고 위로 올라오던 것들. 화장품 브랜드가 아니라 유통 채널이다.
    "다이소", "다이소몰", "코스트코", "무인양품", "이케아", "쿠팡", "네이버",
    "아이허브", "무신사", "쿠팡이츠", "마켓컬리", "오늘의집", "지마켓", "티몬",
    # ★2026-09-05 사장님 "경쟁사 추출한거 보니까 다 이상하다" — 제품 브랜드가 아니라
    #   성분·약 일반명이 제품=true 로 올라 있었다. 실측(data/brand_verdicts.json)에서
    #   실제로 true 로 오른 것 중, **명백한 일반 성분·약만** 넣는다.
    #   ★애매한 것은 넣지 않는다(사장님 "확실하지 않으면 빼지 마라 / 데이터 쌓이면
    #     알게 된다"). '판테놀'·'큐텐' 은 제품명으로도 팔려 뺐다(큐텐은 쇼핑몰 Qoo10 도 됨).
    "케라틴",        # keratin — 머리카락 단백질 성분
    "호호바",        # jojoba — 식물 오일 성분(호호바오일)
    "티트리", "티트리오일",   # tea tree oil — 정유 성분
    "징크피리치온",  # zinc pyrithione — 비듬 완화 활성 성분
    "유황",          # sulfur — 원소·성분(유황비누의 성분명)
    "칼라민",        # calamine — 진정용 약 일반명(칼라민 로션)
}


def is_real_brand(name: str) -> bool:
    """표에 넣을 만한 브랜드인가 — 일반 명칭·장소는 뺀다."""
    key = normalize_name(name)
    if len(key) < 2:
        return False
    return key not in {normalize_name(x) for x in NOT_A_BRAND}


def 우리제품인가(name: str) -> bool:
    """우리 브랜드(뽀얀·두드럼 등)인가 — tally 의 자사 제외와 같은 잣대(부분일치)."""
    key = normalize_name(name)
    return any(s and s in key for s in {normalize_name(x) for x in OUR_PRODUCT_HINTS})


def 표에_남길_경쟁사인가(name: str) -> bool:
    """이어받는 옛 줄에 남길 이름인가 — 자사·장소·일반명(NOT_A_BRAND)을 뺀다.
    ★confirmed_rows(오늘 새로 세는 쪽)와 build_table(옛 줄 이어받는 쪽)이 자사·가게·성분에
      **같은 잣대**를 써야 한다. 안 그러면 제외가 생기기 전에 들어온 줄(두드럼·케라틴·
      다이소)이 이어받기로 눌러앉는다(2026-09-05 실물 확인에서 잡음).
    ★길이(한 글자) 검사는 **안 한다** — 그건 추가 시점(confirmed_rows 의 is_real_brand)이
      이미 막는다. 여기서까지 걸면 옛 자료의 짧은 이름을 새로 지우는 셈이라 범위를 벗어난다."""
    key = normalize_name(name)
    if key in {normalize_name(x) for x in NOT_A_BRAND}:
        return False
    return not 우리제품인가(name)


class CommentFetcher:
    """카페 글 → 댓글 **전부**. 뒷장까지 따라가고, 검색 주소의 열쇠(art)를 쓴다."""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self._club: dict = {}
        self.stat = {"열림": 0, "막힘": 0, "댓글": 0, "뒷장": 0}

    def _club_id(self, url: str, slug: str) -> str:
        club = self._club.get(slug)
        if club is None:
            try:
                page = self.s.get(url, timeout=25)
                mm = _CLUB_ID.search(page.text)
                club = mm.group(1) if mm else ""
            except Exception:
                club = ""
            self._club[slug] = club
        return club

    @staticmethod
    def _items_of(res: dict) -> list:
        items = res.get("comments")
        if isinstance(items, dict):
            items = items.get("items") or items.get("comments") or []
        return items if isinstance(items, list) else []

    @staticmethod
    def _cursor_of(items: list) -> str:
        """다음 장을 부를 때 쓸 마지막 댓글 번호. 못 찾으면 빈 값(=거기서 멈춘다)."""
        last = items[-1] if items else {}
        for k in ("id", "commentId", "refId", "objectId"):
            v = (last or {}).get(k)
            if v:
                return str(v)
        return ""

    def cafe_no(self, url: str) -> str:
        """이 글이 있는 카페 번호. **댓글을 받을 때 이미 받아 둔 값**을 돌려준다.

        ★2026-09-04 검수 지적 #3 — 프로필 주소를 만들려면 이 번호가 필요한데,
        댓글에서 글쓴이를 찾아낸(=잘 된) 경우에 오히려 번호가 비어 있었다.
        성공할수록 프로필이 비고 실패해야 채워지는, 뒤집힌 모양이었다.
        """
        m = _CAFE_URL.search(url)
        if not m:
            return ""
        return self._club.get(m.group(1)) or ""

    def writer(self, url: str) -> dict:
        """글 하나 → 글쓴이 {닉, 키, 카페번호}. 못 받으면 {}.

        댓글에서 글쓴이를 못 찾았을 때만 부른다(요청 하나가 곧 시간이다).
        여기서 실패해도 경쟁사 자료는 그대로 살아 있어야 한다 — 두 갈래는 따로 산다.
        """
        m = _CAFE_URL.search(url)
        if not m:
            return {}
        club = self._club_id(url, m.group(1))
        if not club:
            return {}
        # ★2026-09-04 검수 지적 #4 — 검색 주소에 붙어 있는 열쇠(art)를 버리고
        #   부르면 회원 전용 카페에서 403 이 난다(2026-07-23 실측: 1,106개 중
        #   548개를 그렇게 놓쳤다). 댓글 받는 쪽은 붙이는데 여기만 빠져 있었다.
        #   그리고 회원 전용 카페가 곧 바이럴이 가장 많은 자리다.
        tok = _ART_TOKEN.search(url)
        api = (f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{club}"
               f"/articles/{m.group(2)}"
               + (f"?art={tok.group(1)}" if tok else ""))
        try:
            r = self.s.get(api, headers={"Referer": url}, timeout=25)
            if r.status_code != 200:
                return {}
            res = r.json().get("result", {})
        except Exception:
            return {}
        w = ((res.get("article") or res) or {}).get("writer") or {}
        return {"닉": str(w.get("nick") or w.get("nickName") or "").strip(),
                "키": str(w.get("memberKey") or "").strip(),
                "카페번호": str(club)}

    def comments(self, url: str) -> list:
        m = _CAFE_URL.search(url)
        if not m:
            return []
        article = m.group(2)
        club = self._club_id(url, m.group(1))
        if not club:
            self.stat["막힘"] += 1
            return []
        tok = _ART_TOKEN.search(url)
        art = f"&art={tok.group(1)}" if tok else ""

        out: list = []
        cursor = ""
        for page in range(COMMENT_PAGE_CAP):
            api = (f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{club}"
                   f"/articles/{article}/comments?fromObjectId={cursor}"
                   f"&limit={COMMENT_PAGE_SIZE}&orderBy=asc{art}")
            try:
                r = self.s.get(api, headers={"Referer": url}, timeout=25)
            except Exception:
                break
            if r.status_code != 200:
                break                        # 열쇠가 있어도 안 열리면 진짜 회원 전용
            try:
                res = r.json().get("result", {})
            except Exception:
                break
            items = self._items_of(res)
            if not items:
                break
            out.extend(items)
            if page:
                self.stat["뒷장"] += 1
            if not res.get("hasNext"):
                break
            nxt = self._cursor_of(items)
            if not nxt or nxt == cursor:
                break                        # 같은 장을 또 받으면 멈춘다(무한 반복 방지)
            cursor = nxt

        if not out:
            self.stat["막힘"] += 1
            return []
        self.stat["열림"] += 1
        self.stat["댓글"] += len(out)
        return out


def is_our_item(url: str, our_links: set, our_slugs: set) -> bool:
    """우리 글인지 — 시트 link 매치 또는 우리 카페 slug 매치. (사장님: "우리 글 말고 다른 글")"""
    if is_known_url(url, our_links):
        return True
    slug = cafe_slug_of(url)
    return bool(slug and slug in (our_slugs or set()))


def tikitaka_texts(comments: list, *, window: int = 2) -> list:
    """묻는 댓글 바로 다음 window 개 — '두 번째 댓글 티키타카' 자리.

    ★지금은 쓰지 않는다(2026-07-23). 이 자리만 보니 댓글의 81%를 버렸고
    (144건 중 28건만 통과), 후보 이름도 41종 중 10종밖에 못 잡았다.
    질문 없이 첫 댓글부터 제품을 미는 글이 훨씬 많다. 판별은 뒤(LLM)에서 하면 된다.
    """
    out, left = [], 0
    for c in comments or []:
        text = str((c or {}).get("content") or "")
        if is_asking(text):
            left = window
            continue
        if left > 0:
            out.append(text)
            left -= 1
    return out


def candidates_from_comments(comments: list) -> list:
    """글의 **모든 댓글** → 제품 후보. 제품이냐 아니냐는 여기서 정하지 않는다."""
    out = []
    for c in comments or []:
        t = str((c or {}).get("content") or "")
        if not t:
            continue
        for shown, key, suffix in extract_candidates(t):
            out.append({"표시": shown, "키": key, "종류": suffix, "댓글": t[:120]})
    return out


def candidates_from_title(title: str) -> list:
    """상위 구좌를 차지한 **남의 글 제목** → 제품 후보.

    사장님 2026-07-23 원문: "누락시킨거 보고 상위노출된 경쟁사 리스트업 (매번 갱신)
    제일 많이 보이는 애들 횟수 체크해서 갱신해주는 시스템".
    처음엔 이걸 '카페 이름' 으로 읽어 표를 만들었다가 사장님이 "싹다 정리해" 하셨다 —
    카페는 글이 올라간 장소지 경쟁 상대가 아니다. 상대는 그 글이 밀고 있는 **제품**이다.
    제목은 순위 검사가 이미 받아둔 화면에서 나오므로 새로 긁는 건 0이다.
    """
    t = str(title or "")
    if not t:
        return []
    return [{"표시": shown, "키": key, "종류": suffix, "댓글": t[:120]}
            for shown, key, suffix in extract_candidates(t)]


# ── 로그인 없는 키워드 후보 (2026-09-05, LLM 판정 2026-09-06) ────────────
# 사장님 오늘 지시: "문제를 해결해. 로그인이 꼭 필요해?"
# 갈래 B(계정 프로필 역추적)는 카페 로그인이 있어야 돈다. 그런데 경쟁사 배치는
# 로그인 없이 상위노출 남의 글의 **제목**을 이미 손에 쥐고 있다. 그 제목에서
# 후보를 뽑아 **우리한테 없는 것만** 제품별로 '키워드후보' 탭에 넣는다 —
# 갈래 B 의 로그인 없는 축소판이다(추가 크롤 0).
#
# ★2026-09-06: 전에는 브랜드 추출기(candidates_from_title)를 그대로 써서 제목에서
#   브랜드 조각을 뽑았다 — 게시판 이름·조사·문장 조각이 그대로 후보가 돼 잡음이
#   심했다. 이제 제목→검색 키워드 판정(title_keywords.extract_keywords, LLM)을 쓰고,
#   그 판정을 이 순수함수에 인자로 주입한다(가짜 판정으로 검사한다).
#
# 머리줄·문구는 정본(cafe-external/바이럴_키워드_선별.py)과 똑같이 쓴다 —
# 두 길(로그인 있는 갈래 B · 없는 이 길)이 같은 탭에 같은 모양으로 쌓여야 한다.
키워드후보_머리줄 = ["키워드", "제품군", "접촉지점", "MB", "PC", "총합", "발견경로",
                 "대상카페", "제안자", "제안일", "중복체크(자동)", "주제 분류"]
후보_발견경로 = "남의 글 제목"
후보_제안자 = "자동(제목)"


def _키워드정규화(s) -> str:
    """띄어쓰기·대소문자를 무시한 비교용 모양 — 중복을 이걸로 막는다.

    cafe-external 쪽 `키워드발굴._nospace` 와 같은 규칙(공백 제거 + casefold)이라,
    두 길이 같은 키워드를 같은 것으로 본다.
    """
    return "".join(str(s or "").split()).casefold()


def 제목_키워드후보(by_product: dict, 이미가진: set, 이미후보: set, *,
              오늘: str = "", 발견경로: str = 후보_발견경로,
              제안자: str = 후보_제안자, 키워드뽑기=None) -> list:
    """남의 글 **제목** → 우리한테 없는 검색 키워드 후보 줄(제품군별) · 순수함수.

    by_product = {제품군: [언급...]} — 언급은 최소 '제목' 을 든다(경쟁사 배치가 남긴 모양).
    이미가진 · 이미후보 = **정규화된** 키워드 집합(우리 제품탭 · 이미 후보에 있는 것).
    키워드뽑기 = 제목 목록 → {제목: [키워드,...]} 판정기. 안 주면 진짜 LLM 판정을 쓴다.
      검사에서는 가짜 판정을 주입한다(그래서 이 함수는 LLM·네트워크를 모른다).

    ★브랜드 조각이 아니라 **사람이 검색할 법한 키워드**를 뽑는다(잡음 제거는 판정기 몫).
    ★열쇠(LLM)가 없으면 판정기가 빈 결과를 줘 후보가 한 줄도 안 나온다(지어내지 않음).
    ★줄을 지우지 않는다 — 새 후보만 돌려준다. 중복은 키워드 정규화로 막는다.
    ★검색량(MB·PC·총합)은 비워 둔다 — 집 PC 검색량 도구가 나중에 채운다.
    파일·시트를 모른다.
    """
    이미가진 = 이미가진 or set()
    이미후보 = 이미후보 or set()

    # 모든 제목을 한데 모아 한 번에 판정한다(같은 제목은 판정기가 알아서 한 번만 묻는다).
    모든제목: list = []
    본제목: set = set()
    for 언급들 in (by_product or {}).values():
        for m in 언급들 or []:
            제목 = str((m or {}).get("제목") or "").strip()
            if 제목 and 제목 not in 본제목:
                본제목.add(제목)
                모든제목.append(제목)
    if not 모든제목:
        return []

    if 키워드뽑기 is None:
        키워드뽑기 = title_keywords.extract_keywords
    제목별키워드 = 키워드뽑기(모든제목) or {}

    본것: set = set()
    out: list = []
    for 제품군, 언급들 in (by_product or {}).items():
        for m in 언급들 or []:
            제목 = str((m or {}).get("제목") or "").strip()
            if not 제목:
                continue
            카페 = str((m or {}).get("카페") or "")
            for kw in 제목별키워드.get(제목) or []:
                kw = str(kw).strip()
                n = _키워드정규화(kw)
                if not n or n in 이미가진 or n in 이미후보 or n in 본것:
                    continue
                본것.add(n)
                out.append({
                    "키워드": kw, "제품군": 제품군, "접촉지점": "",
                    "MB": "", "PC": "", "총합": "",
                    "발견경로": 발견경로, "대상카페": 카페,
                    "제안자": 제안자, "제안일": 오늘,
                    "중복체크(자동)": "", "주제 분류": "",
                })
    return out


def 키워드후보_표로(줄들: list) -> list:
    """후보 줄 → 시트에 붙일 값 목록(머리줄 없이) · 순수함수."""
    return [[줄.get(c, "") for c in 키워드후보_머리줄] for 줄 in 줄들 or []]


def _후보탭_갱신(client, by_product: dict, today: str) -> int:
    """제목에서 뽑은 키워드 후보를 '키워드후보' 탭에 **더한다**(줄 안 지움).

    ★경쟁사 탭 쓰기와 **별개**로 산다 — 여기서 넘어져도 경쟁사 탭은 그대로다.
    우리 제품탭('…카외')과 이미 있는 후보를 읽어 그중에 없는 것만 append 한다.
    """
    import gspread

    이미가진, 이미후보 = set(), set()
    for ws in client.spreadsheet.worksheets():
        title = ws.title.strip()
        if title.endswith("카외"):
            대상 = 이미가진
        elif title == "키워드후보":
            대상 = 이미후보
        else:
            continue
        v = ws.get_all_values()
        if not v or "키워드" not in v[0]:
            continue
        ki = v[0].index("키워드")
        for r in v[1:]:
            if ki < len(r) and str(r[ki]).strip():
                대상.add(_키워드정규화(r[ki]))

    새것 = 제목_키워드후보(by_product, 이미가진, 이미후보, 오늘=today)
    if not 새것:
        print("키워드후보: 제목에서 나온 새 후보 없음 (다 이미 갖고 있거나 후보에 있음)")
        return 0
    try:
        ws = client.spreadsheet.worksheet("키워드후보")
    except gspread.exceptions.WorksheetNotFound:
        ws = client.spreadsheet.add_worksheet(
            title="키워드후보", rows=200, cols=len(키워드후보_머리줄))
        ws.update("A1", [키워드후보_머리줄], value_input_option="RAW")
    ws.append_rows(키워드후보_표로(새것), value_input_option="RAW")
    print(f"키워드후보: 제목에서 뽑은 새 후보 {len(새것)}줄 추가 (발견경로='{후보_발견경로}')")
    return len(새것)


def extract_brands(mentions: list, *, verdict_path: str = brand_verdicts.DEFAULT_PATH,
                   today: str = "", reads_path: str = comment_reads.DEFAULT_PATH,
                   max_batches: int | None = None) -> tuple:
    """★새 구조(2026-07-24) — 댓글 원문을 AI 가 읽어 이름을 뽑고, 검색으로 확인한다.

    (브랜드가 붙은 mentions, 판정표, 통계) 를 돌려준다.

    전 구조는 글자 규칙이 후보를 뽑고 AI 는 O/X 만 해서, '안티트로' 가 지워지고
    '터그루트' 같은 잘린 이름이 표에 올랐다. 지금은 두 관문이 서로를 메운다.

    ★읽기 캐시(2026-08-20) — 한 번 읽은 댓글은 comment_reads 에 남겨 다시 보내지
    않는다. 키워드 1,240개 시대에 매일 2.6만 건을 처음부터 읽다가 무료 한도·시간을
    다 태운 것(7/29~8/16 매일 밤 시간 초과)의 근본 수술. 실패한 읽기는 안 남긴다.
    """
    # 같은 댓글이 여러 번 들어와 있으므로 원문 기준으로 한 번만 읽는다.
    자리, 원문들 = {}, []
    for m in mentions or []:
        t = str(m.get("댓글") or "").strip()
        if t and t not in 자리:
            자리[t] = len(원문들)
            원문들.append(t)

    if not today:
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")

    reads = comment_reads.load(reads_path)
    캐시뽑힘: dict = {}
    안읽은: list = []                       # [(원문들 index, 원문)]
    for i, t in enumerate(원문들):
        기억 = comment_reads.get(reads, t)
        if 기억 is None:
            안읽은.append((i, t))
        else:
            if 기억:
                캐시뽑힘[i] = 기억
            comment_reads.touch(reads, t, today)   # 오늘도 보였다 — 청소에서 살린다

    새뽑힘, stat = brand_from_comments.read_all(
        [t for _, t in 안읽은], max_batches=max_batches)
    읽은자리 = stat.pop("읽은자리", set())
    뽑힘 = dict(캐시뽑힘)
    for j, names in (새뽑힘 or {}).items():
        뽑힘[안읽은[j][0]] = names
    for j in 읽은자리:                      # 성공한 자리만 남긴다(빈 결과 포함) — 실패는 내일 다시
        _, t = 안읽은[j]
        comment_reads.put(reads, t, 새뽑힘.get(j) or [], today)
    comment_reads.save(comment_reads.prune(reads, today), reads_path)
    stat["캐시읽음"] = len(원문들) - len(안읽은)

    이름들 = sorted({n for names in 뽑힘.values() for n in names})
    stat["뽑은이름"] = len(이름들)          # 캐시로 되살린 이름까지 합친 수

    # 한 번 확인한 이름은 다시 검색하지 않는다(파일에 쌓인다).
    cached = brand_verdicts.load(verdict_path)
    새이름 = [n for n in 이름들 if n not in cached]
    통과, _ = shop_probe.verified(새이름, stat=stat)

    fresh = {n: {"제품": n in set(통과), "이름": n if n in set(통과) else ""}
             for n in 새이름}
    verdicts = brand_verdicts.merge(cached, fresh, today=today)
    if fresh:
        brand_verdicts.save(verdicts, verdict_path)

    # 뽑힌 이름을 원래 언급 자리에 붙인다 — 키워드·글 링크가 살아 있어야 집계가 된다.
    out: list = []
    for m in mentions or []:
        t = str(m.get("댓글") or "").strip()
        i = 자리.get(t)
        for name in (뽑힘.get(i) or []) if i is not None else []:
            out.append({**m, "표시": name, "키": name, "종류": "제품"})
    stat["언급"] = len(out)
    stat["확정이름"] = len({m["키"] for m in out
                        if brand_verdicts.is_product(verdicts, m["키"])})
    return out, verdicts, stat


def judge_candidates(mentions: list, *, verdict_path: str = brand_verdicts.DEFAULT_PATH,
                     today: str = "") -> tuple:
    """후보 → 판정. (판정표, 통계) · 이미 판정한 이름은 다시 묻지 않는다.

    돌아온 판정표에 없는 후보 = 미판정 → 표에 넣지 않는다(지어내기 금지).
    """
    cached = brand_verdicts.load(verdict_path)
    unknown, seen = [], set()
    for m in mentions or []:
        key = m["키"]
        if key in cached or key in seen:
            continue
        seen.add(key)
        unknown.append({"키": key, "표시": m["표시"], "예시": m["댓글"]})

    물어볼것 = len(unknown)
    # ★언어모델에게 묻기 전에 쇼핑 화면에 먼저 물어본다 — 공짜이고 하루 한도가 없다.
    #   "이 이름으로 물건을 살 수 있나" 가 원래 판정 기준이니, 쇼핑이 더 곧은 답이다.
    #   확실히 아닌 것만 여기서 떼고(신호 5 이하), 나머지는 그대로 언어모델에게 넘긴다.
    #   ★한 번만 나온 이름에만 물어본다. 여러 번 오르내린 이름은 진짜 경쟁사일 확률이
    #   높은데, 검색량이 적은 작은 브랜드는 신호가 낮게 나와 억울하게 걸린다
    #   (실측에서 '뽀얀'·'아크시톨' 이 그렇게 걸렸다).
    말나온횟수: dict = {}
    for m in mentions or []:
        말나온횟수[m["키"]] = 말나온횟수.get(m["키"], 0) + 1
    물어볼이름 = [u["키"] for u in unknown if 말나온횟수.get(u["키"], 0) <= 1]
    쇼핑통계: dict = {}
    아닌것 = shop_probe.not_products(물어볼이름, stat=쇼핑통계)
    unknown = [u for u in unknown if u["키"] not in 아닌것]

    fresh, stat = comment_brand_llm.judge(unknown)
    for k in 아닌것:                      # 쇼핑이 낸 답 — 언어모델 답을 덮지 않는다
        fresh.setdefault(k, {"제품": False, "이름": ""})
    stat.update(쇼핑통계)
    stat["후보"] = 물어볼것               # 쇼핑에서 뗀 몫까지 합쳐 세야 통계가 맞다
    stat["판정"] = len(fresh)
    stat["미판정"] = max(0, 물어볼것 - len(fresh))
    stat["캐시적중"] = len({m["키"] for m in (mentions or [])}) - 물어볼것
    verdicts = brand_verdicts.merge(cached, fresh, today=today)
    if fresh:
        brand_verdicts.save(verdicts, verdict_path)
    return verdicts, stat


def brand_names(mentions: list, verdicts: dict) -> list:
    """판정된 브랜드명 목록(중복 없이) — 이름 묶기에 넣을 재료."""
    seen = []
    for m in mentions or []:
        key = m["키"]
        if not brand_verdicts.is_product(verdicts, key):
            continue
        name = brand_verdicts.display_name(verdicts, key, m["표시"])
        if is_real_brand(name) and name not in seen:
            seen.append(name)
    return seen


def confirmed_rows(mentions: list, verdicts: dict, unified: dict | None = None) -> list:
    """판정된 제품만 남겨 집계. 미판정·제품아님은 조용히 뺀다.

    묶음은 **판정된 브랜드명** 으로 다시 한다 — '맥단' 과 '맥단탈모샴푸' 는 한 줄(맥단비)이다.
    우리 제품을 빼는 것도 이 이름으로 봐야 새는 곳이 없다.
    """
    kept = []
    for m in mentions or []:
        key = m["키"]
        if not brand_verdicts.is_product(verdicts, key):
            continue
        name = brand_verdicts.display_name(verdicts, key, m["표시"])
        name = (unified or {}).get(name, name)   # 흐트러뜨린 표기를 정식 브랜드명 하나로
        if not is_real_brand(name):        # 마지막 그물 — 종류 이름·장소가 판정을 뚫어도 여기서 막는다
            continue
        # 종류 이름까지 벗겨 묶는다 — '안티트로' 와 '안티트로샴푸' 는 한 브랜드다
        kept.append({**m, "표시": name, "키": strip_generic_tail(name) or normalize_name(name)})
    rows = tally(kept, exclude_keys=OUR_PRODUCT_HINTS)
    for r in rows:                          # 몇 개 키워드에서 나왔나 (같은 브랜드끼리 합쳐서 센다)
        mine = [m for m in kept if m["키"] == r["키"]]
        # ★'횟수'는 날짜 열·추세의 재료다 → **댓글 언급만** 센다.
        # 제목 언급까지 섞으면 시트에 쌓인 어제까지의 값(댓글만 세던 정의)과 잣대가 달라져,
        # 아무 일도 없었는데 "▲ 늘었다" 로 보인다. 정의를 바꿔놓고 현실이 변한 걸로 읽는 사고.
        # ★2026-09-04 — '아닌 것 빼기' 에서 '맞는 것만 세기' 로 바꿨다.
        #   글 단위 기록(원천="글", 댓글을 못 연 글의 계정을 살리려고 남긴다)이
        #   '상위노출 이 아니다' 라는 이유로 횟수에 섞여 추세를 부풀렸다.
        #   빼는 목록은 새 값이 생길 때마다 조용히 틀린다 — 넣는 목록으로 쓴다.
        #   원천이 안 적힌 옛 자료는 댓글로 본다(그때는 댓글밖에 없었다).
        r["횟수"] = len([m for m in mine if (m.get("원천") or "댓글") == "댓글"])
        kw_count: dict = {}
        for m in mine:
            kw = m.get("키워드")
            if kw:
                kw_count[kw] = kw_count.get(kw, 0) + 1
        r["키워드수"] = len(kw_count)
        # 많이 나온 키워드부터 — "어디를 치고 들어와야 하나" 가 여기서 보인다
        r["키워드들"] = [k for k, _ in sorted(kw_count.items(), key=lambda x: (-x[1], x[0]))]
        seen_link: list = []
        for m in mine:
            link = m.get("글")
            if link and link not in seen_link:
                seen_link.append(link)
        r["글들"] = seen_link
        # ★2026-09-04 독립 검수 지적 #6 — 전에는 `원천 == "상위노출"` 인 것만 셌는데
        #   그 값을 넣는 코드가 저장소에 **한 줄도 없어** 두 칸이 늘 0이었다.
        #   화면은 그 0을 "우리가 놓친 것 없음" 으로 보이게 했다.
        #   · '상위노출 차지' 는 폐기했다 — 애초에 상위 구좌 글만 훑으므로
        #     '뜬 키워드 수' 와 언제나 같은 값이다. 같은 것을 두 번 적으면
        #     사장님이 서로 다른 뜻으로 읽으신다.
        #   · '우리가 놓친' 은 원천을 안 따지고 센다. 그 키워드 상위 구좌에
        #     우리 글이 하나도 없었나(우리놓침)는 글마다 이미 붙어 있다.
        r["놓친"] = len({m.get("키워드") for m in mine
                        if m.get("우리놓침") and m.get("키워드")})
        # ★2026-09-04 사장님: "어떤 키워드에 몇위에 상위노출되어있는지 알 수 있지".
        #   키워드 하나에 그 브랜드 글이 여러 개면 **가장 좋은 자리**가 그 키워드 성적이다.
        #   순위 0 은 '모른다' 지 '1등보다 좋다' 가 아니므로 셈에서 뺀다 —
        #   섞으면 표가 성적을 거짓으로 좋게 말한다.
        r["순위별"] = _순위표(mine)
        r["최고순위"], r["평균순위"] = _순위요약(r["순위별"])
        r["키워드별순위"] = _순위글(r["순위별"])
    return rows


# 사장님이 '상위노출' 이라 부르는 자리. 다른 구좌(인기글·스마트블록)는 같은 1위여도
# 다른 자리라, 한 평균에 섞으면 성적이 거짓으로 좋아진다(2026-09-04 검수 지적 #5).
상위노출_구좌 = "AB"


def _순위표(mentions: list) -> list:
    """언급 목록 → [{키워드, 구좌, 순위}] · 키워드·구좌마다 **가장 좋은 자리** 하나.

    ★`SlotItem.rank` 는 '그 구좌 **안**의 순위' 다(parser.py 참고).
    AB 1위와 인기글 1위는 서로 다른 자리이므로 구좌를 떼어 두면 안 된다.
    순위 0 은 '모른다' 지 '1위보다 좋다' 가 아니므로 아예 뺀다.
    """
    best: dict = {}
    for m in mentions or []:
        kw = m.get("키워드")
        구좌 = str(m.get("구좌") or "").strip() or "모름"
        try:
            rank = int(m.get("순위") or 0)
        except (TypeError, ValueError):
            rank = 0
        if not kw or rank <= 0:
            continue
        key = (kw, 구좌)
        if key not in best or rank < best[key]:
            best[key] = rank
    return [{"키워드": k, "구좌": g, "순위": v}
            for (k, g), v in sorted(best.items(), key=lambda x: (x[1], x[0]))]


def _순위요약(표):
    """순위표 → (최고순위, 평균순위). **상위노출 구좌만** 센다.

    하나도 없으면 빈 값 — 0 을 쓰지 않는다.
    """
    vals = [r["순위"] for r in (표 or []) if r.get("구좌") == 상위노출_구좌]
    if not vals:
        return "", ""
    return min(vals), round(sum(vals) / len(vals), 1)


def _순위글(표) -> str:
    """순위표 → "지루성두피염샴푸 AB 2위 · 비듬샴푸 인기글 1위". 좋은 자리부터.

    요약에서 빠지는 구좌도 여기에는 남긴다 — 사라지게 두지 않는다.
    """
    표 = sorted(표 or [], key=lambda r: (r["순위"], r["키워드"]))
    if not 표:
        return ""
    보임 = 표[:MAX_KEYWORDS_SHOWN]
    글 = " · ".join(f'{r["키워드"]} {r["구좌"]} {r["순위"]}위' for r in 보임)
    if len(표) > len(보임):
        글 += f" 외 {len(표) - len(보임)}개"
    return 글


def viral_accounts(mentions: list, verdicts: dict, unified: dict | None = None,
                   이름붙은: list | None = None) -> list:
    """언급 목록 → **계정별** 한 줄. 바이럴인지 아닌지는 이 숫자가 답한다.

    사장님 2026-09-04 원문: "대략적으로 전부 크롤링을 한다고 쳐볼게. 그러면 우리가
    키워드 별 노출 횟수를 볼 수 있고 몇개의 키워드에 상위노출 몇위에 되어있는지 그
    개수를 알 수 있으니까 **바이럴인지 아닌지도 판단이 가능하겠지**"

    ★바이럴 판정을 앞에 세우지 않는다. 미리 거르면 그 판정을 만들 재료를 버린다.
    전부 모으고, `키워드수 · 평균순위` 로 드러나게 한다.

    ★2026-09-04 독립 검수 지적 #1 — 이 함수에 **이름이 뽑힌 댓글만** 넘기고 있었다.
    그래서 상위노출은 됐는데 댓글에서 제품명이 안 나온 글의 계정이 통째로 사라졌고,
    키워드 3개에 떠 있는 계정이 1개로 찍혔다. 사장님이 뒤집으신 바로 그 자리를
    코드가 그대로 어기고 있었다. 지금은 `mentions` 에 **원문 그대로** 받는다.
    `이름붙은` 은 미는 제품을 붙일 때만 쓴다 — 세는 일에는 안 쓴다.

    계정키(memberKey)가 없으면 묶지 않는다 — 닉네임이 같은 다른 사람을 한 계정으로
    합치면 **없는 바이럴을 만들어낸다**(이 프로젝트 원칙: 적게 세는 오류 > 지어내는 오류).
    """
    묶음: dict = {}
    버린언급 = 0
    for m in mentions or []:
        키 = str(m.get("글쓴이키") or "").strip()
        if not 키:
            버린언급 += 1
            continue
        a = 묶음.setdefault(키, {
            "계정": str(m.get("글쓴이") or ""), "계정키": 키,
            "카페": str(m.get("카페") or ""), "카페번호": str(m.get("카페번호") or ""),
            "_언급": [], "_글": [], "_제품": []})
        a["_언급"].append(m)
        link = m.get("글")
        if link and link not in a["_글"]:
            a["_글"].append(link)
        if not a["카페번호"] and m.get("카페번호"):
            a["카페번호"] = str(m.get("카페번호"))

    # 미는 제품 = 그 계정 글의 댓글에서 **판정을 통과한** 이름만.
    # 판정 못 받은 것을 넣으면 '약국에서' 같은 조각이 업체 이름처럼 보인다.
    for m in (이름붙은 if 이름붙은 is not None else mentions) or []:
        키 = str(m.get("글쓴이키") or "").strip()
        a = 묶음.get(키)
        pk = m.get("키")
        if not a or not pk or not brand_verdicts.is_product(verdicts, pk):
            continue
        이름 = brand_verdicts.display_name(verdicts, pk, m.get("표시") or "")
        이름 = (unified or {}).get(이름, 이름)
        if 이름 and is_real_brand(이름) and 이름 not in a["_제품"]:
            a["_제품"].append(이름)

    rows = []
    for a in 묶음.values():
        순위별 = _순위표(a["_언급"])
        최고, 평균 = _순위요약(순위별)
        키워드들 = sorted({m.get("키워드") for m in a["_언급"] if m.get("키워드")})
        # ★2026-09-04 사장님 정정 — "우리가 카페 구좌 1등 아닌 키워드들의
        #   우리보다 높이 있는 카페 들을 뒤져봐." 뒤질 순서를 정하는 숫자다.
        #   '견줄 수 없다'("")는 이긴 것으로 세지 않는다.
        이긴것 = sorted({m.get("키워드") for m in a["_언급"]
                       if m.get("우리보다위") is True and m.get("키워드")})
        # ★그 칸이 **아예 없으면** '이긴 적 없다' 가 아니라 '못 잰다' 다
        #   (2026-09-05 실물: 옛 회차가 저장한 댓글을 재사용하는 동안 그 칸이
        #    없어서 1,485개 계정이 전부 0 으로 나왔고, 뒤질 순서가 무의미해졌다.
        #    0 으로 적으면 리그오브레전드·육아 카페 계정부터 뒤지게 된다).
        잴수있나 = any("우리보다위" in (m or {}) for m in a["_언급"])
        rows.append({
            "계정": a["계정"], "계정키": a["계정키"],
            "카페": a["카페"], "카페번호": a["카페번호"],
            "키워드수": len(키워드들), "키워드들": 키워드들,
            "이긴키워드수": len(이긴것) if 잴수있나 else "",
            "이긴키워드": 이긴것,
            "이긴것을_못잼": (not 잴수있나) or None,
            "글수": len(a["_글"]), "글들": a["_글"],
            "순위별": 순위별, "최고순위": 최고, "평균순위": 평균,
            "미는제품": a["_제품"],
        })
    # ★우리를 이긴 계정이 먼저다(사장님 정정) — 그다음이 넓이, 그다음이 성적.
    #   키워드 수만으로 줄 세우면 우리를 못 이기는 계정이 위로 올라온다.
    rows.sort(key=lambda r: (-(r["이긴키워드수"] or 0), -r["키워드수"],
                             r["평균순위"] if r["평균순위"] != "" else 99,
                             r["계정키"]))
    # ★몇 %를 보고 있는지 밝힌다 — 계정키가 없어 못 묶은 언급 수(검수 지적 #15).
    #   "부분만 보고 있으면 몇 %를 보고 있는지 먼저 말한다"(팀 규칙).
    for r in rows:
        r["못묶은언급"] = 버린언급
    return rows


def 프로필주소(카페번호: str, 계정키: str) -> str:
    """계정 프로필 주소. 카페번호나 계정키가 없으면 빈칸 — 주소를 지어내지 않는다."""
    카페번호, 계정키 = str(카페번호 or "").strip(), str(계정키 or "").strip()
    if not 카페번호 or not 계정키:
        return ""
    return f"https://cafe.naver.com/ca-fe/cafes/{카페번호}/members/{계정키}"


# 언급 한 줄이 반드시 들고 있어야 하는 칸. 2026-09-04 에 늘었다(순위·구좌·작성자).
_언급_필수칸 = ("키워드", "글", "순위", "구좌", "제목", "글쓴이", "글쓴이키", "카페번호")


def 모양_모자란칸(by_product: dict) -> list:
    """모아둔 댓글 파일이 지금 코드가 기대하는 모양인가 → 모자란 칸 이름들.

    ★모아둔 댓글을 다시 쓰는 길(reuse_mentions)을 열면서 같이 막는 함정이다.
    모양이 바뀐 뒤 옛 파일을 읽으면 **크롤은 건너뛰는데 계정 표가 조용히 빈다.**
    빈 표는 '경쟁이 없다' 처럼 보이고, 그게 이 저장소가 가장 자주 데인 자리다.
    """
    첫 = next((m for ms in (by_product or {}).values() for m in ms), None)
    if not 첫:
        return []
    return [c for c in _언급_필수칸 if c not in 첫]


def 글쓴이_찾기(comments: list) -> dict:
    """댓글 목록 → 그 글을 쓴 사람 {닉, 키}. 못 찾으면 {}.

    ★추가 요청 없이 공짜로 얻는 자리다. 바이럴 글은 글쓴이가 댓글로 대답하기 때문에
    `isArticleWriter` 가 붙은 댓글이 거의 항상 있다(카페 API 가 직접 달아주는 표식이라
    닉네임 대조보다 정확하다 — 2026-07 실증). 없을 때만 글을 한 번 연다.

    지워진 댓글은 화면에 안 보이므로 근거로 쓰지 않는다.
    """
    for c in comments or []:
        if not (c or {}).get("isArticleWriter") or (c or {}).get("isDeleted"):
            continue
        w = (c or {}).get("writer") or {}
        닉 = str(w.get("nick") or w.get("nickName") or "").strip()
        키 = str(w.get("memberKey") or "").strip()
        if 닉 or 키:
            return {"닉": 닉, "키": 키}
    return {}


def scan_keyword(crawler: CommentFetcher, kw: str, *, our_links: set, our_slugs: set,
                 fetcher: CommentFetcher, top_posts: int) -> list[dict]:
    """키워드 1건 → 그 키워드에서 나온 제품 언급 목록."""
    html = crawler.fetch_search(kw)
    items = [i for i in collect_slot_items(html) if i.kind == "cafe"]
    mentions: list[dict] = []
    seen_url: set = set()
    # 이 키워드의 상위 구좌에 우리 글이 하나도 없나 — "우리가 놓친" 을 세는 잣대.
    우리놓침 = not any(is_our_item(i.url, our_links, our_slugs) for i in items)

    # ★2026-09-04 사장님 정정: "우리가 카페 구좌 1등 아닌 키워드들의
    #   **우리보다 높이 있는** 카페 들을 뒤져봐."
    #   남의 글을 무차별로 보는 것이 아니라, 실제로 우리를 이기고 있는 글을 본다.
    #   구좌가 다르면 견주지 않는다 — AB 3등과 인기글 1등은 다른 자리다.
    우리순위: dict = {}
    for i in items:
        if not is_our_item(i.url, our_links, our_slugs):
            continue
        구 = str(getattr(i, "area", "") or "")
        r = int(getattr(i, "rank", 0) or 0)
        if r > 0 and (구 not in 우리순위 or r < 우리순위[구]):
            우리순위[구] = r
    for it in items:
        if len(seen_url) >= top_posts:
            break
        if is_our_item(it.url, our_links, our_slugs):
            continue          # 우리 글은 보지 않는다 (사장님: "우리 글 말고 다른 글")
        if it.url in seen_url:
            continue
        seen_url.add(it.url)
        # ★댓글만 본다. 사장님 2026-07-24: "다른거 다 무시하고 댓글만 보라고 했잖아".
        #   그리고 여기서는 이름을 뽑지 않는다 — 댓글 원문을 그대로 담아 두고,
        #   판정 단계에서 AI 가 원문을 읽어 이름을 뽑는다(잘림·놓침을 없애려고).
        댓글들 = fetcher.comments(it.url)
        # ★2026-09-04 사장님 프로세스 — 같은 크롤에서 두 갈래가 갈린다.
        #   순위는 검색 화면을 읽을 때 이미 손에 있었는데 버리고 있었다
        #   ("어떤 키워드에 몇위에 상위노출되어있는지 알 수 있지").
        #   작성자는 갈래 B 의 출발점이다("그 계정이 바이럴하는 다른 키워드들").
        글쓴이 = 글쓴이_찾기(댓글들)
        if 글쓴이.get("키"):
            # 카페번호는 댓글을 받을 때 이미 손에 들어와 있다 — 요청 0으로 채운다.
            글쓴이 = {**글쓴이, "카페번호": (getattr(fetcher, "cafe_no", None)
                                        and fetcher.cafe_no(it.url)) or ""}
        else:
            글쓴이 = fetcher.writer(it.url) or {}     # 댓글에 없을 때만 글을 연다
        내구좌 = str(getattr(it, "area", "") or "")
        내순위 = int(getattr(it, "rank", 0) or 0)
        우리것 = 우리순위.get(내구좌)          # 같은 구좌에서 우리는 몇 등인가
        같이 = {"키워드": kw, "글": it.url, "카페": it.source_name or "",
                "우리놓침": 우리놓침,
                # 우리 글이 아예 없으면 모두가 우리보다 위다(우리는 자리에 없다).
                "우리순위": 우리것 if 우리것 else "",
                # 셋으로 갈린다: True(이겼다) / False(못 이겼다) / ""(견줄 수 없다).
                #   · 우리 글이 그 키워드에 아예 없으면 → 다 우리보다 위다.
                #   · 같은 구좌에 우리가 있으면 → 순위로 견준다.
                #   · 우리가 **다른 구좌**에만 있으면 → 견줄 수 없다(빈칸).
                #     AB 3등과 인기글 1등을 견주면 거짓으로 '이겼다' 가 된다.
                "우리보다위": (True if not 우리순위 else
                            (내순위 > 0 and 내순위 < 우리것) if 우리것 else ""),
                "순위": getattr(it, "rank", 0), "구좌": getattr(it, "area", ""),
                "제목": getattr(it, "title", "") or "",
                "글쓴이": str(글쓴이.get("닉") or ""),
                "글쓴이키": str(글쓴이.get("키") or ""),
                "카페번호": str(글쓴이.get("카페번호") or "")}
        붙은 = 0
        for c in 댓글들:
            t = str((c or {}).get("content") or "").strip()
            if t:
                mentions.append({"댓글": t[:300], **같이, "원천": "댓글"})
                붙은 += 1
        if not 붙은:
            # ★2026-09-04 검수 지적 #1 — 댓글을 못 열거나 댓글이 없는 글은 언급이
            #   0건이라 **그 계정이 통째로 사라졌다.** 순위·작성자는 이미 손에 있으니
            #   글 단위로 한 줄 남긴다. 제품 이름을 뽑는 쪽은 댓글이 빈 이 줄을
            #   그냥 지나친다(빈 글은 읽을 것이 없다).
            mentions.append({"댓글": "", **같이, "원천": "글"})
        time.sleep(1.0)       # 네이버 부담 줄이기
    return mentions


# 한 탭에 다 담는다 — 사장님 지시(2026-07-24): "여러개로 나누지 말고 아예 한 시트에 모아줘".
# 한 줄 = 경쟁사 하나. 얼마나 나오나 · 늘고 있나 · 어느 키워드·어느 글에서 나왔나가 한눈에.
# ★2026-09-04 사장님 지적으로 다시 짬 — "무슨 행 길이가 이렇게 길어? … 날짜를 왜
#   저렇게 해둬?" 실제 시트를 열어 보니(그 전까지 한 번도 안 봤다) 날짜 7칸이
#   표 한가운데 있어 정작 볼 숫자를 오른쪽 밖으로 밀어냈고, '댓글 예시' 가 통째로
#   한 칸에 들어가 행 높이를 키우고 있었다.
#   → 읽는 순서대로: 누구인가 · 얼마나 큰가 · 얼마나 넓게 · 얼마나 잘 · 어디서.
FIXED_HEAD = ["제품군", "경쟁사", "검색량", "판정", "뜬 키워드 수", "최고순위", "평균순위",
              "어느 키워드 몇 위", "7일 댓글 수", "추세", "우리가 놓친", "글 링크",
              "이 표를 만들 때 얼마나 읽었나"]

# ★2026-09-05 사장님: "경쟁사 추출한거 보니까 다 이상하다".
#   사장님 프로세스의 확정 기준은 검색량이다 — "그걸 검색해서 검색량이랑 조회해보면
#   경쟁사가 추출이 될거야"(2026-09-04 원문). 그런데 표에는 검색량 빈 칸이 134줄인데
#   **아직 안 물어본 것**과 **물어봤더니 0 이던 것**이 똑같이 보였다.
#   → 검색량 칸 하나로 세 가지를 갈라 적는다. 줄은 지우지 않는다(원칙 5-1
#     "앞에서 자르지 않는다") — 갈라 적고 순서로 밀어 둘 뿐이다.
판정_확인 = "경쟁사(검색량 확인)"
판정_영 = "검색량 0 — 이름 확인 필요"
판정_전 = "검색량 확인 전"


def 판정_말(검색량) -> str:
    """검색량 칸 값 → 판정 세 가지 중 하나 · 순수함수.

    1 이상이면 이름이 실제로 검색되는 것이니 경쟁사로 확정.
    0 이면 그 이름으로는 아무도 검색하지 않는다 — 잘린 이름이거나 제품이 아니다.
    빈 칸이면 아직 안 물어봤다. 숫자로 못 읽는 글자도 '안 물어본 것'으로 둔다
    (모르는 것을 안다고 적지 않는다).
    """
    글 = str(검색량 if 검색량 is not None else "").strip().replace(",", "")
    if not 글:
        return 판정_전
    try:
        수 = int(float(글))
    except ValueError:
        return 판정_전
    return 판정_확인 if 수 >= 1 else 판정_영


# 표에 놓는 순서 — 확인된 것 먼저, 아직 안 물어본 것, 0 은 맨 뒤.
판정_순서 = {판정_확인: 0, 판정_전: 1, 판정_영: 2}
# ★2026-09-05 — 오늘 이 하나를 여섯 번 고쳤는데 사장님 화면은 하루 종일 어제 값이었다.
#   원인은 버그가 아니라 **"다 못 읽으면 아예 안 쓴다"** 는 내 설계였다.
#   22%를 못 읽었다고 이미 확인된 442종을 통째로 버렸다.
#   막은 이유("반쪽짜리 표를 덮으면 사장님이 그게 전부인 줄 안다")는 맞다 —
#   그러면 답은 '안 쓰기' 가 아니라 **'쓰되 몇 % 인지 같이 적기'** 다.
#   (우리 규칙: "부분만 보고 있으면 몇 %를 보고 있는지 먼저 말한다.")
# ★2026-09-04 사장님 프로세스 — 순위·검색량 칸 신설.
#   "어떤 키워드에 몇위에 상위노출되어있는지" / "그 경쟁사의 검색량도 알 수 있지"
#   검색량은 집 PC 도구가 채운다 — 이 배치는 지키기만 한다.
# ★'상위노출 차지' 는 폐기(2026-09-04 검수 지적 #6) — 상위 구좌 글만 훑으므로
#   '나온 키워드 수' 와 언제나 같은 값이었다.
# 꼬리는 비운다 — 날짜 칸이 곧 꼬리다(맨 뒤).
FIXED_TAIL: list = []
# 날짜 칸은 사흘만. 일곱 칸은 표를 넓게만 만들었다(2026-09-04 사장님 지적).
# 더 긴 흐름은 화면(/competitors)이 본다 — 시트는 '지금 어떤가' 를 적는 자리다.
HISTORY_DAYS = 3
MAX_KEYWORDS_SHOWN, MAX_LINKS_SHOWN = 8, 3

# 옛 표(제품군·경쟁 제품·횟수·나온 키워드 수·확인일·댓글 예시) — 이력 없이 그날치만 있던 시절.
SHEET_HEADER = FIXED_HEAD + FIXED_TAIL


def _prev_counts(values: list) -> tuple:
    """지난 표에서 (제품군, 경쟁사) → {날짜: 횟수} 를 되살린다. 시트가 곧 기록이다."""
    if not values or len(values) < 2:
        return {}, []
    head = [str(c).strip() for c in values[0]]
    date_cols = [(i, c) for i, c in enumerate(head) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)]
    if not date_cols:
        return {}, []
    try:
        ip, ib = head.index("제품군"), head.index("경쟁사")
    except ValueError:
        return {}, []
    out: dict = {}
    for row in values[1:]:
        if len(row) <= ib or not str(row[ip]).strip() or not str(row[ib]).strip():
            continue
        per: dict = {}
        for i, day in date_cols:
            raw = str(row[i]).strip() if i < len(row) else ""
            if raw.isdigit() and int(raw) > 0:
                per[day] = int(raw)
        out[(str(row[ip]).strip(), str(row[ib]).strip())] = per
    return out, [d for _, d in date_cols]


def _prev_volumes(values: list) -> dict:
    """지난 표에서 (제품군, 경쟁사) → 검색량 을 되살린다.

    ★검색량은 이 배치가 만드는 값이 아니다. 집 PC 도구가 네이버 검색광고에 물어
    채워 넣는 칸이고, 이 배치는 매일 표를 통째로 다시 쓴다. 지키지 않으면
    사람이 채운 값이 다음 새벽에 사라져 영영 빈칸으로 남는다.
    """
    if not values or len(values) < 2:
        return {}
    head = [str(c).strip() for c in values[0]]
    try:
        ip, ib, iv = head.index("제품군"), head.index("경쟁사"), head.index("검색량")
    except ValueError:
        return {}
    out: dict = {}
    for row in values[1:]:
        if len(row) <= max(ip, ib) or not str(row[ip]).strip() or not str(row[ib]).strip():
            continue
        val = row[iv] if iv < len(row) else ""
        if str(val).strip():
            out[(str(row[ip]).strip(), str(row[ib]).strip())] = val
    return out


# 오늘 결과에 없으면 지난 표에서 되살릴 칸들. 안 되살리면 반쪽 회차가
# 이 칸들을 **빈칸으로 덮는다** — 오늘 고친 그 화면이 그대로 되돌아온다
# (2026-09-05 검수 심각 1). 날짜·검색량만 지키던 것을 여섯 칸으로 넓힌다.
_지킬칸 = ("뜬 키워드 수", "최고순위", "평균순위", "어느 키워드 몇 위",
         "우리가 놓친", "글 링크")


def _prev_extras(values: list) -> dict:
    """지난 표에서 (제품군, 경쟁사) → {칸이름: 값} 을 되살린다 · 순수함수.

    ★오늘 안 본 경쟁사의 성적을 빈칸으로 만들지 않는다. 빈칸은 '0' 도 '없음' 도
    아니고 **'오늘 안 봤다'** 인데, 표에서는 그 셋이 똑같이 보인다.
    """
    if not values or len(values) < 2:
        return {}
    head = [str(c).strip() for c in values[0]]
    try:
        ip, ib = head.index("제품군"), head.index("경쟁사")
    except ValueError:
        return {}
    자리 = {이름: head.index(이름) for 이름 in _지킬칸 if 이름 in head}
    out: dict = {}
    for row in values[1:]:
        if len(row) <= max(ip, ib):
            continue
        제품, 경쟁 = str(row[ip]).strip(), str(row[ib]).strip()
        if not 제품 or not 경쟁:
            continue
        칸 = {이름: row[i] for 이름, i in 자리.items()
             if i < len(row) and str(row[i]).strip()}
        if 칸:
            out[(제품, 경쟁)] = 칸
    return out


def 시트줄_만들기(product: str, r: dict) -> dict:
    """confirmed_rows 한 줄 → 시트에 넘길 줄 · 순수함수.

    ★2026-09-05 실물 사고: 시트 471줄 중 최고순위·평균순위·어느 키워드 몇 위가
    **0/471** 이었다. 계산은 confirmed_rows 가 이미 다 해놨는데, 시트로 옮기는
    자리에서 그 세 칸을 안 담아 그대로 버렸다.
    이게 사장님 프로세스의 핵심이다 —
    "어떤 키워드에 몇위에 상위노출되어있는지 알 수 있지."

    ★옮기는 자리를 함수로 빼 둔다 — 안에 두면 시험이 그 자리를 못 지나고,
      손으로 만든 값으로 통과하는 껍데기 시험이 된다(2026-09-05에 실제로 그랬다).
    """
    return {"제품군": product, "경쟁사": r["제품"], "횟수": r["횟수"],
            "상위노출": r.get("상위노출", 0), "놓친": r.get("놓친", 0),
            "키워드수": r["키워드수"], "키워드들": r.get("키워드들") or [],
            "최고순위": r.get("최고순위", ""),
            "평균순위": r.get("평균순위", ""),
            "키워드별순위": r.get("키워드별순위", ""),
            "글들": r.get("글들") or [], "댓글 예시": r.get("댓글 예시", "")}


def 읽은정도_말(stat: dict | None) -> str:
    """이 표가 몇 %를 읽고 만든 것인지 한 줄로 · 순수함수.

    ★모르면 지어내지 않는다 — 빈 글자로 둔다.
    """
    stat = stat or {}
    묶음 = int(stat.get("묶음") or 0)
    if not 묶음:
        return ""
    읽음 = 묶음 - int(stat.get("못읽은묶음") or 0)
    말 = f"댓글 {round(읽음 * 100 / 묶음)}% 읽음({읽음}/{묶음}묶음)"
    # ★2026-09-05 검수 심각 3: 이 칸이 **댓글 읽기 한 단계만** 재면서 머리글은
    #   표 전체가 온전한 것처럼 말했다. 확정 1종뿐인 반쪽 표에 '100%' 가 찍혔다.
    #   재는 것을 늘리고, 이름도 재는 그대로 부른다.
    확인 = int(stat.get("검색확인") or 0)
    막힘 = int(stat.get("검색막힘") or 0)
    if 확인:
        말 += f" · 이름 확인 {확인 - 막힘}/{확인}"
    elif 막힘:
        말 += f" · 이름 확인 막힘 {막힘}건"
    확정 = int(stat.get("확정제품") or 0)
    if 확정:
        말 += f" · 오늘 확정 {확정}종"
    return 말 + " · 나머지는 다음 회차"


def build_table(prev_values: list, today_rows: list, today: str,
                days: int = HISTORY_DAYS, stat: dict | None = None) -> list:
    """지난 표 + 오늘 결과 → 시트에 쓸 표 전체 · 순수함수.

    today_rows = [{"제품군","경쟁사","횟수","키워드수","키워드들","글들","댓글 예시"}]
    """
    prev, _ = _prev_counts(prev_values)
    검색량 = _prev_volumes(prev_values)
    merged = {k: dict(v) for k, v in prev.items()}
    extra: dict = {}
    for r in today_rows or []:
        key = (r["제품군"], r["경쟁사"])
        merged.setdefault(key, {})[today] = int(r["횟수"])
        extra[key] = r

    # 날짜 열 = 오늘부터 거꾸로 days 일. 빠진 날도 자리를 두어야 추이가 안 헷갈린다.
    from datetime import date, timedelta
    base = date.fromisoformat(today)
    dates = [(base - timedelta(days=i)).isoformat() for i in range(days)]

    header = FIXED_HEAD + dates
    읽은정도 = 읽은정도_말(stat)
    지난값 = _prev_extras(prev_values)
    rows = []
    # 오늘 이 제품군을 **아예 안 봤나**(회차가 거기까지 못 감) — 봤는데 안 나온 것과 다르다.
    본제품군 = {p for p, _ in extra}
    for (product, brand), per in merged.items():
        # ★옛 줄에도 오늘 잣대를 건다 — 제외가 생기기 전에 들어온 자사·가게·일반명
        #   (두드럼·다이소·케라틴)이 이어받기로 눌러앉는 것을 막는다(2026-09-05 실물 확인).
        if not 표에_남길_경쟁사인가(brand):
            continue
        오늘봄 = (product, brand) in extra
        제품군을봄 = product in 본제품군
        # ★오늘 그 제품군을 아예 안 봤으면 오늘 칸을 **0 으로 만들지 않는다** —
        #   0 은 '댓글이 없었다' 는 뜻이고, 안 본 것은 '모른다' 다.
        #   (2026-09-05 검수 심각 2: 안 본 경쟁사에 '▼ -5' 가 찍혔다.)
        #   봤는데 안 나온 것은 그대로 0 이다 — 그건 진짜 0 이다.
        counts = [(per.get(d, 0) if (d != today or 제품군을봄) else "") for d in dates]
        total = sum(c for c in counts if isinstance(c, int))
        r = extra.get((product, brand), {})
        try:
            _키수 = int(r.get("키워드수") or 0)
        except (TypeError, ValueError):
            _키수 = 0
        # 7일 안에 댓글에 한 번도 안 나온 경쟁사는 내린다 — 단, 오늘 보였으면 남긴다.
        # ★내릴지는 **오늘 값**으로만 정한다. 지난 값으로 정하면 사라진 경쟁사가
        #   영영 안 내려간다.
        if not total and not _키수:
            continue
        # ★오늘 이 경쟁사가 안 나왔으면 지난 성적을 **그대로 두되 언제 잰 것인지 붙인다**
        #   (2026-09-05 검수 심각 1). 순위는 '오늘 댓글에 안 나왔다' 고 사라질 값이
        #   아니다 — 빈칸으로 덮으면 어제 알던 것을 오늘 잃는다.
        #   7일 내내 안 나오면 위에서 줄째로 내려가므로 묵은 값이 눌러앉지 않는다.
        if not 오늘봄:
            묵은 = 지난값.get((product, brand)) or {}
            잰날 = 묵은.get("잰날") or ""
            꼬리 = f" ({잰날} 기준)" if 잰날 else " (지난 회차 기준)"
            키별 = str(묵은.get("어느 키워드 몇 위") or "")
            r = {"키워드수": 묵은.get("뜬 키워드 수", ""),
                 "최고순위": 묵은.get("최고순위", ""),
                 "평균순위": 묵은.get("평균순위", ""),
                 "키워드별순위": (키별 + 꼬리) if 키별 and "기준)" not in 키별 else 키별,
                 "놓친": 묵은.get("우리가 놓친", ""),
                 "글들": [묵은.get("글 링크", "")] if 묵은.get("글 링크") else []}
        before = next((c for c in counts[1:] if isinstance(c, int) and c), 0)
        now = counts[0]
        if now == "":
            trend = "오늘은 못 봄"      # 안 본 것을 '줄었다' 로 적지 않는다
        elif not before:
            trend = "신규" if now else ""
        elif now > before:
            trend = f"▲ +{now - before}"
        elif now < before:
            trend = f"▼ -{before - now}"
        else:
            trend = "– 그대로"
        kws = list(r.get("키워드들") or [])
        kw_text = ", ".join(kws[:MAX_KEYWORDS_SHOWN])
        if len(kws) > MAX_KEYWORDS_SHOWN:
            kw_text += f" 외 {len(kws) - MAX_KEYWORDS_SHOWN}개"
        # ★행 높이를 키우던 두 칸을 없앴다 — '댓글 예시'(통째로 들어감)와
        #   여러 줄짜리 '글 링크'. 링크는 대표 하나만 둔다.
        _검색량 = 검색량.get((product, brand), "")
        rows.append([product, brand,
                     _검색량, 판정_말(_검색량),
                     r.get("키워드수", ""),
                     r.get("최고순위", ""), r.get("평균순위", ""),
                     r.get("키워드별순위", ""),
                     total, trend, r.get("놓친", ""),
                     (r.get("글들") or [""])[0], 읽은정도] + counts)

    # ★2026-09-05 — 검색량으로 확인된 경쟁사부터 놓는다.
    #   전에는 제품군으로 묶어 놓아서, 검색량이 확인된 진짜 경쟁사와 아직 안 물어본
    #   이름이 한 덩어리로 섞여 있었다(537줄 중 134줄이 빈 칸). 사장님이 표를 열면
    #   맨 위에 **확인된 경쟁사**가 있어야 한다.
    #   순서: 판정(확인 → 확인 전 → 0) → 넓게 퍼진 것(뜬 키워드 수) → 검색량 큰 것.
    #   ★2026-09-05 사장님 "경쟁사가 카페외부에 노출되어있는 개수" — 경쟁사의 무게는
    #     우리 키워드 몇 개에 걸렸나(뜬 키워드 수)다. 검색량을 앞세우면 우리 키워드에
    #     한 번 걸린 검색량 큰 가게(다이소 283만)가 여섯 키워드에 걸린 진짜 경쟁사
    #     (아토팜 6개) 위로 온다 — 사장님이 "다 이상하다" 하신 그 모양. 개수를 앞세운다.
    def _수(v):
        try:
            return int(str(v or 0).replace(",", ""))
        except (TypeError, ValueError):
            return 0

    i판정, i검색량 = header.index("판정"), header.index("검색량")
    i키수 = header.index("뜬 키워드 수")
    rows.sort(key=lambda x: (판정_순서.get(x[i판정], 9), -_수(x[i키수]),
                             -_수(x[i검색량]), x[0], x[1]))
    return [header] + rows

# 판정을 못 받은 몫이 이만큼을 넘으면 시트를 덮지 않는다.
# 반쪽짜리 표를 어제 표 위에 덮으면, 사장님은 그게 오늘의 전부인 줄 알게 된다.
MAX_UNJUDGED_RATIO = 0.2


def should_skip_write(stat: dict) -> bool:
    """반쪽·무검증 표인가 — 그러면 시트를 덮지 않는다 · 순수함수.

    ★새 구조(2026-07-24)의 두 실패 지점을 본다(독립검토 MAJOR):
      ① AI 가 댓글 묶음을 못 읽음(429·오류) → 뽑힌 이름 자체가 반쪽
      ② 네이버가 검색을 대량 차단 → verified 가 무검증으로 다 통과
    옛 '미판정언급 비율' 은 새 구조에선 늘 0이라(뽑힌 건 전부 verdicts 에 들어감)
    아무 것도 못 막았다. 그래서 '못 읽은 묶음'·'검색 막힘' 비율로 바꾼다.
    """
    stat = stat or {}
    # ★2026-09-05 — '못 읽은 묶음' 만으로는 더 이상 막지 않는다.
    #   이것 때문에 오늘 하루 종일 442종을 확인해 놓고 시트는 어제 값이었다.
    #   대신 표에 **몇 % 읽고 만든 것인지**를 칸으로 적는다(읽은정도_말).
    #   막는 건 '뭔가 잘못된 것' 뿐이다 — 검색이 대량 차단됐거나 확정이 0이거나.
    확인 = int(stat.get("검색확인") or 0)
    if 확인 and (int(stat.get("검색막힘") or 0) / 확인) > MAX_UNJUDGED_RATIO:
        return True                         # 검색이 반 이상 막혔으면 무검증이라 덮지 않는다
    if int(stat.get("언급") or 0) and not int(stat.get("확정제품") or 0):
        return True                         # 언급은 있었는데 확정 0이면 뭔가 잘못된 것
    return False


def run_from_sheet(args) -> int:
    """시트 표시 탭(제품군)의 키워드로 돌고, 결과를 '경쟁사' 탭에 쓴다."""
    from datetime import datetime, timedelta, timezone

    from src.config import CAFE_WHITELIST, SERVICE_ACCOUNT_JSON, SPREADSHEET_ID
    from src.sheets import SheetsClient

    client = SheetsClient(SPREADSHEET_ID, SERVICE_ACCOUNT_JSON)
    meta = client.spreadsheet.fetch_sheet_metadata()
    hidden = {sh["properties"]["title"] for sh in meta.get("sheets", [])
              if sh.get("properties", {}).get("hidden")}

    crawler, fetcher = Crawler(), CommentFetcher()
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    by_product: dict = {}

    # 댓글 훑기가 이 작업의 45분이다. 판정만 실패했을 때 또 훑지 않도록 모아둔 걸 남긴다.
    if args.mentions_file and os.path.exists(args.mentions_file):
        with open(args.mentions_file, encoding="utf-8") as f:
            by_product = json.load(f)
        부족 = 모양_모자란칸(by_product)
        if 부족:
            # 조용히 반쪽으로 돌지 않는다 — 옛 모양이면 그냥 새로 긁는다.
            print(f"모아둔 댓글이 옛 모양입니다(없는 칸: {', '.join(부족)}) — "
                  f"그대로 쓰면 계정 표가 빕니다. 새로 훑습니다.")
            by_product = {}
        print(f"모아둔 댓글 재사용: {args.mentions_file} "
              f"({sum(len(v) for v in by_product.values())}건) — 다시 훑지 않습니다")

    for ws in ([] if by_product else client.spreadsheet.worksheets()):
        tab = ws.title
        if not tab.endswith("카외") or tab in hidden:
            continue                        # 숨김 탭(작업 안 하는 제품)은 제외
        product = tab.replace(" 카외", "").strip()
        values = ws.get_all_values()
        if not values or "키워드" not in values[0]:
            continue
        hdr = values[0]
        ik = hdr.index("키워드")
        iv = hdr.index("총합") if "총합" in hdr else -1

        def vol(row):
            try:
                return int(str(row[iv]).replace(",", "")) if 0 <= iv < len(row) else 0
            except ValueError:
                return 0

        rows = [r for r in values[1:] if len(r) > ik and r[ik].strip()]
        rows.sort(key=vol, reverse=True)    # 검색량 큰 키워드부터 — 경쟁이 실제로 붙는 자리
        # limit 0 = 그 제품군 키워드 전부 (사장님 2026-07-23 "전체로")
        keywords = [r[ik].strip() for r in (rows if args.limit <= 0 else rows[:args.limit])]
        print(f"[{product}] 키워드 {len(keywords)}개")

        mentions: list[dict] = []
        for kw in keywords:
            try:
                mentions.extend(scan_keyword(crawler, kw, our_links=set(),
                                             our_slugs=set(CAFE_WHITELIST),
                                             fetcher=fetcher, top_posts=args.top_posts))
            except Exception as e:          # 키워드 하나 실패가 전체를 죽이지 않는다
                print(f"   {kw} 건너뜀: {type(e).__name__}")
        by_product[product] = mentions
        # ★2026-07-30: 여기서 '제품 후보'는 셀 수 없다 — 이름은 판정 단계(extract_brands)가
        #   붙인다. 원문 mention 에 없는 '키'를 세다 매일 KeyError 로 죽었다(7/24 라이브부터
        #   6일 연속, 29분 수집을 다 마친 직후). 이 시점에 셀 수 있는 것만 센다.
        print(f"[{product}] 댓글 {len(mentions)}건 "
              f"(글 {len({m['글'] for m in mentions})}개)")

    if args.mentions_file and not os.path.exists(args.mentions_file):
        try:
            with open(args.mentions_file, "w", encoding="utf-8") as f:
                json.dump(by_product, f, ensure_ascii=False)
            print(f"모아둔 댓글 저장: {args.mentions_file}")
        except OSError as e:
            print(f"모아둔 댓글 저장 실패(계속 진행): {type(e).__name__}")

    # ★제품군별로 판정한다 — extract_brands 가 브랜드를 붙인 mention 을 돌려주므로
    #   그 결과를 confirmed_rows 에 넘겨야 한다. 원문 mention(키 없음)을 넘기면 죽는다
    #   (2026-07-24 독립검토 BLOCKING). 판정 캐시는 파일 공유라 같은 이름은 한 번만 검색한다.
    # 읽기 예산 — 한 회차가 AI 에 보낼 묶음 수 상한(제품군 셋이 나눠 쓴다).
    # 유료 보험이 있어도 한 번에 다 태우지 않고, 무료만 있어도 한도 안에서
    # 밀린 몫(캐시에 없는 옛 댓글)을 며칠에 걸쳐 소화한다.
    읽기예산 = int(os.environ.get("READ_BATCH_BUDGET", "").strip() or 0)
    남은예산 = 읽기예산 if 읽기예산 > 0 else None

    verdicts: dict = {}
    jstat = {"댓글": 0, "묶음": 0, "못읽은묶음": 0, "뽑은이름": 0, "캐시읽음": 0,
             "검색확인": 0, "검색통과": 0, "검색막힘": 0, "탈": []}
    branded: dict = {}
    for product, mentions in by_product.items():
        ms2, v, stat = extract_brands(mentions, today=today, max_batches=남은예산)
        if 남은예산 is not None:
            남은예산 = max(0, 남은예산 - int(stat.get("예산사용", 0) or 0))
        branded[product] = ms2
        verdicts.update(v)
        for k in ("댓글", "묶음", "못읽은묶음", "뽑은이름", "캐시읽음",
                  "검색확인", "검색통과", "검색막힘"):
            jstat[k] = jstat.get(k, 0) + int(stat.get(k, 0) or 0)
        jstat["탈"] = sorted(set(jstat["탈"]) | set(stat.get("탈", [])))
    all_mentions = [m for ms in branded.values() for m in ms]

    # 같은 브랜드가 여러 표기로 흩어져 있으면 정식 이름 하나로 묶는다(호출 1회).
    unified = comment_brand_llm.unify(brand_names(all_mentions, verdicts))
    if unified:
        merged = {a: r for a, r in unified.items() if a != r}
        print(f"이름 묶기: {len(merged)}개를 정식 브랜드명으로 통일"
              + (f" (예: {', '.join(list(merged)[:3])})" if merged else ""))

    out_rows: list[dict] = []
    for product, mentions in branded.items():
        for r in confirmed_rows(mentions, verdicts, unified):
            out_rows.append(시트줄_만들기(product, r))
        print(f"[{product}] 경쟁 제품 "
              f"{len([x for x in out_rows if x['제품군'] == product])}종")

    jstat["언급"] = len(all_mentions)
    jstat["확정제품"] = len(out_rows)

    # ★2026-09-04 검수 지적 #13 — 글쓴이를 어디서 몇 개나 얻었는지 재는 줄이 하나도
    #   없었다. 댓글에서 공짜로 얻는지, 글을 다시 열어야 하는지에 따라 요청 수가
    #   수천 건 갈리는데 **어느 쪽인지 알 방법이 없었다.**
    #   그리고 계정키를 못 얻으면 바이럴 계정 표가 통째로 빈다 — 그때 표가
    #   '경쟁이 없다' 처럼 보이면 안 되므로, 몇 %를 보고 있는지 숫자로 남긴다.
    글목록 = {}
    for m in (m for ms in by_product.values() for m in ms):
        글목록.setdefault(m.get("글"), m)
    글수 = len(글목록)
    키있음 = sum(1 for m in 글목록.values() if str(m.get("글쓴이키") or "").strip())
    번호있음 = sum(1 for m in 글목록.values() if str(m.get("카페번호") or "").strip())
    jstat["글수"], jstat["글쓴이키확보"], jstat["카페번호확보"] = 글수, 키있음, 번호있음
    if 글수:
        print(f"글쓴이 계정키 {키있음}/{글수}개 확보"
              f" ({키있음 * 100 // 글수}%) · 프로필 주소를 만들 수 있는 글 "
              f"{번호있음}/{글수}개")
        if 키있음 == 0:
            print("  ⚠ 계정키를 하나도 못 얻었습니다 — 바이럴 계정 표가 빕니다. "
                  "'경쟁이 없다' 가 아니라 '못 알아봤다' 입니다.")

    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개 "
          f"· 댓글 {fetcher.stat.get('댓글', 0)}건(뒷장 {fetcher.stat.get('뒷장', 0)}장 포함)")
    print(f"새 댓글 {jstat.get('댓글', 0)}건을 {jstat.get('묶음', 0)}묶음으로 읽음 "
          f"(캐시 재사용 {jstat.get('캐시읽음', 0)}건 · 못 읽은 묶음 {jstat.get('못읽은묶음', 0)}) "
          f"· AI 가 뽑은 이름 {jstat.get('뽑은이름', 0)}종 "
          f"· 검색 확인 {jstat.get('검색확인', 0)}종 중 통과 {jstat.get('검색통과', 0)}종"
          + (f" · 탈: {', '.join(jstat['탈'])}" if jstat.get("탈") else ""))
    for row in out_rows[:30]:
        print(f"  {row['제품군']:<8}{row['경쟁사'][:22]:<24}{row['횟수']:>3}회  "
              f"키워드 {row['키워드수']}개")

    # 반쪽 표는 시트를 덮지 않는다 — 오늘의 전부로 읽히면 안 된다.
    print(f"댓글 {jstat.get('댓글', 0)}건 · 못 읽은 묶음 {jstat.get('못읽은묶음', 0)}/{jstat.get('묶음', 0)}"
          f" · 검색 막힘 {jstat.get('검색막힘', 0)}/{jstat.get('검색확인', 0)}"
          f" · 확정 경쟁 제품 {jstat.get('확정제품', 0)}종")

    if should_skip_write(jstat):
        사유 = (f"못 읽은 묶음 {jstat.get('못읽은묶음', 0)}/{jstat.get('묶음', 0)} "
              f"· 검색 막힘 {jstat.get('검색막힘', 0)}/{jstat.get('검색확인', 0)} "
              f"· 확정 제품 {jstat.get('확정제품', 0)}종 · 탈: "
              + (', '.join(jstat.get('탈') or []) or '없음'))
        print(f"\n❌ {사유}. 시트는 손대지 않았습니다 — 어제 값 그대로입니다.")
        # ★왜 멈췄는지를 파일로 남긴다.
        # 알림 담당(자가치유)은 **자기 job 이 아직 도는 중**이라 GitHub 에서 자기 로그를
        # 못 받는다(2026-07-24 라이브: HTTPError → "원인: 알 수 없음"). 프로그램이 이미
        # 아는 이유를 로그에서 되읽으려다 매번 깜깜이가 됐다.
        try:
            os.makedirs('.harness', exist_ok=True)
            with open('.harness/last_skip_reason.txt', 'w', encoding='utf-8') as f:
                f.write(사유)
        except OSError as e:
            print(f'  (사유 파일 못 남김: {e})')
        return 3

    if args.write_sheet and out_rows:
        import gspread
        try:
            ws = client.spreadsheet.worksheet("경쟁사")
            prev_values = ws.get_all_values()      # 어제까지의 기록 = 시트 자신
        except gspread.exceptions.WorksheetNotFound:
            ws = client.spreadsheet.add_worksheet(title="경쟁사", rows=400, cols=26)
            prev_values = []

        payload = build_table(prev_values, out_rows, today, stat=jstat)
        ws.resize(rows=len(payload) + 20, cols=max(len(payload[0]), 12))
        blank = [""] * len(payload[0])
        ws.update("A1", payload + [list(blank) for _ in range(20)], value_input_option="RAW")
        _format_sheet(ws, payload)
        print(f"\n시트 '경쟁사' 갱신 — 경쟁사 {len(payload) - 1}종 "
              f"(날짜 {len(payload[0]) - len(FIXED_HEAD) - len(FIXED_TAIL)}일치)")

        # ★갈래 B — 계정별로 묶어 바이럴을 드러낸다(2026-09-04 사장님 프로세스).
        #   추가 크롤 0. 이미 훑은 결과를 다른 축으로 세기만 한다.
        #   ★여기서 넘어져도 경쟁사 탭은 이미 새로 써졌다 — 그런데 job 이 죽으면
        #     워크플로가 "시트 '경쟁사' 는 어제 값 그대로입니다" 라는 **거짓 문자**를
        #     보낸다(검수 지적 #16). 두 갈래는 따로 살아야 한다.
        try:
            # ★검수 지적 #1 — 원문(by_product) 을 넘긴다. all_mentions 는 이름이 뽑힌
            #   것만 남은 목록이라, 그것으로 세면 사장님 제1원칙을 어긴다.
            원문언급 = [m for ms in by_product.values() for m in ms]
            계정줄 = viral_accounts(원문언급, verdicts, unified, 이름붙은=all_mentions)
            # ★2026-09-05 사장님 물음('바이럴 계정탭이 왜 필요한데..?') 으로 바꿨다.
            #   시트 탭이 아니라 **저장소 파일**에 적는다. 이 목록은 사장님이 보실
            #   것이 아니라 집 PC 도구가 읽을 것이고(그쪽이 카페 로그인을 갖고 있다),
            #   사장님이 보시는 자리는 화면(/competitors)에 이미 있다.
            #   판정 기억·읽기 기억이 이미 같은 방식으로 저장소에 쌓인다.
            자리 = os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "data", "viral_accounts.json")
            os.makedirs(os.path.dirname(자리), exist_ok=True)
            with open(자리, "w", encoding="utf-8") as f:
                json.dump({"때": today, "계정": 계정줄}, f,
                          ensure_ascii=False, indent=1)
            못잼 = sum(1 for x in 계정줄 if x.get("이긴것을_못잼"))
            if 못잼:
                # ★조용히 0 으로 적지 않는다 — 뒤질 순서를 정하는 값이라
                #   0 이면 엉뚱한 카페부터 뒤지게 된다(2026-09-05 실물).
                print(f"⚠ '우리를 이긴 키워드' 를 못 잰 계정 {못잼}/{len(계정줄)}개 — "
                      f"모아둔 댓글에 그 칸이 없습니다. 다시 훑어야(reuse 없이) 채워집니다.")
            못묶음 = (계정줄[0].get("못묶은언급") if 계정줄 else 0) or 0
            print(f"바이럴 계정 {len(계정줄)}개를 data/viral_accounts.json 에 적음"
                  + (f" (계정을 못 알아본 언급 {못묶음}건은 뺐습니다)" if 못묶음 else ""))
        except Exception as e:
            print(f"바이럴 계정 못 적음({type(e).__name__}) — "
                  f"경쟁사 탭은 위에서 이미 새로 썼습니다")

        # ★로그인 없는 키워드 후보(2026-09-05) — 남의 글 제목에서 우리한테 없는
        #   것만 '키워드후보' 탭에 더한다. 경쟁사 탭 쓰기와 별개로 산다.
        # ★제목→검색 키워드 판정(LLM)을 붙였다(2026-09-06). 다만 **기본은 아직 꺼둔다** —
        #   로컬엔 LLM 열쇠가 없어 실제 판정 품질을 눈으로 못 봤고, 켠 채로 돌리면
        #   기존 잡음 416줄과 섞여 구별이 안 된다. 순서: 잡음 삭제 → 작은 회차로 실제
        #   판정 미리보기(WRITE_TITLE_CANDIDATES=1) → 사장님 눈에 깨끗하면 기본 켜짐으로.
        #   켜기: WRITE_TITLE_CANDIDATES=1. (품질이 자동화보다 먼저 — 의도 앵커)
        if os.environ.get("WRITE_TITLE_CANDIDATES") == "1":
            try:
                _후보탭_갱신(client, by_product, today)
            except Exception as e:
                print(f"키워드후보 못 적음({type(e).__name__}) — "
                      f"경쟁사 탭은 위에서 이미 새로 썼습니다")
        else:
            print("키워드후보: 제목 경로는 아직 꺼져 있습니다(실제 판정 미리보기 뒤 켬) "
                  "— 켜기: WRITE_TITLE_CANDIDATES=1")
    return 0


def _format_sheet(ws, payload: list) -> None:
    """보기 좋게 — 머리줄 고정·굵게, 숫자 가운데, 글 링크 줄바꿈. 실패해도 값은 이미 들어갔다."""
    n_dates = len(payload[0]) - len(FIXED_HEAD) - len(FIXED_TAIL)
    # C열~날짜 끝 + 꼬리에서 이어지는 숫자 3칸
    # (우리가 놓친·최고순위·평균순위). 그 뒤 '키워드별 순위' 는 글이다.
    # ★+3 은 FIXED_TAIL 에 칸 3개가 있던 시절 값이다. 그 꼬리를 비운 뒤로
    #   시작 칸이 끝 칸보다 커져 **서식이 매번 통째로 취소**되고 있었다
    #   (머리줄 고정·굵게·줄바꿈·폭 맞추기 전부. 2026-09-05 검수 중간 6).
    num_from, num_to = 2, min(len(FIXED_HEAD) + n_dates, len(payload[0]))
    try:
        sid = ws.id
        ws.spreadsheet.batch_update({"requests": [
            {"updateSheetProperties": {                   # 머리줄 고정
                "properties": {"sheetId": sid,
                               "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            {"repeatCell": {                              # 머리줄 굵게 + 배경
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": .93, "green": .95, "blue": .98},
                    "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)"}},
            {"repeatCell": {                              # 숫자칸 가운데 정렬
                "range": {"sheetId": sid, "startRowIndex": 1,
                          "startColumnIndex": num_from, "endColumnIndex": num_to},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment"}},
            {"repeatCell": {                              # 키워드·링크·예시는 줄바꿈해서 보이게
                "range": {"sheetId": sid, "startRowIndex": 1,
                          "startColumnIndex": num_to, "endColumnIndex": len(payload[0])},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP",
                                               "verticalAlignment": "TOP"}},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}},
            {"autoResizeDimensions": {                    # 꼬리 칸까지 폭을 맞춘다
                "dimensions": {"sheetId": sid, "dimension": "COLUMNS",
                               "startIndex": 0, "endIndex": len(payload[0])}}},
        ]})
    except Exception as e:                                # 서식은 곁다리 — 값이 먼저다
        print(f"서식 적용 건너뜀: {type(e).__name__}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="")
    ap.add_argument("--product", default="")
    ap.add_argument("--top-posts", type=int, default=4, help="키워드당 볼 남의 글 수")
    ap.add_argument("--out", default="")
    ap.add_argument("--from-sheet", action="store_true", help="시트 표시 탭의 키워드를 쓴다")
    ap.add_argument("--limit", type=int, default=25, help="제품군마다 볼 키워드 수")
    ap.add_argument("--write-sheet", action="store_true", help="'경쟁사' 탭에 결과를 쓴다")
    ap.add_argument("--mentions-file", default="",
                    help="모아둔 댓글을 여기 저장·재사용 (판정만 다시 할 때 45분 아낀다)")
    args = ap.parse_args()

    if args.from_sheet:
        return run_from_sheet(args)

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        print("키워드를 주세요 (--keywords 비듬샴푸,지루성두피샴푸)")
        return 2

    from src.config import CAFE_WHITELIST

    crawler = Crawler()
    fetcher = CommentFetcher()
    all_mentions: list[dict] = []
    for kw in keywords:
        found = scan_keyword(crawler, kw, our_links=set(), our_slugs=set(CAFE_WHITELIST),
                             fetcher=fetcher, top_posts=args.top_posts)
        all_mentions.extend(found)
        print(f"  {kw}: 제품 언급 {len(found)}건")

    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    all_mentions, verdicts, jstat = extract_brands(all_mentions, today=today)
    rows = confirmed_rows(all_mentions, verdicts,
                          comment_brand_llm.unify(brand_names(all_mentions, verdicts)))
    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개")
    print(f"AI 가 뽑은 이름 {jstat.get('뽑은이름', 0)}종 · 검색 통과 {jstat.get('검색통과', 0)}종"
          f"{' (못 읽은 묶음 있음)' if jstat.get('못읽은묶음') else ''}")
    print(f"{'제품':<22}{'종류':<8}{'횟수':>4}")
    for r in rows[:25]:
        print(f"{r['제품'][:20]:<22}{r['종류']:<8}{r['횟수']:>4}")

    if args.out:
        payload = {"product": args.product, "keywords": keywords,
                   "stat": fetcher.stat, "rows": rows, "mentions": all_mentions}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print("\n저장:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
