# -*- coding: utf-8 -*-
"""발행 검수 · 1단계 수집 — 시트의 카페 링크 → 검수기가 읽는 JSON.

실증(run 29980014187)으로 확인된 것만 쓴다:
  - 비로그인으로 본문·댓글이 온다(공개 카페). 12칸 정본 글 12/20 확인.
  - 댓글에 writer(닉네임)·isRef(답글)·isArticleWriter(글쓴이) 가 있다.
    → 닉네임 대조보다 정확하게 글쓴이를 집어낼 수 있다.

출력 스키마 = team-project/cafe-external/발행본_검수.py 입력과 동일:
  {url, keyword, title, body, photos, author, comments[{author,text,depth}]}
  단계·질병은 이 레포가 모르므로 검수 쪽에서 배치목록으로 채운다.

차단 회피는 레포 표준(curl_cffi chrome131 + 3.5~5초 간격)을 따른다.
읽기만 한다 — 시트도 카페도 쓰지 않는다.

환경: SPREADSHEET_ID, SERVICE_ACCOUNT_JSON / COLLECT_LIMIT(기본 30) / OUT(기본 발행본.json)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time

from curl_cffi import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sheets import SheetsClient  # noqa: E402

IMPERSONATE = "chrome131"
CAFE_LINK = re.compile(r"cafe\.naver\.com/(?:f-e/cafes/(\d+)/articles/(\d+)|([^/?#]+)/(\d+))")
제외탭 = ("백업", "삭제전", "복사본", "이력", "스테이징")


def 쉬기():
    time.sleep(random.uniform(3.5, 5.25))


def 본문풀기(html: str) -> tuple[str, int]:
    """카페 본문 HTML → 검수기가 읽는 텍스트. 사진 자리는 (사진N) 으로 남긴다."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    사진 = [0]

    def 사진자리(_m):
        사진[0] += 1
        return f"\n(사진{사진[0]})\n"

    t = re.sub(r"<img\b[^>]*>", 사진자리, t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|h\d)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("​", "")
          .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    줄 = [ln.strip() for ln in t.splitlines()]
    본문 = "\n".join(ln for ln in 줄 if ln)
    return re.sub(r"\n{3,}", "\n\n", 본문).strip(), 사진[0]


def 시트링크(limit: int) -> list[tuple[str, str]]:
    """[(링크, 키워드)] — 최근 발행분이 아래에 쌓이므로 뒤에서부터."""
    sid, sa = os.environ.get("SPREADSHEET_ID", ""), os.environ.get("SERVICE_ACCOUNT_JSON", "")
    sc = SheetsClient(sid, sa)
    본, 키 = [], set()
    for ws in sc.spreadsheet.worksheets():
        if "카외" not in ws.title or any(x in ws.title for x in 제외탭):
            continue
        rows = ws.get_all_values()
        if not rows:
            continue
        헤더 = rows[0]
        kw열 = next((i for i, h in enumerate(헤더) if h.strip() == "키워드"), None)
        for row in reversed(rows[1:]):
            링크 = next((c.strip() for c in row
                        if isinstance(c, str) and c.strip().startswith("http")
                        and CAFE_LINK.search(c)), None)
            if not 링크:
                continue
            m = CAFE_LINK.search(링크)
            ident = (m.group(1) or m.group(3), m.group(2) or m.group(4))
            if ident in 키:
                continue
            키.add(ident)
            본.append((링크, (row[kw열].strip() if kw열 is not None and kw열 < len(row) else "")))
            if len(본) >= limit:
                return 본
    return 본


def 한건(link: str, keyword: str) -> dict | None:
    m = CAFE_LINK.search(link)
    cafe_id, art_id = (m.group(1), m.group(2)) if m.group(1) else (None, m.group(4))

    page = requests.get(link, impersonate=IMPERSONATE, timeout=25)
    쉬기()
    gid = cafe_id
    if not gid:
        mm = re.search(r'g_sClubId\s*=\s*"(\d+)"', page.text or "")
        gid = mm.group(1) if mm else None
    if not gid:
        return {"url": link, "keyword": keyword, "_실패": "카페번호 못 찾음"}

    a = requests.get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{gid}/articles/{art_id}",
                     impersonate=IMPERSONATE, timeout=25, headers={"Referer": link})
    쉬기()
    if a.status_code != 200:
        return {"url": link, "keyword": keyword, "_실패": f"글 못 읽음({a.status_code})"}
    res = a.json().get("result", {})
    art = res.get("article", res)
    본문, 사진 = 본문풀기(art.get("contentHtml") or art.get("content") or "")
    글쓴이 = (art.get("writer") or {})
    글쓴이닉 = 글쓴이.get("nick") or 글쓴이.get("nickName") or ""

    c = requests.get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{gid}"
                     f"/articles/{art_id}/comments/pages/1?requestFrom=A&orderBy=asc&perPage=100",
                     impersonate=IMPERSONATE, timeout=25, headers={"Referer": link})
    쉬기()
    댓글 = []
    if c.status_code == 200:
        body = c.json()
        cres = body.get("result") or (body.get("message") or {}).get("result") or {}
        cs = cres.get("comments", [])
        if isinstance(cs, dict):
            cs = cs.get("items", [])
        for x in cs:
            if x.get("isDeleted"):
                continue
            w = x.get("writer") or {}
            닉 = w.get("nick") or w.get("nickName") or ""
            # 글쓴이 판별은 닉네임 대조보다 API 플래그가 정확하다(실증 확인)
            if x.get("isArticleWriter") and 글쓴이닉:
                닉 = 글쓴이닉
            텍스트, _ = 본문풀기(x.get("content") or "")
            댓글.append({"author": 닉, "text": 텍스트,
                         "depth": 1 if x.get("isRef") else 0})

    return {
        "url": link, "keyword": keyword,
        "title": (art.get("subject") or "").strip(),
        "body": 본문, "photos": 사진,
        "author": 글쓴이닉, "comments": 댓글,
    }


def main() -> int:
    limit = int((os.environ.get("COLLECT_LIMIT") or "30").strip() or "30")
    out = os.environ.get("OUT") or "발행본.json"
    print(f"=== 발행 검수 · 수집 (최대 {limit}건) ===", flush=True)
    목록 = 시트링크(limit)
    print(f"  시트에서 고유 글 {len(목록)}건", flush=True)

    모음 = []
    for i, (link, kw) in enumerate(목록, 1):
        print(f"  [{i}/{len(목록)}] {kw or '?'} · {link.split('?')[0]}", flush=True)
        try:
            r = 한건(link, kw)
        except Exception as e:
            r = {"url": link, "keyword": kw, "_실패": f"{type(e).__name__}"}
        if r:
            모음.append(r)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(모음, f, ensure_ascii=False, indent=1)

    성공 = [x for x in 모음 if not x.get("_실패")]
    십이 = [x for x in 성공 if len(x.get("comments") or []) == 12]
    print(f"\n=== 수집 끝 — {len(성공)}/{len(모음)}건 · 댓글 12칸 {len(십이)}건 → {out}")
    for x in 모음:
        if x.get("_실패"):
            print(f"   ✗ {x['keyword']}: {x['_실패']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
