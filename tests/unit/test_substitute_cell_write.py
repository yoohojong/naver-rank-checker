"""대체 노출 시트 칸 쓰기 (2026-10-29 사장님 승인 10-29 17:5x).

지키는 것: 대체 있음 = 글자 · 없음 = 빈칸 · 찾기 오류 = '확인 못 함 (사유)'(빈칸으로 바꾸지 않음)
· 머리글은 없을 때만 한 번 · SUBSTITUTE_SCAN=0 = 칸 만들기·쓰기 안 함 · 수식 모드 = 숨김 raw 칸에 값.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src import substitute as sub
from src.sheets import (
    HEADER_AREA, HEADER_CURRENT_INPUT_KEY, HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_RAW_SUBSTITUTE, HEADER_SUBSTITUTE, RowUpdate, SheetsClient,
    STALE_FORMULA_WRITE_COLUMNS, SYSTEM_OUTPUT_COLUMNS,
)

TAB = "샴푸 카외"
URL_A = "https://cafe.naver.com/a/1"
URL_B = "https://cafe.naver.com/b/2"
OWN = "https://cafe.naver.com/own/9"


def _hit(url, rank, area="인기글"):
    return {"url": url, "area": area, "rank": rank + 3, "cafe_rank": rank, "block": "", "source": "시트"}


def _sub_row(row, hits, error=""):
    return {"tab": TAB, "row": row, "substitute_count": len(hits),
            "substitute_cell": sub.format_cell(hits), "hits": hits, "error": error}


def _client(headers, all_values=None):
    creds = json.dumps({
        "type": "service_account", "client_email": "x@example.iam.gserviceaccount.com",
        "private_key": "[REDACTED PRIVATE KEY]\n", "token_uri": "https://oauth2.googleapis.com/token",
    })
    with patch("src.sheets.gspread.service_account_from_dict") as auth:
        gc, sheet, ws = MagicMock(), MagicMock(), MagicMock()
        ws.id = 777
        ws.col_count = len(headers)
        ws.row_values.return_value = headers
        ws.get_all_values.return_value = all_values if all_values is not None else [headers]
        sheet.worksheet.return_value = ws
        gc.open_by_key.return_value = sheet
        auth.return_value = gc
        client = SheetsClient(spreadsheet_id="abc", service_account_json=creds)
    return client, ws


def _written(ws):
    out = {}
    for call in ws.batch_update.call_args_list:
        for item in call.args[0]:
            out[item["range"]] = item["values"][0][0]
    return out


PLAIN_HEADERS = ["키워드", "링크", "노출영역", "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "지식인탭", HEADER_SUBSTITUTE]
# 대체 노출 = 7번째 칸 = G


def _plain_write(sub_rows, upd_rows=(2,), *, enabled=True, index_error=""):
    all_values = [PLAIN_HEADERS] + [["kw", OWN, "", "", "", "", ""] for _ in range(max(upd_rows) - 1)]
    client, ws = _client(PLAIN_HEADERS, all_values)
    tab_updates = {TAB: [RowUpdate(row=r, columns={HEADER_AREA: "미노출"}) for r in upd_rows]}
    n = sub.apply_cells(tab_updates, sub_rows, HEADER_SUBSTITUTE, enabled=enabled, index_error=index_error)
    client.write_results(TAB, tab_updates[TAB])
    return n, _written(ws), tab_updates


class TestSubstituteCellPlain:
    def test_대체_있음_한개_글자를_씀(self):
        n, w, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])])
        assert n == 1
        assert w["G2"] == f"인기글 1위 {URL_A}"
        assert w["C2"] == "미노출"  # K 는 그대로

    def test_대체_두개_순서대로_슬래시로_이음(self):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1), _hit(URL_B, 2)])])
        assert w["G2"] == f"인기글 1위 {URL_A} / 인기글 2위 {URL_B}"

    def test_대체_없음과_맞대지_않은_줄은_빈칸(self):
        # 2행 = 맞댔는데 없음, 3행 = 제 글을 찾아 맞대지 않음(기록 줄 없음)
        _, w, _ = _plain_write([_sub_row(2, [])], upd_rows=(2, 3))
        assert w["G2"] == ""
        assert w["G3"] == ""

    def test_찾기_오류는_빈칸이_아니라_확인못함(self):
        _, w, _ = _plain_write([_sub_row(2, [], error="ValueError: 깨진 화면")])
        assert w["G2"].startswith("확인 못 함 (")
        assert "깨진 화면" in w["G2"]

    def test_우리글_목록_못만들면_모든_줄_확인못함(self):
        _, w, _ = _plain_write([], upd_rows=(2, 3), index_error="APIError: 429")
        assert w["G2"] == w["G3"] == "확인 못 함 (APIError: 429)"

    def test_스위치_0이면_칸값을_넣지도_쓰지도_않음(self, monkeypatch):
        monkeypatch.setenv("SUBSTITUTE_SCAN", "0")
        assert sub.substitute_enabled() is False
        n, w, tab_updates = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], enabled=sub.substitute_enabled())
        assert n == 0
        assert HEADER_SUBSTITUTE not in tab_updates[TAB][0].columns
        assert "G2" not in w

    def test_스위치_0이면_칸_만들기도_부르지_않음(self, monkeypatch):
        monkeypatch.setenv("SUBSTITUTE_SCAN", "0")
        client = MagicMock()
        out = sub.prepare_sheet_columns(client, {TAB: [{"_row": 2}]}, formula_mode=False)
        assert out["enabled"] is False
        client.ensure_substitute_columns.assert_not_called()

    def test_대체노출만_시스템출력_추가_사장님_입력칸은_그대로_거부(self):
        assert HEADER_SUBSTITUTE in SYSTEM_OUTPUT_COLUMNS
        client, ws = _client(PLAIN_HEADERS, [PLAIN_HEADERS, ["kw", OWN, "", "", "", "", ""]])
        client.write_results(TAB, [RowUpdate(row=2, columns={"키워드": "바꿈", "링크": URL_A})])
        ws.batch_update.assert_not_called()


class TestSubstituteHeader:
    def test_머리글_두번_돌려도_1개_맨오른쪽_덧붙임(self):
        headers = ["키워드", "링크", "노출영역"]
        client, ws = _client(headers)
        r1 = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert r1["headers_added"] == 1
        first = _written(ws)
        assert first == {"Q1": HEADER_SUBSTITUTE}  # P1(시각 칸) 다음 = 맨 오른쪽, 끼워 넣기 없음
        ws.insert_cols.assert_not_called()
        # 두 번째 회차: 시트에 이미 머리글이 있음
        ws.row_values.return_value = headers + [""] * 13 + [HEADER_SUBSTITUTE]
        ws.batch_update.reset_mock()
        r2 = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert r2["headers_added"] == 0
        ws.batch_update.assert_not_called()


FORMULA_HEADERS = [
    "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
    "카페/게시글", "링크", "노출영역",
    "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
    "현재입력키", "마지막검사입력키", "raw_노출영역", "raw_통합순위",
    "raw_카페순위", "raw_지식인탭", "마지막검사시각",
]


class TestSubstituteFormulaMode:
    def test_수식모드_칸만들기_보이는칸은_수식_raw는_숨김(self):
        client, ws = _client(FORMULA_HEADERS)
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}, {"_row": 3}], formula_mode=True)
        assert out == {"headers_added": 2, "formula_rows": 2}
        w = _written(ws)
        assert w["W1"] == HEADER_SUBSTITUTE and w["X1"] == HEADER_RAW_SUBSTITUTE
        # 보이는 칸 수식 = 입력 키가 같을 때만 raw 값 (K/L/M/O 와 같은 규칙)
        assert w["W2:W3"] == '=IF(AND(LEN(P2)>0,P2=Q2),X2,"")'
        hide = client.spreadsheet.batch_update.call_args.args[0]["requests"][0]["updateDimensionProperties"]
        assert hide["range"]["startIndex"] == 23 and hide["properties"]["hiddenByUser"] is True

    def test_수식모드_쓰기는_숨김_raw칸에만(self):
        assert HEADER_RAW_SUBSTITUTE in STALE_FORMULA_WRITE_COLUMNS
        headers = FORMULA_HEADERS + [HEADER_SUBSTITUTE, HEADER_RAW_SUBSTITUTE]  # W = 보이는, X = raw
        row = {"_row": 2, "키워드": "지루성두피염원인", "링크": OWN}
        all_values = [headers, ["5/21", "", "", "지루성두피염원인", "", "", "", "", "", OWN] + [""] * 14]
        client, ws = _client(headers, all_values)
        upd = RowUpdate(row=2, columns={HEADER_AREA: "미노출", HEADER_SUBSTITUTE: ""})
        sub.apply_cells({TAB: [upd]}, [_sub_row(2, [_hit(URL_A, 1), _hit(URL_B, 2)])],
                        HEADER_SUBSTITUTE, enabled=True)
        client.write_stale_formula_results(TAB, [upd], row_context={2: row}, checked_at="2026-10-30 01:00 KST")
        w = _written(ws)
        assert w["X2"] == f"인기글 1위 {URL_A} / 인기글 2위 {URL_B}"
        assert "W2" not in w  # 보이는 수식 칸은 덮지 않음

    def test_수식모드_대체키_없으면_raw칸_안건드림(self):
        headers = FORMULA_HEADERS + [HEADER_SUBSTITUTE, HEADER_RAW_SUBSTITUTE]
        row = {"_row": 2, "키워드": "지루성두피염원인", "링크": OWN}
        all_values = [headers, ["5/21", "", "", "지루성두피염원인", "", "", "", "", "", OWN] + [""] * 14]
        client, ws = _client(headers, all_values)
        upd = RowUpdate(row=2, columns={HEADER_AREA: "미노출"})
        client.write_stale_formula_results(TAB, [upd], row_context={2: row}, checked_at="t")
        assert "X2" not in _written(ws)

    def test_수식모드_입력키칸_없으면_만들지_않음(self):
        headers = ["키워드", "링크", "노출영역"]
        assert HEADER_CURRENT_INPUT_KEY not in headers and HEADER_LAST_CHECKED_INPUT_KEY not in headers
        client, ws = _client(headers)
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=True)
        assert out["headers_added"] == 0
        ws.batch_update.assert_not_called()
