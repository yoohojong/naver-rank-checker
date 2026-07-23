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

    def __init__(self, values=None, insert_at=None, title="상위노출_이력"):
        # values = [[...], ...] (1행 = 헤더 포함 가능)
        self.values = [list(r) for r in (values or [])]
        self.delete_calls = []  # (start, end) 기록 — 범위삭제(429 fix) 회귀검증용
        self.insert_at = insert_at   # None = 맨 아래(정상). 숫자 = 그 행에 끼워넣기.
        self.title = title

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
        """실제 gspread 정합: 넣은 위치를 응답으로 돌려준다.

        ★insert_at 을 주면 '표 중간에 끼워넣기'를 흉내낸다. Sheets values.append 는
          '시트 끝'이 아니라 '찾아낸 표의 끝' 다음에 넣으므로, 중간에 빈 줄이 있으면
          실제로 이렇게 동작할 수 있다(독립검토 HIGH-1 재현용).
        """
        at = self.insert_at if self.insert_at is not None else len(self.values) + 1
        self.values[at - 1:at - 1] = [list(r) for r in rows]
        return {"updates": {"updatedRange":
                            "'%s'!A%d:E%d" % (self.title, at, at + len(rows) - 1),
                            "updatedRows": len(rows)}}

    def delete_rows(self, start, end=None):
        # 실제 gspread 정합: start~end(1-based, inclusive) 를 한 번에 삭제.
        # end 생략 시 start 한 행만. 호출을 delete_calls 에 기록(범위삭제 검증용).
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


def _rows_for(date_str, keywords):
    return [[date_str, "샴푸 카외", kw, "AB", "1"] for kw in keywords]


# ----- 429 fix: 날짜블록 삭제 = 구간당 API 1회 (행마다 X) -----

def test_delete_block_batches_contiguous_range_single_call():
    """그날 블록(연속 N행)을 지울 때 delete_rows 를 N번이 아니라 '구간 1회'만 호출해야 함.
    (2026-07-02 회귀: 행마다 삭제 → 수백 API 호출 → 시트 429 → cron 크래시.)"""
    from src.archive import _delete_date_block

    grid = [ARCHIVE_HEADER]
    grid += [["2026-07-01", "샴푸 카외", "old1", "AB", "1"],
             ["2026-07-01", "샴푸 카외", "old2", "AB", "2"]]
    grid += _rows_for("2026-07-02", ["k1", "k2", "k3", "k4", "k5"])  # 4~8행 연속
    ws = FakeWorksheet(grid)

    n = _delete_date_block(ws, "2026-07-02")

    assert n == 5                                  # 5행 삭제 보고
    assert ws.delete_calls == [(4, 8)]             # ★ 단 1회 범위삭제(5회 아님)
    assert not any(r[0] == "2026-07-02" for r in ws.values)  # 오늘 행 전부 제거
    assert sum(1 for r in ws.values if r[0] == "2026-07-01") == 2  # 다른날짜 보존
    assert ws.values[0] == ARCHIVE_HEADER          # 헤더 보존


def test_delete_block_fragmented_ranges_bottom_up():
    """비연속(사이에 다른날짜 낀) 경우: 구간별 1회씩, 아래→위로 지워 행번호 안 밀림."""
    from src.archive import _delete_date_block

    grid = [ARCHIVE_HEADER,
            ["2026-07-02", "샴푸 카외", "a", "AB", "1"],   # 2행 (대상)
            ["2026-07-01", "샴푸 카외", "x", "AB", "1"],   # 3행 (보존)
            ["2026-07-02", "샴푸 카외", "b", "AB", "2"],   # 4행 (대상)
            ["2026-07-02", "샴푸 카외", "c", "AB", "3"]]   # 5행 (대상)
    ws = FakeWorksheet(grid)

    n = _delete_date_block(ws, "2026-07-02")

    assert n == 3
    assert ws.delete_calls == [(4, 5), (2, 2)]     # 아래 구간부터, 구간당 1회
    assert [r[2] for r in ws.values[1:]] == ["x"]  # 오늘 전부 제거·다른날짜만 남음


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


class TestAppendPositionGuard:
    """2026-07-23 독립검토 HIGH-1/HIGH-2 회귀.

    '넣고 지우기' 순서는 '새 줄이 항상 맨 아래' 라는 가정 위에 서 있다. 그 가정이
    깨지면 옛 행번호가 밀려 **엉뚱한 날짜를 지운다**. 그래서 확인하고 지운다.
    """

    def _sheet(self, insert_at=None):
        vals = [list(ARCHIVE_HEADER)]
        vals += [["2026-07-01", "샴푸 카외", "old%d" % i, "AB", "1"] for i in range(3)]
        vals += [["2026-07-23", "샴푸 카외", "today%d" % i, "미노출", ""] for i in range(2)]
        return FakeWorksheet(vals, insert_at=insert_at)

    def test_맨아래에_붙으면_그날_옛줄만_지운다(self):
        ws = self._sheet()
        client = FakeClient(FakeSpreadsheet({ARCHIVE_TAB_NAME: ws}))
        res = append_daily_archive(
            client, _rows_for("2026-07-23", ["a", "b"]), "2026-07-23")
        assert res["replaced_rows"] == 2
        dates = [r[0] for r in ws.values[1:]]
        assert dates.count("2026-07-01") == 3, "다른 날짜를 건드리면 안 됨"
        assert dates.count("2026-07-23") == 2, "그날은 새 것 한 벌만"

    def test_중간에_끼워넣으면_아무것도_안_지운다(self):
        """행번호가 밀렸으므로 지우면 7/01 을 지우게 된다 → 지우지 않는다."""
        ws = self._sheet(insert_at=2)          # 헤더 바로 아래에 끼워넣기
        client = FakeClient(FakeSpreadsheet({ARCHIVE_TAB_NAME: ws}))
        res = append_daily_archive(
            client, _rows_for("2026-07-23", ["a", "b"]), "2026-07-23")
        assert "skipped_delete" in res, "위치가 어긋났는데 지우면 안 됨"
        assert ws.delete_calls == [], "삭제 호출 자체가 없어야 함"
        dates = [r[0] for r in ws.values[1:]]
        assert dates.count("2026-07-01") == 3, "다른 날짜가 살아있어야 함"
        assert dates.count("2026-07-23") == 4, "최악은 중복 한 벌(다음 cron 이 정리)"

    def test_위치를_모르면_안_지운다(self):
        ws = self._sheet()
        ws.append_rows = lambda *a, **k: None       # 응답 없음 = 위치 모름
        client = FakeClient(FakeSpreadsheet({ARCHIVE_TAB_NAME: ws}))
        res = append_daily_archive(
            client, _rows_for("2026-07-23", ["a"]), "2026-07-23")
        assert "skipped_delete" in res and ws.delete_calls == []

    def test_기록할게_0행이면_그날_블록을_안_지운다(self):
        """헤더가 바뀌어 전 행이 스킵되면 rows=[] 가 된다. 그때 지우면 그날이 사라진다."""
        ws = self._sheet()
        client = FakeClient(FakeSpreadsheet({ARCHIVE_TAB_NAME: ws}))
        res = append_daily_archive(client, [], "2026-07-23")
        assert res["rows_written"] == 0 and "skipped" in res
        assert ws.delete_calls == []
        assert [r[0] for r in ws.values[1:]].count("2026-07-23") == 2, "그날 기록 보존"
