# -*- coding: utf-8 -*-
"""카페 구좌순위가 '사람이 화면에서 세는 순서'와 같은지 대조하는 감사 (읽기 전용).

왜 필요한가 (2026-08-05):
    사장님이 '약산성샴푸' 를 직접 검색해 우리 글이 2등인 걸 보셨는데 시트엔 3등이었다.
    네이버가 같은 카페 글 여러 개를 화면 한 칸에 묶는데 파서가 링크 개수대로 세면서
    아래 글 순위가 밀린 것. 3개월(2026-05-13~08-05)간 아무도 못 잡은 이유 = 검사가 전부 '찾았는가' 만
    보고 '숫자가 화면과 같은가' 는 안 봤기 때문. 그 빈자리를 메우는 감사다.

독립성:
    파서와 **다른 방법으로 센다** — 파서는 DOM 칸 구조, 감사는 연속 같은 출처 묶기.
    같은 코드를 쓰면 자기 자신과 비교하는 셈이라 결함을 못 잡는다. 단 파서도 DOM 을 못
    읽어 되돌린 행은 두 방법이 같아지므로, 그 행은 "일치" 로 넘기지 않고 따로 센다.

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
from src.parser import (
    _POPULAR_SKIP_PATTERNS,
    _is_slot_block,
    parse_search_result,
    slot_owner_key,
)
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


def _owner(url: str) -> tuple:
    """이 글의 '주인'(카페/블로그) 식별자.

    파서와 **같은 판별 규칙**(slot_owner_key)을 쓴다 — 주인을 확실히 못 뽑으면 뭉치지 않는다.
    예전엔 첫 경로 조각만 봐서 신형 카페 주소(ca-fe/cafes/{id})가 전부 한 주인으로 뭉쳤고,
    그러면 감사가 파서보다 부정확해 헛된 '어긋남'을 쏟아낸다(2026-08-05 독립검증 M-3).
    감사의 독립성은 '주인 판별'이 아니라 '세는 방식'(연속 묶기 대 DOM 칸)에 있다.
    """
    return slot_owner_key(url)


# 출처 대문 링크의 실제 형태들. 좁게 잡으면 정상 칸이 'orphan' 으로 뒤집혀
# 헛경보가 쏟아진다 — 실측에서 인플루언서 블로그는 대문이 in.naver.com/{id} 로 실리고,
# 모바일 페이지는 m. 접두가 붙는다(2026-08-05 독립검증 M-1: 실측 7박스 중 2개 오탐).
_HOME_LINK_RE = re.compile(r"^https?://(m\.)?(cafe|blog|in)\.naver\.com/[^/]+/?$")


def _has_orphan_card(box) -> bool:
    """대문 링크가 없는 칸이 있는가 = '원래 앞 칸의 일부였다' 는 지문.

    화면의 한 칸은 자기 출처 대문 링크를 정확히 하나 갖는다(실측 칸 50개에서 2개 이상은 0건).
    묶여 있던 글이 별도 칸으로 쪼개지면, 쪼개진 쪽은 대문 없이 글만 있다.

    쓰는 이유(2026-08-05 독립검증 M-1): 두 계산의 차이 1은 두 가지 원인에서 나온다 —
      (a) 같은 카페가 이웃한 별도 두 칸 = 정상, 파서가 맞다
      (b) 한 칸이던 묶음이 두 칸으로 쪼개짐 = **2026-05-13 사고와 같은 모양**, 파서가 틀리다
    차이 1을 전부 통과시키면 (b)가 조용히 지나간다. 이 지문이 둘을 가른다.
    """
    for container in box.select("div[class*='fds-ugc']")[:1]:
        for child in container.find_all(recursive=False):
            if "sds-comps-divider" in " ".join(child.get("class", [])):
                continue
            if not _post_links(child):
                continue  # 글이 없는 조각은 칸이 아니다
            homes = {
                a["href"].split("?")[0]
                for a in child.find_all("a", href=True)
                if _HOME_LINK_RE.match(a["href"].split("?")[0])
            }
            if not homes:
                return True
    return False


def screen_cafe_slot(html: str, our_link: str) -> tuple[int | None, int | None, bool, bool]:
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
    orphan_box = False
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
        if _has_orphan_card(box):
            orphan_box = True

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
            return (cafe_slot, card_idx, True, orphan_box)
    return (None, None, counted_any, orphan_box)


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
    mismatch = notfound = failed = fallback_rows = outside = 0
    for i, t in enumerate(targets, 1):
        link = resolve_short_url(t["링크"]) if "naver.me" in t["링크"] else t["링크"]
        try:
            html = crawler.fetch_search(t["키워드"])
        except Exception as e:  # 검색 실패는 감사 실패로 남기고 계속
            failed += 1
            rows.append({**t, "파서구좌": "", "화면구좌": "", "판정": f"검색실패:{type(e).__name__}"})
            print(f"  [{i}/{len(targets)}] {t['키워드']}: 검색 실패 {e}")
            continue

        res = parse_search_result(html, None, link_set={link})
        parsed = res.cafe_slot_rank

        if res.exposure_area.value == "AB" and res.rank_from_dom_cards:
            # 진짜 AB 박스만 건너뛴다. 박스 하나가 곧 한 칸이라 이 결함과 무관하고,
            # 여기서 ★로 세면 헛경보가 되며 헛경보는 진짜 경보를 못 믿게 만든다.
            #
            # 단 rank_from_dom_cards=False 인 AB 는 JSON 대체 경로로 잡힌 것이다.
            # 그 경로는 아직 링크 개수로 세므로 사장님이 겪은 그 오류가 남아 있다 —
            # 조건 없이 건너뛰면 유일한 감시자를 끄는 셈이다(2026-08-05 독립검증 H-1).
            outside += 1
            rows.append({**t, "파서구좌": parsed or "", "화면구좌": "", "판정": "대상 아님(지금은 AB 구좌)"})
            continue

        if parsed is not None and not res.rank_from_dom_cards:
            # 파서도 화면 칸을 못 읽어 출처 묶기로 계산한 행 — 감사와 같은 방법이 되어
            # 이 대조는 서로를 검증하지 못한다. '일치' 로 넘기지 않고 따로 센다.
            fallback_rows += 1
        screen, _card, structure_ok, orphan = screen_cafe_slot(html, link)

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
        elif int(parsed) - int(screen) == 1 and not orphan:
            # 딱 한 칸 차이 = 같은 카페가 이웃한 별도 칸 2개를 차지한 경우.
            # 2026-08-05 '닭살피부바디워시' 실측으로 확인된 정상 모양이고, 이때는 파서가 맞다.
            # (감사의 묶기 방식은 그 둘을 한 칸으로 합쳐 하나 적게 센다.)
            verdict = f"일치(한 칸 차 — 같은 카페 이웃 칸, 파서{parsed} 채택)"
        elif int(parsed) - int(screen) == 1:
            # 차이 1인데 대문 없는 칸이 있다 = 묶음이 쪼개진 것 = 원래 사고와 같은 모양.
            mismatch += 1
            verdict = f"★어긋남 파서{parsed} ≠ 화면{screen} — 대문 없는 칸 발견(묶음이 쪼개졌을 수 있음)"
        else:
            # 두 칸 이상 벌어졌다 = 위 사유로 설명되지 않는다. 사람이 봐야 한다.
            mismatch += 1
            verdict = f"★어긋남 파서{parsed} ≠ 화면{screen} (차이 {int(parsed)-int(screen)})"

        rows.append({**t, "파서구좌": parsed or "", "화면구좌": screen or "", "판정": verdict})
        if verdict != "일치":
            print(f"  [{i}/{len(targets)}] {t['탭']} r{t['행']} {t['키워드']}: {verdict}")

    total = len(rows)
    checked = total - notfound - failed - outside
    print(f"\n[감사 결과] 대상 {total} · 대조 {checked} · 어긋남 {mismatch} · "
          f"검색에 안 잡힘 {notfound} · 검색실패 {failed} · 대상 아님(AB) {outside}")
    if fallback_rows:
        print(f"\n⚠ 이 중 {fallback_rows}행은 파서도 화면 칸을 못 읽어 감사와 같은 방법으로 계산했습니다.")
        print("  = 그 행들의 '일치' 는 서로를 검증한 것이 아닙니다. 네이버 화면 구조 변경을 확인하세요.")
    if mismatch:
        print("\n※ 어긋난 행이 있습니다 — 두 계산이 두 칸 이상 벌어졌습니다. 사람이 봐야 합니다.")
        print("  (한 칸 차이는 '같은 카페 이웃 칸' 으로 설명되는 정상이라 여기 안 셉니다.")
        print("   두 칸 이상은 그 사유로 설명되지 않습니다.)")
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
