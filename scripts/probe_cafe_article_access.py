# -*- coding: utf-8 -*-
"""발행 검수 실증 v2 — 서버에서 카페 글을 '검수에 쓸 만큼' 온전히 가져올 수 있는가?

v1 은 결론이 성급했다(독립검증 판정 '성급함'). 고친 것:
  - 표본 중복: URL 문자열로 중복을 걸러 같은 글이 두 번 셌다 → (cafeId, articleId) 로.
  - 12칸 정본 글 미검증: 우리 정본은 댓글 12칸인데 표본이 3개짜리였다 → 표본을 넓혀
    **댓글 12개인 글을 찾는 것 자체를 목표**로 둔다.
  - 본문 온전성 미확인: 키 존재만 봤다 → 태그 제거 글자수 + 앞/끝 100자를 찍는다
    (끝이 살아 있어야 잘린 게 아니다).
  - 댓글 완전성 미확인: 개수만 셌다 → totalCount·페이지정보·첫 댓글의 **필드 키 전체**를
    찍는다. 검수기는 닉네임과 답글깊이가 있어야 돌아간다.
  - 차단 위험: plain requests 로 간격 없이 불렀다. 이 레포는 그 방식으로 네이버에
    차단당한 이력이 있어 curl_cffi(TLS 지문 위장)+3.5~5초 간격을 쓴다 → 같은 방식으로.

읽기만 한다. 시트도 카페도 쓰지 않는다.

환경: SPREADSHEET_ID, SERVICE_ACCOUNT_JSON / PROBE_LIMIT(기본 20)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time

from curl_cffi import requests            # 레포 표준(차단 회피)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sheets import SheetsClient  # noqa: E402

IMPERSONATE = "chrome131"
CAFE_LINK = re.compile(r"cafe\.naver\.com/(?:f-e/cafes/(\d+)/articles/(\d+)|([^/?#]+)/(\d+))")
간격 = lambda: random.uniform(3.5, 5.25)   # noqa: E731 — 레포 표준 간격


def 태그빼기(html: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"[ \t]+", " ", t).strip()


def 링크모으기(limit: int) -> list[str]:
    sid, sa = os.environ.get("SPREADSHEET_ID", ""), os.environ.get("SERVICE_ACCOUNT_JSON", "")
    if not sid or not sa:
        print("SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 이 없습니다.")
        return []
    sc = SheetsClient(sid, sa)
    제외 = ("백업", "삭제전", "복사본", "이력", "스테이징")
    본, 키 = [], set()
    for ws in sc.spreadsheet.worksheets():
        if "카외" not in ws.title or any(x in ws.title for x in 제외):
            continue
        try:
            rows = ws.get_all_values()
        except Exception as e:
            print(f"  탭 '{ws.title}' 읽기 실패: {type(e).__name__}")
            continue
        before = len(본)
        # ★최근 발행분이 아래쪽에 쌓이므로 뒤에서부터 — 12칸 정본(2026-07-22 확정)을 만날 확률↑
        for row in reversed(rows):
            for cell in row:
                if not isinstance(cell, str):
                    continue
                link = cell.strip()
                if not link.startswith("http"):
                    continue
                m = CAFE_LINK.search(link)
                if not m:
                    continue
                ident = (m.group(1) or m.group(3), m.group(2) or m.group(4))   # 같은 글은 한 번만
                if ident in 키:
                    continue
                키.add(ident)
                본.append(link)
                if len(본) >= limit:
                    print(f"  '{ws.title}' 까지 {len(본)}건 수집(고유 글 기준)")
                    return 본
        print(f"  '{ws.title}' 에서 +{len(본)-before}건")
    print(f"  총 {len(본)}건(고유 글)")
    return 본


def 찔러보기(url: str) -> dict:
    m = CAFE_LINK.search(url)
    cafe_id, art_id = (m.group(1), m.group(2)) if m.group(1) else (None, m.group(4))
    r: dict = {"url": url.split("?")[0], "slug": m.group(3), "articleId": art_id}

    def 부르기(addr, ref=None):
        try:
            return requests.get(addr, impersonate=IMPERSONATE, timeout=25,
                                headers={"Referer": ref} if ref else None)
        except Exception as e:
            return type("X", (), {"status_code": -1, "text": f"{type(e).__name__}"})()

    page = 부르기(url)
    r["페이지"] = {"status": page.status_code, "len": len(page.text)}
    time.sleep(간격())

    gid = cafe_id
    if not gid:
        for pat in (r'g_sClubId\s*=\s*"(\d+)"', r'"cafeId"\s*:\s*"?(\d{4,})', r'clubid=(\d+)'):
            mm = re.search(pat, page.text or "")
            if mm:
                gid = mm.group(1)
                break
    r["cafeId"] = gid
    if not gid:
        r["판정"] = "카페번호 못 찾음"
        return r

    a = 부르기(f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{gid}/articles/{art_id}", url)
    r["글API"] = {"status": a.status_code}
    time.sleep(간격())
    if a.status_code == 200:
        try:
            res = a.json().get("result", {})
            art = res.get("article", res)
            본문 = 태그빼기(art.get("contentHtml") or art.get("content") or "")
            r["글API"].update({
                "제목": (art.get("subject") or "")[:40],
                "본문글자수": len(re.sub(r"\s", "", 본문)),
                "본문_앞": 본문[:80].replace("\n", " "),
                "본문_끝": 본문[-80:].replace("\n", " "),     # 끝이 살아야 안 잘린 것
                "작성자": (art.get("writer") or {}).get("nick") or (art.get("writer") or {}).get("nickName"),
            })
        except Exception as e:
            r["글API"]["파싱실패"] = type(e).__name__

    c = 부르기(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{gid}"
               f"/articles/{art_id}/comments/pages/1?requestFrom=A&orderBy=asc&perPage=100", url)
    r["댓글API"] = {"status": c.status_code}
    time.sleep(간격())
    if c.status_code == 200:
        try:
            cres = c.json().get("result", {})
            cs = cres.get("comments", [])
            r["댓글API"].update({
                "가져온수": len(cs),
                "전체수": cres.get("commentCount") or (cres.get("pageInfo") or {}).get("totalCount"),
                "페이지정보": cres.get("pageInfo"),
                "첫댓글_필드키": sorted((cs[0] or {}).keys())[:25] if cs else [],
                "닉네임_예": ((cs[0] or {}).get("writer") or {}).get("nick") if cs else None,
                "답글관계_후보": [k for k in (cs[0] or {}) if k.lower() in
                                  ("isref", "refid", "parentid", "depth", "refcommentid")] if cs else [],
            })
        except Exception as e:
            r["댓글API"]["파싱실패"] = type(e).__name__
    return r


def main() -> int:
    limit = int((os.environ.get("PROBE_LIMIT") or "20").strip() or "20")
    print(f"=== 발행 검수 · 카페 글 서버 접근 실증 v2 (표본 {limit}건) ===")
    링크 = 링크모으기(limit)
    if not 링크:
        print("찔러볼 카페 링크를 못 찾았습니다.")
        return 2

    결과 = []
    for i, u in enumerate(링크, 1):
        print(f"  [{i}/{len(링크)}] {u.split('?')[0]}", flush=True)
        결과.append(찔러보기(u))
    print(json.dumps(결과, ensure_ascii=False, indent=1))

    본문ok = [r for r in 결과 if (r.get("글API") or {}).get("본문글자수", 0) > 300]
    댓글ok = [r for r in 결과 if (r.get("댓글API") or {}).get("가져온수", 0) > 0]
    십이칸 = [r for r in 결과 if (r.get("댓글API") or {}).get("가져온수", 0) == 12]
    필드ok = [r for r in 결과 if (r.get("댓글API") or {}).get("닉네임_예")
              and (r.get("댓글API") or {}).get("답글관계_후보")]

    print("\n=== 판정 ===")
    print(f"  고유 글 {len(결과)}건")
    print(f"  본문 300자 이상 가져옴 : {len(본문ok)}")
    print(f"  댓글 1개 이상 가져옴   : {len(댓글ok)}")
    print(f"  ★댓글 정확히 12개(정본): {len(십이칸)}")
    print(f"  닉네임+답글관계 필드 확인: {len(필드ok)}")
    if 십이칸 and 필드ok:
        print("  → 12칸 정본 글을 검수에 쓸 만큼 온전히 가져온다. 서버 자동화 근거 확보.")
    elif 본문ok and 댓글ok:
        print("  → 본문·댓글은 오지만 12칸 정본 글이 표본에 없다. 아직 확정 못 함.")
    else:
        print("  → 서버로는 부족하다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
