"""댓글 계정 길 (작업 가지 전용 · 카드 t_7d0ced83) — 읽기만 · 로그인 0 · AI 0 · 시트 0 · 열쇠 0.

할 일 파일(JSON 목록)의 줄 하나 = 일 하나. 갈래 셋:
  search : {"kind":"search","cafeId","aid","title","cafeName"} — 글 제목을 통합검색 카페 탭(ssc=tab.cafe.all)에 쳐서
           그 글 주소(바깥 검색 열쇠 art)를 찾고 → 글(v2.1) · 댓글(v3, 댓글 쓴이 열쇠 포함)을 읽는다(사장님 11-14 방법).
  url    : {"kind":"url","url"} — 이미 바깥 검색 열쇠가 붙은 주소(앞 순위 받기의 카페 칸 글) → 글 · 댓글만 읽는다.
  writer : {"kind":"writer","cafeId","key","nick"} — 카페 안 글쓴이 검색(searchBy=3)으로 그 계정이 쓴 글 제목 목록.
못 읽은 칸은 status '못 봄' + why(응답 번호 · 원문 앞부분)로 남긴다 — 찾은 것으로 세지 않는다.

쓰는 법: python -m scripts.antitro_comment_path --items data/antitro_cp_items.json --shard 0 --shards 6 --out out.jsonl
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crawler import Crawler, CircuitBreakerOpen  # noqa: E402

NAME = re.compile(r"안[^가-힣a-z0-9]{0,3}티[^가-힣a-z0-9]{0,3}트[^가-힣a-z0-9]{0,3}로|큐[^가-힣]{0,2}레[^가-힣]{0,2}브|antitro|curev", re.I)
TAG = re.compile(r"<[^>]+>")
H = {"Accept": "application/json", "x-cafe-product": "pc"}


def now() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def get(cr: Crawler, url: str, referer: str = "https://search.naver.com/", js: bool = True):
    if "search.naver.com" in url:
        cr.slowdown.wait()
    else:
        time.sleep(0.6)
    r = cr.session.get(url, headers={**cr._headers(), **(H if js else {}), "Referer": referer}, timeout=25)
    if r.status_code == 429:
        cr.slowdown.on_block_detected()
    else:
        cr.slowdown.on_success()
    return r


def find_art(cr: Crawler, it: dict) -> tuple[str, str, list]:
    """제목으로 카페 탭 검색 → 그 글 번호의 art 주소. 검색어 셋을 차례로(제목 / "제목" / 제목 + 카페 이름)."""
    aid = str(it["aid"])
    pat = re.compile(r"https?://cafe\.naver\.com/[^/\"'?#]+/" + aid + r"\?art=[^\"'&<\s]+")
    tried = []
    qs = [it["title"], f'"{it["title"]}"']
    if it.get("cafeName"):
        qs.append(f'{it["title"]} {it["cafeName"]}')
    for q in qs:
        r = get(cr, "https://search.naver.com/search.naver?" + urllib.parse.urlencode({"ssc": "tab.cafe.all", "query": q}), js=False)
        txt = r.text.replace("&amp;", "&")
        if re.search(r"captcha|자동입력 방지|이용이 제한", txt[:20000], re.I) and r.status_code != 200:
            raise CircuitBreakerOpen("검색 화면 막힘(captcha/이용 제한)")
        m = pat.search(txt)
        tried.append({"q": q, "st": r.status_code, "카페글주소수": len(re.findall(r"cafe\.naver\.com/[^/\"'?#]+/\d+\?art=", txt)), "hit": bool(m)})
        if m:
            return m.group(0), q, tried
        time.sleep(1.5)
    return "", "", tried


def read_post(cr: Crawler, url: str, club: str = "") -> dict:
    m = re.search(r"cafe\.naver\.com/([^/?#]+)/(\d+)", url)
    tok = re.search(r"[?&]art=([^&#]+)", url)
    if not m:
        return {"status": "못 봄", "why": "주소 꼴 다름"}
    aid, art = m.group(2), (tok.group(1) if tok else "")
    if not club:
        page = get(cr, url, js=False)
        mm = re.search(r'g_sClubId\s*=\s*"(\d+)"', page.text) or re.search(r"clubid=(\d+)", page.text, re.I)
        club = mm.group(1) if mm else ""
    if not club:
        return {"status": "못 봄", "why": "카페 번호 못 받음"}
    rec: dict = {"cafeId": club, "aid": aid, "slug": m.group(1)}
    r = get(cr, f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{club}/articles/{aid}?useCafeId=true&requestFrom=A"
                + (f"&art={art}" if art else ""), referer=url)
    rec["글응답"] = r.status_code
    if r.status_code != 200:
        rec.update(status="못 봄", why=f"글 {r.status_code} {r.text[:200]}")
        return rec
    a = (r.json().get("result") or {}).get("article") or {}
    w = a.get("writer") or {}
    body = TAG.sub(" ", a.get("contentHtml") or "")
    rec["글"] = {"제목": a.get("subject"), "글쓴이키": w.get("memberKey") or "", "글쓴이": w.get("nick") or "",
                "본문_이름": bool(NAME.search(body or "") or NAME.search(a.get("subject") or "")),
                "본문_이름줄": [body[max(0, x.start() - 60):x.end() + 60] for x in NAME.finditer(body)][:5],
                "날짜": a.get("writeDate"), "댓글수": a.get("commentCount")}
    cs, cursor = [], ""
    for _ in range(20):
        r = get(cr, f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{club}/articles/{aid}/comments"
                    f"?fromObjectId={cursor}&limit=100&orderBy=asc" + (f"&art={art}" if art else ""), referer=url)
        if r.status_code != 200:
            rec["댓글응답"] = f"{r.status_code} {r.text[:200]}"
            break
        res = r.json().get("result") or {}
        items = (res.get("comments") or {}).get("items") or res.get("items") or []
        if not items:
            break
        cs.extend(items)
        if not res.get("hasNext"):
            break
        nxt = str(items[-1].get("id") or "")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    rec["댓글"] = [{"키": (c.get("writer") or {}).get("memberKey") or "", "닉": (c.get("writer") or {}).get("nick") or "",
                   "글쓴이댓글": bool(c.get("isArticleWriter")), "지움": bool(c.get("isDeleted")),
                   "이름": bool(NAME.search(c.get("content") or "")), "내용": (c.get("content") or "")[:300]} for c in cs]
    rec["status"] = "읽음"
    return rec


def writer_posts(cr: Crawler, it: dict) -> dict:
    out: list = []
    rec: dict = {"status": "읽음"}
    for page in range(1, 6):
        url = (f"https://apis.cafe.naver.com/search/v2/cafes/{it['cafeId']}/search/articles?"
               + urllib.parse.urlencode({"query": it["nick"], "perPage": "50", "page": str(page), "menuId": "0",
                                         "searchBy": "3", "views": "MEMBER_LEVEL,COUNT,SALE_INFO,CAFE_MENU"}))
        r = get(cr, url, referer=f"https://cafe.naver.com/f-e/cafes/{it['cafeId']}/menus/0")
        if r.status_code != 200:
            rec.update(status="못 봄" if not out else "일부", why=f"검색 {r.status_code} {r.text[:200]}")
            break
        res = r.json().get("result") or {}
        arts = [x.get("item", x) for x in (res.get("articleList") or [])]
        for x in arts:
            wk = (x.get("writerInfo") or {}).get("memberKey") or ""
            if wk == it["key"]:
                out.append({"글번호": x.get("articleId"), "제목": x.get("subject"), "날짜": (x.get("addDate") or "")[:16],
                            "댓글수": x.get("commentCount")})
        if len(arts) < 50:
            break
    rec["글_목록"] = out
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    items = json.load(open(a.items, encoding="utf-8"))
    mine = [x for i, x in enumerate(items) if i % a.shards == a.shard]
    print(f"일 {len(items)} 중 이 묶음({a.shard}/{a.shards}) {len(mine)}", flush=True)
    cr = Crawler()
    cr.warmup()
    stop = ""
    with open(a.out, "a", encoding="utf-8") as f:
        for n, it in enumerate(mine, 1):
            rec = {"일": it, "at": now()}
            if stop:
                rec.update(status="못 봄", why=stop, err=True)
            else:
                try:
                    if it["kind"] == "search":
                        hit, q, tried = find_art(cr, it)
                        rec["찾기"] = tried
                        if not hit:
                            rec.update(status="못 봄", why="통합검색 카페 탭에 그 글 주소(art 열쇠)가 안 나옴(검색어 %d개)" % len(tried))
                        else:
                            rec["주소"], rec["맞은검색어"] = hit, q
                            rec.update(read_post(cr, hit, str(it.get("cafeId") or "")))
                    elif it["kind"] == "url":
                        rec["주소"] = it["url"]
                        rec.update(read_post(cr, it["url"], str(it.get("cafeId") or "")))
                    else:
                        rec.update(writer_posts(cr, it))
                except CircuitBreakerOpen as e:
                    stop = f"막힘 연속 — 이 뒤 안 부름: {e}"
                    rec.update(status="못 봄", why=stop, err=True)
                except Exception as e:
                    rec.update(status="못 봄", why=f"{type(e).__name__}: {str(e)[:200]}", err=True)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0:
                print(f"  {n}/{len(mine)}", flush=True)
            time.sleep(1.0)
    print("끝 · 멈춤:", stop or "없음", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
