"""대체 노출 재기 (2026-10-29 사장님: "미노출이라고 떠도 실제로 그 자리를 우리가 작업한 다른 글로
대체되어서 상위노출 되는 경우" · "한 키워드에서도 1 2위로").

한 줄 정리:
  링크 있는 줄이 제 글을 못 찾았을 때(미노출·누락·삭제), 또는 빈 링크 줄이 미노출일 때,
  **이미 받은 같은 검색 화면**을 우리 글 전체와 다시 맞대어 떠 있는 우리 글을 전부 적는다.

지키는 것:
  - 새 검색 0번: 판정에 쓴 html 을 그대로 다시 읽기만 한다(crawler 를 부르지 않는다).
  - 노출영역(K)·L·M·O 는 손대지 않는다: 결과는 cols["_substitute"] 메타 키 → 회차 끝에
    기록 파일(.harness/substitutes/*.jsonl)로만 간다. 시트 새 칸 쓰기는 사장님 승인 뒤 별도.
  - 공개 저장소에 우리 글 목록을 두지 않는다: 옛 글은 비공개 시트의 숨긴 탭(LEDGER_TAB_NAME)과
    상위노출_이력(링크 칸)에서 회차마다 읽는다.

한 스위치: 환경값 SUBSTITUTE_SCAN=0 이면 통째로 끈다(기본 켬). 끄면 회차 결과는 고침 전과 같다.
주인: 순위체커(카페외부). 되돌리는 법: SUBSTITUTE_SCAN=0 또는 이 파일과 main.py 의 호출 4곳 되돌림.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import urlparse

from src.parser import OurPostHit, _normalize_cafe_url, find_all_our_posts

# 비공개 시트 안의 숨긴 탭 — 이 PC 글 장부(post_ledger.db assignments)를 옮겨 둔 곳.
# scripts/ledger_to_sheet_tab.py 가 채운다(운영 쓰기는 사장님 승인 뒤).
LEDGER_TAB_NAME = "우리글_장부"
LEDGER_TAB_HEADER = ["탭", "키워드", "링크", "작업일", "장부키"]
ARCHIVE_TAB_NAME = "상위노출_이력"

SOURCE_SHEET = "시트"
SOURCE_LEDGER = "글장부"
SOURCE_ARCHIVE = "이력"


def substitute_enabled() -> bool:
    return os.environ.get("SUBSTITUTE_SCAN", "1").strip().lower() not in {"0", "false", "no", "off"}


def norm_keyword(value: object) -> str:
    return " ".join(str(value or "").split())


def link_key(url: str) -> Optional[tuple]:
    """parser._urls_match 와 같은 뜻의 비교 열쇠.

    카페 글은 (주소 앞, 글번호) — _urls_match 가 구형·신형 모두 netloc+글번호로만 가르므로 같다.
    그 밖은 (주소 앞, 경로). 이 열쇠로 사전을 만들면 줄마다 2천 개 링크를 하나씩 맞대지 않아도 된다.
    """
    url = (url or "").strip()
    if not url or not url.startswith("http"):
        return None
    netloc, key = _normalize_cafe_url(urlparse(url))
    if key.startswith(("OLD:", "NEW:")):
        return (netloc, "POST:" + key[4:])
    return (netloc, key)


@dataclass
class OurLinkIndex:
    """우리 글 목록 — 시트 전체 링크(모든 탭) + (탭, 키워드)별 옛 글."""

    global_keys: dict = field(default_factory=dict)  # link_key → 출처
    per_keyword: dict = field(default_factory=dict)  # (탭, 키워드) → {link_key: 출처}
    counts: dict = field(default_factory=dict)  # 출처별 링크 수 / '못 읽음' 사유
    scan_seconds: float = 0.0  # 맞대기에 걸린 시간 합(회차 요약용)
    scan_calls: int = 0  # 맞댄 줄 수
    build_seconds: float = 0.0  # 목록 만들기(시트 읽기 포함)에 걸린 시간

    def size(self) -> dict:
        return {"전체": len(self.global_keys),
                "키워드별": sum(len(v) for v in self.per_keyword.values()),
                "키워드수": len(self.per_keyword)}

    def add_global(self, url: str, source: str) -> None:
        k = link_key(url)
        if k is not None:
            self.global_keys.setdefault(k, source)

    def add_keyword(self, tab: str, keyword: str, url: str, source: str) -> None:
        k = link_key(url)
        kw = norm_keyword(keyword)
        if k is None or not kw or not tab:
            return
        self.per_keyword.setdefault((tab.strip(), kw), {}).setdefault(k, source)

    def matcher_for(self, tab: str, keyword: str, own_link: str = ""):
        """그 줄 하나에 쓸 판정 함수. 그 줄 제 링크는 '대체'가 아니므로 뺀다."""
        local = self.per_keyword.get(((tab or "").strip(), norm_keyword(keyword)), {})
        own = link_key(own_link) if own_link else None

        def source_of(url: str) -> Optional[str]:
            k = link_key(url)
            if k is None or k == own:
                return None
            return self.global_keys.get(k) or local.get(k)

        return source_of


def build_index(
    data: dict,
    ledger_rows: Optional[Iterable[dict]] = None,
    archive_rows: Optional[Iterable[dict]] = None,
    *,
    ledger_error: str = "",
    archive_error: str = "",
) -> OurLinkIndex:
    """data = 이번 회차 시트(탭별 행). ledger_rows/archive_rows = {탭, 키워드, 링크} dict."""
    idx = OurLinkIndex()
    n_sheet = 0
    for tab_rows in (data or {}).values():
        for r in tab_rows:
            link = str(r.get("링크") or "").strip()
            if not link or "naver.me" in link:
                continue
            idx.add_global(link, SOURCE_SHEET)
            n_sheet += 1
    idx.counts[SOURCE_SHEET] = n_sheet
    for rows, source, err in (
        (ledger_rows, SOURCE_LEDGER, ledger_error),
        (archive_rows, SOURCE_ARCHIVE, archive_error),
    ):
        if err:
            idx.counts[source] = f"못 읽음: {err}"
            continue
        n = 0
        for r in rows or []:
            link = str(r.get("링크") or "").strip()
            if not link or "naver.me" in link:
                continue
            idx.add_keyword(str(r.get("탭") or ""), str(r.get("키워드") or ""), link, source)
            n += 1
        idx.counts[source] = n
    return idx


def _rows_from_values(values: list, need: tuple) -> list[dict]:
    if not values:
        return []
    header = [str(h).strip() for h in values[0]]
    if any(h not in header for h in need):
        raise ValueError(f"머리줄에 {need} 없음")
    pos = {h: header.index(h) for h in need}
    out = []
    for row in values[1:]:
        out.append({h: (row[i] if i < len(row) else "") for h, i in pos.items()})
    return out


def read_private_sources(client) -> tuple[list, str, list, str]:
    """비공개 시트에서 옛 글 두 출처를 읽는다. 실패는 사유 글자로 돌려준다(0건으로 바꾸지 않음)."""
    ledger_rows: list = []
    archive_rows: list = []
    ledger_err = archive_err = ""
    try:
        ws = client.spreadsheet.worksheet(LEDGER_TAB_NAME)
        ledger_rows = _rows_from_values(ws.get_all_values(), ("탭", "키워드", "링크"))
    except Exception as e:  # 탭이 아직 없음(승인 전) 포함
        ledger_err = f"{type(e).__name__}: {e}"[:200]
    try:
        ws = client.spreadsheet.worksheet(ARCHIVE_TAB_NAME)
        archive_rows = _rows_from_values(ws.get_all_values(), ("탭", "키워드", "링크"))
    except Exception as e:
        archive_err = f"{type(e).__name__}: {e}"[:200]
    return ledger_rows, ledger_err, archive_rows, archive_err


def scan(html: str, index: Optional[OurLinkIndex], tab: str, keyword: str, own_link: str = "") -> list[dict]:
    """이미 받은 html 에서 떠 있는 우리 글 전부 → 기록용 dict 목록 (없으면 [])."""
    if index is None or not html:
        return []
    t0 = time.perf_counter()
    source_of = index.matcher_for(tab, keyword, own_link)
    try:
        hits: list[OurPostHit] = find_all_our_posts(html, lambda u: source_of(u) is not None)
    finally:
        index.scan_seconds += time.perf_counter() - t0
        index.scan_calls += 1
    out = []
    seen = set()
    for h in hits:
        k = link_key(h.url)
        if k in seen:  # 같은 글이 두 구좌에 뜨면 위쪽(먼저 찾은) 한 번만
            continue
        seen.add(k)
        out.append({
            "url": h.url,
            "area": h.area,
            "rank": h.integrated_rank,
            "cafe_rank": h.cafe_slot_rank,
            "block": h.block_name,
            "source": source_of(h.url),
            "rank_from_dom_cards": h.rank_from_dom_cards,
        })
    return out


def format_cell(hits: list[dict]) -> str:
    """시트 새 칸 '대체 노출'에 적을 글자. 없으면 빈칸.

    예: "인기글 1위 https://cafe.naver.com/a/1 / 인기글 2위 https://cafe.naver.com/b/2"
    순위 = 카페 구좌 순위(M 칸과 같은 셈), 없으면 통합 순위.
    """
    parts = []
    for h in hits:
        rank = h.get("cafe_rank") or h.get("rank")
        parts.append(f"{h['area']} {rank}위 {h['url']}")
    return " / ".join(parts)


ERROR_CELL_PREFIX = "확인 못 함"


def cell_text(sub_row: dict) -> str:
    """기록 줄 하나 → 시트 칸 글자. 찾기 오류는 빈칸(=없음)으로 바꾸지 않고 '확인 못 함 (사유)' 로 적는다."""
    err = str(sub_row.get("error") or "").strip()
    if err:
        return f"{ERROR_CELL_PREFIX} ({err[:80]})"
    return str(sub_row.get("substitute_cell") or "")


def prepare_sheet_columns(client, data: dict, *, formula_mode: bool) -> dict:
    """회차 앞: 탭마다 '대체 노출' 칸(수식 모드면 숨김 raw 칸도)을 없을 때만 만든다. 스위치 끔 = 아무것도 안 함."""
    out = {"enabled": substitute_enabled(), "tabs": 0, "headers_added": 0, "errors": {}}
    if not out["enabled"]:
        return out
    for tab_name, rows in (data or {}).items():
        try:
            res = client.ensure_substitute_columns(tab_name, rows, formula_mode=formula_mode)
            out["tabs"] += 1
            out["headers_added"] += int(res.get("headers_added", 0) or 0)
        except Exception as e:  # 칸 못 만듦 = 그 탭은 쓰기 때 칸이 없어 건너뜀(판정·회차는 계속)
            out["errors"][tab_name] = f"{type(e).__name__}: {e}"[:200]
    return out


def apply_cells(tab_updates: dict, substitute_rows: list[dict], header: str, *,
                enabled: bool, index_error: str = "") -> int:
    """회차 끝: 시트에 쓸 RowUpdate 마다 '대체 노출' 값을 넣는다.

    - 스위치 끔 = 아무것도 넣지 않음(칸 쓰기 없음 = 고침 전과 같음).
    - 맞댄 줄 = 대체 글자 또는 '확인 못 함 (사유)'. 맞대지 않은 줄(제 글 찾음) = 빈칸(지난 값 지움).
    - 우리 글 목록 자체를 못 만듦(index_error) = 모든 줄 '확인 못 함 (사유)'(빈칸=없음 으로 속이지 않음).
    돌려주는 값 = 값을 넣은 RowUpdate 수.
    """
    if not enabled:
        return 0
    by_row = {(r["tab"], r["row"]): cell_text(r) for r in substitute_rows or []}
    err_text = f"{ERROR_CELL_PREFIX} ({str(index_error)[:80]})" if index_error else ""
    n = 0
    for tab_name, updates in (tab_updates or {}).items():
        for upd in updates:
            upd.columns[header] = err_text or by_row.get((tab_name, upd.row), "")
            n += 1
    return n


def collect_rows(tab_updates: dict, row_context: dict, run_id: str, checked_at: str) -> list[dict]:
    """회차 끝: 각 RowUpdate 의 '_substitute' 메타 키를 꺼내(지우며) 기록 줄로 만든다."""
    out = []
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            meta = upd.columns.pop("_substitute", None)
            if meta is None:
                continue
            row = row_context.get((tab_name, upd.row)) or {}
            hits = meta.get("hits") or []
            out.append({
                "run_id": run_id,
                "checked_at": checked_at,
                "tab": tab_name,
                "row": upd.row,
                "keyword": row.get("키워드", ""),
                "row_link": row.get("링크", ""),
                "k_full": upd.columns.get("노출영역", ""),
                "substitute_count": len(hits),
                "substitute_cell": format_cell(hits),
                "hits": hits,
                "error": meta.get("error", ""),
            })
    return out
