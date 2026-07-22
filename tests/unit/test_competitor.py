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
    build_competitor_rows,
    identify_actor,
    ranking_to_sheet_values,
    rows_to_sheet_values,
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
    <li><a href="https://cafe.naver.com/bigcafe/2001">인기글 첫번째 글 제목</a></li>
    <li><a href="https://blog.naver.com/blogger1/2002">인기글 두번째 글 제목</a></li>
    <li><a href="https://cafe.naver.com/ourcafe/2003">우리 카페 글 제목</a></li>
  </ul>
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

def _hist(date, keyword, actor, rank, state="누락", kind="카페", url="https://cafe.naver.com/x/1"):
    return {
        "날짜": date, "탭": "샴푸 카외", "키워드": keyword, "우리상태": state,
        "구좌": "인기글", "블록명": "", "순위": rank, "주체": actor, "종류": kind,
        "제목": "", "URL": url,
    }


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
    assert values[0][0] == "bigcafe"


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


def _values(date, keywords):
    return [
        [date, "샴푸 카외", kw, "누락", "인기글", "비듬샴푸 인기글", "1", "bigcafe", "카페", "", "u"]
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


def test_write_ranking_rewrites_whole_tab():
    sheet = FakeSpreadsheet()
    client = FakeClient(sheet)
    write_ranking(client, [["bigcafe", "카페", 5, 3, 1.5, 2, 3, "2026-07-23", "u"]])
    write_ranking(client, [["rivalcafe", "카페", 1, 1, 2.0, 0, 1, "2026-07-23", "u"]])

    ws = sheet.worksheet("경쟁사_랭킹")
    assert ws.values[0] == RANKING_HEADER
    assert len(ws.values) == 2          # 매 실행 전체 갱신 = 이전 행 잔류 X
    assert ws.values[1][0] == "rivalcafe"
