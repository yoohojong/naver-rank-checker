"""competitor 단위 테스트 (경쟁사 리스트업 + 등장 횟수 집계).

검증:
- collect_slot_items: 우리 글 매치 여부와 무관하게 구좌별 상위 글 목록을 그대로 뽑는다.
- identify_actor: 카페 구형/신형 URL, 블로그, 지식iN, 일반 웹 주체 식별.
- build_competitor_rows: 우리 글 제외, 같은 주체 1회만, 구좌별 top_n 제한.
- aggregate_ranking: 등장 횟수/키워드 수/평균 순위/1위 횟수/놓친 키워드 수 + 정렬.
- append_daily_competitors: 같은 날 재실행 멱등, 보관기간 지난 날짜 정리, 구간 삭제.
- write_ranking: 매 실행 전체 재작성.

시트 I/O 는 in-memory 대역으로 검증(네트워크 0).
"""
import gspread

from src.competitor import (
    HISTORY_HEADER,
    RANKING_HEADER,
    aggregate_ranking,
    append_daily_competitors,
    build_actor_aliases,
    build_competitor_rows,
    identify_actor,
    ranking_to_sheet_values,
    rows_to_sheet_values,
    run_competitor_update,
    write_ranking,
    CompetitorCollector,
)
from src.parser import SlotItem, collect_slot_items


# ----- identify_actor -----

def test_identify_actor_cafe_old_url():
    assert identify_actor("https://cafe.naver.com/rivalcafe/12345") == ("rivalcafe", "카페")


def test_identify_actor_cafe_new_url_uses_cafe_id():
    actor, kind = identify_actor("https://cafe.naver.com/ca-fe/cafes/30256014/articles/777")
    assert actor == "카페#30256014"
    assert kind == "카페"


def test_identify_actor_blog_and_kin_and_web():
    assert identify_actor("https://blog.naver.com/beautyguy/223") == ("beautyguy", "블로그")
    assert identify_actor("https://m.blog.naver.com/beautyguy/223") == ("beautyguy", "블로그")
    assert identify_actor("https://kin.naver.com/qna/detail.naver?d1id=7") == ("지식iN", "지식iN")
    assert identify_actor("https://www.oliveyoung.co.kr/goods/1") == ("www.oliveyoung.co.kr", "웹")


def test_identify_actor_empty():
    assert identify_actor("") == ("", "")


# ----- collect_slot_items -----

_AB_BOX = """
<div class="desktop_mode api_subject_bx">
  <div class="total_tit"><a href="https://cafe.naver.com/rivalcafe/1001">라이벌 카페 비듬샴푸 후기</a></div>
  <div class="detail_box">본문 미리보기 텍스트입니다. 두피가 가렵고 각질이 생겨서 고생했어요.</div>
</div>
"""

_POPULAR_BOX = """
<div class="desktop_mode api_subject_bx">
  <h2>비듬샴푸 인기글</h2>
  <ul>
    <li><a href="https://cafe.naver.com/bigcafe">빅카페 - 두피 고민 커뮤니티</a>
        <a href="https://cafe.naver.com/bigcafe/2001">인기글 첫번째 글 제목</a></li>
    <li><a href="https://blog.naver.com/blogger1/2002">인기글 두번째 글 제목</a></li>
    <li><a href="https://cafe.naver.com/ourcafe/2003">우리 카페 글 제목</a></li>
  </ul>
</div>
"""

# 스마트블록 = h2 있고 '인기글' 아님. 작성자 홈/피드 링크가 글 링크와 섞여 나온다.
_SMART_BLOCK_BOX = """
<div class="desktop_mode api_subject_bx">
  <h2>비듬샴푸 추천</h2>
  <div><a href="https://blog.naver.com/writer1">❣작성자1의 블로그❣</a>
       <a href="https://blog.naver.com/writer1/PostList.naver">블로그 글목록</a>
       <a href="https://blog.naver.com/writer1/223456789">스마트블록 글 제목</a></div>
  <div><a href="https://in.naver.com/writer2/feed">피드</a>
       <a href="https://cafe.naver.com/rivalcafe/5001">라이벌 카페 글</a></div>
</div>
"""

_PADDING = "<div class='pad'>" + ("x" * 800) + "</div>"


def _html(*boxes):
    return "<html><body>" + "".join(boxes) + _PADDING + "</body></html>"


def test_collect_slot_items_reads_ab_and_popular():
    items = collect_slot_items(_html(_AB_BOX, _POPULAR_BOX))

    ab = [i for i in items if i.area == "AB"]
    popular = [i for i in items if i.area == "인기글"]

    assert len(ab) == 1
    assert ab[0].rank == 1
    assert ab[0].url == "https://cafe.naver.com/rivalcafe/1001"
    assert ab[0].kind == "cafe"
    assert "라이벌 카페" in ab[0].title

    # 우리 글 매치 여부와 무관하게 박스 안 글 전부 (= 경쟁사 집계의 재료)
    assert [i.url for i in popular] == [
        "https://cafe.naver.com/bigcafe/2001",
        "https://blog.naver.com/blogger1/2002",
        "https://cafe.naver.com/ourcafe/2003",
    ]
    assert [i.rank for i in popular] == [1, 2, 3]
    assert popular[0].block_name == "비듬샴푸 인기글"


def test_collect_slot_items_empty_or_short_html():
    assert collect_slot_items("") == []
    assert collect_slot_items("<html>too short</html>") == []


def test_collect_slot_items_respects_max_per_area():
    items = collect_slot_items(_html(_AB_BOX, _POPULAR_BOX), max_per_area=2)
    popular = [i for i in items if i.area == "인기글"]
    assert len(popular) == 2


def test_collect_slot_items_smart_block_excludes_home_and_feed_links():
    """스마트블록 순위는 '글' 기준이어야 한다.

    작성자 홈(blog.naver.com/writer1)·글목록(PostList.naver)·피드(in.naver.com/writer2/feed)가
    자리를 차지하면 순위가 밀려 시트 L열(순위 판정)과 어긋나고, 작성자 홈이 경쟁 '글' 로 잡힌다.
    """
    items = collect_slot_items(_html(_SMART_BLOCK_BOX))
    smart = [i for i in items if i.area == "스마트블록"]

    assert [i.url for i in smart] == [
        "https://blog.naver.com/writer1/223456789",
        "https://cafe.naver.com/rivalcafe/5001",
    ]
    assert [i.rank for i in smart] == [1, 2]  # 홈·피드가 자리를 먹지 않는다


def test_collect_slot_items_picks_up_source_display_name():
    """출처 대문 링크 텍스트 = 사람이 읽는 이름. 주소만으로는 누군지 모른다."""
    items = collect_slot_items(_html(_POPULAR_BOX, _SMART_BLOCK_BOX))
    by_url = {i.url: i.source_name for i in items}

    assert by_url["https://cafe.naver.com/bigcafe/2001"] == "빅카페 - 두피 고민 커뮤니티"
    assert by_url["https://blog.naver.com/writer1/223456789"] == "❣작성자1의 블로그❣"


def test_collect_slot_items_matches_live_ranker_extractor_for_smart_block():
    """수집기와 순위 판정기가 같은 추출기를 써야 순위 숫자가 일치한다."""
    from bs4 import BeautifulSoup
    from src.parser import _extract_popular_items

    soup = BeautifulSoup(_html(_SMART_BLOCK_BOX), "lxml")
    box = soup.select(".desktop_mode.api_subject_bx")[0]
    ranker_urls = _extract_popular_items(box)
    collected = [i.url for i in collect_slot_items(_html(_SMART_BLOCK_BOX)) if i.area == "스마트블록"]

    assert collected == ranker_urls


# ----- build_competitor_rows -----

def _items():
    return [
        SlotItem(area="AB", rank=1, url="https://cafe.naver.com/rivalcafe/1001", kind="cafe", title="라이벌 글"),
        SlotItem(area="인기글", rank=1, url="https://cafe.naver.com/bigcafe/2001", kind="cafe", title="빅카페 글"),
        SlotItem(area="인기글", rank=2, url="https://blog.naver.com/blogger1/2002", kind="blog", title="블로거 글"),
        SlotItem(area="인기글", rank=3, url="https://cafe.naver.com/ourcafe/2003", kind="cafe", title="우리 글"),
        SlotItem(area="인기글", rank=4, url="https://cafe.naver.com/bigcafe/2004", kind="cafe", title="빅카페 두번째 글"),
    ]


def test_build_competitor_rows_excludes_our_link():
    rows = build_competitor_rows(
        date_str="2026-07-23",
        tab="샴푸 카외",
        keyword="비듬샴푸",
        our_state="누락",
        items=_items(),
        our_links={"https://cafe.naver.com/ourcafe/2003"},
    )
    actors = [r["주체"] for r in rows]
    assert "ourcafe" not in actors
    assert actors == ["rivalcafe", "bigcafe", "blogger1"]


def test_build_competitor_rows_excludes_our_cafe_slug():
    rows = build_competitor_rows(
        date_str="2026-07-23",
        tab="샴푸 카외",
        keyword="비듬샴푸",
        our_state="누락",
        items=_items(),
        our_cafe_slugs={"ourcafe"},
    )
    assert "ourcafe" not in [r["주체"] for r in rows]


def test_build_competitor_rows_counts_same_actor_once_at_best_rank():
    # bigcafe 가 인기글에 2개(1위·4위) 깔았어도 등장은 1회, 순위는 더 높은 쪽.
    rows = build_competitor_rows(
        date_str="2026-07-23",
        tab="샴푸 카외",
        keyword="비듬샴푸",
        our_state="누락",
        items=_items(),
        our_cafe_slugs={"ourcafe"},
    )
    big = [r for r in rows if r["주체"] == "bigcafe"]
    assert len(big) == 1
    assert big[0]["순위"] == 1


def test_build_competitor_rows_best_rank_across_different_areas():
    """구좌가 여러 개면 문서 순서 ≠ 순위 순서 — 낮은 자리가 먼저 나와도 높은 자리를 남겨야 한다."""
    items = [
        SlotItem(area="스마트블록", rank=4, url="https://cafe.naver.com/bigcafe/9004", kind="cafe"),
        SlotItem(area="인기글", rank=1, url="https://cafe.naver.com/bigcafe/9001", kind="cafe"),
    ]
    rows = build_competitor_rows(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락", items=items
    )
    assert len(rows) == 1
    assert rows[0]["순위"] == 1
    assert rows[0]["구좌"] == "인기글"


def test_total_cap_does_not_starve_ab():
    """AB 순위는 페이지 전체 1..N, 스마트블록은 박스마다 1부터 — 한 줄로 세워 자르면 AB 가 밀린다.

    사장님이 제일 중요하게 보는 구좌가 잘리면 안 되므로 구좌를 번갈아 채운다.
    """
    items = [
        SlotItem(area="AB", rank=r, url=f"https://cafe.naver.com/ab{r}/1", kind="cafe")
        for r in range(1, 6)
    ] + [
        SlotItem(area="스마트블록", rank=1, url=f"https://blog.naver.com/sb{b}/1", kind="blog")
        for b in range(3)
    ] + [
        SlotItem(area="인기글", rank=1, url="https://cafe.naver.com/pop1/1", kind="cafe"),
    ]
    rows = build_competitor_rows(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락",
        items=items, top_n=5, max_per_keyword=6,
    )
    ab_rows = [r for r in rows if r["구좌"] == "AB"]
    assert len(rows) == 6
    assert len(ab_rows) >= 3  # 한 줄 정렬이면 2건까지 밀렸었다
    assert ab_rows[0]["순위"] == 1


def test_single_area_page_uses_full_budget():
    """구좌가 하나뿐인 페이지에서는 번갈아 채우기가 오히려 적게 담으면 안 된다."""
    items = [
        SlotItem(area="AB", rank=r, url=f"https://cafe.naver.com/ab{r}/1", kind="cafe")
        for r in range(1, 8)
    ]
    rows = build_competitor_rows(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락",
        items=items, top_n=5, max_per_keyword=6,
    )
    assert len(rows) == 5  # 구좌 상한(top_n)까지는 채운다
    assert [r["순위"] for r in rows] == [1, 2, 3, 4, 5]


def test_build_competitor_rows_caps_total_per_keyword():
    """구좌가 3종이라 구좌별 상한만으로는 최대 3배가 된다 — 키워드 총량 상한이 필요."""
    items = [
        SlotItem(area=area, rank=rank, url=f"https://cafe.naver.com/c{area}{rank}/1", kind="cafe")
        for area in ("AB", "스마트블록", "인기글")
        for rank in range(1, 6)
    ]
    rows = build_competitor_rows(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락",
        items=items, top_n=5, max_per_keyword=6,
    )
    assert len(rows) == 6


def test_build_competitor_rows_top_n_per_area():
    rows = build_competitor_rows(
        date_str="2026-07-23",
        tab="샴푸 카외",
        keyword="비듬샴푸",
        our_state="누락",
        items=_items(),
        top_n=1,
    )
    by_area = {}
    for row in rows:
        by_area.setdefault(row["구좌"], 0)
        by_area[row["구좌"]] += 1
    assert all(count <= 1 for count in by_area.values())


def test_build_competitor_rows_blank_keyword_or_no_items():
    assert build_competitor_rows(
        date_str="2026-07-23", tab="t", keyword="", our_state="누락", items=_items()
    ) == []
    assert build_competitor_rows(
        date_str="2026-07-23", tab="t", keyword="비듬샴푸", our_state="누락", items=[]
    ) == []


def test_rows_to_sheet_values_matches_header_order():
    rows = build_competitor_rows(
        date_str="2026-07-23",
        tab="샴푸 카외",
        keyword="비듬샴푸",
        our_state="누락",
        items=_items()[:1],
    )
    values = rows_to_sheet_values(rows)
    assert len(values[0]) == len(HISTORY_HEADER)
    assert values[0][0] == "2026-07-23"
    assert values[0][HISTORY_HEADER.index("주체")] == "rivalcafe"


# ----- CompetitorCollector -----

def test_collector_last_write_wins_per_keyword():
    collector = CompetitorCollector(our_cafe_slugs={"ourcafe"})
    collector.add(date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락", items=_items())
    first_len = len(collector)
    # 재시도로 같은 키워드를 다시 처리해도 중복 누적되지 않는다.
    collector.add(date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락", items=_items())
    assert len(collector) == first_len


# ----- aggregate_ranking -----

def _hist(date, keyword, actor, rank, state="누락", kind="카페", url="https://cafe.naver.com/x/1", name=""):
    return {
        "날짜": date, "탭": "샴푸 카외", "키워드": keyword, "우리상태": state,
        "구좌": "인기글", "블록명": "", "순위": rank, "주체": actor, "이름": name,
        "종류": kind, "제목": "", "URL": url,
    }


def test_build_actor_aliases_merges_old_and_new_cafe_url_forms():
    """같은 카페가 구형 주소(slug)와 신형 주소(카페#숫자)로 갈리면 횟수가 반씩 쪼개진다."""
    history = [
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 1, name="빅카페 - 두피 커뮤니티"),
        _hist("2026-07-22", "지루성두피", "카페#30256014", 2, name="빅카페 - 두피 커뮤니티"),
    ]
    aliases = build_actor_aliases(history)
    assert aliases == {"카페#30256014": "bigcafe"}  # 이름 있는 쪽이 대표


def test_aggregate_ranking_merges_split_actor_into_one_row():
    history = [
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 1, name="빅카페"),
        _hist("2026-07-22", "지루성두피", "카페#30256014", 2, name="빅카페"),
        _hist("2026-07-22", "탈모샴푸", "rivalcafe", 1, name="라이벌카페"),
    ]
    ranking = aggregate_ranking(history)
    assert [r["주체"] for r in ranking] == ["bigcafe", "rivalcafe"]
    assert ranking[0]["등장 횟수"] == 2  # 쪼개지지 않고 합산
    assert ranking[0]["이름"] == "빅카페"


def test_build_actor_aliases_no_merge_without_shared_name():
    history = [
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 1, name="빅카페"),
        _hist("2026-07-22", "지루성두피", "카페#999", 2, name=""),
    ]
    assert build_actor_aliases(history) == {}


def test_build_actor_aliases_does_not_merge_blogs_sharing_generic_name():
    """블로그 이름은 '일상'·'리뷰' 처럼 흔해서 겹친다 — 엮으면 없는 경쟁사를 1위로 만든다."""
    history = [
        _hist("2026-07-22", "a", "blogger1", 1, kind="블로그", name="일상"),
        _hist("2026-07-22", "b", "blogger2", 1, kind="블로그", name="일상"),
        _hist("2026-07-22", "c", "blogger3", 1, kind="블로그", name="일상"),
    ]
    assert build_actor_aliases(history) == {}

    ranking = aggregate_ranking(history)
    assert sorted(r["주체"] for r in ranking) == ["blogger1", "blogger2", "blogger3"]


def test_build_actor_aliases_does_not_merge_across_kinds():
    """카페·블로그·웹샵이 같은 이름을 쓸 수 있다 — 종류가 다르면 절대 안 묶는다."""
    history = [
        _hist("2026-07-22", "a", "somecafe", 1, kind="카페", name="같은이름"),
        _hist("2026-07-22", "b", "someblog", 1, kind="블로그", name="같은이름"),
        _hist("2026-07-22", "c", "shop.co.kr", 1, kind="웹", name="같은이름"),
    ]
    assert build_actor_aliases(history) == {}


def test_build_actor_aliases_requires_exactly_one_named_side():
    """이름 형태가 둘 이상이면 어느 쪽이 그 숫자 ID 인지 알 수 없다 — 묶지 않는다."""
    history = [
        _hist("2026-07-22", "a", "cafeA", 1, name="같은이름"),
        _hist("2026-07-22", "b", "cafeB", 1, name="같은이름"),
        _hist("2026-07-22", "c", "카페#777", 1, name="같은이름"),
    ]
    assert build_actor_aliases(history) == {}


def test_aggregate_ranking_counts_and_sorts():
    history = [
        _hist("2026-07-21", "비듬샴푸", "bigcafe", 1),
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 3),
        _hist("2026-07-22", "지루성두피", "bigcafe", 2, state="AB"),
        _hist("2026-07-22", "비듬샴푸", "rivalcafe", 2),
    ]
    ranking = aggregate_ranking(history)

    top = ranking[0]
    assert top["주체"] == "bigcafe"
    assert top["등장 횟수"] == 3          # (날짜×키워드) 조합 3건
    assert top["노출 키워드 수"] == 2
    assert top["평균 순위"] == 2.0        # (1+3+2)/3
    assert top["1위 횟수"] == 1
    assert top["우리가 놓친 키워드 수"] == 1  # 지루성두피는 우리가 AB 노출 = 놓친 것 아님
    assert top["최근 등장일"] == "2026-07-22"

    assert ranking[1]["주체"] == "rivalcafe"
    assert ranking[1]["등장 횟수"] == 1


def test_aggregate_ranking_same_day_same_keyword_counts_once():
    history = [
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 1),
        _hist("2026-07-22", "비듬샴푸", "bigcafe", 4),  # 같은 날 같은 키워드 재적재
    ]
    ranking = aggregate_ranking(history)
    assert ranking[0]["등장 횟수"] == 1


def test_aggregate_ranking_empty():
    assert aggregate_ranking([]) == []
    assert aggregate_ranking(None) == []


def test_ranking_to_sheet_values_matches_header_order():
    ranking = aggregate_ranking([_hist("2026-07-22", "비듬샴푸", "bigcafe", 1)])
    values = ranking_to_sheet_values(ranking)
    assert len(values[0]) == len(RANKING_HEADER)
    assert values[0][RANKING_HEADER.index("주체")] == "bigcafe"


# ----- 시트 I/O 대역 -----

class FakeWorksheet:
    def __init__(self, values=None):
        self.values = [list(r) for r in (values or [])]
        self.delete_calls = []

    def row_values(self, row_1based):
        idx = row_1based - 1
        if 0 <= idx < len(self.values):
            return list(self.values[idx])
        return []

    def get_all_values(self):
        return [list(r) for r in self.values]

    def update(self, cell, data, value_input_option="RAW"):
        if cell != "A1":
            return
        for offset, line in enumerate(data):
            if offset < len(self.values):
                self.values[offset] = list(line)
            else:
                self.values.append(list(line))

    def clear(self):
        self.values = []

    def resize(self, rows=None, cols=None):
        # 실제 시트 정합: 격자를 줄이면 넘치는 행은 잘린다.
        if rows is not None and rows < len(self.values):
            self.values = self.values[:rows]
        self.grid_rows = rows

    def append_rows(self, rows, value_input_option="RAW", insert_data_option="INSERT_ROWS"):
        for r in rows:
            self.values.append(list(r))

    def delete_rows(self, start, end=None):
        end = start if end is None else end
        self.delete_calls.append((start, end))
        del self.values[start - 1:end]


class FakeSpreadsheet:
    def __init__(self, worksheets=None):
        self._worksheets = dict(worksheets or {})
        self.added = []

    def worksheet(self, title):
        if title not in self._worksheets:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self._worksheets[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet()
        self._worksheets[title] = ws
        self.added.append(title)
        return ws


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet


def _values(date, keywords, actor="bigcafe"):
    return [
        [date, "샴푸 카외", kw, "누락", "인기글", "블록", "1", actor, "빅카페", "카페", "", "u"]
        for kw in keywords
    ]


def test_append_creates_tab_with_header():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    result = append_daily_competitors(client, _values("2026-07-23", ["비듬샴푸"]), "2026-07-23")

    assert result["created_tab"] is True
    assert result["rows_written"] == 1
    ws = sheet.worksheet("경쟁사_이력")
    assert ws.values[0] == HISTORY_HEADER
    assert ws.values[1][2] == "비듬샴푸"


def test_append_is_idempotent_for_same_date():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    append_daily_competitors(client, _values("2026-07-23", ["a", "b"]), "2026-07-23")
    append_daily_competitors(client, _values("2026-07-23", ["a", "b"]), "2026-07-23")

    ws = sheet.worksheet("경쟁사_이력")
    data_rows = [r for r in ws.values[1:] if r]
    assert len(data_rows) == 2  # 두 번 돌아도 그날 1벌


def test_append_keeps_other_dates_and_prunes_old_ones():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    append_daily_competitors(client, _values("2026-06-01", ["old"]), "2026-06-01")
    append_daily_competitors(client, _values("2026-07-22", ["yesterday"]), "2026-07-22")
    append_daily_competitors(
        client, _values("2026-07-23", ["today"]), "2026-07-23", retention_days=30
    )

    ws = sheet.worksheet("경쟁사_이력")
    dates = {r[0] for r in ws.values[1:] if r}
    assert dates == {"2026-07-22", "2026-07-23"}  # 30일 지난 6/1 정리


def test_append_deletes_contiguous_rows_in_one_call():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    append_daily_competitors(client, _values("2026-07-23", ["a", "b", "c"]), "2026-07-23")
    ws = sheet.worksheet("경쟁사_이력")
    ws.delete_calls.clear()
    append_daily_competitors(client, _values("2026-07-23", ["a", "b", "c"]), "2026-07-23")

    # 연속 3행 = delete_rows 3번이 아니라 구간 1회 (시트 429 방어)
    assert ws.delete_calls == [(2, 4)]


def test_append_error_is_captured_not_raised():
    class BrokenClient:
        @property
        def spreadsheet(self):
            raise RuntimeError("no auth")

    result = append_daily_competitors(BrokenClient(), [["x"]], "2026-07-23")
    assert result["rows_written"] == 0
    assert "error" in result


def test_partial_run_keeps_todays_other_keywords():
    """차단으로 중간에 끊긴 run(일부 키워드만 수집)이 그날 나머지 기록을 지우면 안 된다.

    03:00 run 이 3개 키워드를 적재한 뒤, 09:00 run 이 1개만 돌고 끊긴 상황.
    """
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    append_daily_competitors(client, _values("2026-07-23", ["a", "b", "c"]), "2026-07-23")
    append_daily_competitors(client, _values("2026-07-23", ["b"]), "2026-07-23")

    ws = sheet.worksheet("경쟁사_이력")
    keywords = sorted(r[2] for r in ws.values[1:] if r)
    assert keywords == ["a", "b", "c"]  # a·c 는 이번에 안 돌았을 뿐, 사라지면 안 됨


def test_append_returns_history_for_aggregation_without_second_read():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    append_daily_competitors(client, _values("2026-07-22", ["a"]), "2026-07-22")
    result = append_daily_competitors(client, _values("2026-07-23", ["b"]), "2026-07-23")

    history = result["history"]
    assert {row["키워드"] for row in history} == {"a", "b"}
    assert {row["날짜"] for row in history} == {"2026-07-22", "2026-07-23"}


def test_run_competitor_update_writes_both_tabs():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    collector = CompetitorCollector(our_cafe_slugs={"ourcafe"})
    collector.add(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락", items=_items()
    )
    result = run_competitor_update(client, collector, "2026-07-23")

    assert result["history"]["rows_written"] > 0
    assert result["actors"] > 0
    assert sheet.worksheet("경쟁사_랭킹").values[0] == RANKING_HEADER
    assert len(sheet.worksheet("경쟁사_랭킹").values) > 1


def test_run_competitor_update_preserves_ranking_when_history_fails():
    """이력 적재/읽기 실패 시 집계 탭을 백지로 덮어쓰면 안 된다(지난 집계 보존)."""
    class HalfBrokenClient:
        def __init__(self, spreadsheet):
            self.spreadsheet = spreadsheet
            self._calls = 0

    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    write_ranking(client, [["빅카페", "bigcafe", "카페", 5, 3, 1.5, 2, 3, "2026-07-22", "u"]])

    class BrokenSpreadsheet:
        def worksheet(self, title):
            raise RuntimeError("read quota exceeded")

        def add_worksheet(self, title, rows, cols):
            raise RuntimeError("read quota exceeded")

    broken = FakeClient(BrokenSpreadsheet())
    collector = CompetitorCollector()
    collector.add(
        date_str="2026-07-23", tab="샴푸 카외", keyword="비듬샴푸", our_state="누락", items=_items()
    )
    result = run_competitor_update(broken, collector, "2026-07-23")

    assert "error" in result["history"]
    assert result["ranking"]["rows_written"] == 0
    assert "skipped" in result["ranking"]
    # 기존 집계 탭은 그대로 남아 있다.
    assert len(sheet.worksheet("경쟁사_랭킹").values) == 2


def test_scattered_deletions_collapse_into_one_call_and_lose_nothing():
    """이번에 0건 나온 키워드가 사이사이 끼면 지울 구간이 흩어진다 → 호출 폭증(429) 위험.

    구간이 많으면 한 통으로 지우고, 그 사이 살아남아야 할 행은 다시 넣어야 한다.
    """
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    keywords = [f"k{i:02d}" for i in range(20)]
    append_daily_competitors(client, _values("2026-07-23", keywords), "2026-07-23")

    ws = sheet.worksheet("경쟁사_이력")
    ws.delete_calls.clear()
    # 짝수 키워드만 다시 수집됨 = 지울 행이 한 칸 걸러 흩어진 상태
    rerun = [k for i, k in enumerate(keywords) if i % 2 == 0]
    append_daily_competitors(client, _values("2026-07-23", rerun), "2026-07-23")

    assert len(ws.delete_calls) == 1  # 10회가 아니라 1회
    surviving = sorted(r[2] for r in ws.values[1:] if r)
    assert surviving == sorted(keywords)  # 안 돈 키워드도 전부 살아 있다


def test_header_mismatch_stops_instead_of_writing_shifted_data():
    """탭 헤더가 코드와 다르면 칸이 밀려 읽힌다 — 그 값으로 집계 탭을 덮어쓰면 안 된다."""
    old_header = [c for c in HISTORY_HEADER if c != "이름"]  # 이름 칸 없던 옛 스키마
    stale_ws = FakeWorksheet([old_header, ["2026-07-22", "샴푸 카외", "a", "누락", "인기글",
                                           "블록", "1", "bigcafe", "카페", "", "u"]])
    sheet = FakeSpreadsheet({"경쟁사_이력": stale_ws})
    client = FakeClient(sheet)

    result = append_daily_competitors(client, _values("2026-07-23", ["b"]), "2026-07-23")

    assert result["history"] is None
    assert "헤더" in result["error"]
    assert len(stale_ws.values) == 2  # 아무것도 안 건드림


def test_ranking_tab_resized_to_fit_and_capped():
    """격자(기본 2000행)보다 큰 내용을 쓰면 시트가 거부해 탭이 빈 채 남는다."""
    from src.competitor import RANKING_MAX_ROWS

    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    many = [[f"이름{i}", f"actor{i}", "카페", 1, 1, 1.0, 0, 1, "2026-07-23", "u"] for i in range(500)]
    result = write_ranking(client, many)

    ws = sheet.worksheet("경쟁사_랭킹")
    assert result["rows_written"] == RANKING_MAX_ROWS
    assert result["dropped_rows"] == 500 - RANKING_MAX_ROWS  # 잘린 수를 숨기지 않는다
    assert ws.grid_rows >= len(ws.values)
    assert ws.values[0] == RANKING_HEADER


def test_write_ranking_rewrites_whole_tab():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    write_ranking(client, [["빅카페", "bigcafe", "카페", 5, 3, 1.5, 2, 3, "2026-07-23", "u"]])
    write_ranking(client, [["라이벌", "rivalcafe", "카페", 1, 1, 2.0, 0, 1, "2026-07-23", "u"]])

    ws = sheet.worksheet("경쟁사_랭킹")
    assert ws.values[0] == RANKING_HEADER
    assert len(ws.values) == 2          # 매 실행 전체 갱신 = 이전 행 잔류 X
    assert ws.values[1][1] == "rivalcafe"
