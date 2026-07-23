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

# ★ 사장님이 시트에서 실제로 보는 표 (2026-07-23 "그냥 제품군이랑 경쟁사 이름. 그리고 횟수").
#   원본 기록(경쟁사_이력)은 계산용이라 숨김 처리하고, 눈에 보이는 건 이 표 하나다.
SUMMARY_TAB_NAME = "경쟁사"
SUMMARY_HEADER = ["제품군", "경쟁사 이름", "횟수", "우리가 놓친", "평균 순위", "확인일"]
SUMMARY_TOP_N = 20  # 제품군마다 몇 곳까지 보여줄지

# 집계 결과 열 이름 (성과 대시보드·요약용. 시트에는 쓰지 않는다 — 탭은 이력 하나뿐).
RANKING_HEADER = [
    "이름", "주체", "종류", "등장 횟수", "노출 키워드 수", "평균 순위", "1위 횟수",
    "우리가 놓친 키워드 수", "최근 등장일", "대표 URL",
]
# 제품별 집계 열 이름 (대시보드용).
PRODUCT_HEADER = [
    "기준일", "제품", "이름", "주체", "종류", "노출 키워드 수", "점유율(%)",
    "평균 순위", "우리가 놓친 키워드 수", "경쟁 키워드 수",
]
PRODUCT_TOP_N = 20  # 제품마다 상위 몇 곳까지 시트에 남길지

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
# 그래도 남는 삭제 호출 수의 절대 상한. 넘으면 이번 실행은 정리를 건너뛴다
# (수백 번 지우다 한도에 걸려 '지우다 만 상태' 가 되는 것보다 안 지우는 편이 안전).
HARD_MAX_DELETE_CALLS = 20

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
        skip_tabs: set | None = None,
    ) -> None:
        self.our_links = our_links or set()
        self.our_cafe_slugs = our_cafe_slugs or set()
        self.top_n = top_n
        # 기록에서 통째로 뺄 탭(숨김 탭 = 작업 안 하는 제품).
        # 사장님 2026-07-23 "두드러기는 섞지마" — 보고·집계에서 숨김 탭 제외 규칙과 같은 잣대.
        self.skip_tabs = {_clean(t) for t in (skip_tabs or set())}
        self._by_keyword: dict[tuple[str, str], list[dict]] = {}

    def add(  # noqa: PLR0913 — 호출부 가독성 위해 키워드 인자 유지
        self, *, date_str: str, tab: str, keyword: str, our_state: str, items: list[SlotItem]
    ) -> int:
        if _clean(tab) in self.skip_tabs:
            return 0  # 숨김 탭 = 기록하지 않는다(시트에도 대시보드에도 안 섞임)
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


def build_actor_aliases(history_rows: list[dict]) -> dict:  # noqa: ARG001
    """★ 폐기(2026-07-23 4차 검토) — 항상 빈 dict. 아무것도 합치지 않는다.

    원래 목적: 카페 주소가 구형(이름)/신형(숫자)으로 갈려 한 카페가 두 곳으로 세어지는 것 보정.
    폐기 이유: 표시 이름이 같다는 것 말고는 같은 곳이라는 근거가 없다. 네이버 카페 이름은
    유일하지 않아("다이어트", "맘스카페") **서로 다른 두 카페가 1:1 로 짝지어져 한 곳으로 합쳐지고,
    없는 경쟁사가 2배 횟수로 1위에 오른다.** 조건을 아무리 좁혀도 이 구멍은 안 닫혔다(3차·4차 연속 검출).

    이 프로젝트 확정 원칙: **적게 세는 오류 > 지어내는 오류.**
    같은 카페가 갈려 횟수가 나뉘는 건 감수하고(안내문에 한계로 명시), 합치기는 하지 않는다.
    합치려면 근거가 필요하다 — 시트 '카페매핑' 탭 같은 실제 대조표가 생기면 그때 다시 넣는다.
    """
    return {}


def aggregate_ranking(history_rows: list[dict]) -> list[dict]:
    """이력 행 전체 → 주체별 집계 · 순수함수.

    - 등장 횟수 = (날짜 × 키워드) 조합 수. 같은 날 같은 키워드는 1회.
    - 노출 키워드 수 = 서로 다른 키워드 수.
    - 평균 순위 = 등장한 자리들의 평균(소수 1자리).
    - 1위 횟수 = 순위 1로 잡힌 횟수.
    - 우리가 놓친 키워드 수 = 그 주체가 보인 키워드 중 우리 상태가 누락/미노출/삭제인 키워드 수.
    - 주체를 합치는 보정은 하지 않는다(build_actor_aliases 폐기 사유 참고).
    정렬 = 등장 횟수 내림차순 → 평균 순위 오름차순 → 주체 이름.
    """
    aliases = build_actor_aliases(history_rows)
    stats: dict[str, dict] = {}
    # 같은 (날짜·키워드·주체)가 두 번 적재된 경우(넣기 재시도 등) 평균 순위·1위 횟수가
    # 부풀지 않도록 한 번만 센다. 등장 횟수는 원래 집합이라 영향 없음.
    counted: set = set()
    for row in history_rows or []:
        actor = _clean(row.get("주체"))
        if not actor:
            continue
        actor = aliases.get(actor, actor)
        dedupe_key = (_clean(row.get("날짜")), _clean(row.get("키워드")), actor)
        if dedupe_key in counted:
            continue
        counted.add(dedupe_key)
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




def build_summary_rows(history_rows: list[dict], *, top_n: int = SUMMARY_TOP_N) -> list[list]:
    """사장님이 시트에서 볼 표 — 제품군 · 경쟁사 이름 · 횟수 (+ 곁들이는 3칸).

    ★ 2026-07-23 사장님: "그냥 제품군이랑 경쟁사 이름. 그리고 횟수 같은걸 알고싶은건데
      왜 이렇게 되어있지?" — 그 전까지 시트에 날짜·키워드·순위·URL 까지 든 원본 기록을
      그대로 뒀더니 열어봐도 뭘 봐야 할지 모르는 표가 됐다. 보는 표는 이 세 칸이 중심이다.

    - 횟수 = 그 제품군에서 그 경쟁사가 **상위권에 뜬 키워드 수**(최신 확인일 기준).
    - 제품군마다 top_n 곳까지, 횟수 많은 순.
    """
    rows_all = list(history_rows or [])
    dates = {_clean(r.get("날짜")) for r in rows_all if _clean(r.get("날짜"))}
    latest = max(dates) if dates else ""

    acc: dict = {}
    for row in [r for r in rows_all if _clean(r.get("날짜")) == latest]:
        product = _clean(row.get("탭")).replace(" 카외", "").strip()
        actor = _clean(row.get("주체"))
        keyword = _clean(row.get("키워드"))
        if not product or not actor or not keyword:
            continue
        entry = acc.setdefault((product, actor), {
            "이름": _clean(row.get("이름")) or actor,
            "keywords": set(), "missed": set(), "ranks": [],
        })
        if keyword in entry["keywords"]:
            continue
        entry["keywords"].add(keyword)
        if not entry["이름"] or entry["이름"] == actor:
            entry["이름"] = _clean(row.get("이름")) or actor
        try:
            rank = int(row.get("순위") or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank > 0:
            entry["ranks"].append(rank)
        if _clean(row.get("우리상태")) in MISSED_STATES:
            entry["missed"].add(keyword)

    ordered = sorted(
        acc.items(), key=lambda kv: (kv[0][0], -len(kv[1]["keywords"]), kv[0][1])
    )
    out: list[list] = []
    per_product: dict = {}
    for (product, actor), entry in ordered:
        if per_product.get(product, 0) >= top_n:
            continue
        per_product[product] = per_product.get(product, 0) + 1
        ranks = entry["ranks"]
        out.append([
            product,
            entry["이름"],
            len(entry["keywords"]),
            len(entry["missed"]),
            round(sum(ranks) / len(ranks), 1) if ranks else "",
            latest,
        ])
    return out


def aggregate_by_product(history_rows: list[dict], *, top_n: int = PRODUCT_TOP_N) -> list[dict]:
    """제품(시트 탭)별 경쟁사 집계 · 순수함수. **최근 1일치만** 본다.

    사장님 요청(2026-07-23): "구글 스프레드시트에도 하나 섹터 추가 / 제품별로 분류해서".

    ★ 기간을 최신 날짜 하루로 못박는다 (2026-07-23 검토 지적).
      21일 전체를 합치면 '그동안 한 번이라도 보인 비율'이 되어 시간이 갈수록 100%로 수렴하고,
      같은 이름(점유율)으로 대시보드(최신일 기준)와 다른 숫자가 나와 사장님이 헷갈린다.
    ★ 분모 = 그 제품에서 **경쟁사가 한 곳이라도 잡힌 키워드 수**.
      우리가 모든 자리를 차지한 키워드는 기록 자체가 없어 분모에 안 들어간다 — 그래서
      '추적 키워드 대비'가 아니라 '경쟁이 있었던 키워드 대비' 다. 열 이름도 그렇게 적는다.
    """
    rows_all = list(history_rows or [])
    dates = {_clean(r.get("날짜")) for r in rows_all if _clean(r.get("날짜"))}
    latest = max(dates) if dates else ""
    keywords_by_product: dict = {}
    stats: dict = {}
    for row in [r for r in rows_all if _clean(r.get("날짜")) == latest]:
        product = _clean(row.get("탭"))
        actor = _clean(row.get("주체"))
        keyword = _clean(row.get("키워드"))
        if not product or not actor or not keyword:
            continue
        keywords_by_product.setdefault(product, set()).add(keyword)
        entry = stats.setdefault((product, actor), {
            "이름": _clean(row.get("이름")),
            "종류": _clean(row.get("종류")),
            "keywords": set(),
            "ranks": [],
            "missed": set(),
        })
        if keyword in entry["keywords"]:
            continue  # 같은 키워드 중복 적재 = 평균 순위 부풀림 방지(집계 탭과 같은 규칙)
        entry["keywords"].add(keyword)
        try:
            rank = int(row.get("순위") or 0)
        except (TypeError, ValueError):
            rank = 0
        if rank > 0:
            entry["ranks"].append(rank)
        if _clean(row.get("우리상태")) in MISSED_STATES:
            entry["missed"].add(keyword)
        if not entry["이름"]:
            entry["이름"] = _clean(row.get("이름"))

    out: list[dict] = []
    for (product, actor), entry in stats.items():
        total = len(keywords_by_product.get(product) or ())
        share = round(len(entry["keywords"]) / total * 100, 1) if total else ""
        ranks = entry["ranks"]
        out.append({
            "기준일": latest,
            "제품": product,
            "이름": entry["이름"],
            "주체": actor,
            "종류": entry["종류"],
            "노출 키워드 수": len(entry["keywords"]),
            "점유율(%)": share,   # 경쟁이 있었던 키워드 대비
            "평균 순위": round(sum(ranks) / len(ranks), 1) if ranks else "",
            "우리가 놓친 키워드 수": len(entry["missed"]),
            "경쟁 키워드 수": total,
        })

    out.sort(key=lambda r: (r["제품"], -int(r["노출 키워드 수"]), r["주체"]))
    # 제품별 상위 N 곳만 남긴다(시트에서 한눈에 보이도록).
    trimmed: list[dict] = []
    seen_count: dict = {}
    for row in out:
        product = row["제품"]
        if seen_count.get(product, 0) >= top_n:
            continue
        seen_count[product] = seen_count.get(product, 0) + 1
        trimmed.append(row)
    return trimmed




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
    ranges = _contiguous_ranges(target_rows)
    if len(ranges) > max_calls:
        span = (min(target_rows), max(target_rows))
        ws.delete_rows(span[0], span[1])
        return span[1] - span[0] + 1, span

    deleted = _execute_deletions(ws, ranges)
    return deleted, None


def _contiguous_ranges(row_numbers) -> list:
    """행 번호 → 연속 구간 [(start, end), ...] (오름차순)."""
    rows = sorted(set(row_numbers))
    if not rows:
        return []
    ranges: list[tuple[int, int]] = []
    start = prev = rows[0]
    for row_num in rows[1:]:
        if row_num == prev + 1:
            prev = row_num
        else:
            ranges.append((start, prev))
            start = prev = row_num
    ranges.append((start, prev))
    return ranges


def _merge_ranges(ranges: list) -> list:
    """겹치거나 맞닿은 구간을 합친다 (오름차순 반환)."""
    merged: list[list] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _execute_deletions(ws, ranges: list) -> int:
    """구간들을 아래→위 순서로 지운다. 위를 먼저 지우면 아래 행 번호가 밀려 어긋난다."""
    total = 0
    for start, end in sorted(_merge_ranges(ranges), reverse=True):
        ws.delete_rows(start, end)
        total += end - start + 1
    return total


def plan_deletion_ranges(groups: list, kept_rows, *, max_calls: int = MAX_DELETE_CALLS,
                         max_readd: int = MAX_READD_ROWS) -> list:
    """지울 행 무리들 → 실제로 지울 구간 목록 · 순수함수(시트 접근 없음).

    ★ 무리별로 따로 '묶을지' 판단한 뒤, 마지막에 전부 합쳐 한 번에 계획한다
      (2026-07-23 4차 검토 지적). 무리를 순서대로 지우면, 무리들이 서로 엇갈려 있을 때
      (사장님이 시트를 키워드순으로 정렬해두는 등) 먼저 지운 만큼 아래 행 번호가 밀려
      **엉뚱한 행이 지워지고 살아야 할 행이 사라진다.** 구간을 합쳐 한 번에 계획하면
      엇갈려 있어도 안전하고, '묶기' 판단은 무리별이라 구간이 표 전체로 번지지도 않는다.

    Args:
        groups: 지울 행 번호 리스트들 (예: [보관만료 행들, 오늘 교체분 행들])
        kept_rows: 보존해야 할 행 번호 모음 (묶어 지울 때 다시 넣을 대상 판정용)

    Returns:
        (지울 구간 [(start, end), ...], 포기한 무리 수)
        구간은 겹침 없이 합쳐진 상태. 포기한 무리가 있으면 이번엔 그만큼 안 지운다.
    """
    planned: list[tuple[int, int]] = []
    skipped = 0
    for group in groups:
        if not group:
            continue
        ranges = _contiguous_ranges(group)
        if len(ranges) > max_calls:
            span = (min(group), max(group))
            inside = [n for n in kept_rows if span[0] <= n <= span[1]]
            if len(inside) <= max_readd:
                # 다시 넣을 양이 감당 가능 → 한 통으로 묶어 1회에 끝낸다.
                ranges = [span]
            elif len(ranges) > HARD_MAX_DELETE_CALLS:
                # 묶지도 못하고 구간도 너무 많다(예: 시트를 정렬해 날짜가 뒤섞인 경우).
                # 수백 번 지우면 분당 한도에 걸려 지우다 만 상태가 된다 →
                # 이번 실행은 **안 지우고 넘어간다**. 남은 옛 행은 집계에서 (날짜·키워드·주체)로
                # 한 번만 세므로 숫자는 안 틀리고, 다음 정상 실행에서 정리된다.
                skipped += 1
                continue
        planned.extend(ranges)
    return _merge_ranges(planned), skipped


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
                if not values or not any(_clean(cell) for cell in values):
                    continue  # 빈 줄 = 보존 대상도 아님(다시 넣지 않는다)
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
            # 무리별로 '묶을지' 판단 → 전부 합쳐 한 번에 계획 → 아래부터 삭제.
            # 무리를 차례로 지우면 무리가 엇갈릴 때 행 번호가 밀려 엉뚱한 행이 지워진다.
            planned, skipped_groups = plan_deletion_ranges(
                [expired_rows, replaced_rows], set(kept_by_row)
            )
            if skipped_groups:
                print(
                    f"[경쟁사] 이력 정리 일부 건너뜀 — 지울 행이 표 전체에 흩어져 있음"
                    f"(무리 {skipped_groups}개). 숫자는 중복 제거로 유지되고 다음 실행에서 정리됨."
                )
            pruned = _execute_deletions(ws, planned)
            # 지운 구간 안에 있던 보존 행 = 다시 넣는다(순서 무관).
            readd = [
                values for num, values in sorted(kept_by_row.items())
                if any(start <= num <= end for start, end in planned)
            ]
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


def write_summary(client, rows: list[list], *, tab_name: str = SUMMARY_TAB_NAME) -> dict:
    """사장님이 보는 표를 매 실행 새로 쓴다(제품군 · 경쟁사 이름 · 횟수).

    격자를 내용 크기에 맞춘 뒤 쓰고, 여유 줄은 빈 값으로 덮어 지난 줄이 남지 않게 한다.
    """
    try:
        ws, created = _get_or_create_ws(client, tab_name, SUMMARY_HEADER)
        payload = [SUMMARY_HEADER] + list(rows)
        from src.sheets import _sheets_api_retry

        try:
            _sheets_api_retry(
                lambda: ws.resize(rows=len(payload) + 10, cols=max(len(SUMMARY_HEADER), 8)),
                ctx="경쟁사 표 resize",
            )
        except Exception:  # noqa: BLE001
            ws.clear()
        blank = [""] * len(SUMMARY_HEADER)
        ws.update("A1", payload + [list(blank) for _ in range(10)], value_input_option="RAW")
        return {"rows_written": len(rows), "created_tab": created}
    except Exception as e:  # noqa: BLE001
        return {"rows_written": 0, "created_tab": False, "error": str(e)}


def hide_history_tab(client, *, tab_name: str = HISTORY_TAB_NAME) -> bool:
    """원본 기록 탭은 계산용이라 숨긴다 — 사장님 눈에 보이는 표는 '경쟁사' 하나."""
    try:
        ws = client.spreadsheet.worksheet(tab_name)
        if ws._properties.get("hidden"):
            return True
        client.spreadsheet.batch_update({"requests": [{
            "updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True},
                "fields": "hidden",
            }
        }]})
        return True
    except Exception:  # noqa: BLE001 — 숨기기 실패가 cron 을 죽이면 안 됨
        return False


def run_competitor_update(
    client,
    collector: CompetitorCollector,
    date_str: str,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """경쟁사 기록을 **시트 탭 하나**에 적재하고, 집계는 값만 돌려준다.

    ★ 2026-07-23 사장님: "구글스프레드 뭐 3개까지 만들어 하나로 취합해 나눌거까지 없잖아"
      → 시트에 쓰는 탭은 `경쟁사_이력` **하나뿐**. 랭킹·제품별 표는 시트에 만들지 않고
        성과 대시보드에서 같은 기록으로 계산해 보여준다(사장님이 지표는 대시보드에서 본다고 확정).
      집계 값은 그대로 돌려주므로 텔레그램 요약·로그에서는 계속 쓸 수 있다.
    """
    rows = collector.rows()
    append_result = append_daily_competitors(
        client, rows_to_sheet_values(rows), date_str, retention_days=retention_days
    )
    history = append_result.get("history")
    if history is None:
        return {
            "history": append_result,
            "actors": 0,
            "top": [],
        }
    ranking = aggregate_ranking(history)
    summary_rows = build_summary_rows(history)
    summary_result = write_summary(client, summary_rows)
    hide_history_tab(client)
    return {
        "history": append_result,
        "summary": summary_result,
        "byProduct": aggregate_by_product(history),
        "actors": len(ranking),
        "top": ranking[:10],
    }
