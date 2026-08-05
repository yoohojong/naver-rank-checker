# -*- coding: utf-8 -*-
"""카페 구좌순위가 '사람이 화면에서 세는 순서'와 같은지 대조하는 감사 (읽기 전용).

왜 필요한가 (2026-08-05):
    사장님이 '약산성샴푸' 를 직접 검색해 우리 글이 2등인 걸 보셨는데 시트엔 3등이었다.
    네이버가 같은 카페 글 여러 개를 화면 한 칸에 묶는데 파서가 링크 개수대로 세면서
    아래 글 순위가 밀린 것. 15개월간 아무도 못 잡은 이유 = 검사가 전부 '찾았는가' 만
    보고 '숫자가 화면과 같은가' 는 안 봤기 때문. 그 빈자리를 메우는 감사다.

독립성:
    파서(src.parser)의 순위 계산을 쓰지 않고 DOM 에서 칸을 직접 세어 대조한다.
    파서와 같은 코드를 쓰면 자기 자신과 비교하는 셈이라 결함을 못 잡는다.

쓰는 법:
    python scripts/audit/구좌순위_화면대조.py                 # 인기글 계열 전 행
    python scripts/audit/구좌순위_화면대조.py --limit 20      # 앞 20개만
    python scripts/audit/구좌순위_화면대조.py --tab "샴푸 카외"
    python scripts/audit/구좌순위_화면대조.py --out 결과.csv

시트에 아무것도 쓰지 않는다. 어긋난 행만 표로 뽑아 보여준다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # 윈도우 콘솔에서 한글이 깨지지 않게
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from bs4 import BeautifulSoup

from src.config import SERVICE_ACCOUNT_JSON, SPREADSHEET_ID
from src.crawler import Crawler, SlowdownController, resolve_short_url
from src.parser import _POPULAR_SKIP_PATTERNS, _is_slot_block, parse_search_result
from src.sheets import SheetsClient

# 인기글/스마트블록 계열만 대상 — AB 는 박스 하나가 곧 한 칸이라 이 결함이 생기지 않는다.
TARGET_AREAS = {"인기글", "스마트블록", "중복노출(인기글)", "중복노출(스마트블록)", "중복노출"}
DEFAULT_TABS = ("샴푸 카외", "바디워시 카외", "두드러기 카외")

_STAMP_RE = re.compile(r"^(.*?)\s*\(\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}~?\)$")


def _base(value: str) -> str:
    """'인기글 (8/5 18:00~)' → '인기글'."""
    s = (value or "").strip()
    m = _STAMP_RE.match(s)
    return m.group(1).strip() if m else s


def _norm(url: str) -> str:
    u = (url or "").split("?")[0].rstrip("/").lower()
    for pre in ("https://", "http://"):
        if u.startswith(pre):
            u = u[len(pre):]
    return u.replace("m.cafe.naver", "cafe.naver")


def _post_links(node) -> list[str]:
    """이 조각 안의 본문 글 링크(주소 끝이 글번호). 같은 글 중복 제거.

    중복 기준은 파서(_extract_popular_items)와 같이 도메인+경로 — 경로만 쓰면
    m.cafe.naver.com 과 cafe.naver.com 이 섞였을 때 헛 어긋남이 난다.
    """
    out: list[str] = []
    seen: set[str] = set()
    for a in node.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http") or "keep.naver.com" in href:
            continue
        parsed = urlparse(href)
        parts = [s for s in parsed.path.split("/") if s]
        if len(parts) < 2 or not parts[-1].isdigit():
            continue
        key = _norm(href)
        if key in seen:
            continue
        seen.add(key)
        out.append(href)
    return out


def _owner(url: str) -> str:
    """이 글의 '주인'(카페/블로그) 식별자. cafe.naver.com/{slug}/{글번호} → cafe.naver.com/{slug}."""
    parsed = urlparse(url)
    parts = [s for s in parsed.path.split("/") if s]
    host = _norm("https://" + parsed.netloc).rstrip("/")
    return f"{host}/{parts[0]}" if parts else host


def screen_cafe_slot(html: str, our_link: str) -> tuple[int | None, int | None, bool]:
    """화면 칸 기준 (카페 구좌순위, 전체 칸순위, 셀 수 있었는가).

    **파서와 다른 방법으로 센다** — 이것이 이 감사의 존재 이유다.
      · 파서 = DOM 칸 구조(네이버 클래스 이름 기반)
      · 감사 = 연속 같은 출처 묶기(클래스와 무관한 규칙)
    두 방법이 같은 답을 내야 정상이다. 한쪽 가정이 무너지면 다른 쪽이 잡아낸다.
    (2026-08-05 독립검증 지적: 예전 판은 파서 코드를 그대로 옮겨 적어, 가정이 깨지면
     감사도 같이 눈을 감았다.)

    광고 칸은 글 링크가 없어(ader.naver.com) 자연히 빠진다.
    """
    soup = BeautifulSoup(html, "html.parser")
    counted_any = False
    for box in soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx"):
        h2 = box.find("h2")
        if h2 is None:
            continue  # h2 없는 박스 = AB = 박스 하나가 곧 한 칸이라 이 결함과 무관
        # 박스 '선별' 규칙만 파서와 맞춘다 — 같은 자리를 봐야 비교가 성립하기 때문.
        # '세는 방식' 은 아래에서 독립으로 간다.
        h2_text = h2.get_text(strip=True)
        if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
            continue  # 광고·이미지·AI·쇼핑
        if "인기글" not in h2_text and not _is_slot_block(box, h2_text):
            continue  # 네이버 편성 영역(메이트·브랜드 콘텐츠·뉴스·숏텐츠) = 구좌 아님

        links = _post_links(box)
        if not links:
            continue
        counted_any = True

        # 연속 같은 출처 = 한 칸 (네이버가 같은 카페 글을 한 칸에 묶어 보여주기 때문)
        cafe_slot = 0
        card_idx = 0
        prev_owner = None
        found_here = False
        for url in links:
            owner = _owner(url)
            if owner != prev_owner:
                card_idx += 1
                if "cafe.naver.com" in url:
                    cafe_slot += 1
                prev_owner = owner
            if _norm(url) == _norm(our_link):
                found_here = True
                break
        if found_here:
            return (cafe_slot, card_idx, True)
    return (None, None, counted_any)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="구좌순위가 화면 칸 순서와 같은지 대조 (읽기 전용)")
    ap.add_argument("--tab", action="append", help="검사할 탭 (여러 번 지정 가능)")
    ap.add_argument("--limit", type=int, default=0, help="앞 N개만 검사 (0 = 전부)")
    ap.add_argument("--out", help="결과 CSV 저장 경로")
    ap.add_argument("--slowdown", type=float, default=3.0, help="검색 간격 기준 초")
    ap.add_argument("--key", help="서비스계정 JSON 파일 경로 (없으면 환경변수 SERVICE_ACCOUNT_JSON)")
    ap.add_argument("--sheet", help="스프레드시트 ID (없으면 환경변수 SPREADSHEET_ID)")
    args = ap.parse_args(argv)

    creds = SERVICE_ACCOUNT_JSON
    if args.key:
        creds = Path(args.key).read_text(encoding="utf-8")
    sheet_id = args.sheet or SPREADSHEET_ID
    if not creds or not sheet_id:
        print("서비스계정 열쇠와 시트 ID 가 필요합니다. --key / --sheet 로 주거나 "
              "환경변수 SERVICE_ACCOUNT_JSON · SPREADSHEET_ID 를 설정하세요.")
        return 2

    client = SheetsClient(sheet_id, creds)
    tabs = args.tab or list(DEFAULT_TABS)

    targets: list[dict] = []
    for tab in tabs:
        try:
            values = client.spreadsheet.worksheet(tab).get_all_values()
        except Exception as e:
            print(f"  [건너뜀] 탭을 못 읽음: {tab} ({e})")
            continue
        if not values:
            print(f"  [건너뜀] 빈 탭: {tab}")
            continue
        header = values[0]
        try:
            i_kw = header.index("키워드")
            i_link = header.index("링크")
            i_area = header.index("노출영역")
            i_slot = header.index("노출여부(카페구좌순위)")
        except ValueError as e:
            print(f"  [건너뜀] {tab}: 필요한 칸을 못 찾음 ({e})")
            continue
        for rownum, row in enumerate(values[1:], start=2):
            cell = lambda i: (row[i] if i < len(row) else "").strip()
            if _base(cell(i_area)) not in TARGET_AREAS:
                continue
            if not cell(i_kw) or not cell(i_link):
                continue
            targets.append({
                "탭": tab, "행": rownum, "키워드": cell(i_kw),
                "노출영역": _base(cell(i_area)), "시트구좌": cell(i_slot), "링크": cell(i_link),
            })

    if args.limit:
        targets = targets[:args.limit]
    print(f"[감사 시작] 인기글 계열 {len(targets)}행\n")

    crawler = Crawler(slowdown=SlowdownController(base=args.slowdown, max_=90.0))
    crawler.warmup()

    rows: list[dict] = []
    mismatch = notfound = failed = 0
    for i, t in enumerate(targets, 1):
        link = resolve_short_url(t["링크"]) if "naver.me" in t["링크"] else t["링크"]
        try:
            html = crawler.fetch_search(t["키워드"])
        except Exception as e:  # 검색 실패는 감사 실패로 남기고 계속
            failed += 1
            rows.append({**t, "파서구좌": "", "화면구좌": "", "판정": f"검색실패:{type(e).__name__}"})
            print(f"  [{i}/{len(targets)}] {t['키워드']}: 검색 실패 {e}")
            continue

        parsed = parse_search_result(html, None, link_set={link}).cafe_slot_rank
        screen, _card, structure_ok = screen_cafe_slot(html, link)

        if not structure_ok and parsed is not None:
            # 감사는 셀 자리를 못 찾았는데 파서만 값을 냈다 = 한쪽 가정이 무너진 신호.
            mismatch += 1
            verdict = f"★감사가 셀 자리를 못 찾음(파서값 {parsed}) — 화면 구조 확인 필요"
        elif screen is None and parsed is not None:
            mismatch += 1
            verdict = f"★파서만 값을 냄(파서{parsed}, 화면엔 없음)"
        elif screen is None:
            notfound += 1
            verdict = "지금 검색에 안 잡힘"
        elif parsed is None:
            mismatch += 1
            verdict = "★파서가 못 찾음(화면엔 있음)"
        elif int(parsed) == int(screen):
            verdict = "일치"
        else:
            mismatch += 1
            verdict = f"★어긋남 파서{parsed} ≠ 화면{screen}"

        rows.append({**t, "파서구좌": parsed or "", "화면구좌": screen or "", "판정": verdict})
        if verdict != "일치":
            print(f"  [{i}/{len(targets)}] {t['탭']} r{t['행']} {t['키워드']}: {verdict}")

    total = len(rows)
    checked = total - notfound - failed
    print(f"\n[감사 결과] 대상 {total} · 대조 {checked} · 어긋남 {mismatch} · "
          f"검색에 안 잡힘 {notfound} · 검색실패 {failed}")
    if mismatch:
        print("\n※ 어긋난 행이 있습니다 — 순위 세는 규칙이 화면과 벌어졌다는 뜻입니다.")
        for r in rows:
            if str(r["판정"]).startswith("★"):
                print(f"   {r['탭']} r{r['행']} {r['키워드']}: {r['판정']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["판정"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n저장: {args.out}")

    return 1 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
