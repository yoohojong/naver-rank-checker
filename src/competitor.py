"""competitor: 상위 구좌를 차지한 '남의 글' 주체 수집 + 등장 횟수 집계 (기본 OFF).

사장님 요청 (2026-07-23 원문):
    "누락시킨거 보고 상위노출된 경쟁사 리스트업 (매번 갱신)
     제일 많이 보이는 애들 횟수 체크해서 갱신해주는 시스템"
확정 범위 (2026-07-23): **전 키워드** 수집 (누락·미노출뿐 아니라 우리가 1등인 키워드까지).
  → 우리 상태를 행에 같이 적어두므로 "누락 건만" 보기는 시트에서 필터로 언제든 가능.

설계 정합 (archive.py 와 동일한 규율):
- 추가 크롤링 0. main.py 가 순위 검사용으로 이미 받아둔 같은 HTML 을 재사용한다.
- 순위 판정 코드(_parse_*)는 건드리지 않는다. parser.collect_slot_items 가 읽기 전용으로 따로 돈다.
- 순수함수(build_* / aggregate_*)와 시트 I/O(append_* / write_*)를 분리 → 로컬 테스트 가능.
- 공개 repo 라 데이터는 repo 아닌 **비공개 시트 탭**에만 남긴다.
- 날짜별 멱등: 하루 여러 번 cron 이 돌아도 그날 1벌만 남는다.
- 시트 I/O 실패가 cron 을 죽이지 않는다(호출부도 try/except 로 격리).
"""
from __future__ import annotations

from urllib.parse import urlparse

from src.parser import SlotItem, cafe_slug_of, is_known_url

# 이력 탭 스키마 (고정). "우리상태" = 그 키워드에서 우리 글이 어떤 상태였나(누락/미노출/AB…).
HISTORY_HEADER = [
    "날짜", "탭", "키워드", "우리상태", "구좌", "블록명", "순위", "주체", "종류", "제목", "URL",
]
HISTORY_TAB_NAME = "경쟁사_이력"

# 집계 탭 스키마 (고정). 사장님이 보는 화면 = 이 탭.
RANKING_HEADER = [
    "주체", "종류", "등장 횟수", "노출 키워드 수", "평균 순위", "1위 횟수",
    "우리가 놓친 키워드 수", "최근 등장일", "대표 URL",
]
RANKING_TAB_NAME = "경쟁사_랭킹"

# 키워드 1건당 시트에 남길 상위 몇 개까지. 423 키워드 × 5 = 하루 ~2천 행.
DEFAULT_TOP_N = 5
# 이력 탭 보관 일수. 이보다 오래된 날짜 블록은 적재할 때 같이 정리한다.
DEFAULT_RETENTION_DAYS = 30

# "우리가 놓친" 으로 볼 상태값 (K 컬럼 base 기준).
MISSED_STATES = {"누락", "미노출", "삭제"}


def _clean(value: object) -> str:
    return str(value or "").strip()


def identify_actor(url: str) -> tuple[str, str]:
    """URL → (주체, 종류). 주체 = 사람이 알아볼 수 있는 최소 단위 이름.

    - 카페 구형 URL (cafe.naver.com/{slug}/{id}) → slug (예 "dieselmania")
    - 카페 신형 URL (cafe.naver.com/ca-fe/cafes/{cafe_id}/…) → "카페#{cafe_id}"
      (신형은 주소에 이름이 없어 숫자 ID 로만 식별 — 이름 대조표는 후속 작업)
    - 블로그 (blog.naver.com/{id}/…) → 블로그 ID
    - 지식iN → "지식iN"
    - 그 외 → 도메인

    Returns:
        (주체 문자열, 종류 문자열). URL 이 비면 ("", "").
    """
    url = _clean(url)
    if not url:
        return "", ""

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("m."):
        netloc = netloc[2:]
    parts = [seg for seg in parsed.path.split("/") if seg]

    if "cafe.naver.com" in netloc:
        slug = cafe_slug_of(url)
        if slug:
            return slug, "카페"
        # 신형 URL: ca-fe/cafes/{cafe_id}/articles/{post_id}
        if len(parts) >= 3 and parts[0] == "ca-fe" and parts[1] == "cafes":
            return f"카페#{parts[2]}", "카페"
        return "카페(미상)", "카페"

    if "blog.naver.com" in netloc:
        if parts:
            return parts[0], "블로그"
        return "블로그(미상)", "블로그"

    if "kin.naver.com" in netloc:
        return "지식iN", "지식iN"

    if "in.naver.com" in netloc or "post.naver.com" in netloc:
        return (parts[0] if parts else netloc), "네이버포스트"

    return netloc, "웹"


def is_our_item(url: str, our_links: set | None, our_cafe_slugs: set | None) -> bool:
    """이 글이 우리 글인지 — 시트 link 정확 매치 또는 우리 카페 slug 매치."""
    if is_known_url(url, our_links):
        return True
    if our_cafe_slugs:
        slug = cafe_slug_of(url)
        if slug and slug in our_cafe_slugs:
            return True
    return False


def build_competitor_rows(
    *,
    date_str: str,
    tab: str,
    keyword: str,
    our_state: str,
    items: list[SlotItem],
    our_links: set | None = None,
    our_cafe_slugs: set | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict]:
    """키워드 1건의 구좌 목록 → 경쟁사 행 dict 리스트 · 순수함수.

    - 우리 글은 제외한다(우리 글 제외가 곧 "경쟁사").
    - 같은 주체가 한 키워드에 여러 글을 올렸으면 **가장 높은 순위 1건만** 센다.
      (한 카페가 3개 깔았다고 등장 3회로 세면 "제일 많이 보이는 애들" 이 왜곡됨)
    - 구좌별로 top_n 까지만 남긴다(시트 적재량 방어).
    """
    keyword = _clean(keyword)
    if not keyword or not items:
        return []

    rows: list[dict] = []
    seen_actor: set[str] = set()
    per_area_count: dict[str, int] = {}

    for item in items:
        url = _clean(item.url)
        if not url:
            continue
        if is_our_item(url, our_links, our_cafe_slugs):
            continue
        actor, actor_kind = identify_actor(url)
        if not actor or actor in seen_actor:
            continue
        if per_area_count.get(item.area, 0) >= top_n:
            continue
        seen_actor.add(actor)
        per_area_count[item.area] = per_area_count.get(item.area, 0) + 1
        rows.append({
            "날짜": date_str,
            "탭": _clean(tab),
            "키워드": keyword,
            "우리상태": _clean(our_state),
            "구좌": _clean(item.area),
            "블록명": _clean(item.block_name),  # 스마트블록·인기글 박스 제목 (AB 는 "")
            "순위": int(item.rank),
            "주체": actor,
            "종류": actor_kind,
            "제목": _clean(item.title),
            "URL": url,
        })
    return rows


def rows_to_sheet_values(rows: list[dict]) -> list[list]:
    """행 dict 리스트 → 시트 append 용 2D 리스트(헤더 순서 고정)."""
    return [[row.get(col, "") for col in HISTORY_HEADER] for row in rows]


class CompetitorCollector:
    """run 1회 동안 키워드별 경쟁사 행을 모은다 (재시도 시 마지막 결과가 이김)."""

    def __init__(
        self,
        *,
        our_links: set | None = None,
        our_cafe_slugs: set | None = None,
        top_n: int = DEFAULT_TOP_N,
    ) -> None:
        self.our_links = our_links or set()
        self.our_cafe_slugs = our_cafe_slugs or set()
        self.top_n = top_n
        self._by_keyword: dict[tuple[str, str], list[dict]] = {}

    def add(self, *, date_str: str, tab: str, keyword: str, our_state: str, items: list[SlotItem]) -> int:
        rows = build_competitor_rows(
            date_str=date_str,
            tab=tab,
            keyword=keyword,
            our_state=our_state,
            items=items,
            our_links=self.our_links,
            our_cafe_slugs=self.our_cafe_slugs,
            top_n=self.top_n,
        )
        # 같은 (탭, 키워드) 재처리 = 마지막 결과로 교체 (재시도 중복 방지).
        self._by_keyword[(_clean(tab), _clean(keyword))] = rows
        return len(rows)

    def rows(self) -> list[dict]:
        out: list[dict] = []
        for key in sorted(self._by_keyword):
            out.extend(self._by_keyword[key])
        return out

    def __len__(self) -> int:
        return sum(len(rows) for rows in self._by_keyword.values())


def aggregate_ranking(history_rows: list[dict]) -> list[dict]:
    """이력 행 전체 → 주체별 집계 · 순수함수.

    - 등장 횟수 = (날짜 × 키워드) 조합 수. 같은 날 같은 키워드는 1회.
    - 노출 키워드 수 = 서로 다른 키워드 수.
    - 평균 순위 = 등장한 자리들의 평균(소수 1자리).
    - 1위 횟수 = 순위 1로 잡힌 횟수.
    - 우리가 놓친 키워드 수 = 그 주체가 보인 키워드 중 우리 상태가 누락/미노출/삭제인 키워드 수.
    정렬 = 등장 횟수 내림차순 → 평균 순위 오름차순 → 주체 이름.
    """
    stats: dict[str, dict] = {}
    for row in history_rows or []:
        actor = _clean(row.get("주체"))
        if not actor:
            continue
        entry = stats.setdefault(actor, {
            "종류": _clean(row.get("종류")),
            "hits": set(),
            "keywords": set(),
            "ranks": [],
            "first_place": 0,
            "missed_keywords": set(),
            "last_date": "",
            "sample_url": _clean(row.get("URL")),
        })
        date_str = _clean(row.get("날짜"))
        keyword = _clean(row.get("키워드"))
        entry["hits"].add((date_str, keyword))
        if keyword:
            entry["keywords"].add(keyword)
        try:
            rank = int(row.get("순위") or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank > 0:
            entry["ranks"].append(rank)
            if rank == 1:
                entry["first_place"] += 1
        if _clean(row.get("우리상태")) in MISSED_STATES and keyword:
            entry["missed_keywords"].add(keyword)
        if date_str > entry["last_date"]:
            entry["last_date"] = date_str
            entry["sample_url"] = _clean(row.get("URL")) or entry["sample_url"]

    out: list[dict] = []
    for actor, entry in stats.items():
        ranks = entry["ranks"]
        avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else ""
        out.append({
            "주체": actor,
            "종류": entry["종류"],
            "등장 횟수": len(entry["hits"]),
            "노출 키워드 수": len(entry["keywords"]),
            "평균 순위": avg_rank,
            "1위 횟수": entry["first_place"],
            "우리가 놓친 키워드 수": len(entry["missed_keywords"]),
            "최근 등장일": entry["last_date"],
            "대표 URL": entry["sample_url"],
        })

    out.sort(key=lambda r: (
        -int(r["등장 횟수"]),
        float(r["평균 순위"]) if r["평균 순위"] != "" else 999.0,
        r["주체"],
    ))
    return out


def ranking_to_sheet_values(ranking: list[dict]) -> list[list]:
    return [[row.get(col, "") for col in RANKING_HEADER] for row in ranking]


# ─────────────────────────────────────────────────────────────────────────────
# 시트 I/O — 로컬엔 서비스계정 키가 없어 라이브 R/W 는 못 하므로 방어적으로 짠다.
# ─────────────────────────────────────────────────────────────────────────────


def _get_or_create_ws(client, tab_name: str, header: list[str]):
    """탭 get-or-create. 없으면 생성 + 헤더 기입. Returns (worksheet, created)."""
    import gspread

    spreadsheet = client.spreadsheet
    try:
        ws = spreadsheet.worksheet(tab_name)
        if not ws.row_values(1):
            ws.update("A1", [header], value_input_option="RAW")
        return ws, False
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=2000, cols=max(len(header), 5))
        ws.update("A1", [header], value_input_option="RAW")
        return ws, True


def _delete_row_numbers(ws, target_rows: list[int]) -> int:
    """행 번호 리스트를 연속 구간으로 묶어 아래→위 삭제 (API 호출 최소화).

    archive.py 의 429 사고(행 하나씩 삭제 → 분당 쓰기 한도 초과) 교훈을 그대로 적용.
    """
    if not target_rows:
        return 0
    target_rows = sorted(set(target_rows))
    ranges: list[tuple[int, int]] = []
    start = prev = target_rows[0]
    for row_num in target_rows[1:]:
        if row_num == prev + 1:
            prev = row_num
        else:
            ranges.append((start, prev))
            start = prev = row_num
    ranges.append((start, prev))
    for start, end in sorted(ranges, reverse=True):
        ws.delete_rows(start, end)
    return len(target_rows)


def append_daily_competitors(
    client,
    rows: list[list],
    date_str: str,
    *,
    tab_name: str = HISTORY_TAB_NAME,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """경쟁사 이력 행을 비공개 시트 탭에 멱등 append + 보관기간 지난 날짜 정리.

    Returns:
        {"rows_written": n, "date": date_str, "created_tab": bool, "pruned_rows": n}
        실패 시 rows_written=0 + "error" 키.
    """
    try:
        ws, created = _get_or_create_ws(client, tab_name, HISTORY_HEADER)
        pruned = 0
        if not created:
            all_values = ws.get_all_values()
            cutoff = _cutoff_date(date_str, retention_days)
            same_date_rows: list[int] = []
            old_rows: list[int] = []
            for row_num, values in enumerate(all_values[1:], start=2):
                if not values:
                    continue
                cell_date = _clean(values[0])
                if cell_date == _clean(date_str):
                    same_date_rows.append(row_num)
                elif cutoff and cell_date and cell_date < cutoff:
                    old_rows.append(row_num)
            pruned = _delete_row_numbers(ws, same_date_rows + old_rows)
        if rows:
            ws.append_rows(rows, value_input_option="RAW", insert_data_option="INSERT_ROWS")
        return {
            "rows_written": len(rows),
            "date": date_str,
            "created_tab": created,
            "pruned_rows": pruned,
        }
    except Exception as e:  # noqa: BLE001 — 적재 실패가 cron 을 죽이면 안 됨
        return {"rows_written": 0, "date": date_str, "created_tab": False, "error": str(e)}


def _cutoff_date(date_str: str, retention_days: int) -> str:
    """date_str("YYYY-MM-DD") 기준 보관 시작일. 파싱 실패 시 "" (정리 안 함)."""
    if not retention_days or retention_days <= 0:
        return ""
    from datetime import date, timedelta

    try:
        year, month, day = (int(part) for part in _clean(date_str).split("-"))
        return (date(year, month, day) - timedelta(days=retention_days)).isoformat()
    except (ValueError, TypeError):
        return ""


def read_history_rows(client, *, tab_name: str = HISTORY_TAB_NAME) -> list[dict]:
    """이력 탭 전체를 행 dict 리스트로 읽는다. 실패 시 빈 리스트."""
    try:
        ws, created = _get_or_create_ws(client, tab_name, HISTORY_HEADER)
        if created:
            return []
        values = ws.get_all_values()
        if len(values) < 2:
            return []
        header = [_clean(cell) for cell in values[0]]
        out: list[dict] = []
        for line in values[1:]:
            if not line:
                continue
            out.append({header[i]: line[i] for i in range(min(len(header), len(line)))})
        return out
    except Exception:  # noqa: BLE001
        return []


def write_ranking(
    client,
    ranking_values: list[list],
    *,
    tab_name: str = RANKING_TAB_NAME,
) -> dict:
    """집계 탭 전체 재작성 (헤더 + 집계 행). 매 실행 갱신 = 항상 최신 상태.

    Returns:
        {"rows_written": n, "created_tab": bool} / 실패 시 "error" 키.
    """
    try:
        ws, created = _get_or_create_ws(client, tab_name, RANKING_HEADER)
        ws.clear()
        payload = [RANKING_HEADER] + list(ranking_values)
        ws.update("A1", payload, value_input_option="RAW")
        return {"rows_written": len(ranking_values), "created_tab": created}
    except Exception as e:  # noqa: BLE001
        return {"rows_written": 0, "created_tab": False, "error": str(e)}


def run_competitor_update(
    client,
    collector: CompetitorCollector,
    date_str: str,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """이력 적재 → 이력 전체 재집계 → 집계 탭 갱신. 한 번에 처리하는 진입점."""
    rows = collector.rows()
    append_result = append_daily_competitors(
        client, rows_to_sheet_values(rows), date_str, retention_days=retention_days
    )
    history = read_history_rows(client)
    ranking = aggregate_ranking(history)
    write_result = write_ranking(client, ranking_to_sheet_values(ranking))
    return {
        "history": append_result,
        "ranking": write_result,
        "actors": len(ranking),
        "top": ranking[:10],
    }
