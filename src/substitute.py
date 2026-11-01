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

2026-10-30 품질 1차 반려 고침: ① 글 비교 열쇠는 카페+글번호(다른 카페 같은 번호 = 다른 글)
② 옛 글 출처를 못 읽으면 맞댄 줄마다 error(기록 파일 · 집계 맞대기실패) — '대체 없음'과 가름.

2026-11-01 사장님: "대체노출 일단 1위인것만 측정? 표기만 해주면 되는거고, 2 ~ 5위는 솔직히 필요없어"
· "대체노출이 2 ~ 5위면 따로 덮어씌울 필요 없는거지. 원래 링크있는것들은 그대로 유지해 표기방식.
확인못함은 말이안됨." → 시트 칸에는 '대체노출 1위 <링크>' 한 개만 적고(초록 글자 = sheets.py 조건부 서식),
2위 이하·찾기 오류·목록 실패는 빈칸. 사유와 2위 이하 전부는 기록 파일(substitute_cell · hits · error)에 그대로 남는다.

한 스위치: 환경값 SUBSTITUTE_SCAN=0 이면 통째로 끈다(기본 켬). 끄면 회차 결과는 고침 전과 같다.
주인: 순위체커(카페외부). 되돌리는 법: SUBSTITUTE_SCAN=0 또는 이 파일과 main.py 의 호출 4곳 되돌림.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlparse

from src.parser import OurPostHit, find_all_our_posts

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


_CAFE_HOSTS = {"cafe.naver.com", "m.cafe.naver.com"}  # m. = 같은 글(parser._normalize_netloc 2026-05-08 확인)
_CAFE_NEW_PATH_RE = re.compile(r"^/ca-fe/cafes/(\d+)/articles/(\d+)$")
_CAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CAFE_NOT_SLUG = {"ca-fe", "f-e", "articleread.nhn", "cafeview"}


def link_key(url: str, aliases: Optional[dict] = None) -> Optional[tuple]:
    """대체 노출 전용 비교 열쇠 — **카페 + 글번호** 둘 다 (2026-10-30 품질 1차 반려 지적 3).

    parser._urls_match 는 카페 이름을 버리고 글번호만 비교해, 다른 카페의 같은 번호를 같은 글로 본다
    (기존 K 판정 쪽 — 이 카드에서는 고치지 않음). 여기서는 카페 식별자를 버리지 않는다.

      구형 cafe.naver.com/{카페이름}/{글번호}             → ("cafe", "slug:카페이름", 글번호)
      신형 cafe.naver.com/ca-fe/cafes/{카페번호}/articles/{글번호} → ("cafe", "id:카페번호", 글번호)
      ArticleRead.nhn?clubid=&articleid=                  → ("cafe", "clubid:번호", 글번호)  (신형과 같다고 확인된 자료가 없어 따로 둔다)
      글을 가리키지 못하는 카페 주소(카페 첫 화면 · 글번호 없음) → None (어느 글과도 같지 않음)
      카페 밖 주소                                        → (호스트, 경로)

    같다고 보는 것: m. 앞머리 · http/https · 물음표 뒤(?art= 등) · 끝 / — 같은 글의 주소 꼴(확인됨).
    카페 이름 ↔ 카페 번호 · 대소문자 다른 카페 이름은 **확인된 매핑(aliases: {"slug:이름": "id:번호"})** 이 있을 때만 같게 본다.
    """
    url = (url or "").strip()
    if not url or not url.startswith("http"):
        return None
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path.rstrip("/")
    if host not in _CAFE_HOSTS:
        return (host[2:] if host.startswith("m.") else host, path)
    m = _CAFE_NEW_PATH_RE.match(path)
    if m:
        cafe, post = "id:" + m.group(1), m.group(2)
    elif path.lower() == "/articleread.nhn":
        q = parse_qs(p.query)
        club, art = (q.get("clubid") or [""])[0], (q.get("articleid") or [""])[0]
        if not (club.isdigit() and art.isdigit()):
            return None
        cafe, post = "clubid:" + club, art
    else:
        parts = [x for x in path.split("/") if x]
        if (len(parts) != 2 or not parts[1].isdigit() or not _CAFE_SLUG_RE.match(parts[0])
                or parts[0].lower() in _CAFE_NOT_SLUG):
            return None
        cafe, post = "slug:" + parts[0], parts[1]
    if aliases:
        cafe = aliases.get(cafe, cafe)
    return ("cafe", cafe, post)


@dataclass
class OurLinkIndex:
    """우리 글 목록 — 시트 전체 링크(모든 탭) + (탭, 키워드)별 옛 글."""

    global_keys: dict = field(default_factory=dict)  # link_key → 출처
    per_keyword: dict = field(default_factory=dict)  # (탭, 키워드) → {link_key: 출처}
    counts: dict = field(default_factory=dict)  # 출처별 링크 수 / '못 읽음' 사유
    # 2026-10-30 지적 2: 못 읽은 옛 글 출처 {출처: 사유}. 비어 있지 않으면 이 회차의 '대체 없음'은
    # 완전한 없음이 아니다 → 맞댄 줄마다 error 로 남겨 기록 파일 · 집계 맞대기실패로 간다(시트 칸은 빈칸 · 11-01).
    source_errors: dict = field(default_factory=dict)
    # 2026-10-30 지적 3: 확인된 카페 별칭 {"slug:이름": "id:번호"}. 여기 없는 별칭은 같은 카페로 보지 않는다.
    aliases: dict = field(default_factory=dict)
    scan_seconds: float = 0.0  # 맞대기에 걸린 시간 합(회차 요약용)
    scan_calls: int = 0  # 맞댄 줄 수
    build_seconds: float = 0.0  # 목록 만들기(시트 읽기 포함)에 걸린 시간

    def size(self) -> dict:
        return {"전체": len(self.global_keys),
                "키워드별": sum(len(v) for v in self.per_keyword.values()),
                "키워드수": len(self.per_keyword)}

    def key(self, url: str) -> Optional[tuple]:
        return link_key(url, self.aliases)

    def source_error_text(self) -> str:
        """못 읽은 출처 → 한 줄 사유. 다 읽었으면 빈 글자."""
        if not self.source_errors:
            return ""
        return "옛 글 출처 못 읽음: " + " · ".join(
            f"{src}({str(err)[:60]})" for src, err in sorted(self.source_errors.items()))

    def add_global(self, url: str, source: str) -> None:
        k = self.key(url)
        if k is not None:
            self.global_keys.setdefault(k, source)

    def add_keyword(self, tab: str, keyword: str, url: str, source: str) -> None:
        k = self.key(url)
        kw = norm_keyword(keyword)
        if k is None or not kw or not tab:
            return
        self.per_keyword.setdefault((tab.strip(), kw), {}).setdefault(k, source)

    def matcher_for(self, tab: str, keyword: str, own_link: str = ""):
        """그 줄 하나에 쓸 판정 함수. 그 줄 제 링크는 '대체'가 아니므로 뺀다."""
        local = self.per_keyword.get(((tab or "").strip(), norm_keyword(keyword)), {})
        own = self.key(own_link) if own_link else None

        def source_of(url: str) -> Optional[str]:
            k = self.key(url)
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
    aliases: Optional[dict] = None,
) -> OurLinkIndex:
    """data = 이번 회차 시트(탭별 행). ledger_rows/archive_rows = {탭, 키워드, 링크} dict.

    출처를 못 읽으면(ledger_error/archive_error) counts 에 사유를 적고 source_errors 에도 남긴다 —
    그 출처의 옛 글이 빠진 목록이므로 이 목록으로 낸 '대체 없음'은 확인 못 함이다(2026-10-30 지적 2).
    aliases = 확인된 카페 별칭 매핑만(지적 3). 없으면 카페 이름·번호가 다르면 다른 글.
    """
    idx = OurLinkIndex(aliases=dict(aliases or {}))
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
            idx.source_errors[source] = str(err)
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
    if not values:  # 머리줄도 없는 탭 = 읽었다고 볼 수 없음(0건으로 치지 않음 — 2026-10-30 지적 2)
        raise ValueError("빈 탭 — 머리줄 없음")
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
    out: list[dict] = []
    pos_by_key: dict = {}
    for h in hits:
        k = index.key(h.url)
        item = {
            "url": h.url,
            "area": h.area,
            "rank": h.integrated_rank,
            "cafe_rank": h.cafe_slot_rank,
            "block": h.block_name,
            "source": source_of(h.url),
            "rank_from_dom_cards": h.rank_from_dom_cards,
        }
        # 같은 글이 두 구좌에 뜨면 한 줄만 남긴다(기록 형식 그대로). 남기는 것 = 순위가 가장 좋은 쪽
        # (같으면 위쪽) · 자리는 처음 찾은 자리. 2026-11-01 GPT 1차 지적 B: 위 구좌 2위 · 아래 구좌 1위인
        # 같은 글을 위쪽만 남겨 1위를 놓쳤다.
        if k in pos_by_key:
            i = pos_by_key[k]
            if _rank_num(item) < _rank_num(out[i]):
                out[i] = item
            continue
        pos_by_key[k] = len(out)
        out.append(item)
    return out


def _rank_num(h: dict) -> float:
    """견주기용 순위 숫자(작을수록 좋음). 순위를 못 읽으면 맨 뒤."""
    try:
        r = int(_hit_rank(h) or 0)
    except (TypeError, ValueError):
        return float("inf")
    return float(r) if r > 0 else float("inf")


def format_cell(hits: list[dict]) -> str:
    """기록 파일(substitute_cell)에 남길 전체 목록 글자. 없으면 빈칸.

    2026-11-01부터 시트 칸에는 이 글자가 아니라 rank1_cell(1위 한 개)만 적는다 — 2위 이하는 기록에만.
    예: "인기글 1위 https://cafe.naver.com/a/1 / 인기글 2위 https://cafe.naver.com/b/2"
    순위 = 카페 구좌 순위(M 칸과 같은 셈), 없으면 통합 순위.
    """
    parts = []
    for h in hits:
        rank = h.get("cafe_rank") or h.get("rank")
        parts.append(f"{h['area']} {rank}위 {h['url']}")
    return " / ".join(parts)


# 2026-11-01 사장님 원문 위 머리말. 시트 칸 앞머리 — sheets.py 조건부 서식(초록 글자)도 이 글자로 고른다.
RANK1_CELL_PREFIX = "대체노출 1위"


def _hit_rank(h: dict):
    """순위 = 카페 구좌 순위(M 칸과 같은 셈), 없으면 통합 순위."""
    return h.get("cafe_rank") or h.get("rank")


def rank1_cell(hits: list[dict]) -> str:
    """시트 '대체 노출' 칸 글자 — 우리 다른 글이 1위일 때만 '대체노출 1위 <링크>' 한 개. 아니면 빈칸.

    1위가 둘 이상(다른 구좌)이면 화면 위쪽(먼저 찾은) 하나만. 2위 이하는 칸에 적지 않는다.
    """
    for h in hits or []:
        try:
            rank = int(_hit_rank(h) or 0)
        except (TypeError, ValueError):
            continue
        if rank == 1 and h.get("url"):
            return f"{RANK1_CELL_PREFIX} {h['url']}"
    return ""


def cell_text(sub_row: dict) -> str:
    """기록 줄 하나 → 시트 칸 글자 (2026-11-01 고침).

    - 찾은 우리 다른 글 중 1위가 있으면 '대체노출 1위 <링크>' — 맞대기 오류·옛 글 출처 못 읽음이 같이 있어도 적는다
      (1위로 뜬 것은 화면에서 직접 본 사실이라서).
    - 그 밖(2위 이하만 · 없음 · 찾기 오류)은 빈칸. '확인 못 함' 글자는 시트에 쓰지 않는다(사장님 "확인못함은 말이안됨").
      오류 사유는 기록 파일 error · 로그 줄에만 남는다.
    """
    return rank1_cell(sub_row.get("hits") or [])


def prepare_sheet_columns(client, data: dict, *, formula_mode: bool) -> dict:
    """회차 앞: 탭마다 '대체 노출' 칸(수식 모드면 숨김 raw 칸도)과 1위 초록 글자 규칙을 없을 때만 만든다.
    스위치 끔 = 아무것도 안 함.

    2026-11-01 GPT 1차 지적 A: 이번 회차에 처리 못 하는 줄(검색 실패 · 키워드 빈 줄)은 apply_cells 가
    닿지 않아 옛 형식 값('확인 못 함 …' · '인기글 2위 …')이 남는다 → 탭마다 '대체노출 1위'로 시작하지 않는
    값을 회차 앞에 한 번에 비운다(stale_cleared = 비운 칸 수). 지적 C·D: 같은 초록 규칙이 여럿이면 하나만
    (formats_removed), 범위·색이 다르면 고침(formats_fixed)."""
    keys = ("headers_added", "formats_added", "formats_fixed", "formats_removed", "stale_cleared")
    out = {"enabled": substitute_enabled(), "tabs": 0, **{k: 0 for k in keys}, "errors": {}}
    if not out["enabled"]:
        return out
    for tab_name, rows in (data or {}).items():
        try:
            res = client.ensure_substitute_columns(tab_name, rows, formula_mode=formula_mode)
            out["tabs"] += 1
            for k in keys:
                out[k] += int(res.get(k, 0) or 0)
        except Exception as e:  # 칸 못 만듦 = 그 탭은 쓰기 때 칸이 없어 건너뜀(판정·회차는 계속)
            out["errors"][tab_name] = f"{type(e).__name__}: {e}"[:200]
    return out


def apply_cells(tab_updates: dict, substitute_rows: list[dict], header: str, *,
                enabled: bool, index_error: str = "") -> int:
    """회차 끝: 시트에 쓸 RowUpdate 마다 '대체 노출' 값을 넣는다.

    - 스위치 끔 = 아무것도 넣지 않음(칸 쓰기 없음 = 고침 전과 같음).
    - 맞댄 줄 = 1위 대체가 있으면 '대체노출 1위 <링크>', 아니면 빈칸.
      맞대지 않은 줄(제 글 찾음) = 빈칸(지난 값 지움) — 그 줄의 K/L/M/O 표기는 여기서 건드리지 않는다.
    - 우리 글 목록 자체를 못 만듦(index_error) = 모든 줄 빈칸(2026-11-01: '확인 못 함' 글자 안 씀).
      사유는 main 의 '[대체노출] 목록 구성 실패' 로그 줄과 회차 요약 substitute_index_counts 에 남는다.
    돌려주는 값 = 값을 넣은 RowUpdate 수.
    """
    if not enabled:
        return 0
    by_row = {} if index_error else {(r["tab"], r["row"]): cell_text(r) for r in substitute_rows or []}
    n = 0
    for tab_name, updates in (tab_updates or {}).items():
        for upd in updates:
            upd.columns[header] = by_row.get((tab_name, upd.row), "")
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
                # 완전 확인 = 맞대기 오류도 없고 옛 글 출처도 다 읽음. 아니면 대체가 있어도 부분 자료.
                "complete": not meta.get("error"),
            })
    return out
