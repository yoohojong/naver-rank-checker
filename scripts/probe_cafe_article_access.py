# -*- coding: utf-8 -*-
"""실증 1건 — 서버에서 카페 글 본문·댓글을 로그인 없이 가져올 수 있는가?

이 답 하나로 '발행 검수' 자동화 설계가 갈린다:
  된다   → Actions 크론이 시트 link 를 읽어 자동 수집·검수 (직원 손 0)
  안 된다 → 직원 브라우저 확장이 도는 순간에만 수집 가능

사장님 PC·Claude 환경에서는 네이버 접속이 정책으로 막혀 있어 여기(Actions)서만 답이 나온다.
읽기만 한다 — 시트도 카페도 아무것도 쓰지 않는다.

실행:  python -m scripts.probe_cafe_article_access
환경:  SPREADSHEET_ID, SERVICE_ACCOUNT_JSON (기존 워크플로와 동일)
       PROBE_LIMIT (선택, 기본 3) — 몇 개 글을 찔러볼지
"""
from __future__ import annotations

import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sheets import SheetsClient  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CAFE_LINK = re.compile(r"cafe\.naver\.com/(?:f-e/cafes/(\d+)/articles/(\d+)|([^/?#]+)/(\d+))")


def 링크모으기(limit: int) -> list[str]:
    """시트에서 카페 글 링크를 몇 개만 꺼낸다(읽기 전용)."""
    sid = os.environ.get("SPREADSHEET_ID", "")
    sa = os.environ.get("SERVICE_ACCOUNT_JSON", "")
    if not sid or not sa:
        print("SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 이 없습니다.")
        return []
    sc = SheetsClient(sid, sa)
    out: list[str] = []
    for ws in sc.spreadsheet.worksheets():
        제외 = ("백업", "삭제전", "복사본", "이력", "스테이징")
        if "카외" not in ws.title or any(x in ws.title for x in 제외):
            continue
        try:
            rows = ws.get_all_values()
        except Exception as e:
            print(f"  탭 '{ws.title}' 읽기 실패: {type(e).__name__}")
            continue
        for row in rows:
            for cell in row:
                if not isinstance(cell, str):
                    continue
                link = cell.strip()
                if link.startswith("http") and CAFE_LINK.search(link):
                    if link not in out:
                        out.append(link)
                    if len(out) >= limit:
                        print(f"  탭 '{ws.title}' 에서 링크 수집 — 총 {len(out)}개")
                        return out
    print(f"  링크 {len(out)}개 수집")
    return out


def 찔러보기(url: str) -> dict:
    m = CAFE_LINK.search(url)
    cafe_id, art_id = (m.group(1), m.group(2)) if m.group(1) else (None, m.group(4))
    slug = m.group(3)
    r: dict = {"url": url, "cafeId": cafe_id, "slug": slug, "articleId": art_id}

    def 부르기(이름, addr, **kw):
        try:
            resp = requests.get(addr, headers={"User-Agent": UA, **kw.pop("headers", {})},
                                timeout=25, **kw)
            r[이름] = {"status": resp.status_code, "len": len(resp.text)}
            if resp.status_code != 200 or len(resp.text) < 300:
                r[이름]["맛보기"] = " ".join(resp.text[:180].split())
            return resp
        except Exception as e:
            r[이름] = {"error": type(e).__name__}
            return None

    # ① 사람이 보는 주소 그대로
    resp = 부르기("①페이지", url)
    if resp is not None and resp.status_code == 200:
        r["①페이지"]["본문DOM"] = bool(
            re.search(r"(se-main-container|article_viewer|ArticleContentBox|postViewArea)", resp.text))
        r["①페이지"]["로그인유도"] = "nid.naver.com" in resp.text[:20000]

    # slug 만 있으면 cafeId 를 얻는다.
    # 1차 실증: CafeGate.json 이 87자짜리 빈 응답을 줘 cafeId 를 못 얻었고
    # 그래서 정작 중요한 글·댓글 API 를 한 번도 못 찔러봤다 → 글 페이지 HTML 에서 뽑는다.
    global_id = cafe_id
    if not global_id and resp is not None and getattr(resp, "text", ""):
        for pat in (r'"cafeId"\s*:\s*"?(\d{4,})', r'g_sClubId\s*=\s*"(\d+)"',
                    r'clubid=(\d+)', r'cafes/(\d+)/'):
            mm = re.search(pat, resp.text)
            if mm:
                global_id = mm.group(1)
                r["②카페번호"] = {"찾음": global_id, "출처": pat}
                break
        else:
            r["②카페번호"] = {"찾음": None}

    if global_id:
        resp = 부르기("③글API",
                     f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{global_id}/articles/{art_id}",
                     headers={"Referer": url})
        if resp is not None and resp.status_code == 200:
            try:
                res = resp.json().get("result", {})
                art = res.get("article", res)
                r["③글API"]["제목있음"] = bool(art.get("subject"))
                r["③글API"]["본문있음"] = bool(art.get("contentHtml") or art.get("content"))
            except Exception:
                pass
        resp = 부르기("④댓글API",
                     f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{global_id}"
                     f"/articles/{art_id}/comments/pages/1?requestFrom=A",
                     headers={"Referer": url})
        if resp is not None and resp.status_code == 200:
            try:
                cs = resp.json().get("result", {}).get("comments", [])
                r["④댓글API"]["댓글수"] = len(cs)
            except Exception:
                pass
    return r


def main() -> int:
    limit = int(os.environ.get("PROBE_LIMIT", "3"))
    print("=== 발행 검수 · 카페 글 서버 접근 실증 ===")
    링크 = 링크모으기(limit)
    if not 링크:
        print("찔러볼 카페 링크를 못 찾았습니다.")
        return 2

    결과 = [찔러보기(u) for u in 링크]
    print(json.dumps(결과, ensure_ascii=False, indent=1))

    본문성공 = sum(1 for r in 결과 if (r.get("③글API") or {}).get("본문있음"))
    댓글성공 = sum(1 for r in 결과 if (r.get("④댓글API") or {}).get("댓글수"))
    print("\n=== 판정 ===")
    print(f"  본문 가져옴 {본문성공}/{len(결과)} · 댓글 가져옴 {댓글성공}/{len(결과)}")
    if 본문성공 and 댓글성공:
        print("  → 서버 자동 크롤링 가능. 크론이 알아서 검수한다(직원 손 0).")
    elif 본문성공:
        print("  → 본문만 가능. 댓글은 직원 확장이 필요하다(반쪽 자동).")
    else:
        print("  → 서버로는 못 읽는다. 직원 확장이 유일한 길이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
