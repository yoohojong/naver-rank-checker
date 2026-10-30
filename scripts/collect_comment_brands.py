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
                               strip_generic_tail, tally, 이름_다듬기)
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
        # ★2026-10-21 — v3 글 주소가 9/23부터 500(9999)만 돌려줘 글쓴이를 하나도 못 얻었다
        #   (실패하면 빈 값이라 조용했다). v2.1 은 nick·memberKey 가 그대로 온다(art 열쇠로
        #   회원 전용 카페도 열림 — cantsb 실측). v3 '댓글' 주소는 지금도 정상이라 그대로 둔다.
        w = self._글쓴이_원자료(url, m, club)
        if w is None:
            return {}
        return {"닉": str(w.get("nick") or w.get("nickName") or "").strip(),
                "키": str(w.get("memberKey") or "").strip(),
                "카페번호": str(club)}

    def _글쓴이_원자료(self, url: str, m, club: str):
        """v2.1 글 주소의 writer 칸 그대로. 못 받으면 None."""
        tok = _ART_TOKEN.search(url)
        api = (f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{club}"
               f"/articles/{m.group(2)}?useCafeId=true&requestFrom=A"
               + (f"&art={tok.group(1)}" if tok else ""))
        try:
            r = self.s.get(api, headers={"Referer": url}, timeout=25)
            if r.status_code != 200:
                return None
            res = r.json().get("result", {})
        except Exception:
            return None
        w = ((res.get("article") or res) or {}).get("writer")
        return w if isinstance(w, dict) else {}

    def 회원여부(self, url: str) -> str:
        """그 글을 쓴 사람이 지금 그 카페 회원인가 → '회원' / '탈퇴' / ''(확인 못 함).

        ★2026-10-24 사장님: "탈퇴멤버면 글 삭제 요청해야하고 탈퇴 아닌 멤버는 신고해야함"
          → 기준은 writer.isCafeMember(거짓 = 탈퇴 · 사장님 확정 "탈퇴임").
          실측(계정 40개 첫 글): 회원 21 · 회원 아님 4 · 401(로그인 필요한 카페) 15.
          못 연 글 · 칸이 없는 글은 '확인 못 함' — 지어내지 않는다.
        """
        m = _CAFE_URL.search(url or "")
        if not m:
            return ""
        처음 = m.group(1) not in self._club
        club = self._club_id(url, m.group(1))
        if not club:
            return ""
        if 처음:
            time.sleep(0.5)          # 카페번호를 방금 물었다 — 바로 또 묻지 않는다
        v = (self._글쓴이_원자료(url, m, club) or {}).get("isCafeMember")
        if v is True:
            return "회원"
        if v is False:
            return "탈퇴"
        return ""

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
    ★여기 적히는 '제품군' 은 **그 제목을 어느 탭에서 주웠나** 다(경쟁사 표와 달리 그대로 둔다).
      키워드가 실제로 어느 제품 이야기인지는 집 PC 가 매일 한 번
      `cafe-external/키워드후보_제품군.py` 로 키워드 글자를 보고 다시 판정한다.
      여기서 억지로 정하면 근거(키워드 글자)를 못 보고 탭 이름만 베끼게 된다.
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
                if not n or n in 이미후보 or n in 본것:
                    continue
                # ★사장님 2026-09-07 "그거 다 지금 우리 키워드에 포함되어있잖아":
                #   후보가 우리 키워드 **안에 들어가면**(= 더 구체적인 걸 이미 가짐) 뺀다.
                #   예: '아토피샴푸' 는 우리 '아토피샴푸추천' 에 포함 → 새것 아님.
                #   방향은 하나 — 후보 ⊆ 우리 것. 반대(우리 것 ⊆ 후보)는 더 구체적인 새
                #   후보라 남긴다(예: '탈모샴푸추천' 은 우리 '샴푸추천' 을 품어도 새것).
                if n in 이미가진 or any(n in o for o in 이미가진):
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
                   max_batches: int | None = None,
                   깎음언급: list | None = None) -> tuple:
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
    캐시깎음: dict = {}
    캐시종류: dict = {}                     # 2026-10-25 — 깎은 종류(약 · 병원 · 시술 · 제품 종류)
    안읽은: list = []                       # [(원문들 index, 원문)] — 처음 보는 댓글
    다시읽을: list = []                     # 깎음 칸이 생기기 전에 읽은 옛 항목(이름 있는 것만)
    for i, t in enumerate(원문들):
        기억 = comment_reads.get_full(reads, t)
        if 기억 is None:
            안읽은.append((i, t))
            continue
        # ★옛 항목은 다시 읽기 전까지 옛 이름을 그대로 쓴다 — 예산이 모자라 못 다시 읽은
        #   날 경쟁사 표가 갑자기 비지 않게. 다시 읽으면 아래에서 새 결과가 덮는다.
        if 기억["이름"]:
            캐시뽑힘[i] = 기억["이름"]
        if 기억["깎음"]:
            캐시깎음[i] = 기억["깎음"]
        종 = comment_reads.get_종류(reads, t)
        if 종:
            캐시종류[i] = 종
        if comment_reads.needs_reread(기억):
            다시읽을.append((i, t))
        comment_reads.touch(reads, t, today)   # 오늘도 보였다 — 청소에서 살린다

    # 처음 보는 댓글을 먼저 보낸다 — 회차 예산이 모자라면 다시 읽기가 밀리고 새 댓글은 안 밀린다.
    보낼 = 안읽은 + 다시읽을
    새뽑힘, stat = brand_from_comments.read_all(
        [t for _, t in 보낼], max_batches=max_batches)
    읽은자리 = stat.pop("읽은자리", set())
    답한자리 = stat.pop("답한자리", None)       # 없으면(옛 모양) 읽은 자리 전부를 답한 것으로
    새깎음 = stat.pop("깎음", None) or {}
    새종류 = stat.pop("종류", None) or {}    # '종류' 칸이 온 자리만 들어 있다(빈 목록 포함)
    # ★GPT 검토 10-24: 다시 읽은 옛 항목인데 AI 답에서 그 줄이 빠졌으면 읽은 것이 아니다 —
    #   옛 이름을 빈 결과로 덮지 않고 다음 회차에 다시 읽는다(처음 보는 댓글은 지금처럼 둔다).
    if 답한자리 is not None:
        읽은자리 = {j for j in 읽은자리 if j < len(안읽은) or j in 답한자리}
    뽑힘 = dict(캐시뽑힘)
    깎힘 = dict(캐시깎음)
    종힘 = dict(캐시종류)
    for j in 읽은자리:                      # 성공한 자리만 남긴다(빈 결과 포함) — 실패는 내일 다시
        i, t = 보낼[j]
        뽑힘.pop(i, None)
        깎힘.pop(i, None)
        종힘.pop(i, None)
        if 새뽑힘.get(j):
            뽑힘[i] = 새뽑힘[j]
        if 새깎음.get(j):
            깎힘[i] = 새깎음[j]
        if 새종류.get(j):
            종힘[i] = 새종류[j]
        # 종류 칸이 안 온 자리는 None 으로 남긴다 — '봤는데 없음'([])과 섞지 않는다.
        comment_reads.put(reads, t, 새뽑힘.get(j) or [], today, 깎음=새깎음.get(j) or [],
                          종류=새종류.get(j) if j in 새종류 else None)
    for j, names in (새뽑힘 or {}).items():   # 읽은자리를 안 싣는 옛 모양 통계도 받는다
        if j not in 읽은자리:
            뽑힘[보낼[j][0]] = names
    # '일부만 셈' 재료(2026-10-25) — 오늘 본 댓글 중 '종류' 칸을 아직 못 본 것.
    #   종류 칸 하나 때문에 옛 댓글을 다시 읽지는 않는다(다시 읽기 속도는 그대로 · 카드 범위).
    stat["종류칸없음"] = sum(1 for t in 원문들 if comment_reads.get_종류(reads, t) is None)
    comment_reads.save(comment_reads.prune(reads, today), reads_path)
    stat["캐시읽음"] = len(원문들) - len(안읽은)
    stat["다시읽기대상"] = len(다시읽을)
    stat["다시읽음"] = len([j for j in 읽은자리 if j >= len(안읽은)])

    이름들 = sorted({n for names in list(뽑힘.values()) + list(깎힘.values()) for n in names})
    stat["뽑은이름"] = len({n for names in 뽑힘.values() for n in names})  # 캐시로 되살린 이름까지

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
    # ★깎은 이름은 out 에 넣지 않는다 — 경쟁사 표·계정의 '미는제품'은 out 만 센다.
    #   (2026-10-24 사장님 "아니 경쟁사 말한거임 경쟁사" — 깎으려고 꺼낸 대안 제품은 경쟁사가 아니다)
    #   부르는 쪽이 `깎음언급` 에 목록을 주면 같은 모양({**m, 표시, 키, 종류="깎음"})으로 채운다.
    out: list = []
    for m in mentions or []:
        t = str(m.get("댓글") or "").strip()
        i = 자리.get(t)
        for name in (뽑힘.get(i) or []) if i is not None else []:
            out.append({**m, "표시": name, "키": name, "종류": "제품"})
        if 깎음언급 is not None and i is not None:
            for name in 깎힘.get(i) or []:
                깎음언급.append({**m, "표시": name, "키": name, "종류": "깎음"})
            # 깎은 종류(상표 아님) — 제품 판정 · 검색 확인을 거치지 않는다(이름들에 안 넣음).
            for name in 종힘.get(i) or []:
                깎음언급.append({**m, "표시": name, "키": name, "종류": "깎은종류"})
    stat["언급"] = len(out)
    stat["깎음언급"] = sum(len(v) for v in 깎힘.values())
    stat["종류언급"] = sum(len(v) for v in 종힘.values())
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


def 표시할_브랜드명(m: dict, verdicts: dict, unified: dict | None = None) -> str | None:
    """언급 하나 → 표에 적을 최종 브랜드 이름. 표에 못 넣을 언급이면 None · 순수함수.

    판정 → 정식 이름 → 이름 묶기 → 마지막 그물(종류 이름·장소·성분) 순서로 거른다.

    ★이 자리를 함수로 뺀 이유: 오늘 언급을 세는 쪽(confirmed_rows)과 제품군을 옮기는
      쪽(제품군_재배치)이 **같은 이름**을 봐야 한다. 두 곳에 같은 코드를 적어 두면
      한쪽만 고쳐져 옮긴 줄과 센 줄이 어긋난다(같은 뿌리 사고를 여러 번 겪었다).
    """
    key = m["키"]
    if not brand_verdicts.is_product(verdicts, key):
        return None
    name = brand_verdicts.display_name(verdicts, key, m["표시"])
    name = (unified or {}).get(name, name)   # 흐트러뜨린 표기를 정식 브랜드명 하나로
    if not is_real_brand(name):        # 마지막 그물 — 종류 이름·장소가 판정을 뚫어도 여기서 막는다
        return None
    # ★2026-10-24 — 판정이 되살린 이름에 점·띄어쓰기가 남아('클모.엔') 그대로 표에 올랐다.
    return 이름_다듬기(name) or name


def confirmed_rows(mentions: list, verdicts: dict, unified: dict | None = None) -> list:
    """판정된 제품만 남겨 집계. 미판정·제품아님은 조용히 뺀다.

    묶음은 **판정된 브랜드명** 으로 다시 한다 — '맥단' 과 '맥단탈모샴푸' 는 한 줄(맥단비)이다.
    우리 제품을 빼는 것도 이 이름으로 봐야 새는 곳이 없다.
    """
    kept = []
    for m in mentions or []:
        name = 표시할_브랜드명(m, verdicts, unified)
        if name is None:
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
            "_언급": [], "_글": [], "_제품": [], "_제품열쇠": set()})
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
        if not 이름 or not is_real_brand(이름):
            continue
        # ★경쟁사 표(confirmed_rows)와 **같은 이름 · 같은 열쇠**로 묶는다(2026-10-24).
        #   전에는 글자 그대로 견줘서 '라보 h' 와 '라보H', '클모.엔' 이 따로 남았다.
        이름 = 이름_다듬기(이름) or 이름
        열쇠 = strip_generic_tail(이름) or normalize_name(이름)
        if 열쇠 not in a["_제품열쇠"]:
            a["_제품열쇠"].add(열쇠)
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
            # 2026-10-24 사장님 "바이럴 계정은 아예 그 프로필 링크까지 연결해줘봐"
            "프로필": 프로필주소(a["카페번호"], a["계정키"]),
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


# ── 깎인 대상(시장 조사 때 '대안이 무엇이 있나') ──────────────────────────────────
# ★2026-10-25 사장님: "경쟁사 댓글은 그떄분이라고하는건 자기 제품 바이럴 하기 위해서 상징적인 제품들을
#   일부로 이용하는거에요 나중에 시장 조사할떄 대안이 무엇이 있나를 찾아봐야할떄 활용하는거는 무조건
#   필요해요" — 써 봤는데 그때뿐 · 효과 없다 · 부작용으로 깎아 넘기게 한 대상이면 **상표든 종류든**
#   모으고, 그 글이 경쟁 글 / 우리 글 / 바이럴 아님(같은 글에서 민 제품 없음) 중 어디인지 가른다.
# 종류 갈래 글자 무늬 — 새로 만들지 않고 이미 쓰던 것에서 가져왔다(순서대로 본다).
#   약·연고 = team project/cafe-external/_극단_묶기.py:17 '약·연고 실패' + NOT_A_BRAND 의 '약국'
#   시술    = 같은 파일 :19 '돈 낭비' 의 '스케일링'
#   병원    = 같은 파일 :16 '병원 순례' 의 낱말(대학병원 · 상급병원 · 피부과 · 병원 · 한의원 · 응급실)
#   그 밖   = 제품 종류(약산성샴푸 · 보습 샴푸 — 경쟁사_안티트로_설득구조_분석.md:165 '대안 제거' 의 '보습')
깎은종류_갈래 = (
    ("약·연고", re.compile(r"스테로이드|연고|처방|약용샴푸|항생제|먹는\s*약|바르는\s*약|리바운드|약국")),
    ("시술", re.compile(r"스케일링")),
    ("병원", re.compile(r"대학병원|상급병원|피부과|병원|한의원|응급실")),
)
깎은종류_그밖 = "제품 종류"
예시댓글_길이 = 120

# ── 깎음 근거 확인(2026-10-26) ─────────────────────────────────────────────────
# ★품질 1차 반려(중요 1): 긍정 후기(썬플라워 · 글루타셀 · 댄드러프 · 아베다)가 '깎인제품'으로 확정됐다.
#   원인 = 이 묶음이 AI 읽기의 '깎음' 표시(읽기 기억 data/comment_reads.json + 새 읽기)를 원문 확인 없이
#   믿었다. 기억에는 AI 가 좋게 말한 대상도 '깎음'으로 들어가 있다(같은 재료의 니조랄 댓글 70개에
#   '니조랄이 정답' · '사서 샴푸하면 싹 낫습니다' 도 섞여 있다). 기억은 다시 판정하지 않으므로(카드 범위)
#   출력 한 곳 — 깎인제품_집계 — 에 문지기를 둔다. 옛 기억과 새 읽기 · 상표와 종류에 같은 문지기가 걸린다.
#   예전 _깎는말 은 예시를 '먼저 고르기'에만 썼지 확정 조건이 아니었다(그 낱말은 아래 갈래에 들어갔다).
# 세 갈래 = 판정기 지시문 7 · 8번의 정의(그때뿐 · 효과 없음 · 부작용) — 새 기준을 만들지 않았다.
# ★틀리는 쪽을 정했다: 근거를 못 찾은 댓글은 지우지 않고 '깎인제품_확인필요'로 간다. 그래서 무늬는
#   '좋은 말을 깎음으로 잡지 않는 것'을 먼저 지키고, 놓친 깎음은 확인필요 칸에서 사람이 본다.
깎는말_갈래 = (
    ("그때뿐", re.compile(
        r"그\s*때\s*뿐|일시\s*적|일시저|임시\s*방편|반짝\s*(?:효과|하고|했|일\s*뿐|뿐)|"
        r"잠깐\s*(?:만|은|뿐|괜찮다|괜찮았|좋다|좋았|효과|잠잠|나아)|"
        r"(?:쓸|바를|받을|먹을)\s*때만\s*(?:\S{0,6}\s*)?(?:잠잠|괜찮|좋|시원|낫|효과|반짝|들)|"
        r"(?:다시|또|도로)\s*(?:올라와|올라오|올라왔|제자리|생기|생겨|생겼|심해|번지|번져|재발)|금방\s*다시|"
        r"(?:또|다시|자꾸|계속)\s*재발|재발\s*(?:했|해요|하더|되더|돼서|됐)|(?:계속|자꾸)\s*반복|"
        r"반복\s*(?:돼|되|됐)|만성\s*(?:으로|이\s*되|화)|리바운드|반동|내성|"
        r"끊으면\s*(?:다시|또|바로|금방|도로)|안\s*쓰면\s*(?:또|다시|바로)|단기\s*(?:증상|효과)만|표면만|"
        r"효과\s*뿐|오래\s*(?:못|안)\s*가")),
    ("효과없음", re.compile(
        r"효과\S{0,3}\s*(?:없|못|모르|별로|글쎄|미미|애매|크게\s*있진\s*않)|"
        r"(?:효과|완화|진정|세정)\S{0,2}\s*약하|별\s*효과|별\s*차이\s*없|차이\s*(?:가\s*)?없|거기서\s*거기|"
        r"소용\s*(?:이\s*)?없|의미\s*(?:가\s*)?없|턱도\s*없|돈만\s*버리|돈\s*(?:낭비|아깝)|(?:안|못)\s*잡히|"
        r"해결\s*(?:이\s*)?(?:안|못)|나아지(?:지|질|는\s*게)\s*(?:않|없)|안\s*나아|좋아지지\s*(?:않|도)|"
        r"줄지는\s*않|가라앉지\s*않|전혀\s*(?:효과|해결|소용|안\s*(?:잡|나아|낫|들))|실패|비추|최악|실망|애매|"
        r"기대\s*이하|재구매\s*(?:는\s*)?안|재구매\s*의사\s*(?:가\s*)?없|안\s*좋(?:았|아|더)|"
        r"별로(?:였|예|에요|이었|더라|네|라서|임|ㅠ|ㅜ|\s*효과|\s*$|[.!])|별루|"
        r"다\s*(?:써|해)\s*(?:봤|봐|본)\S*도|웬만한\S*\s*(?:\S+\s*)?다\s*(?:써|해)\s*(?:봤|봐|본)|다시는\s*안|절대\s*(?:안\s*(?:써|쓰|씁|사|삽)|쓰지|사지|비추|하지\s*마)|"
        r"중단|그만\s*(?:두|썼|쓰)|쓰다\s*(?:가\s*)?말았|사용\s*(?:을\s*)?(?:멈|중단)|끊었|끊어|끊으시|끊을")),
    ("부작용", re.compile(
        r"(?<![저무])자극|부작용|따갑|따가[워웠]|따끔|뒤집어[지진졌짐]|"
        r"(?:더|오히려|증상\S{0,2})\s*(?:심해|많아|번지|번져|나빠|악화|민감|건조|가려|빠지|빠져)|악화|"
        r"가려워[지졌짐]|(?:두피|피부|머리|모발)\S{0,2}\s*(?:가\s*)?건조해[지져]|건조해지는\s*느낌|"
        r"속당김|뻑뻑|뻣뻣|엉켜|엉킴|푸석|개털|찝찝|독하|독한|락스|"
        r"냄새\S{0,2}\s*(?:도\s*)?(?:너무\s*)?(?:독|별로|이상|역하|심하|싫|불호)|냄새\S{0,2}\s*(?:도\s*)?너무\s*(?:\.{2,}|…|ㅠ|ㅜ|$)|"
        r"(?:붉은기|열감|뾰루지)\S{0,4}\s*(?:(?![안않덜])\S+\s*)?"
        r"(?:올라와(?!\s*있)|올라오더|올라왔|돋더|돋았|돋고|생겼|생기더|생겨서)|"
        r"안\s*맞|맞지\s*(?:가\s*)?않|(?:머리|모발|머리카락|머리털)\S{0,2}\s*(?:(?![덜안])\S+\s*)?"
        r"(?:빠져서|빠지다가|빠지더|빠졌어|빠지기\s*시작)|움큼|거품\S{0,2}\s*(?:도\s*)?(?:잘\s*)?안\s*나")),
)
깎은갈래_이름 = tuple(g for g, _ in 깎는말_갈래)
깎음창_길이 = 80                      # 대상 자리 뒤로 볼 글자 수(같은 문장 · 다음 이름 앞까지)
# 깎는 말 바로 뒤가 부정이면 근거가 아니다 — '부작용은 없는듯' · '자극 없이' · '내성 안 생겨요' · '독하지 않'
_부정 = re.compile(r"\S{0,3}\s*(?:걱정\s*)?(?:전혀|별로|크게|하나도|거의|딱히|그닥|그다지)?\s*"
                   r"(?:없|않|덜|아니|아닌|적(?:어|었|고|은|더|당)|못\s*느|안\s*(?:느껴|생|나|올|일|해|하))")
# 깎는 말 바로 앞이 부정이면 근거가 아니다 — '안 따가워요' · '덜 뻑뻑'
_앞_부정 = re.compile(r"(?:안|덜|노)\s*$")
# 견준 자리 — '니조랄 보다 훨씬 등급 센 스테로이드' 처럼 그 대상은 잣대일 뿐 깎이는 쪽이 아니다.
_견줌 = re.compile(r"\s*(?:샴푸|크림|로션|바디워시|제품|연고)?\s*보다(?!가)")
# 문장 끝 — 느낌표 · 물음표 · 줄바꿈 · 물결 · 띄어쓰기 앞의 마침표, 맺는 말(…요 · …죠 · …네 · …다) 뒤의
#   띄어쓰기 · ㅠㅠ · 말줄임('…다' 는 '했다 · 습니다' 같은 맺음만 — '쓰다 말았' 은 안 끊음), 음슴체(…함 · …음 · …임) 뒤의 ㅋㅋ · 마침표. '진짜.. 자극' 처럼 맺지 않은 말
#   뒤의 말줄임은 문장 끝이 아니다.
_문장끝 = re.compile(r"(?:(?<=[가-힣][요죠네])|(?<=니다|었다|았다|였다|했다|된다|한다|이다|는다))"
                    r"(?:\s*[ㅠㅜㅋㅎ;.…?!~]+\s*|\s+)|"
                    r"(?<=[가-힣][함음임됨짐])\s*[ㅠㅜㅋㅎ;.…?!~]+\s*|"
                    r"[!?？\n\r~]+|(?<!\.)\.(?!\.)(?=\s|$)")
_이어짐 = re.compile(r"[\sㅠㅜㅋㅎ.;~!]*(?:근데|그런데|하지만|그치만|그렇지만|다만|그래도|헌데|그러나)")
_물음어미 = re.compile(r"(?:나요|까요|가요|을까|를까|는지|던가|려나|셨나|셔요|세요|인가|건가|나여|까여|니|냐|죠|나|까)"
                     r"\s*[.…~ㅠㅜ]*\s*$")
_물음어미_강 = re.compile(r"(?:나요|까요|을까요|는지요|던가요|려나요|셨나요|인가요|건가요)\s*[.…~ㅠㅜ]*\s*$")
_물음_이음 = re.compile(r"(?:데|지만|고|서|며|면)\s")
# 남의 것으로 넘어가는 자리 — 그 뒤 깎는 말은 이 대상 것이 아니다('… 다른 샴푸는 자극이').
_다른것 = re.compile(r"다른\s*\S{0,4}?(?:샴푸|제품|거|건|것|약|병원|크림|브랜드)|반면|나머지")
# 좋게 말한 자리 — 두 이름 사이에 이 말이 있으면 둘을 한 목록으로 보지 않는다('니조랄은 좋았고 헤드앤숄더는 최악')
_좋은말 = re.compile(r"좋았|좋아요|좋더|좋네|좋음|좋구|좋고|좋죠|나았|낫더|낫습|나아졌|괜찮았|괜찮아요|괜찮더|정착|"
                    r"추천(?:해요|합니다|이요|드려)|효과\s*(?:가\s*)?(?:좋|봤|있었)|만족|잘\s*맞|사라졌|진정(?:되|돼)")
# 대상 바로 앞에서 꾸미는 깎는 말 — '그때뿐인 니조랄' · '효과 없던 니조랄' · '자극 강한 헤드앤숄더'
_앞_꾸밈 = re.compile(r"(?:그\s*때\s*뿐인|효과\s*(?:없|못\s*본|없었)[던는은]?|자극\S{0,2}\s*(?:강|센|심)한|"
                     r"최악인|별로인|안\s*맞(?:는|던|았던))\s*$")
_이름글자 = re.compile(r"[가-힣a-zA-Z0-9]")
_빠진까닭_말 = {"원문없음": "원문 없음", "이름자리없음": "원문에서 이름을 못 찾음", "깎는말없음": "깎는 말 없음",
             "물음만": "물어본 말뿐", "견줌만": "견준 말뿐"}


def _이름_자리(text: str, name: str) -> list:
    """원문에서 이름이 나온 자리들 [(시작, 끝)] · 순수함수.

    띄어쓰기 · 점 · 흐트러뜨림('안ㅌ티트로')은 건너뛰고 찾는다. 통째로 없으면 가장 긴 공통 조각
    (2글자 이상 · 이름의 40% 이상)으로 찾는다 — AI 가 되살린 이름('헤드앤숄더' ← 원문 '헤드엔숄더').
    """
    t = str(text or "")
    자리표 = [i for i, ch in enumerate(t) if _이름글자.match(ch)]
    납작 = "".join(t[i].lower() for i in 자리표)
    열쇠 = "".join(ch.lower() for ch in str(name or "") if _이름글자.match(ch))
    if len(열쇠) < 2 or not 납작:
        return []
    가장짧게 = max(2, -(-len(열쇠) * 2 // 5))
    for L in range(len(열쇠), 가장짧게 - 1, -1):
        찾음 = set()
        for 앞 in range(len(열쇠) - L + 1):
            j = 납작.find(열쇠[앞:앞 + L])
            while j != -1:
                s = max(0, j - 앞)
                e = min(len(납작), j - 앞 + len(열쇠))
                찾음.add((자리표[s], 자리표[e - 1] + 1))
                j = 납작.find(열쇠[앞:앞 + L], j + 1)
        if 찾음:
            return sorted(찾음)
    return []


def _물음인가(조각: str, 끝말: str) -> bool:
    """문장 하나가 물음인가 — 물음표 + 묻는 끝말, 또는 물음표 없이도 확실한 묻는 끝말('…있나요')."""
    s = 조각.rstrip()
    if "?" in 끝말 or "？" in 끝말:
        return bool(_물음어미.search(s))
    return bool(_물음어미_강.search(s))


def _판단_조각(t: str, s: int, e: int, 민자리: list, 곁자리: list, 같은자리: list) -> list:
    """대상 자리 (s, e) → 깎는 말을 찾아볼 조각들 [(시작, 끝, 물음)] · 순수함수.

    벽(넘지 않음) = 같은 댓글이 민 제품 · 사이에 좋은 말이 낀 다른 깎인 대상 ·
    같은 이름이 다시 나온 자리 · '다른 샴푸는' 같은 넘어감. 그 안에서 문장 단위로 본다(문장마다 80자):
    ① 대상이 든 문장 ② '근데 …' 로 이어지면 다음 문장 ③ 물은 문장이면 다음 한 문장('…안하셔요..?
    머리결 너무 뻑뻑해지네요') ④ 대상 문장에 좋은 말도 깎는 말도 없으면 다음 한 문장('처음 써보고
    놀랐어요 냄새도 너무 독하고').
    """
    벽 = len(t)
    for p in 민자리:
        if e <= p < 벽:
            벽 = p
            break
    for p in 곁자리:
        # 다른 깎인 대상은 사이에 좋은 말이 있을 때만 벽이다 — '니조랄은 좋았고 헤드앤숄더는 최악' 은 끊고,
        #   '니조랄 샴푸, 연고, 스테로이드 처방도 받아봤지만 그때뿐' 처럼 한 목록으로 깎은 것은 넘는다.
        if e <= p < 벽 and _좋은말.search(t, e, p):
            벽 = p
            break
    for p in 같은자리:
        if e < p < 벽:
            벽 = p
            break
    m = _다른것.search(t, e, 벽)
    if m:
        벽 = m.start()
    조각: list = []
    시작 = pos = 창 = e
    덧붙임 = 0
    while 시작 < 벽:
        끝 = min(벽, 창 + 깎음창_길이)
        m = _문장끝.search(t, pos, 끝)
        if m and _이어짐.match(t, m.end()) and m.end() - 시작 < 깎음창_길이 * 2:
            pos = 창 = m.end()             # '…괜찮았어요. 근데 …' — 이어진 문장도 80자를 새로 준다
            continue
        조각끝 = m.start() if m else 끝
        물음 = _물음인가(t[시작:조각끝], m.group(0) if m else "")
        조각.append((시작, 조각끝, 물음))
        if not m or 덧붙임:
            break
        좋음 = bool(_좋은말.search(t, 시작, 조각끝))
        깎음 = bool(_깎는말_찾기(t[시작:조각끝], 물음))
        if 물음 or (len(조각) == 1 and not 좋음 and not 깎음):
            덧붙임 = 1
            시작 = pos = 창 = m.end()
            continue
        break
    return 조각


def _깎는말_찾기(창: str, 물음: bool) -> list:
    """판단 창 → 그 안의 깎는 말 갈래들(부정 · 물음 안의 말은 뺀다) · 순수함수."""
    got = []
    for 갈래, rx in 깎는말_갈래:
        for m in rx.finditer(창):
            if _부정.match(창, m.end()) or _앞_부정.search(창, max(0, m.start() - 3), m.start()):
                continue
            if 물음 and not _물음_이음.search(창, m.end()):
                continue                    # '니조랄 효과 없나요?' — 물은 것이지 깎은 것이 아니다
            got.append(갈래)
            break
    return got


def 깎음_근거(text, name: str, 민이름들=(), 곁이름들=()) -> tuple:
    """댓글 원문에서 이 대상을 깎는 말을 찾는다 → (갈래 목록, 까닭) · 순수함수.

    갈래 목록이 비지 않으면 근거 있음(까닭 ''). 비면 까닭 = '원문없음' / '이름자리없음' /
    '깎는말없음' / '물음만' / '견줌만'.
    민이름들 = 같은 댓글에서 AI 가 '제품'(민 것)으로 읽은 이름 — 그 앞에서 끊는다.
    곁이름들 = 같은 댓글의 다른 깎인 대상 — 한 목록으로 이어지지 않았으면 그 앞에서 끊는다.
    """
    t = str(text or "")
    if not t.strip():
        return [], "원문없음"
    자리 = _이름_자리(t, name)
    if not 자리:
        return [], "이름자리없음"

    def 자리들(names):
        return sorted({p for n in names or () if str(n or "").strip() and n != name
                       for p, _ in _이름_자리(t, n)})
    민자리 = 자리들(민이름들)
    곁자리 = 자리들(곁이름들)
    같은자리 = [p for p, _ in 자리]
    찾음: list = []
    까닭들: list = []
    for s, e in 자리:
        if _견줌.match(t, e):
            까닭들.append("견줌만")
            continue
        got: list = []
        물음뿐 = True
        for a, b, 물음 in _판단_조각(t, s, e, [p for p in 민자리 if not s <= p < e],
                                    [p for p in 곁자리 if not s <= p < e], 같은자리):
            got += _깎는말_찾기(t[a:b], 물음)
            물음뿐 = 물음뿐 and 물음
        꾸밈 = _앞_꾸밈.search(t, max(0, s - 14), s)
        if 꾸밈:
            got += _깎는말_찾기(꾸밈.group(0), False)
        if got:
            찾음 += [g for g in got if g not in 찾음]
        else:
            까닭들.append("물음만" if 물음뿐 else "깎는말없음")
    if 찾음:
        return [g for g in 깎은갈래_이름 if g in 찾음], ""
    for 까닭 in ("깎는말없음", "물음만", "견줌만"):
        if 까닭 in 까닭들:
            return [], 까닭
    return [], "깎는말없음"


def 종류_갈래(name: str) -> str | None:
    """깎인 이름 → 종류 갈래(약·연고 / 시술 / 병원). 무늬에 안 걸리면 None · 순수함수."""
    s = str(name or "")
    for 갈래, rx in 깎은종류_갈래:
        if rx.search(s):
            return 갈래
    return None


def 글_열쇠(url) -> str:
    """글 주소 → 같은 글 열쇠. 검색 화면이 키워드마다 다른 '?art=' 꼬리를 붙여 같은 글이
    키워드 수만큼 따로 세였다(니조랄 글 71 = 서로 다른 글 30 · 2026-10-25 실측)."""
    return str(url or "").split("?")[0].split("#")[0].rstrip("/")


_연락처 = re.compile(r"\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{4}")
_메일 = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_주소 = re.compile(r"(?:https?://|www\.)\S+|\b\S+\.(?:com|net|kr|me|ly)\S*", re.I)
_아이디 = re.compile(r"@[\w.]+|\b[A-Za-z]+\d+[\w.]*|\b(?:카톡|카카오|오픈채팅|아이디|id|ID)\s*[:：]?\s*\S+")
_님 = re.compile(r"[가-힣A-Za-z0-9_]{1,12}님")
# 사람을 가리키지 않는 '○님' — 지우면 문맥이 사라진다('교수님이 약용샴푸는 단기 증상만').
_님_그대로 = {"교수님", "선생님", "원장님", "의사님", "약사님", "고객님", "회원님", "작성자님", "글쓴이님",
            "사장님", "언니님", "형님", "부모님", "엄마님", "아버님", "어머님", "선배님", "님"}
# ★2026-10-31 오탐 시험(같은 재료의 서로 다른 댓글 16,070개를 옛 · 새 함수로 견줌): '○○님' 무늬가 이름 모양을
#   보지 않고 '님' 으로 끝나는 말을 다 지웠다 — '광고 아님'(21곳) · '아드님' · '의사선생님' · '담당선생님' 도 '○○님'.
#   '님' 바로 앞이 부르는 말(선생 · 원장 · 아드 · 맘 …)이면 그 말은 남기고, 그 앞에 붙은 것(이름 · 닉네임 ·
#   성)만 지운다('양민석교수님' → '○○교수님'). '의사선생님 · 담당선생님 · 여선생님' 처럼 꾸밈이면 그대로.
_님_부름 = re.compile(r"(.*?)(선생|원장|교수|의사|약사|간호사|실장|과장|부장|팀장|기자|작가|사장|대장|"
                    r"고객|회원|횐|손|보호자|산모|견주|집사|아드|따|어머|아버|부모|형|누|언니|오빠|"
                    r"글쓴이|글쓴|작성자|쓰니|윗댓|맘|엄마|아빠|선배|이모|고모|사모|주인)님$")
_님_부름앞 = {"의사", "담당", "주치의", "전문의", "동네", "우리", "아는", "친한", "여자", "남자", "카페",
          "피부과", "한의원", "소아과", "약국", "병원", "옆집", "친정", "시댁", "작은", "큰"}


def _님_바꿈(mm) -> str:
    w = mm.group(0)
    if w in _님_그대로:
        return w
    if w == "아님" or (len(w) >= 3 and w.endswith("아님") and w[-3] in "도가이은는고게건거"):
        return w                                  # '광고 아님' · '음식도아님' — 아니라는 말이지 부름이 아니다
    m = _님_부름.match(w)
    if m:
        앞 = m.group(1)
        if not 앞 or 앞 in _님_부름앞 or (len(앞) == 1 and (앞 not in _성씨 or 앞 in "여남전현")):
            return w                              # '아드님' · '의사선생님' · '여선생님'
        return "○○" + w[len(앞):]                  # '양민석교수님' · '김선생님' → '○○교수님' · '○○선생님'
    return "○○님"


# ★2026-10-26 품질 1차 반려(중요 3): '제 이름은 김가상입니다'(직접 밝힘) · '김가상 교수님'(이름+직함)이
#   그대로 남았다. 위 무늬는 닉네임 · 연락처 · 붙여 쓴 '○○님'만 봤다.
# 직접 밝힘 — '제 이름은 ○○입니다' · '성함: ○○' · '저는 ○○이라고 합니다'. 이름 자리가 조사로 시작하지 않게
#   ('이름은요 …' 의 '은요' 를 이름으로 지우고 진짜 이름을 남기지 않게) 앞을 막는다.
#   '이름은 · 이름이' 뒤는 이름 다음에 '입니다 · 이에요' 같은 맺음이 올 때만 — '이름이 기억이 안 나요' 를 안 지운다.
# ★2026-10-31 오탐 시험: '확신 못 함' 검사가 임자 없는 '이름은' 도 밝힘으로 봐서 '제품 이름은 뽀ㅇ얀샴푸인데' ·
#   '이름은 들어봤어요' 댓글 37개를 버렸다(대부분 경쟁 글 — 시장 조사에서 볼 바로 그 예시). 지우기는 그대로 넓게
#   두고('이름은 ○○입니다'), 지웠나 못 지웠나 검사만 임자가 사람일 때로 좁힌다 — '제 · 내 · 본인 · 우리 아이' 의
#   이름, 처음부터 사람에게만 쓰는 '성함 · 본명 · 실명', 서식처럼 쓴 '이름:'.
_밝힘_맺음 = r"(?:입니다|이에요|예요|이고|이라고|라고|이구요|이요|이야|이래요|임|인데|이며|씨|님)"
_밝힘_주인 = (r"(?:(?<![가-힣])(?:제|저의|내|나의|본인|본인의|우리\s*(?:애|아이|아들|딸)(?:의)?)\s*"
          r"(?:이름|본명|실명)|성함|본명|실명)")
_이름밝힘 = re.compile(r"((?:이름|성함|본명|실명)\s*(?:은|는|이)\s*)((?![은는요])[가-힣]{2,4}?)(?=\s*" + _밝힘_맺음 + ")|"
                    r"((?:이름|성함|본명|실명)\s*[:：]\s*)((?![은는요])[가-힣]{2,4}?)"
                    r"(?=\s*" + _밝힘_맺음 + r"|[\s.,!~)]|$)")
# 사물이 임자인 '이름' — '제품 이름은 ○○샴푸인데' 의 제품 이름을 사람 이름으로 지우지 않는다.
_사물_이름 = re.compile(r"(?:제품|상품|브랜드|샴푸|크림|연고|로션|약|성분|병원|회사|가게|채널|카페|모임|강아지|고양이)"
                     r"(?:의)?\s*$")


def _밝힘_바꿈(mm) -> str:
    앞말 = mm.group(1) or mm.group(3)
    if _사물_이름.search(mm.string, max(0, mm.start() - 12), mm.start()):
        return mm.group(0)
    return 앞말 + "○○"


_라고밝힘 = re.compile(r"((?<![가-힣])(?:저는|전|제가|나는|난|저|나)\s*)([가-힣]{2,4}?)"
                    r"((?:이)?라고\s*(?:합니다|해요|하구요|하고요|불러))")
# 이름 + 직함 — 성씨 글자로 시작하는 이름 꼴 + (띄어쓰기) + 직함. 성씨 글자 하나는 이 저장소 낱말 규칙
#   (CLAUDE.md '영구 한국어 표준어') 때문에 글자 번호(\ubc15)로 적었다 — 같은 글자다.
_성씨 = ("김이\ubc15최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진지엄채원천방"
       "공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉")
_겹성 = "남궁|황보|제갈|선우|독고|사공|서문"
# '대표 · 이사 · 작가' 는 뺐다 — '도브 대표 제품' · '작년 이사' 처럼 사람이 아닌 뜻이 흔하다.
_긴직함 = r"(?:교수|선생|원장|의사|약사|\ubc15사|간호사|실장|과장|부장|팀장|변호사|기자)"
# 한 글자 직함(씨 · 님 · 쌤 · 샘)은 뒤가 조사이거나 글자가 끝날 때만 — '정품 샘플' · '씨앗' 을 이름으로 안 본다.
#   '씨' 바로 앞이 날 · 솜 · 맵 · 말 · 음이면 '날씨 · 솜씨 · 마음씨' 다('한국날씨가' 를 지웠었다).
_직함 = (r"(?:" + _긴직함 + r"|(?<![날솜맵말음])씨(?![가-힣])|(?<![날솜맵말음])씨(?=[이가은는께도의랑한])|"
       r"(?:님|쌤|샘)(?![가-힣])|(?:님|쌤|샘)(?=[이가은는께도의랑한]))")
# ★2026-10-31 오탐 시험: 성 글자 + 한두 글자를 다 이름으로 보니 '연고 약사님'(6곳) · '어느 교수님' · '이거 약사님' ·
#   '최근에 약사' · '마시고 약사님' · '고대 교수님' 을 지웠다. 이름 꼴을 좁힌다 —
#   성 + 두 글자(겹성 + 한두 글자)이고 끝 글자가 조사 · 맺음(에 · 고 · 면 · 이 …)이 아닐 때만 지운다('경희대 교수님'
#   은 '○○ 교수님' 이 된다 — 학교 이름은 빠져도 뜻은 남고, '김성대' 같은 이름을 남기는 쪽보다 낫다).
#   성 + 한 글자('연고 · 고대 · 이거' 처럼 낱말이 너무 많다)는 지우지도 남기지도 않고 '확신 못 함' — 그 예시를 버린다.
_이름꼴 = r"(?:(?:" + _겹성 + r")[가-힣]{1,2}|[" + _성씨 + r"][가-힣]{2})"
_이름직함 = re.compile(r"(?<![가-힣])(" + _이름꼴 + r")(\s*)(?=" + _직함 + ")")
_두글자직함 = re.compile(r"(?<![가-힣])([" + _성씨 + r"][가-힣])\s*(?=" + _긴직함 + ")")
_이름끝_아님 = set("에고과이면가을를도의로와랑께는다요데거")
# 성씨 글자로 시작하지만 사람 이름이 아닌 말 — 지우면 문맥만 사라진다('우리 원장님' · '이번 교수님').
_이름아닌말 = {"우리", "이번", "지난", "한번", "주치의", "진짜", "정말", "유명", "유명한", "전문", "전담", "동네",
            "이분", "그분", "친한", "해당", "원래", "처음", "다른", "여러", "모든", "어떤", "무슨", "이런", "그런",
            "이전", "기존", "현재", "남편", "신랑", "아내", "친구", "지인", "오빠", "엄마", "아빠", "이모", "고모",
            "삼촌", "사촌", "조카", "아들", "선배", "후배", "동기", "전공", "주변", "근처", "옆집", "시댁", "친정",
            "한의", "한의원", "한의사", "한방", "전문의", "소아과", "피부", "성형", "치과", "안과", "내과", "소아", "약국", "방금", "오늘", "어제", "요즘",
            "예전", "여기", "거기", "저기", "이쪽", "그쪽", "제가", "저희", "모두", "다들", "남자", "여자", "고딩",
            "어느", "이거", "고대", "연대", "강남", "강북", "서울", "부산", "인천", "광주", "대전", "울산", "수원",
            "성남", "일산", "분당", "판교", "신촌", "홍대", "명동", "종로", "유튜브", "인스타", "블로그", "신규"}
# 지운 뒤에도 남으면 '확신 못 함' — 사람이 이름을 밝히는 말이 나왔는데 그 자리가 지워지지 않았다.
_밝힘_남음 = re.compile(_밝힘_주인 + r"\s*(?:은|는|이|:|：)\s*(?!○○)[가-힣]|(?:이름|성함|본명|실명)\s*[:：]\s*(?!○○)[가-힣]|"
                     r"(?<![가-힣])(?:저는|전|제가|나는|난)\s*(?!○○)[가-힣]{1,4}?(?:이)?라고\s*"
                     r"(?:합니다|해요|하구요|하고요|불러)")


# 직함 말 자체의 앞 두 글자 — '원장님' 의 '원장' 이 성씨(원)로 시작해 이름으로 읽히지 않게.
_직함머리 = {"원장", "선생", "고객", "어머", "아버", "회원", "작성", "글쓴", "사장", "언니", "부모", "엄마", "선배",
          "교수", "의사", "약사", "실장", "과장", "부장", "팀장", "간호", "기자", "변호", "주인", "사모", "형님",
          "누님", "동생", "할머", "할아", "고모", "이모", "삼촌", "부인", "남편", "아내", "자녀", "애기", "아기"}


def _이름일까(이름: str) -> bool:
    """성씨로 시작하는 말이 사람 이름 꼴인가 — 아닌 말 · 직함 그 자체 · 성 + 직함('김원장') · 조사 끝이면 아니다."""
    return not (이름 in _이름아닌말 or 이름[:2] in _직함머리 or 이름[1:3] in _직함머리
                or 이름[-1] in _이름끝_아님)


def _애매한_이름(이름: str) -> bool:
    """'김서이 · 조합이' 처럼 성 + 두 글자인데 끝이 '이' — 이름('서이')인지 낱말 + 조사('조합' + 이)인지 못 가린다."""
    return (len(이름) == 3 and 이름[-1] == "이" and 이름 not in _이름아닌말
            and 이름[:2] not in _직함머리 and 이름[1:3] not in _직함머리)


def _이름직함_지우기(s: str) -> str:
    def 바꿈(mm):
        return "○○" + mm.group(2) if _이름일까(mm.group(1)) else mm.group(0)
    return _이름직함.sub(바꿈, s)


def 개인정보_지우기(text, 글쓴이: str = "", 길이: int = 예시댓글_길이) -> str:
    """예시 댓글 → 연락처 · 메일 · 주소 · 아이디 · '○○님' 부름 · 글쓴이 닉네임 · 밝힌 이름 ·
    이름+직함을 지운 한 줄(길이 자 안). **지웠다고 확신 못 하면 빈 글자**를 돌려준다 — 부르는 쪽은
    그 예시를 저장하지 않는다(다음 예시로 넘어간다).

    읽기 기억은 일부러 원문을 안 남긴다(comment_reads.key_of — 크기 · 사생활). 여기서도 한 줄만,
    지운 뒤에 남긴다. 줄바꿈은 띄어쓰기로.
    ★2026-10-26 — '제 이름은 김가상입니다' · '김가상 교수님' 도 지운다(품질 1차 반려 중요 3).
      '교수님이 …' 처럼 사람을 안 가리키는 부름은 그대로 둔다.
    ★2026-10-31 — 이름 꼴을 좁혔다(오탐 시험): '원장님이 · 선생님 · 고객님 · 어머님 · 광고 아님 · 연고 약사님 ·
      제품 이름은 …' 은 그대로. 성 + 한 글자 + 직함('김준 교수님') · 끝이 '이' 인 세 글자 + 직함('김서이 원장님')은
      이름인지 가릴 수 없어 그 예시를 버린다.
    """
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    닉 = str(글쓴이 or "").strip()
    if len(닉) >= 2:
        s = s.replace(닉, "○○")
    for rx in (_메일, _주소, _연락처, _아이디):
        s = rx.sub("○○", s)
    s = _이름밝힘.sub(_밝힘_바꿈, s)
    s = _라고밝힘.sub(lambda mm: mm.group(1) + "○○" + mm.group(3), s)
    s = _이름직함_지우기(s)
    s = _님.sub(_님_바꿈, s)
    s = s[:길이]
    if (_밝힘_남음.search(s) or any(_이름일까(mm.group(1)) for mm in _두글자직함.finditer(s))
            or any(_애매한_이름(mm.group(1)) for mm in _이름직함.finditer(s))):
        return ""                         # 이름일지 모르는 말이 남았는데 못 지웠다 — 이 예시는 저장하지 않는다
    return s


def 깎인제품_집계(깎음언급: list, 민언급: list, verdicts: dict,
                unified: dict | None = None, 셈상태: dict | None = None,
                확인필요: list | None = None) -> list:
    """깎인 언급 → 대상마다 한 줄 · 순수함수. 서로 다른 댓글 많은 순. 돌려주는 것 = **확정**('깎인제품').

    한 줄 = {이름, 종류('상표'/'종류'), 종류갈래, 제품판정, 댓글수(서로 다른 댓글), 글수(서로 다른 글),
             끌어온경쟁계정수, 글쓴이갈래{경쟁글·우리글·바이럴아님}, 예시댓글, 예시글, 함께민제품, 일부만셈,
             깎는말갈래{그때뿐·효과없음·부작용}, 근거못찾은댓글수}
    옛 칸(이름 · 댓글수 · 글수 · 함께민제품)은 이름 그대로 — margin-auto 스냅샷이 그대로 읽는다.

    ★2026-10-24 사장님: "이거는 니조랄 바이럴이 아니라 안티트로가 본인 바이럴 하기 위한
      대안제거임" — 경쟁사 셈에서는 빼고(extract_brands 가 out 에 안 넣음) 여기서 따로 묶는다.
    ★2026-10-25 바꾼 것(대조 보고 ②③④⑤):
      · 셈 — 같은 댓글이 키워드마다 한 번씩 더해졌다(니조랄 161 = 서로 다른 댓글 70). (글, 댓글) 로 한 번.
      · 상표만 → 종류도 — 제품 판정을 통과 못 한 깎인 이름(스테로이드 · 크레오신티)과 '종류' 칸을
        버리지 않는다. 경쟁사 셈 길(표시할_브랜드명 → confirmed_rows)은 그대로다.
      · 글쓴이 갈래 — 같은 글에서 민 제품이 우리 것뿐이면 우리 글, 남의 것이 하나라도 있으면 경쟁 글,
        없으면 바이럴 아님(스냅샷 우리_계정_거르기 와 같은 잣대 — 섞어 민 것은 경쟁 쪽).
      · 버리던 재료 — 끌어온 경쟁 계정 수(글쓴이키) · 예시 댓글 한 줄(개인 정보 지움)을 남긴다.
    ★2026-10-26 바꾼 것(품질 1차 반려 중요 1 · 3):
      · AI 의 '깎음' 표시를 그대로 믿지 않는다 — 댓글마다 원문에서 그 대상을 깎는 말(깎음_근거)을 찾는다.
        근거 있는 댓글이 하나라도 있는 대상만 확정. 셈 · 갈래 · 함께민제품 · 예시는 **근거 있는 댓글로만**
        세고, 나머지는 '근거못찾은댓글수'로 남긴다(지우지 않음 · 섞인 행은 두고 수만 가름).
      · 근거가 하나도 없는 대상은 버리지 않고 `확인필요` 목록(같은 모양 + '빠진까닭' 한 줄)에 넣는다 —
        부르는 쪽이 viral_accounts.json 의 '깎인제품_확인필요' 칸에 적는다. 읽기 기억은 안 고친다.
      · 예시는 개인 정보를 지웠다고 확신하는 댓글만 — 확신 못 하면 다음 댓글, 없으면 빈칸.
    셈상태 = {"다시안읽은옛댓글": n, "종류칸못본댓글": n} — 0 이 아니면 그 갈래 줄에 일부만셈=True.
    """
    셈상태 = 셈상태 or {}
    민: dict = {}                               # 글 열쇠 → 같은 글에서 민 제품(표에 올릴 이름)
    민원문: dict = {}                           # 댓글 원문 → 그 댓글에서 AI 가 민 것으로 읽은 이름(원문 표기)
    for m in 민언급 or []:
        이름 = 표시할_브랜드명(m, verdicts, unified)
        글 = 글_열쇠(m.get("글"))
        if 이름 and 글:
            민.setdefault(글, [])
            if 이름 not in 민[글]:
                민[글].append(이름)
        t = str(m.get("댓글") or "").strip()
        n = str(m.get("표시") or m.get("키") or "").strip()
        if t and n:
            민원문.setdefault(t, set()).add(n)
    깎원문: dict = {}                           # 댓글 원문 → 그 댓글의 깎인 대상들(원문 표기)
    for m in 깎음언급 or []:
        t = str(m.get("댓글") or "").strip()
        n = str(m.get("표시") or m.get("키") or "").strip()
        if t and n:
            깎원문.setdefault(t, set()).add(n)
    근거_기억: dict = {}

    def 근거(댓글: str, 날것: str, 이름: str) -> tuple:
        k = (댓글, 날것, 이름)
        if k not in 근거_기억:
            곁 = 깎원문.get(댓글, set()) - {날것}
            민것 = 민원문.get(댓글, set()) - {날것}
            갈래, 까닭 = 깎음_근거(댓글, 날것 or 이름, 민것, 곁)
            if 까닭 == "이름자리없음" and 이름 and 이름 != 날것:
                갈래, 까닭 = 깎음_근거(댓글, 이름, 민것, 곁)   # 판정이 되살린 이름으로 한 번 더
            근거_기억[k] = (갈래, 까닭)
        return 근거_기억[k]

    def 대상(m):
        """언급 → (이름, 종류, 종류갈래, 제품판정) 또는 None(우리 것 · 빈 이름)."""
        if m.get("종류") == "깎은종류":
            이름 = 이름_다듬기(m.get("표시") or m.get("키") or "")
            if not 이름 or 우리제품인가(이름):
                return None
            return 이름, "종류", 종류_갈래(이름) or 깎은종류_그밖, ""
        이름 = 표시할_브랜드명(m, verdicts, unified)
        if 이름:
            if any(h in 이름 for h in OUR_PRODUCT_HINTS):
                return None
            return 이름, "상표", "", "통과"
        # 제품 판정을 못 넘은 깎인 이름 — 예전엔 여기서 버렸다. 종류 무늬면 종류로, 아니면 상표로 남긴다.
        날것 = 이름_다듬기(m.get("표시") or m.get("키") or "")
        if len(normalize_name(날것)) < 2 and len(날것) < 2:
            return None
        if 우리제품인가(날것):
            return None
        갈래 = 종류_갈래(날것)
        if 갈래:
            return 날것, "종류", 갈래, ""
        # '아님'(판정이 제품 아니라 함)과 '미판정'(판정표에 없음 · 검색이 막힌 날)을 섞지 않는다.
        if m.get("키") not in (verdicts or {}):
            판정 = "미판정"
        else:
            판정 = "통과" if brand_verdicts.is_product(verdicts, m.get("키")) else "아님"
        return 날것, "상표", "", 판정

    모음: dict = {}
    for m in 깎음언급 or []:
        d = 대상(m)
        if not d:
            continue
        이름, 종류, 갈래, 판정 = d
        b = 모음.setdefault((종류, 이름), {
            "이름": 이름, "종류": 종류, "종류갈래": 갈래, "제품판정": 판정, "_건": []})
        글 = 글_열쇠(m.get("글"))
        댓글 = str(m.get("댓글") or "").strip()
        깎은갈래, 까닭 = 근거(댓글, str(m.get("표시") or m.get("키") or "").strip(), 이름)
        b["_건"].append((글, 댓글, m, 깎은갈래, 까닭))

    갈래_순서 = {"경쟁글": 0, "바이럴아님": 1, "우리글": 2}

    def 줄(b: dict, 건들: list) -> dict:
        댓글들: set = set()
        글들: dict = {}
        함께: list = []
        깎은수 = {g: 0 for g in 깎은갈래_이름}
        for 글, 댓글, m, 깎은갈래, _까닭 in 건들:
            if (글, 댓글) not in 댓글들:
                댓글들.add((글, 댓글))
                for g in 깎은갈래:
                    깎은수[g] += 1
            if 글 and 글 not in 글들:
                글들[글] = m
            for p in 민.get(글) or []:
                if p != b["이름"] and p not in 함께:
                    함께.append(p)
        갈래수 = {"경쟁글": 0, "우리글": 0, "바이럴아님": 0}
        글갈래: dict = {}
        경쟁계정: set = set()
        for 글, m in 글들.items():
            민것 = [p for p in 민.get(글) or [] if p != b["이름"]]
            if not 민것:
                g = "바이럴아님"
            elif all(우리제품인가(p) for p in 민것):
                g = "우리글"
            else:
                g = "경쟁글"
            글갈래[글] = g
            갈래수[g] += 1
            키 = str(m.get("글쓴이키") or "").strip()
            if g == "경쟁글" and 키:
                경쟁계정.add(키)
        # 예시는 경쟁 글 먼저 — 시장 조사에서 보려는 것이 '경쟁 글이 어떻게 깎았나' 다. 같은 입력이면 같은 예시.
        #   개인 정보를 지웠다고 확신 못 하는 댓글(빈 글자)은 건너뛴다 — 다 그러면 빈칸.
        후보 = sorted(건들, key=lambda x: (갈래_순서[글갈래.get(x[0], "바이럴아님")], x[0], x[1]))
        예시댓글, 예시글 = "", (후보[0][0] if 후보 else "")
        for 글, 댓글, m, _g, _k in 후보:
            s = 개인정보_지우기(댓글, m.get("글쓴이") or "")
            if s:
                예시댓글, 예시글 = s, 글
                break
        일부 = bool(셈상태.get("종류칸못본댓글") if b["종류"] == "종류"
                  else 셈상태.get("다시안읽은옛댓글"))
        return {
            "이름": b["이름"], "종류": b["종류"], "종류갈래": b["종류갈래"], "제품판정": b["제품판정"],
            "댓글수": len(댓글들), "글수": len(글들),
            "끌어온경쟁계정수": len(경쟁계정), "글쓴이갈래": 갈래수,
            "예시댓글": 예시댓글, "예시글": 예시글,
            "함께민제품": 함께[:8], "일부만셈": 일부, "깎는말갈래": 깎은수,
        }

    out, 뺀것 = [], []
    for b in 모음.values():
        있음 = [x for x in b["_건"] if x[3]]
        없음 = [x for x in b["_건"] if not x[3]]
        if 있음:
            r = 줄(b, 있음)
            r["근거못찾은댓글수"] = len({(x[0], x[1]) for x in 없음} - {(x[0], x[1]) for x in 있음})
            out.append(r)
            continue
        r = 줄(b, 없음)
        r["근거못찾은댓글수"] = r["댓글수"]
        까닭별: dict = {}
        for 글, 댓글, _m, _g, 까닭 in 없음:
            까닭별.setdefault((글, 댓글), 까닭)
        까닭수: dict = {}
        for 까닭 in 까닭별.values():
            까닭수[까닭] = 까닭수.get(까닭, 0) + 1
        r["빠진까닭"] = "원문에서 이 대상을 깎는 말(그때뿐 · 효과 없음 · 부작용)을 못 찾음 — " + " · ".join(
            f"{_빠진까닭_말.get(k, k)} {n}" for k, n in sorted(까닭수.items(), key=lambda kv: (-kv[1], kv[0])))
        뺀것.append(r)
    out.sort(key=lambda x: (-x["댓글수"], x["종류"], x["이름"]))
    뺀것.sort(key=lambda x: (-x["댓글수"], x["종류"], x["이름"]))
    if 확인필요 is not None:
        확인필요.extend(뺀것)
    return out


회원_기억_날 = 7          # 회원 여부는 이 날수 동안 다시 묻지 않는다
회원_회차_상한 = 400      # 한 회차에 새로 물어볼 계정 수 상한(네이버 부담 · 시간)


def 회원_붙이기(계정줄: list, 묻기, 기억: dict, today: str,
              상한: int = 회원_회차_상한) -> dict:
    """계정마다 '회원' 칸('회원'/'탈퇴'/'') 을 붙인다. 묻기(글주소) → 그 값.

    기억 = {"카페번호:계정키": {"회원": …, "날": …}} — 7일 안이면 다시 묻지 않는다.
    상한을 넘는 계정은 묻지 않고 기억값(없으면 '')으로 둔다. 통계를 돌려준다.
    """
    from datetime import date as _d
    stat = {"물음": 0, "기억": 0, "못물음": 0}
    for a in 계정줄 or []:
        열 = f'{a.get("카페번호") or ""}:{a.get("계정키") or ""}'
        e = (기억 or {}).get(열) or {}
        try:
            묵은날 = (_d.fromisoformat(today) - _d.fromisoformat(str(e.get("날") or ""))).days
        except ValueError:
            묵은날 = None
        if e and 묵은날 is not None and 0 <= 묵은날 < 회원_기억_날:
            a["회원"] = e.get("회원") or ""
            stat["기억"] += 1
            continue
        글 = next((g for g in a.get("글들") or [] if g), "")
        if not 글 or stat["물음"] >= 상한:
            a["회원"] = e.get("회원") or ""
            stat["못물음"] += 1
            continue
        try:
            값 = 묻기(글) or ""
        except Exception:
            값 = ""
        stat["물음"] += 1
        a["회원"] = 값
        기억[열] = {"회원": 값, "날": today}
    return stat


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
#   ★2026-09-09 사장님 "경쟁사 추출도 제품군 잘 구분해서 좀 해놔봐" — 칸 두 개를 더한다.
#     그동안 '제품군' 은 **그 댓글을 어느 탭 키워드에서 주웠나** 였다. 그래서 샴푸인
#     안티트로가 바디워시 줄에 앉아 있었다(등여드름 키워드 댓글 하나 때문에).
#     515줄 중 59개 브랜드가 두세 제품군에 겹쳐 있었다(2026-09-09 실측).
#     → '파는 제품군' = 그 브랜드가 **실제로 파는** 것. 집 PC 도구가 브랜드+제품종류로
#       검색량을 물어 채운다. 이 배치는 그 값을 지키고, 그 값대로 줄을 옮긴다.
#     → '검색량 키워드' = 그 검색량이 어느 말로 나온 것인가. '안티트로' 990 이 아니라
#       '안티트로샴푸' 12,580 이 그 브랜드의 크기다.
FIXED_HEAD = ["제품군", "경쟁사", "검색량", "검색량 키워드", "파는 제품군",
              "판정", "뜬 키워드 수", "최고순위", "평균순위",
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
        # 같은 (제품군, 경쟁사) 줄이 둘이면 날짜별로 더한다 — 이름을 다듬어 합친 줄이 그렇다.
        묶음 = out.setdefault((str(row[ip]).strip(), str(row[ib]).strip()), {})
        for day, n in per.items():
            묶음[day] = 묶음.get(day, 0) + n
    return out, [d for _, d in date_cols]


def _지난표_이름_다듬기(values: list) -> list:
    """지난 표의 '경쟁사' 칸을 이름_다듬기 로 고친 사본 · 순수함수(원본은 안 건드린다)."""
    if not values or len(values) < 2:
        return values
    head = [str(c).strip() for c in values[0]]
    if "경쟁사" not in head:
        return values
    ib = head.index("경쟁사")
    out = [values[0]]
    for row in values[1:]:
        if len(row) > ib and str(row[ib]).strip():
            row = list(row)
            row[ib] = 이름_다듬기(row[ib]) or str(row[ib]).strip()
        out.append(row)
    return out


# 집 PC 도구(cafe-external/경쟁사_검색량.py)가 채우는 칸들. 이 배치는 지키기만 한다.
_검색칸 = ("검색량", "검색량 키워드", "파는 제품군")

# '파는 제품군' 칸에 적히는 세 가지 모양.
#   빈 칸        = 아직 안 물어봤다      (열쇠 자체가 없다 → 줄을 옮기지 않는다)
#   못 정함 글자 = 물어봤는데 못 정했다  ([] → 줄을 옮기지 않는다)
#   "샴푸·바디워시" = 파는 제품군 목록   (검색량 큰 순)
파는제품군_못정함 = "못 정함(검색량 없음)"
제품군_이름들 = ("샴푸", "바디워시", "두드러기")


def _수로(값) -> int:
    """검색량 칸 글자 → 숫자. 못 읽으면 0 · 순수함수."""
    try:
        return int(float(str(값 if 값 is not None else "").strip().replace(",", "") or 0))
    except ValueError:
        return 0


def _prev_volumes(values: list) -> dict:
    """지난 표에서 **경쟁사 이름** → {검색량, 검색량 키워드, 파는 제품군} 을 되살린다.

    ★검색량은 이 배치가 만드는 값이 아니다. 집 PC 도구가 네이버 검색광고에 물어
    채워 넣는 칸이고, 이 배치는 매일 표를 통째로 다시 쓴다. 지키지 않으면
    사람이 채운 값이 다음 새벽에 사라져 영영 빈칸으로 남는다.

    ★2026-09-09 — 열쇠를 (제품군, 경쟁사) 에서 **경쟁사 이름 하나**로 바꿨다.
      브랜드가 파는 제품군으로 줄이 옮겨 다니는데 제품군을 열쇠에 넣어 두면,
      옮기는 그 날 검색량이 통째로 빈칸이 된다(어제 채운 값을 오늘 잃는다).
    ★같은 이름이 여러 줄이면 **검색량이 가장 큰 줄**을 쓴다. 그 줄에 없는 칸은
      다른 줄에서 있는 것으로 메운다 — 채워 둔 값을 버리지 않는다.
    ★'0' 도 지킨다. 빈칸으로 되돌리면 집 PC 도구가 매일 같은 이름을 다시 조회한다.
    """
    if not values or len(values) < 2:
        return {}
    head = [str(c).strip() for c in values[0]]
    if "경쟁사" not in head or "검색량" not in head:
        return {}
    ib = head.index("경쟁사")
    자리 = {이름: head.index(이름) for 이름 in _검색칸 if 이름 in head}
    out: dict = {}
    for row in values[1:]:
        if len(row) <= ib:
            continue
        brand = str(row[ib]).strip()
        if not brand:
            continue
        # ★오늘 이름과 같은 모양으로 — 제품군 재배치(run_from_sheet)가 이 표를 build_table
        #   보다 먼저 읽는다. '클모.엔' 열쇠로 두면 오늘의 '클모엔' 이 파는 제품군을 못 찾아
        #   두 줄로 갈라졌다(2026-10-24 GPT 검토 지적).
        brand = 이름_다듬기(brand) or brand
        칸 = {이름: row[i] for 이름, i in 자리.items()
             if i < len(row) and str(row[i]).strip()}
        if not 칸:
            continue
        기존 = out.get(brand)
        if 기존 is None:
            out[brand] = 칸
        elif _수로(칸.get("검색량")) > _수로(기존.get("검색량")):
            out[brand] = {**{k: v for k, v in 기존.items() if k not in 칸}, **칸}
        else:
            for k, v in 칸.items():
                기존.setdefault(k, v)
    return out


def _prev_families(values: list) -> dict:
    """지난 표에서 경쟁사 이름 → **실제로 파는 제품군 목록** 을 되살린다 · 순수함수.

    빈 칸(아직 안 물어봄)은 열쇠 자체를 안 만든다 — '모른다' 와 '없다' 를 가른다.
    "못 정함(검색량 없음)" 은 빈 목록. 둘 다 줄을 옮기지 않는다
    (사장님 원칙: 확실하지 않으면 빼지 마라).
    """
    out: dict = {}
    for brand, 칸 in (_prev_volumes(values) or {}).items():
        글 = str(칸.get("파는 제품군") or "").strip()
        if not 글:
            continue
        if 글 == 파는제품군_못정함:
            out[brand] = []
            continue
        out[brand] = [p for p in (x.strip() for x in 글.split("·"))
                      if p in 제품군_이름들]
    return out


def 옮길_제품군(product: str, brand: str, families: dict | None) -> str:
    """이 줄을 어느 제품군에 놓을 것인가 · 순수함수.

    그 브랜드가 파는 것을 알고(목록이 비지 않았고) 지금 자리가 그 안에 없으면,
    파는 것 중 **첫째**(검색량이 가장 큰 것)로 옮긴다. 모르면 그대로 둔다.

    ★우리가 아는 세 제품군(제품군_이름들) 안에 있는 줄만 옮긴다.
      '파는 제품군' 목록에는 그 셋 말고 다른 이름이 들어올 수 없다(_prev_families 가
      걸러낸다). 그래서 네 번째 키워드 탭('린스 카외' 같은 것)이 하루 생기면,
      그 탭의 이름 아는 브랜드가 **전부** 샴푸·바디워시로 쓸려 나간다 —
      새 탭은 첫날부터 빈 통이 되고 그 탭을 봤다는 사실도 사라진다.
      모르는 제품군은 '틀린 자리' 가 아니라 '판정할 수 없는 자리' 다. 그대로 둔다.
    """
    if product not in 제품군_이름들:
        return product
    fam = (families or {}).get(brand)
    if fam and product not in fam:
        return fam[0]
    return product


def 제품군_재배치(branded: dict, verdicts: dict, unified: dict | None,
             families: dict | None) -> dict:
    """오늘 언급을 그 브랜드가 **실제로 파는** 제품군 통으로 옮긴다 · 순수함수.

    branded = {제품군(탭): [이름 붙은 언급...]} — extract_brands 가 돌려준 모양.

    ★안티트로는 샴푸다. 그런데 바디워시 탭 키워드('등여드름없애는법') 댓글에서
      한 번 나왔다고 바디워시 경쟁사로 표에 앉아 있었다(2026-09-09 실측).
      제품군은 '어느 탭에서 주웠나' 가 아니라 '무엇을 파나' 여야 한다.
    ★모르는 브랜드(칸이 빈 것)와 못 정한 브랜드는 **그대로 둔다** —
      사장님: "확실하지 않으면 빼지 마라".
    ★원래 있던 통은 비어도 열쇠를 남긴다. 오늘 그 탭을 봤다는 사실이 사라지면
      안 되기 때문이다(build_table 의 '오늘은 못 봄' 판정이 그것을 본다).
    """
    out: dict = {p: [] for p in (branded or {})}
    for product, mentions in (branded or {}).items():
        for m in mentions or []:
            name = 표시할_브랜드명(m, verdicts, unified)
            갈곳 = 옮길_제품군(product, name, families) if name else product
            out.setdefault(갈곳, []).append(m)
    return out


def 옛줄_재배치(prev_counts: dict, prev_extras: dict, families: dict | None) -> tuple:
    """어제까지 쌓인 줄도 파는 제품군으로 옮긴다 · 순수함수. → (날짜별 횟수, 지난 성적)

    같은 브랜드 줄이 두 제품군에 갈라져 있었으면 한 줄로 합친다 —
    날짜별 횟수는 **더하고**, 성적 칸은 원래 그 자리에 있던 줄 것을 그대로 둔다
    (옮겨온 줄이 제자리 줄을 덮으면 오늘 잰 성적이 옛 값으로 되돌아간다).
    """
    counts: dict = {}
    for (product, brand), per in (prev_counts or {}).items():
        키 = (옮길_제품군(product, brand, families), brand)
        묶음 = counts.setdefault(키, {})
        for day, n in (per or {}).items():
            묶음[day] = 묶음.get(day, 0) + int(n or 0)

    extras: dict = {}
    for (product, brand), 칸 in (prev_extras or {}).items():        # ① 제자리 줄 먼저
        if 옮길_제품군(product, brand, families) == product:
            extras[(product, brand)] = 칸
    for (product, brand), 칸 in (prev_extras or {}).items():        # ② 옮겨온 줄은 빈 자리에만
        키 = (옮길_제품군(product, brand, families), brand)
        if 키 != (product, brand):
            extras.setdefault(키, 칸)
    return counts, extras


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
            out.setdefault((제품, 경쟁), 칸)   # 합친 줄이 둘이면 위(먼저) 줄 성적을 쓴다
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
                days: int = HISTORY_DAYS, stat: dict | None = None,
                scanned_products: set | None = None) -> list:
    """지난 표 + 오늘 결과 → 시트에 쓸 표 전체 · 순수함수.

    today_rows = [{"제품군","경쟁사","횟수","키워드수","키워드들","글들","댓글 예시"}]
    scanned_products = 오늘 **실제로 훑은** 제품군(탭) 이름들. 안 주면 오늘 줄에서 뽑는다.
      ★2026-09-09 — 오늘 줄에서 뽑으면 안 된다. 제품군 재배치로 옮겨온 언급밖에
        없는 통이 생기면, 그 제품군을 오늘 훑은 적이 없는데도 '봤다' 가 되어
        그 통의 다른 경쟁사들에 0 이 찍힌다('오늘은 못 봄' 이어야 할 자리에).
    """
    # ★2026-10-24 — 지난 표의 이름도 오늘과 같은 모양('클모.엔' → '클모엔')으로 읽는다.
    #   안 그러면 어제 줄 '클모.엔' 과 오늘 줄 '클모엔' 이 한 브랜드인데 두 줄로 갈라진다.
    prev_values = _지난표_이름_다듬기(prev_values)
    지킨칸 = _prev_volumes(prev_values)
    파는제품군 = _prev_families(prev_values)
    prev, _ = _prev_counts(prev_values)
    지난값 = _prev_extras(prev_values)
    prev, 지난값 = 옛줄_재배치(prev, 지난값, 파는제품군)
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
    rows = []
    # 오늘 이 제품군을 **아예 안 봤나**(회차가 거기까지 못 감) — 봤는데 안 나온 것과 다르다.
    본제품군 = (set(scanned_products) if scanned_products is not None
             else {p for p, _ in extra})
    for (product, brand), per in merged.items():
        # ★옛 줄에도 오늘 잣대를 건다 — 제외가 생기기 전에 들어온 자사·가게·일반명
        #   (두드럼·다이소·케라틴)이 이어받기로 눌러앉는 것을 막는다(2026-09-05 실물 확인).
        if not 표에_남길_경쟁사인가(brand):
            continue
        오늘봄 = (product, brand) in extra
        # ★오늘 이 줄이 실제로 나왔으면 그 자체가 '봤다' 는 증거다(2026-09-09).
        #   본제품군 은 **옮기기 전** 탭 이름들이라, 훑은 탭에서 주운 브랜드가
        #   재배치로 안 훑은 제품군에 가 앉으면 오늘 센 값이 통째로 버려졌다 —
        #   '뜬 키워드 수' 에는 오늘 값이 적히는데 옆의 오늘 칸은 '오늘은 못 봄'.
        제품군을봄 = product in 본제품군 or 오늘봄
        # ★오늘 그 제품군을 아예 안 봤으면 오늘 칸을 **0 으로 만들지 않는다** —
        #   0 은 '댓글이 없었다' 는 뜻이고, 안 본 것은 '모른다' 다.
        #   (2026-09-05 검수 심각 2: 안 본 경쟁사에 '▼ -5' 가 찍혔다.)
        #   봤는데 안 나온 것은 그대로 0 이다 — 그건 진짜 0 이다.
        # ★같은 날 다시 돌린 회차: 오늘 칸은 이번에 센 값이다 — 아까 센 값이 남지 않게(GPT 검토 10-24).
        counts = [(per.get(d, 0) if d != today
                   else (per.get(d, 0) if 오늘봄 else (0 if 제품군을봄 else ""))) for d in dates]
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
        # ★검색량 세 칸은 **브랜드 이름**으로 이어받는다 — 줄이 제품군을 옮겨도 남는다.
        칸 = 지킨칸.get(brand) or {}
        _검색량 = 칸.get("검색량", "")
        rows.append([product, brand,
                     _검색량, 칸.get("검색량 키워드", ""), 칸.get("파는 제품군", ""),
                     판정_말(_검색량),
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
    i판정, i검색량 = header.index("판정"), header.index("검색량")
    i키수 = header.index("뜬 키워드 수")
    rows.sort(key=lambda x: (판정_순서.get(x[i판정], 9), -_수로(x[i키수]),
                             -_수로(x[i검색량]), x[0], x[1]))
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
    깎음언급: list = []          # 2026-10-24 — 깎으려고 꺼낸 대안 제품(경쟁사로 세지 않음)
    for product, mentions in by_product.items():
        ms2, v, stat = extract_brands(mentions, today=today, max_batches=남은예산,
                                      깎음언급=깎음언급)
        if 남은예산 is not None:
            남은예산 = max(0, 남은예산 - int(stat.get("예산사용", 0) or 0))
        branded[product] = ms2
        verdicts.update(v)
        for k in ("댓글", "묶음", "못읽은묶음", "뽑은이름", "캐시읽음",
                  "검색확인", "검색통과", "검색막힘", "다시읽기대상", "다시읽음", "깎음언급",
                  "종류언급", "종류칸없음"):
            jstat[k] = jstat.get(k, 0) + int(stat.get(k, 0) or 0)
        jstat["탈"] = sorted(set(jstat["탈"]) | set(stat.get("탈", [])))
    all_mentions = [m for ms in branded.values() for m in ms]

    # 같은 브랜드가 여러 표기로 흩어져 있으면 정식 이름 하나로 묶는다(호출 1회).
    # ★2026-10-26 — 예전 기록은 묶인 이름 3개만, 그것도 **어디로** 묶였는지 없이 찍었다.
    #   그래서 '닥터그루트 → 고루트' 같은 잘못 묶음이 밤마다 표에 들어가도 기록에서 안 보였다.
    #   지금은 묶은 것 전부와, 글자가 안 닮아 안 묶은 AI 답을 '→' 로 다 남긴다.
    묶기거절: list = []
    unified = comment_brand_llm.unify(brand_names(all_mentions, verdicts), 거절=묶기거절)
    if unified:
        merged = {a: r for a, r in unified.items() if a != r}
        print(f"이름 묶기: {len(merged)}개를 정식 브랜드명으로 통일"
              + (f" ({' · '.join(f'{a}→{r}' for a, r in merged.items())})" if merged else ""))
    if 묶기거절:
        print(f"이름 묶기: AI 가 묶자고 했지만 글자가 안 닮아 안 묶은 것 {len(묶기거절)}개 "
              f"({' · '.join(f'{a}→{r}' for a, r in 묶기거절)})")

    # ★어제까지의 '경쟁사' 표를 **여기서** 읽는다(쓰기 직전이 아니라).
    #   오늘 언급을 어느 제품군에 놓을지가 그 표의 '파는 제품군' 칸에 적혀 있다 —
    #   집 PC 도구가 브랜드+제품종류로 검색량을 물어 채워 둔 값이다.
    #   쓰기 직전에 읽으면 재배치가 그 값을 못 보고 지나간다.
    import gspread
    try:
        경쟁사탭 = client.spreadsheet.worksheet("경쟁사")
        prev_values = 경쟁사탭.get_all_values()      # 어제까지의 기록 = 시트 자신
    except gspread.exceptions.WorksheetNotFound:
        경쟁사탭, prev_values = None, []

    파는제품군 = _prev_families(prev_values)
    본탭 = set(branded)                    # 오늘 **실제로 훑은** 제품군 — 옮기기 전 모양
    옮기기전 = {p: len(ms) for p, ms in branded.items()}
    branded = 제품군_재배치(branded, verdicts, unified, 파는제품군)
    옮김 = [f"{p} {len(ms) - 옮기기전.get(p, 0):+d}건"
          for p, ms in branded.items() if len(ms) != 옮기기전.get(p, 0)]
    if 옮김:
        print(f"제품군 재배치(파는 제품군 기준): {' · '.join(옮김)}")

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
        ws = 경쟁사탭 or client.spreadsheet.add_worksheet(title="경쟁사", rows=400, cols=26)

        payload = build_table(prev_values, out_rows, today, stat=jstat,
                              scanned_products=본탭)
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
            # ★2026-10-24 — 탈퇴면 글 삭제 요청, 회원이면 신고(사장님). 기억은 따로 둔다.
            회원자리 = os.path.join(os.path.dirname(자리), "cafe_member_status.json")
            try:
                with open(회원자리, encoding="utf-8") as f:
                    회원기억 = json.load(f)
                if not isinstance(회원기억, dict):
                    회원기억 = {}
            except (OSError, ValueError):
                회원기억 = {}

            def _묻기(글):
                try:
                    return fetcher.회원여부(글)
                finally:
                    time.sleep(0.5)      # 네이버 부담 줄이기 — 실패해도 쉰다
            회원통계 = 회원_붙이기(계정줄, _묻기, 회원기억, today)
            with open(회원자리, "w", encoding="utf-8") as f:
                json.dump(회원기억, f, ensure_ascii=False, indent=0, sort_keys=True)
            세기: dict = {}
            for x in 계정줄:
                k = x.get("회원") or "확인 못 함"
                세기[k] = 세기.get(k, 0) + 1
            print(f"회원 여부: {세기} (새로 물음 {회원통계['물음']} · 기억 {회원통계['기억']} "
                  f"· 상한으로 못 물음 {회원통계['못물음']})")
            # '일부만 셈' — 옛 댓글을 다 다시 읽기 전(상표) · 종류 칸을 못 본 댓글이 남은 동안(종류).
            셈상태 = {"다시안읽은옛댓글": max(0, int(jstat.get("다시읽기대상", 0) or 0)
                                         - int(jstat.get("다시읽음", 0) or 0)),
                     "종류칸못본댓글": int(jstat.get("종류칸없음", 0) or 0)}
            # ★2026-10-26 — 원문에서 깎는 말을 못 찾은 대상은 지우지 않고 '깎인제품_확인필요' 칸에 둔다.
            확인필요: list = []
            깎인 = 깎인제품_집계(깎음언급, all_mentions, verdicts, unified, 셈상태=셈상태,
                                 확인필요=확인필요)
            종류줄 = sum(1 for x in 깎인 if x.get("종류") == "종류")
            print(f"깎인 대상 {len(깎인)}개(상표 {len(깎인) - 종류줄} · 종류 {종류줄} · 경쟁사 셈에서 뺌) "
                  f"· 원문에서 깎는 말을 못 찾아 확인필요로 둔 대상 {len(확인필요)}개 "
                  f"· 다시 읽은 옛 댓글 {jstat.get('다시읽음', 0)}/{jstat.get('다시읽기대상', 0)} "
                  f"· 종류 칸 못 본 댓글 {셈상태['종류칸못본댓글']}")
            with open(자리, "w", encoding="utf-8") as f:
                json.dump({"때": today, "계정": 계정줄, "깎인제품": 깎인, "깎인제품_확인필요": 확인필요},
                          f, ensure_ascii=False, indent=1)
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
        # ★제목→검색 키워드 판정(LLM)을 붙이고(2026-09-06), 잡음 삭제 + 작은 회차 실물
        #   미리보기로 품질을 확인해 기본 켜짐으로 되돌린다. 미리보기 결과: 탈모샴푸·
        #   모공각화증·햇빛 알레르기 치료·홍조·병원 등 — 게시판 이름·조사 조각만 판정기가
        #   버리고, 병원·후기 같은 진짜 검색어는 남긴다(사장님 2026-09-06 교정 "병원은
        #   키워드 후보가 맞지"). 안전장치: LLM 열쇠 없으면 빈 결과. 끄개: WRITE_TITLE_CANDIDATES=0.
        if os.environ.get("WRITE_TITLE_CANDIDATES") == "0":
            print("키워드후보: 제목 경로가 꺼져 있습니다(WRITE_TITLE_CANDIDATES=0)")
        else:
            try:
                _후보탭_갱신(client, by_product, today)
            except Exception as e:
                print(f"키워드후보 못 적음({type(e).__name__}) — "
                      f"경쟁사 탭은 위에서 이미 새로 썼습니다")
    return 0


# 숫자로 읽는 칸 — 가운데 정렬한다. 날짜 칸도 숫자다(그날 댓글 수).
# 나머지는 글이라 줄바꿈해서 보인다.
숫자로_읽는칸 = {"검색량", "뜬 키워드 수", "최고순위", "평균순위", "7일 댓글 수", "우리가 놓친"}


def 서식_칸묶음(header: list) -> tuple:
    """머리줄 → (가운데 정렬할 칸 묶음, 줄바꿈할 칸 묶음) · 순수함수.
    묶음은 (시작, 끝) — 끝 칸은 안 들어간다(구글 시트 range 와 같은 모양).

    ★칸 자리를 숫자로 적어 두지 않는다. 그렇게 적어 뒀다가 꼬리를 비운 뒤
      시작 칸이 끝 칸보다 커져 **서식이 매번 통째로 취소**되고 있었다
      (머리줄 고정·굵게·줄바꿈·폭 맞추기 전부. 2026-09-05 검수 중간 6).
      칸이 늘 때마다 또 어긋나므로 **이름으로** 고른다.
    """
    숫자냐 = [str(c).strip() in 숫자로_읽는칸
            or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c).strip()))
            for c in header or []]
    가운데, 줄바꿈 = [], []
    i = 0
    while i < len(숫자냐):
        j = i
        while j < len(숫자냐) and 숫자냐[j] == 숫자냐[i]:
            j += 1
        (가운데 if 숫자냐[i] else 줄바꿈).append((i, j))
        i = j
    # 앞의 두 칸(제품군·경쟁사)은 이름이라 줄바꿈하지 않는다 — 짧고, 얼어 있는 칸이다.
    return 가운데, [(a, b) for a, b in ((max(a, 2), b) for a, b in 줄바꿈) if a < b]


def _format_sheet(ws, payload: list) -> None:
    """보기 좋게 — 머리줄 고정·굵게, 숫자 가운데, 글 링크 줄바꿈. 실패해도 값은 이미 들어갔다."""
    가운데, 줄바꿈 = 서식_칸묶음(payload[0])
    try:
        sid = ws.id
        요청 = [
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
        ]
        요청 += [{"repeatCell": {                          # 숫자칸 가운데 정렬
            "range": {"sheetId": sid, "startRowIndex": 1,
                      "startColumnIndex": a, "endColumnIndex": b},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}} for a, b in 가운데]
        요청 += [{"repeatCell": {                          # 키워드·링크는 줄바꿈해서 보이게
            "range": {"sheetId": sid, "startRowIndex": 1,
                      "startColumnIndex": a, "endColumnIndex": b},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP",
                                           "verticalAlignment": "TOP"}},
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}} for a, b in 줄바꿈]
        요청.append({"autoResizeDimensions": {             # 꼬리 칸까지 폭을 맞춘다
            "dimensions": {"sheetId": sid, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": len(payload[0])}}})
        ws.spreadsheet.batch_update({"requests": 요청})
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
