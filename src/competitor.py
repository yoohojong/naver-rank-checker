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
    "날짜", "탭", "키워드", "우리상태", "구좌", "블록명", "순위", "주체", "이름", "종류", "제목", "URL",
]
HISTORY_TAB_NAME = "경쟁사_이력"

# 집계 탭 스키마 (고정). 사장님이 보는 화면 = 이 탭.
RANKING_HEADER = [
    "이름", "주체", "종류", "등장 횟수", "노출 키워드 수", "평균 순위", "1위 횟수",
    "우리가 놓친 키워드 수", "최근 등장일", "대표 URL",
]
RANKING_TAB_NAME = "경쟁사_랭킹"

# 시트 적재량 상한. 구좌(AB/스마트블록/인기글)가 3종이라 구좌별 상한만 두면 최대 3배가 된다
# → 키워드 총량 상한을 따로 둔다. 423 키워드 × 6 = 하루 ~2,500행(약 3만 셀).
DEFAULT_TOP_N = 5           # 한 구좌에서 최대 몇 곳까지
DEFAULT_MAX_PER_KEYWORD = 6  # 한 키워드에서 최대 몇 곳까지(구좌 합산)
# 이력 탭 보관 일수. 이보다 오래된 날짜 블록은 적재할 때 같이 정리한다.
# 21일 × 2,500행 × 12열 ≈ 63만 셀 — 스프레드시트 전체 상한(1천만 셀) 대비 안전 구간.
DEFAULT_RETENTION_DAYS = 21
# 행 삭제 API 호출 상한. 넘으면 한 구간으로 묶어 1회만 지운다(분당 쓰기 한도 방어).
MAX_DELETE_CALLS = 5
# 묶어 지울 때 '다시 넣어야 할' 행 수 상한. 이보다 크면 묶지 않는다 —
# 다시 넣다 실패하면 그만큼이 사라지므로, 호출을 몇 번 더 쓰는 편이 안전하다.
MAX_READD_ROWS = 3000
# 집계 탭에 남길 최대 줄 수. 사장님이 보는 건 위쪽 몇십 곳이고,
# 전체를 쓰면 한 번에 보내는 양이 커져 실패 위험이 오른다. 잘린 수는 로그로 알린다.
RANKING_MAX_ROWS = 300

# "우리가 놓친" 으로 볼 상태값 (K 컬럼 base 기준).
MISSED_STATES = {"누락", "미노출", "삭제"}

# 총량 상한을 채울 때 구좌를 도는 순서 (사장님 중요도 순).
_AREA_ORDER = ["AB", "스마트블록", "인기글"]


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
    max_per_keyword: int = DEFAULT_MAX_PER_KEYWORD,
) -> list[dict]:
    """키워드 1건의 구좌 목록 → 경쟁사 행 dict 리스트 · 순수함수.

    - 우리 글은 제외한다(우리 글 제외가 곧 "경쟁사").
    - 같은 주체가 한 키워드에 여러 글을 올렸으면 **가장 높은 자리 1건만** 센다.
      (한 카페가 3개 깔았다고 등장 3회로 세면 "제일 많이 보이는 애들" 이 왜곡됨)
      구좌가 여러 개면 문서 순서 ≠ 순위 순서라, 순위로 먼저 정렬한 뒤 고른다.
    - 구좌별 top_n · 키워드 총 max_per_keyword 까지만 남긴다(시트 적재량 방어).
      총량 상한은 **구좌를 번갈아** 채운다. 순위 숫자는 구좌끼리 비교할 수 있는 값이 아니라
      (AB 는 페이지 전체 1..N, 스마트블록은 박스마다 1부터 다시 시작) 한 줄로 세워 자르면
      AB 가 밀려난다 — 사장님이 제일 중요하게 보는 구좌가 잘리는 셈(2026-07-23 검토 지적).
    """
    keyword = _clean(keyword)
    if not keyword or not items:
        return []

    # 1단계: 순위 오름차순으로 훑어 주체별 '가장 높은 자리' 1건만 남긴다(구좌 무관).
    picked: dict[str, list] = {}
    seen_actor: set[str] = set()
    for item in sorted(items, key=lambda it: int(it.rank or 999)):
        url = _clean(item.url)
        if not url:
            continue
        if is_our_item(url, our_links, our_cafe_slugs):
            continue
        actor, actor_kind = identify_actor(url)
        if not actor or actor in seen_actor:
            continue
        area_bucket = picked.setdefault(_clean(item.area), [])
        if len(area_bucket) >= top_n:
            continue
        seen_actor.add(actor)
        area_bucket.append((item, actor, actor_kind))

    # 2단계: 구좌를 번갈아 뽑아 총량 상한을 채운다(한 구좌가 상한을 독식하지 않도록).
    ordered: list[tuple] = []
    for idx in range(top_n):
        for area in _AREA_ORDER + [a for a in picked if a not in _AREA_ORDER]:
            bucket = picked.get(area) or []
            if idx < len(bucket):
                ordered.append(bucket[idx])
            if len(ordered) >= max_per_keyword:
                break
        if len(ordered) >= max_per_keyword:
            break

    return [
        {
            "날짜": date_str,
            "탭": _clean(tab),
            "키워드": keyword,
            "우리상태": _clean(our_state),
            "구좌": _clean(item.area),
            "블록명": _clean(item.block_name),  # 스마트블록·인기글 박스 제목 (AB 는 "")
            "순위": int(item.rank),
            "주체": actor,
            "이름": _clean(item.source_name),  # 검색 결과에 뜬 카페·블로그 표시 이름
            "종류": actor_kind,
            "제목": _clean(item.title),
            "URL": url_of(item),
        }
        for item, actor, actor_kind in ordered[:max_per_keyword]
    ]


def url_of(item) -> str:
    return _clean(item.url)


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

    def add(  # noqa: PLR0913 — 호출부 가독성 위해 키워드 인자 유지
        self, *, date_str: str, tab: str, keyword: str, our_state: str, items: list[SlotItem]
    ) -> int:
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


def build_actor_aliases(history_rows: list[dict]) -> dict:
    """주소 형태가 갈린 **같은 카페**만 하나로 묶는 대조표 · 순수함수.

    네이버 카페 주소는 구형(cafe.naver.com/{이름})과 신형(ca-fe/cafes/{숫자})이 섞여 나온다.
    한 카페가 "pusanmommy" 와 "카페#123" 으로 갈리면 등장 횟수가 반씩 쪼개진다.

    ★ 묶는 조건을 아주 좁게 건다 (2026-07-23 독립 검토 지적 반영):
      ① 종류가 '카페' 로 같고 ② 한쪽이 숫자 ID 형태("카페#…") 이고 ③ 표시 이름이 같을 때만.
      이름만 같으면 묶던 이전 판은 "일상"·"리뷰" 같은 흔한 블로그 이름끼리 엮여 **없는 경쟁사를
      1위로 만들어내는** 더 나쁜 답을 냈다. 못 묶어서 적게 세는 쪽이 지어내는 쪽보다 안전하다.

    Returns:
        {숫자 ID 주체: 이름 형태 주체}. 조건 안 맞으면 빈 dict.
    """
    by_name: dict[str, dict] = {}
    for row in history_rows or []:
        name = _clean(row.get("이름"))
        actor = _clean(row.get("주체"))
        kind = _clean(row.get("종류"))
        if not name or not actor or kind != "카페":
            continue
        by_name.setdefault(name, {})[actor] = kind

    aliases: dict = {}
    for actors in by_name.values():
        numeric = [a for a in actors if a.startswith("카페#")]
        named = sorted(a for a in actors if not a.startswith("카페#"))
        # 이름 형태 1개 + 숫자 ID 1개 = 1:1 짝일 때만 묶는다.
        # 어느 한쪽이라도 여러 개면 어느 것과 어느 것이 같은 곳인지 알 수 없다
        # (이름만 같은 서로 다른 카페 여럿을 한 곳으로 만들어버린다 — 2026-07-23 3차 검토).
        if len(numeric) != 1 or len(named) != 1:
            continue
        aliases[numeric[0]] = named[0]
    return aliases


def aggregate_ranking(history_rows: list[dict]) -> list[dict]:
    """이력 행 전체 → 주체별 집계 · 순수함수.

    - 등장 횟수 = (날짜 × 키워드) 조합 수. 같은 날 같은 키워드는 1회.
    - 노출 키워드 수 = 서로 다른 키워드 수.
    - 평균 순위 = 등장한 자리들의 평균(소수 1자리).
    - 1위 횟수 = 순위 1로 잡힌 횟수.
    - 우리가 놓친 키워드 수 = 그 주체가 보인 키워드 중 우리 상태가 누락/미노출/삭제인 키워드 수.
    - 주소 형태가 갈린 같은 곳은 표시 이름으로 묶는다(build_actor_aliases).
    정렬 = 등장 횟수 내림차순 → 평균 순위 오름차순 → 주체 이름.
    """
    aliases = build_actor_aliases(history_rows)
    stats: dict[str, dict] = {}
    for row in history_rows or []:
        actor = _clean(row.get("주체"))
        if not actor:
            continue
        actor = aliases.get(actor, actor)
        entry = stats.setdefault(actor, {
            "이름": _clean(row.get("이름")),
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
        if not entry["이름"]:
            entry["이름"] = _clean(row.get("이름"))
        if date_str > entry["last_date"]:
            entry["last_date"] = date_str
            entry["sample_url"] = _clean(row.get("URL")) or entry["sample_url"]

    out: list[dict] = []
    for actor, entry in stats.items():
        ranks = entry["ranks"]
        avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else ""
        out.append({
            "이름": entry["이름"],
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


def _delete_row_numbers(ws, target_rows: list[int], *, max_calls: int = MAX_DELETE_CALLS) -> tuple:
    """행 번호 리스트를 연속 구간으로 묶어 아래→위 삭제 (API 호출 최소화).

    archive.py 의 429 사고(행 하나씩 삭제 → 분당 쓰기 한도 초과) 교훈을 그대로 적용.

    ★ 구간이 흩어지면(= 이번에 안 돈 키워드가 사이사이 남아 구멍이 뚫리면) 호출 수가
      구간 수만큼 늘어 다시 429 위험이 된다. max_calls 를 넘으면 **한 통으로 묶어**
      (맨 위 대상 ~ 맨 아래 대상) 1회만 지우고, 그 사이에 살아남아야 할 행은
      호출부가 다시 넣는다(2026-07-23 독립 검토 지적 반영).

    Returns:
        (지운 행 수, 통째로 지운 구간 (start, end) 또는 None)
        두 번째 값이 있으면 = 그 구간 안 보존 행을 호출부가 재적재해야 한다.
    """
    if not target_rows:
        return 0, None
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

    if len(ranges) > max_calls:
        span = (target_rows[0], target_rows[-1])
        ws.delete_rows(span[0], span[1])
        return span[1] - span[0] + 1, span

    for start, end in sorted(ranges, reverse=True):
        ws.delete_rows(start, end)
    return len(target_rows), None


def append_daily_competitors(
    client,
    rows: list[list],
    date_str: str,
    *,
    tab_name: str = HISTORY_TAB_NAME,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """경쟁사 이력 행을 비공개 시트 탭에 멱등 append + 보관기간 지난 날짜 정리.

    ★ 멱등 단위 = (날짜 × 키워드). '그날 전체'를 지우고 새로 쓰지 않는다.
      네이버 차단으로 중간에 끊긴 run, 일부 행만 도는 재검사 run 이 이번에 못 돈 키워드의
      오늘치 기록까지 날려버리는 사고를 구조적으로 막는다 — 이번에 돈 키워드만 갈아끼운다.

    적재하면서 이미 읽은 시트 내용을 그대로 돌려준다(집계용). 같은 탭을 두 번 읽지 않는다.

    Returns:
        {"rows_written": n, "date": date_str, "created_tab": bool, "pruned_rows": n,
         "history": [행 dict, ...]}  ← 적재 후 탭에 남은 전체 내용
        실패 시 rows_written=0 + "error" 키 + history=None (집계 단계가 이걸 보고 멈춘다).
    """
    try:
        ws, created = _get_or_create_ws(client, tab_name, HISTORY_HEADER)
        pruned = 0
        kept: list[list] = []
        header = list(HISTORY_HEADER)
        keyword_col = HISTORY_HEADER.index("키워드")
        # 이번 run 이 다시 쓴 키워드만 교체 대상.
        replaced_keywords = {
            _clean(row[keyword_col]) for row in rows if len(row) > keyword_col
        }
        readd: list[list] = []
        if not created:
            all_values = ws.get_all_values()
            if all_values and all_values[0]:
                header = [_clean(cell) for cell in all_values[0]]
            # 헤더가 코드와 다르면(옛 스키마·1행 밀림) 칸이 어긋난 채 읽힌다.
            # 어긋난 값으로 집계 탭을 통째로 다시 쓰면 조용히 틀린 표가 나가므로 여기서 멈춘다.
            # 시트가 빈 칸을 채워 넓혀 돌려주는 경우가 있어(오른쪽 아무 칸에 글자 하나만 있어도)
            # 뒤쪽 빈 칸은 떼고 비교한다. 안 그러면 그 한 칸 때문에 기능이 영구히 멈춘다.
            while header and not header[-1]:
                header.pop()
            if header[:len(HISTORY_HEADER)] != list(HISTORY_HEADER):
                return {
                    "rows_written": 0, "date": date_str, "created_tab": False,
                    "error": f"이력 탭 헤더 불일치 — 적재 중단 (탭 헤더={header[:3]}…)",
                    "history": None,
                }
            header = list(HISTORY_HEADER)
            cutoff = _cutoff_date(date_str, retention_days)
            expired_rows: list[int] = []   # 보관기간 지남 — 항상 맨 위 연속 블록
            replaced_rows: list[int] = []  # 이번에 다시 쓴 오늘치 — 아래쪽에 흩어짐
            kept_by_row: dict[int, list] = {}
            for row_num, values in enumerate(all_values[1:], start=2):
                if not values:
                    continue
                cell_date = _clean(values[0])
                cell_keyword = _clean(values[keyword_col]) if len(values) > keyword_col else ""
                if cutoff and cell_date and cell_date < cutoff:
                    expired_rows.append(row_num)
                elif cell_date == _clean(date_str) and cell_keyword in replaced_keywords:
                    replaced_rows.append(row_num)
                else:
                    kept_by_row[row_num] = values  # 다른 날짜 · 이번에 안 돈 키워드 = 보존

            # ★ 두 무리를 반드시 따로 지운다 (2026-07-23 3차 검토 지적).
            #   같이 묶으면 '맨 위 오래된 행 ~ 맨 아래 오늘 행' = 사실상 표 전체가 한 구간이 되어,
            #   지운 뒤 다시 넣다가 한 번만 실패해도 21일치가 통째로 사라진다.
            #   따로 지우면 오래된 블록은 붙어 있어 1회로 끝나고, 다시 넣을 양도 하루치로 제한된다.
            pruned = 0
            readd_nums: set = set()
            # 아래쪽 무리부터 지운다 — 위를 먼저 지우면 아래 행 번호가 밀려 엉뚱한 행이 지워진다.
            groups = [g for g in (expired_rows, replaced_rows) if g]
            for group in sorted(groups, key=max, reverse=True):
                # 한 통으로 묶었을 때 다시 넣어야 할 양이 너무 크면 묶지 않는다
                # (다시 넣다 실패하면 그만큼이 날아가므로, 호출 몇 번 더 쓰는 편이 안전).
                inside = [n for n in kept_by_row if group[0] <= n <= group[-1]]
                max_calls = MAX_DELETE_CALLS if len(inside) <= MAX_READD_ROWS else len(group)
                deleted, span = _delete_row_numbers(ws, group, max_calls=max_calls)
                pruned += deleted
                if span is not None:
                    readd_nums.update(n for n in kept_by_row if span[0] <= n <= span[1])
            readd = [kept_by_row[n] for n in sorted(readd_nums)]
            kept = list(kept_by_row.values())
        payload = readd + list(rows)
        if payload:
            # 지우기는 이미 끝났으므로 이 넣기가 실패하면 그만큼이 사라진다 → 재시도로 감싼다.
            from src.sheets import _sheets_api_retry
            _sheets_api_retry(
                lambda: ws.append_rows(
                    payload, value_input_option="RAW", insert_data_option="INSERT_ROWS"
                ),
                ctx="경쟁사 이력 append",
            )
        history = _values_to_dicts(header, kept) + _values_to_dicts(HISTORY_HEADER, rows)
        return {
            "rows_written": len(rows),
            "date": date_str,
            "created_tab": created,
            "pruned_rows": pruned,
            "history": history,
        }
    except Exception as e:  # noqa: BLE001 — 적재 실패가 cron 을 죽이면 안 됨
        return {
            "rows_written": 0, "date": date_str, "created_tab": False,
            "error": str(e), "history": None,
        }


def _values_to_dicts(header: list[str], values: list[list]) -> list[dict]:
    """2D 시트 값 → 행 dict 리스트 (헤더 길이 넘는 칸은 버림)."""
    out: list[dict] = []
    for line in values or []:
        if not line:
            continue
        out.append({header[i]: line[i] for i in range(min(len(header), len(line)))})
    return out


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
        shown = list(ranking_values)[:RANKING_MAX_ROWS]
        dropped = max(0, len(ranking_values) - len(shown))
        payload = [RANKING_HEADER] + shown
        # 탭 격자를 payload 크기에 맞춘다. 격자보다 큰 내용을 쓰면 시트가 거부하고,
        # clear() 로 비운 뒤였다면 탭이 빈 채로 남는다. resize 는 넘치는 옛 행도 함께 잘라준다.
        try:
            ws.resize(rows=len(payload) + 10, cols=max(len(RANKING_HEADER), 10))
        except Exception:  # noqa: BLE001 — resize 미지원 대역/구버전이면 clear 로 대체
            ws.clear()
        ws.update("A1", payload, value_input_option="RAW")
        # 경쟁사가 줄어든 날, 예전 줄이 아래에 그대로 남아 오늘 것처럼 보이는 걸 막는다.
        # (쓰기 '뒤' 에 잘라내므로 중간에 실패해도 표가 비는 창은 없다.)
        try:
            ws.resize(rows=len(payload), cols=max(len(RANKING_HEADER), 10))
        except Exception:  # noqa: BLE001
            pass
        return {"rows_written": len(shown), "created_tab": created, "dropped_rows": dropped}
    except Exception as e:  # noqa: BLE001
        return {"rows_written": 0, "created_tab": False, "error": str(e)}


def run_competitor_update(
    client,
    collector: CompetitorCollector,
    date_str: str,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """이력 적재 → 이력 전체 재집계 → 집계 탭 갱신. 한 번에 처리하는 진입점.

    이력 적재가 실패했으면 집계 탭은 **건드리지 않는다** — 읽기 실패로 빈 집계를 써서
    사장님이 보는 탭이 백지가 되는 사고를 막는다(실패 시 지난 집계가 그대로 남는 편이 낫다).
    """
    rows = collector.rows()
    append_result = append_daily_competitors(
        client, rows_to_sheet_values(rows), date_str, retention_days=retention_days
    )
    history = append_result.get("history")
    if history is None:
        return {
            "history": append_result,
            "ranking": {"rows_written": 0, "skipped": "이력 적재 실패 — 집계 탭 보존"},
            "actors": 0,
            "top": [],
        }
    ranking = aggregate_ranking(history)
    write_result = write_ranking(client, ranking_to_sheet_values(ranking))
    return {
        "history": append_result,
        "ranking": write_result,
        "actors": len(ranking),
        "top": ranking[:10],
    }
