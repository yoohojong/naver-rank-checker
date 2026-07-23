# -*- coding: utf-8 -*-
"""키워드 → 상위노출된 남의 글 → 댓글 → 경쟁 제품명 · 횟수.

사장님 정의(2026-07-23): 경쟁사 = 남의 글 댓글에서 팔리는 **제품**.

흐름
  1) 키워드 검색 (순위 검사와 같은 크롤러)
  2) 상위 구좌 카페 글 중 **우리 글 제외**
  3) 각 글의 댓글 가져오기 (로그인 없이 됨 — 2026-07-23 실증)
  4) 묻는 댓글 다음에 나온 제품명 추출 + 흐트러뜨린 글자 정리
  5) 제품군(시트 탭)별 · 제품별 횟수 집계

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

from src.comment_brand import extract_products, is_asking, normalize_name, tally  # noqa: E402
from src import comment_brand_llm  # noqa: E402
from src.crawler import Crawler  # noqa: E402
from src.parser import collect_slot_items  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CAFE_URL = re.compile(r"cafe\.naver\.com/([^/?#]+)/(\d+)")
_CLUB_ID = re.compile(r'g_sClubId\s*=\s*"(\d+)"')

# 우리 제품 — 세지 않는다(경쟁이 아니다). 흐트러진 표기도 정리 후 비교한다.
OUR_PRODUCT_HINTS = {"뽀얀", "얀샴푸"}


class CommentFetcher:
    """카페 글 → 댓글. 못 여는 글(회원 전용)은 조용히 건너뛴다."""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self._club: dict = {}
        self.stat = {"열림": 0, "막힘": 0}

    def comments(self, url: str) -> list:
        m = _CAFE_URL.search(url)
        if not m:
            return []
        slug, article = m.group(1), m.group(2)
        club = self._club.get(slug)
        if club is None:
            try:
                page = self.s.get(url, timeout=25)
                mm = _CLUB_ID.search(page.text)
                club = mm.group(1) if mm else ""
            except Exception:
                club = ""
            self._club[slug] = club
        if not club:
            self.stat["막힘"] += 1
            return []
        try:
            r = self.s.get(
                f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{club}"
                f"/articles/{article}/comments/pages/1?requestFrom=A",
                headers={"Referer": url}, timeout=25)
        except Exception:
            self.stat["막힘"] += 1
            return []
        if r.status_code != 200:
            self.stat["막힘"] += 1   # 회원 전용 카페 = 403
            return []
        try:
            res = r.json().get("result", {})
        except Exception:
            self.stat["막힘"] += 1
            return []
        items = res.get("comments")
        if isinstance(items, dict):
            items = items.get("items") or items.get("comments") or []
        self.stat["열림"] += 1
        return items if isinstance(items, list) else []


def tikitaka_texts(comments: list, *, window: int = 2) -> list:
    """묻는 댓글 바로 다음 window 개 — 사장님이 말한 '두 번째 댓글 티키타카' 자리."""
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


def mentions_from_comments(comments: list) -> list:
    """티키타카 자리 댓글 → 제품 언급. 판정은 LLM, 키 없으면 규칙으로 폴백."""
    texts = tikitaka_texts(comments)
    if not texts:
        return []
    names = comment_brand_llm.extract(texts)
    if names is None:                      # 키 없음·실패 → 규칙 폴백(적게 잡히지만 멈추지 않는다)
        out = []
        for t in texts:
            for shown, key, suffix in extract_products(t):
                out.append({"표시": shown, "키": key, "종류": suffix, "댓글": t[:120], "판정": "규칙"})
        return out
    joined = " / ".join(texts)[:200]
    return [{"표시": n, "키": normalize_name(n), "종류": "제품", "댓글": joined, "판정": "LLM"}
            for n in names]


def scan_keyword(crawler: CommentFetcher, kw: str, *, our_links: set, our_slugs: set,
                 fetcher: CommentFetcher, top_posts: int) -> list[dict]:
    """키워드 1건 → 그 키워드에서 나온 제품 언급 목록."""
    from src.competitor import is_our_item

    html = crawler.fetch_search(kw)
    items = [i for i in collect_slot_items(html) if i.kind == "cafe"]
    mentions: list[dict] = []
    seen_url: set = set()
    for it in items:
        if len(seen_url) >= top_posts:
            break
        if is_our_item(it.url, our_links, our_slugs):
            continue          # 우리 글은 보지 않는다 (사장님: "우리 글 말고 다른 글")
        if it.url in seen_url:
            continue
        seen_url.add(it.url)
        for m in mentions_from_comments(fetcher.comments(it.url)):
            m["키워드"] = kw
            m["글"] = it.url
            m["카페"] = it.source_name or ""
            mentions.append(m)
        time.sleep(1.0)       # 네이버 부담 줄이기
    return mentions


SHEET_HEADER = ["제품군", "경쟁 제품", "횟수", "나온 키워드 수", "확인일", "댓글 예시"]


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
    out_rows: list[list] = []

    for ws in client.spreadsheet.worksheets():
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
        keywords = [r[ik].strip() for r in rows[:args.limit]]
        print(f"[{product}] 키워드 {len(keywords)}개")

        mentions: list[dict] = []
        for kw in keywords:
            try:
                mentions.extend(scan_keyword(crawler, kw, our_links=set(),
                                             our_slugs=set(CAFE_WHITELIST),
                                             fetcher=fetcher, top_posts=args.top_posts))
            except Exception as e:          # 키워드 하나 실패가 전체를 죽이지 않는다
                print(f"   {kw} 건너뜀: {type(e).__name__}")
        for r in tally(mentions, exclude_keys=OUR_PRODUCT_HINTS):
            kws = {m["키워드"] for m in mentions if m["키"] == r["키"]}
            out_rows.append([product, r["제품"], r["횟수"], len(kws), today, r["댓글 예시"][:120]])
        print(f"[{product}] 경쟁 제품 {len([x for x in out_rows if x[0] == product])}종")

    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개")
    for row in out_rows[:30]:
        print(f"  {row[0]:<8}{row[1][:22]:<24}{row[2]:>3}회  키워드 {row[3]}개")

    if args.write_sheet and out_rows:
        from src.competitor import _get_or_create_ws
        ws, _ = _get_or_create_ws(client, "경쟁사", SHEET_HEADER)
        payload = [SHEET_HEADER] + out_rows
        # 격자를 내용에 맞춘 뒤 쓰고, 여유 줄은 빈 값으로 덮어 지난 줄이 안 남게 한다.
        ws.resize(rows=len(payload) + 10, cols=max(len(SHEET_HEADER), 8))
        blank = [""] * len(SHEET_HEADER)
        ws.update("A1", payload + [list(blank) for _ in range(10)], value_input_option="RAW")
        print(f"\n시트 '경쟁사' 갱신 — {len(out_rows)}줄")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="")
    ap.add_argument("--product", default="")
    ap.add_argument("--top-posts", type=int, default=4, help="키워드당 볼 남의 글 수")
    ap.add_argument("--out", default="")
    ap.add_argument("--from-sheet", action="store_true", help="시트 표시 탭의 키워드를 쓴다")
    ap.add_argument("--limit", type=int, default=25, help="제품군마다 볼 키워드 수")
    ap.add_argument("--write-sheet", action="store_true", help="'경쟁사' 탭에 결과를 쓴다")
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

    rows = tally(all_mentions, exclude_keys=OUR_PRODUCT_HINTS)
    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개")
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
