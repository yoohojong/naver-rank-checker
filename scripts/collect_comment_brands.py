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

from src.comment_brand import extract_candidates, is_asking, normalize_name, tally  # noqa: E402
from src import brand_verdicts  # noqa: E402
from src import comment_brand_llm  # noqa: E402
from src.crawler import Crawler  # noqa: E402
from src.parser import cafe_slug_of, is_known_url  # noqa: E402
from src.parser import collect_slot_items  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CAFE_URL = re.compile(r"cafe\.naver\.com/([^/?#]+)/(\d+)")
_CLUB_ID = re.compile(r'g_sClubId\s*=\s*"(\d+)"')

# 우리 제품 — 세지 않는다(경쟁이 아니다). 흐트러뜨린 표기·되살린 표기 둘 다 막는다.
# 샴푸만 넣어놨다가 바디워시 표기('ㅃ얀 바디워시')가 표에 남았다(2026-07-23 실측) → 브랜드로 막는다.
OUR_PRODUCT_HINTS = {"뽀얀", "얀"}

# 제품이 아니라 '무엇'을 가리키는 말 — 표에 들어가면 안 된다.
# 실측에서 '지루성두피염샴푸' 가 제품처럼 올라왔다(2026-07-23).
NOT_A_BRAND = {
    "샴푸", "탈모샴푸", "비듬샴푸", "지루성샴푸", "지루성두피염샴푸", "두피샴푸",
    "바디워시", "바디로션", "트리트먼트", "린스", "크림", "앰플", "토닉",
    "약국", "병원", "피부과", "대학병원", "올리브영", "공홈", "본사",
    "스테로이드", "항생제", "소염제", "영양제", "유산균", "케토코나졸", "미녹시딜",
}


def is_real_brand(name: str) -> bool:
    """표에 넣을 만한 브랜드인가 — 일반 명칭·장소는 뺀다."""
    key = normalize_name(name)
    if len(key) < 2:
        return False
    return key not in {normalize_name(x) for x in NOT_A_BRAND}


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


def is_our_item(url: str, our_links: set, our_slugs: set) -> bool:
    """우리 글인지 — 시트 link 매치 또는 우리 카페 slug 매치. (사장님: "우리 글 말고 다른 글")"""
    if is_known_url(url, our_links):
        return True
    slug = cafe_slug_of(url)
    return bool(slug and slug in (our_slugs or set()))


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


def candidates_from_comments(comments: list) -> list:
    """티키타카 자리 댓글 → 제품 **후보**. 제품이냐 아니냐는 여기서 정하지 않는다."""
    out = []
    for t in tikitaka_texts(comments):
        for shown, key, suffix in extract_candidates(t):
            out.append({"표시": shown, "키": key, "종류": suffix, "댓글": t[:120]})
    return out


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

    fresh, stat = comment_brand_llm.judge(unknown)
    stat["캐시적중"] = len({m["키"] for m in (mentions or [])}) - len(unknown)
    verdicts = brand_verdicts.merge(cached, fresh, today=today)
    if fresh:
        brand_verdicts.save(verdicts, verdict_path)
    return verdicts, stat


def confirmed_rows(mentions: list, verdicts: dict) -> list:
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
        if not is_real_brand(name):        # 마지막 그물 — 종류 이름·장소가 판정을 뚫어도 여기서 막는다
            continue
        kept.append({**m, "표시": name, "키": normalize_name(name)})
    rows = tally(kept, exclude_keys=OUR_PRODUCT_HINTS)
    for r in rows:                          # 몇 개 키워드에서 나왔나 (같은 브랜드끼리 합쳐서 센다)
        r["키워드수"] = len({m.get("키워드") for m in kept
                          if m["키"] == r["키"] and m.get("키워드")})
    return rows


def scan_keyword(crawler: CommentFetcher, kw: str, *, our_links: set, our_slugs: set,
                 fetcher: CommentFetcher, top_posts: int) -> list[dict]:
    """키워드 1건 → 그 키워드에서 나온 제품 언급 목록."""
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
        for m in candidates_from_comments(fetcher.comments(it.url)):
            m["키워드"] = kw
            m["글"] = it.url
            m["카페"] = it.source_name or ""
            mentions.append(m)
        time.sleep(1.0)       # 네이버 부담 줄이기
    return mentions


SHEET_HEADER = ["제품군", "경쟁 제품", "횟수", "나온 키워드 수", "확인일", "댓글 예시"]

# 판정을 못 받은 후보가 이만큼을 넘으면 시트를 덮지 않는다.
# 반쪽짜리 표를 어제 표 위에 덮으면, 사장님은 그게 오늘의 전부인 줄 알게 된다.
MAX_UNJUDGED_RATIO = 0.2


def should_skip_write(stat: dict) -> bool:
    """판정이 많이 비었나 — 비었으면 시트를 덮지 않는다 · 순수함수."""
    asked = int((stat or {}).get("후보") or 0)
    if not asked:
        return False                        # 물어볼 게 없던 run 은 정상
    return (int(stat.get("미판정") or 0) / asked) > MAX_UNJUDGED_RATIO


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
        print(f"[{product}] 제품 후보 {len({m['키'] for m in mentions})}종")

    # 후보를 한데 모아 한 번에 판정한다 — 제품군이 달라도 같은 이름은 한 번만 묻는다.
    all_mentions = [m for ms in by_product.values() for m in ms]
    verdicts, jstat = judge_candidates(all_mentions, today=today)

    out_rows: list[list] = []
    for product, mentions in by_product.items():
        for r in confirmed_rows(mentions, verdicts):
            out_rows.append([product, r["제품"], r["횟수"], r["키워드수"], today,
                             r["댓글 예시"][:120]])
        print(f"[{product}] 경쟁 제품 {len([x for x in out_rows if x[0] == product])}종")

    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개")
    print(f"후보 {jstat['후보'] + jstat.get('캐시적중', 0)}종 "
          f"(전에 판정해둔 것 {jstat.get('캐시적중', 0)}종 · 새로 물어본 것 {jstat['판정']}종 "
          f"· 판정 못 받음 {jstat['미판정']}종)")
    for row in out_rows[:30]:
        print(f"  {row[0]:<8}{row[1][:22]:<24}{row[2]:>3}회  키워드 {row[3]}개")

    # 판정이 많이 빈 run 은 표를 덮지 않는다 — 반쪽 표가 오늘의 전부로 읽히면 안 된다.
    if should_skip_write(jstat):
        print(f"\n❌ 제품명 판정이 {jstat['미판정']}/{jstat['후보']}종 비었습니다 "
              f"(Groq 하루 한도·오류 의심). 시트는 손대지 않았습니다 — 어제 값 그대로입니다.")
        return 3

    if args.write_sheet and out_rows:
        import gspread
        try:
            ws = client.spreadsheet.worksheet("경쟁사")
        except gspread.exceptions.WorksheetNotFound:
            ws = client.spreadsheet.add_worksheet(title="경쟁사", rows=200,
                                                  cols=max(len(SHEET_HEADER), 8))
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

    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    verdicts, jstat = judge_candidates(all_mentions, today=today)
    rows = confirmed_rows(all_mentions, verdicts)
    print(f"\n댓글 연 글 {fetcher.stat['열림']}개 · 못 연 글 {fetcher.stat['막힘']}개")
    print(f"후보 {jstat['후보'] + jstat.get('캐시적중', 0)}종 · 판정 못 받음 {jstat['미판정']}종"
          f"{' (판정 없이는 표에 넣지 않습니다)' if jstat['미판정'] else ''}")
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
