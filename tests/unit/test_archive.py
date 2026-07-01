"""archive 단위 테스트 (상위노출 실적 일별 아카이빙 · 검증판).

검증:
- build_archive_rows: 여러 탭·여러 상태(AB/누락/삭제/미노출/빈키워드) 정확 행 생성,
  빈 키워드 스킵, rank None → "".
- append_daily_archive 멱등: 같은 날짜 2번 호출 시 중복 안 쌓이고 1벌만,
  다른 날짜는 보존. get-or-create(탭 없을 때 생성 + 헤더).

시트 I/O 는 in-memory worksheet 대역(FakeWorksheet)으로 검증(네트워크 0, gspread 실호출 X).
"""
import gspread

from src.archive import (
    ARCHIVE_HEADER,
    ARCHIVE_TAB_NAME,
    append_daily_archive,
    build_archive_rows,
)


def _row(kw, area, l=""):
    return {
        "키워드": kw,
        "노출영역": area,
        "노출여부(통합탭 순위)": l,
    }


# ----- build_archive_rows -----

def test_build_archive_rows_multiple_tabs_and_states():
    tabs = {
        "샴푸 카외": [
            _row("비듬샴푸", "AB (6/19 13:00~)", "5"),
            _row("탈모샴푸", "누락 (6/18 03:00~)", ""),
        ],
        "토닉 카외": [
            _row("두피토닉", "삭제 (6/17 03:00)", ""),
            _row("모발토닉", "미노출 (6/18 03:00~)", ""),
        ],
    }
    rows = build_archive_rows(tabs, "2026-07-02")

    assert rows == [
        ["2026-07-02", "샴푸 카외", "비듬샴푸", "AB", "5"],
        ["2026-07-02", "샴푸 카외", "탈모샴푸", "누락", ""],
        ["2026-07-02", "토닉 카외", "두피토닉", "삭제", ""],
        ["2026-07-02", "토닉 카외", "모발토닉", "미노출", ""],
    ]


def test_build_archive_rows_skips_blank_keyword():
    tabs = {
        "샴푸 카외": [
            _row("비듬샴푸", "AB", "3"),
            _row("", "AB", "1"),        # 빈 키워드 = 스킵
            _row("   ", "인기글", "2"),  # 공백만 = 스킵
        ]
    }
    rows = build_archive_rows(tabs, "2026-07-02")
    assert len(rows) == 1
    assert rows[0][2] == "비듬샴푸"


def test_build_archive_rows_rank_none_becomes_empty():
    tabs = {"샴푸 카외": [_row("탈모샴푸", "누락 (6/18 03:00~)", "")]}
    rows = build_archive_rows(tabs, "2026-07-02")
    assert rows[0][4] == ""  # rank None → ""


def test_build_archive_rows_empty_area_is_minochul():
    # 빈 노출영역 → k_base_of 가 "미노출" 로.
    tabs = {"샴푸 카외": [_row("비듬샴푸", "", "")]}
    rows = build_archive_rows(tabs, "2026-07-02")
    assert rows[0][3] == "미노출"


def test_build_archive_rows_injectable_helpers():
    # k_base_of/rank_of 주입으로 교체 가능(테스트 용이성 검증).
    tabs = {"t": [_row("kw", "whatever", "99")]}
    rows = build_archive_rows(
        tabs,
        "2026-07-02",
        k_base_of=lambda r: "CUSTOM",
        rank_of=lambda r: 7,
    )
    assert rows[0] == ["2026-07-02", "t", "kw", "CUSTOM", "7"]


def test_build_archive_rows_empty_tabs():
    assert build_archive_rows({}, "2026-07-02") == []
    assert build_archive_rows(None, "2026-07-02") == []


# ----- append_daily_archive (fake client) -----

class FakeWorksheet:
    """in-memory worksheet 대역. 시트 그리드를 2D 리스트로 흉내낸다."""

    def __init__(self, values=None):
        # values = [[...], ...] (1행 = 헤더 포함 가능)
        self.values = [list(r) for r in (values or [])]

    def row_values(self, row_1based):
        idx = row_1based - 1
        if 0 <= idx < len(self.values):
            return list(self.values[idx])
        return []

    def get_all_values(self):
        return [list(r) for r in self.values]

    def update(self, cell, data, value_input_option="RAW"):
        # A1 헤더 기입만 지원(대역).
        if cell == "A1":
            if not self.values:
                self.values.append(list(data[0]))
            else:
                self.values[0] = list(data[0])

    def append_rows(self, rows, value_input_option="RAW", insert_data_option="INSERT_ROWS"):
        for r in rows:
            self.values.append(list(r))

    def delete_rows(self, row_1based):
        idx = row_1based - 1
        if 0 <= idx < len(self.values):
            self.values.pop(idx)


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


def _rows_for(date_str, keywords):
    return [[date_str, "샴푸 카외", kw, "AB", "1"] for kw in keywords]


def test_append_creates_tab_with_header_when_missing():
    ss = FakeSpreadsheet()  # 아카이브 탭 없음
    client = FakeClient(ss)

    rows = _rows_for("2026-07-02", ["비듬샴푸", "탈모샴푸"])
    result = append_daily_archive(client, rows, "2026-07-02")

    assert result["created_tab"] is True
    assert result["rows_written"] == 2
    assert ARCHIVE_TAB_NAME in ss.added
    ws = ss.worksheet(ARCHIVE_TAB_NAME)
    # 1행 = 헤더, 이후 = 데이터 2행.
    assert ws.values[0] == ARCHIVE_HEADER
    assert len(ws.values) == 3


def test_append_idempotent_same_date_no_duplication():
    ss = FakeSpreadsheet()
    client = FakeClient(ss)

    rows = _rows_for("2026-07-02", ["비듬샴푸", "탈모샴푸"])
    append_daily_archive(client, rows, "2026-07-02")
    # 같은 날짜 2번째 호출(하루 4번 cron 시뮬레이션) → 중복 안 쌓임.
    result2 = append_daily_archive(client, rows, "2026-07-02")

    ws = ss.worksheet(ARCHIVE_TAB_NAME)
    # 헤더 1 + 그날 2행 = 3 (2벌이면 5가 됨).
    assert len(ws.values) == 3
    assert result2["created_tab"] is False


def test_append_preserves_other_dates():
    ss = FakeSpreadsheet()
    client = FakeClient(ss)

    # 어제 데이터 먼저.
    append_daily_archive(client, _rows_for("2026-07-01", ["어제키워드"]), "2026-07-01")
    # 오늘 데이터 2번(멱등).
    append_daily_archive(client, _rows_for("2026-07-02", ["오늘A", "오늘B"]), "2026-07-02")
    append_daily_archive(client, _rows_for("2026-07-02", ["오늘A", "오늘B"]), "2026-07-02")

    ws = ss.worksheet(ARCHIVE_TAB_NAME)
    data_rows = ws.values[1:]  # 헤더 제외
    dates = [r[0] for r in data_rows]
    # 어제 1행 보존 + 오늘 2행(중복 없음) = 3행.
    assert dates.count("2026-07-01") == 1
    assert dates.count("2026-07-02") == 2
    assert len(data_rows) == 3


def test_append_empty_rows_ok():
    ss = FakeSpreadsheet()
    client = FakeClient(ss)
    result = append_daily_archive(client, [], "2026-07-02")
    assert result["rows_written"] == 0
    assert result["created_tab"] is True  # 탭은 만들어짐(헤더만)
    ws = ss.worksheet(ARCHIVE_TAB_NAME)
    assert ws.values == [ARCHIVE_HEADER]


def test_append_existing_tab_missing_header_backfills():
    # 탭은 있는데 헤더가 비어있을 때 헤더부터 기록(방어적).
    ss = FakeSpreadsheet(worksheets={ARCHIVE_TAB_NAME: FakeWorksheet()})
    client = FakeClient(ss)
    append_daily_archive(client, _rows_for("2026-07-02", ["k"]), "2026-07-02")
    ws = ss.worksheet(ARCHIVE_TAB_NAME)
    assert ws.values[0] == ARCHIVE_HEADER


def test_append_error_is_swallowed():
    # 시트 I/O 예외가 위로 안 던져지고 안전 dict 로 반환되는지.
    class BoomSpreadsheet:
        def worksheet(self, title):
            raise RuntimeError("boom")

    client = FakeClient(BoomSpreadsheet())
    result = append_daily_archive(client, _rows_for("2026-07-02", ["k"]), "2026-07-02")
    assert result["rows_written"] == 0
    assert "error" in result
