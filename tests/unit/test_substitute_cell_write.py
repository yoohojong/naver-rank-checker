"""대체 노출 시트 칸 쓰기 (2026-10-29 사장님 승인 10-29 17:5x).

지키는 것 (2026-11-01 사장님 "대체노출 일단 1위인것만 … 2 ~ 5위는 솔직히 필요없어" · "확인못함은 말이안됨"):
1위 대체 있음 = '대체노출 1위 <링크>' 한 개 · 2위 이하만/없음/찾기 오류/목록 실패 = 빈칸(1위를 찾았으면 오류여도 1위)
· '확인 못 함' 글자는 시트에 안 씀 · 1위 초록 글자 조건부 서식은 두 번 걸어도 1개
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
    def test_1위_대체만_한개_적힘(self):
        n, w, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])])
        assert n == 1
        assert w["G2"] == f"대체노출 1위 {URL_A}"
        assert w["C2"] == "미노출"  # K 는 그대로

    def test_1위와_2위가_같이_있으면_1위_한개만(self):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1), _hit(URL_B, 2)])])
        assert w["G2"] == f"대체노출 1위 {URL_A}"

    def test_2위가_먼저_찾혀도_1위를_고름(self):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_B, 2, area="스마트블록"), _hit(URL_A, 1)])])
        assert w["G2"] == f"대체노출 1위 {URL_A}"

    @pytest.mark.parametrize("rank", [2, 3, 4, 5])
    def test_2_5위만_있으면_빈칸(self, rank):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_B, rank)])])
        assert w["G2"] == ""
        assert w["C2"] == "미노출"  # K 는 그대로

    def test_카페순위_없으면_통합순위로_1위_판정(self):
        hit = {"url": URL_A, "area": "AB", "rank": 1, "cafe_rank": None, "block": "", "source": "시트"}
        _, w, _ = _plain_write([_sub_row(2, [hit])])
        assert w["G2"] == f"대체노출 1위 {URL_A}"
        hit2 = {"url": URL_A, "area": "AB", "rank": 2, "cafe_rank": None, "block": "", "source": "시트"}
        _, w2, _ = _plain_write([_sub_row(2, [hit2])])
        assert w2["G2"] == ""

    def test_대체_없음과_맞대지_않은_줄은_빈칸(self):
        # 2행 = 맞댔는데 없음, 3행 = 제 글을 찾아 맞대지 않음(기록 줄 없음)
        _, w, _ = _plain_write([_sub_row(2, [])], upd_rows=(2, 3))
        assert w["G2"] == ""
        assert w["G3"] == ""

    def test_찾기_오류는_빈칸_확인못함_안씀(self):
        _, w, _ = _plain_write([_sub_row(2, [], error="ValueError: 깨진 화면")])
        assert w["G2"] == ""

    def test_오류여도_1위를_찾았으면_1위_적힘(self):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1), _hit(URL_B, 2)], error="옛 글 출처 못 읽음: 글장부(x)")])
        assert w["G2"] == f"대체노출 1위 {URL_A}"

    def test_오류이고_2위뿐이면_빈칸(self):
        _, w, _ = _plain_write([_sub_row(2, [_hit(URL_B, 2)], error="옛 글 출처 못 읽음: 이력(x)")])
        assert w["G2"] == ""

    def test_우리글_목록_못만들면_모든_줄_빈칸(self):
        _, w, _ = _plain_write([], upd_rows=(2, 3), index_error="APIError: 429")
        assert w["G2"] == w["G3"] == ""

    def test_시트_칸에_확인못함_글자가_어떤_경우에도_없음(self):
        cases = [
            _sub_row(2, [], error="ValueError: x"),
            _sub_row(2, [_hit(URL_B, 3)], error="ValueError: x"),
            _sub_row(2, [_hit(URL_A, 1)], error="ValueError: x"),
        ]
        for c in cases:
            assert "확인 못 함" not in sub.cell_text(c)

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
        assert out == {"headers_added": 2, "formula_rows": 2, "stale_cleared": 0,
                       "formats_added": 0, "formats_fixed": 0, "formats_removed": 0}  # 서식 목록 못 읽음(MagicMock) = 안 더함
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
        assert w["X2"] == f"대체노출 1위 {URL_A}"
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


# ── 2026-11-01 1위 초록 글자 조건부 서식 ──────────────────────────────────

def _rule_requests(client):
    out = []
    for call in client.spreadsheet.batch_update.call_args_list:
        for req in call.args[0]["requests"]:
            if "addConditionalFormatRule" in req:
                out.append(req["addConditionalFormatRule"])
    return out


def _with_live_rules(client):
    """spreadsheet.batch_update 로 더한 규칙을 다음 fetch_sheet_metadata 가 돌려주게(실제 시트처럼)."""
    rules: list = []

    def fetch(params=None):
        return {"sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": list(rules)}]}

    def batch(body):
        for req in body["requests"]:
            if "addConditionalFormatRule" in req:
                rules.append(req["addConditionalFormatRule"]["rule"])
        return {}

    client.spreadsheet.fetch_sheet_metadata.side_effect = fetch
    client.spreadsheet.batch_update.side_effect = batch
    return rules


class TestSubstituteRank1Format:
    def test_초록_글자_규칙_내용(self):
        client, _ = _client(PLAIN_HEADERS)
        _with_live_rules(client)
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert out["formats_added"] == 1
        (req,) = _rule_requests(client)
        rule = req["rule"]
        assert req["index"] == 0
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}]  # G
        cond = rule["booleanRule"]["condition"]
        assert cond == {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "대체노출 1위"}]}
        assert cond["values"][0]["userEnteredValue"] == sub.RANK1_CELL_PREFIX
        color = rule["booleanRule"]["format"]["textFormat"]["foregroundColor"]
        assert "#%02X%02X%02X" % tuple(round(color[c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_같은_클라이언트로_두번_불러도_규칙_1개(self):
        client, _ = _client(PLAIN_HEADERS)
        rules = _with_live_rules(client)
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        out2 = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert out2["formats_added"] == 0
        assert len(rules) == 1

    def test_다음_회차_새_클라이언트도_시트_규칙을_읽고_안_더함(self):
        client1, _ = _client(PLAIN_HEADERS)
        rules = _with_live_rules(client1)
        client1.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        client2, _ = _client(PLAIN_HEADERS)
        client2.spreadsheet.fetch_sheet_metadata.return_value = {
            "sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": list(rules)}]}
        out = client2.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert out["formats_added"] == 0
        assert _rule_requests(client2) == []

    def test_다른_칸이나_다른_조건의_규칙은_같은_규칙으로_안_봄(self):
        client, _ = _client(PLAIN_HEADERS)
        other_col = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}],
                     "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH",
                                                   "values": [{"userEnteredValue": "대체노출 1위"}]}}}
        other_cond = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}],
                      "booleanRule": {"condition": {"type": "TEXT_CONTAINS",
                                                    "values": [{"userEnteredValue": "인기글"}]}}}
        client.spreadsheet.fetch_sheet_metadata.return_value = {
            "sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": [other_col, other_cond]}]}
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert out["formats_added"] == 1

    def test_서식_목록_못_읽으면_안_더함(self):
        client, _ = _client(PLAIN_HEADERS)
        client.spreadsheet.fetch_sheet_metadata.side_effect = RuntimeError("403")
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert out["formats_added"] == 0
        assert _rule_requests(client) == []

    def test_수식모드는_보이는_칸에_규칙_raw칸은_아님(self):
        client, _ = _client(FORMULA_HEADERS)
        rules = _with_live_rules(client)
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=True)
        assert out["formats_added"] == 1 and len(rules) == 1
        rg = rules[0]["ranges"][0]
        assert (rg["startColumnIndex"], rg["endColumnIndex"]) == (22, 23)  # W = 보이는 '대체 노출'(X = 숨김 raw)

    def test_수식모드_머리글_이미_있을_때_두번_불러도_1개(self):
        headers = FORMULA_HEADERS + [HEADER_SUBSTITUTE, HEADER_RAW_SUBSTITUTE]
        client, _ = _client(headers)
        rules = _with_live_rules(client)
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=True)
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=True)
        assert len(rules) == 1
        assert rules[0]["ranges"][0]["startColumnIndex"] == 22

    def test_prepare_sheet_columns_가_더한_규칙_수를_모음(self):
        client = MagicMock()
        client.ensure_substitute_columns.return_value = {"headers_added": 0, "formula_rows": 0, "formats_added": 1}
        out = sub.prepare_sheet_columns(client, {TAB: [{"_row": 2}], "탭2": [{"_row": 2}]}, formula_mode=False)
        assert out["formats_added"] == 2


# ── 2026-11-01 GPT 1차 검토 지적 A~D ─────────────────────────────────────
# A. 이번 회차에 처리하지 못한 줄(검색 실패 · 키워드 빈 줄)에 옛 형식 값이 남는다
#    → 회차 앞에 '대체 노출' 값 칸에서 '대체노출 1위' 로 시작하지 않는 값을 한 번에 비운다.
# B. 같은 글이 위 구좌 2위 · 아래 구좌 1위면 scan 이 위쪽만 남겨 1위를 놓친다.
# C. 규칙 추가가 서버엔 들어갔는데 503 → 다시 보내 규칙 2개. 같은 규칙이 여럿이면 하나만 남긴다.
# D. 같은 조건 · 같은 칸이지만 범위가 일부 행뿐이거나 색이 다른 규칙도 '있다'로 쳤다 → 맞게 고친다.

from src.parser import OurPostHit  # noqa: E402

PREFIX = sub.RANK1_CELL_PREFIX
GREEN = {"red": 24 / 255, "green": 128 / 255, "blue": 56 / 255}


def _plain_rows(values: dict, header=HEADER_SUBSTITUTE, last=6):
    """{행: '대체 노출' 값} → 시트 읽기 결과(load_all_data_tabs 모양). 6행 = 키워드 빈 줄."""
    return [{"_row": r, "_tab": TAB, "키워드": "kw" if r != 6 else "", header: values.get(r, "")}
            for r in range(2, last + 1)]


class TestStaleSubstituteClear:
    """지적 A."""

    def test_보통모드_옛_형식_값만_한번에_비움_1위는_그대로(self):
        rows = _plain_rows({
            2: "확인 못 함 (ValueError: x)",
            3: f"인기글 2위 {URL_B}",
            4: f"{PREFIX} {URL_A}",
            6: "확인 못 함 (APIError: 429) — 찾은 것: 인기글 1위 x",
        })
        client, ws = _client(PLAIN_HEADERS)
        out = client.ensure_substitute_columns(TAB, rows, formula_mode=False)
        assert out["stale_cleared"] == 3
        assert ws.batch_update.call_count == 1  # 한 번에
        assert _written(ws) == {"G2": "", "G3": "", "G6": ""}  # G 칸만 · 1위(G4) 와 빈칸(G5)은 안 건드림

    def test_수식모드는_숨김_raw칸만_비우고_보이는_수식칸은_안_건드림(self):
        headers = FORMULA_HEADERS + [HEADER_SUBSTITUTE, HEADER_RAW_SUBSTITUTE]  # W = 보이는, X = raw
        rows = [
            {"_row": 2, "_tab": TAB, HEADER_SUBSTITUTE: "확인 못 함 (x)", HEADER_RAW_SUBSTITUTE: "확인 못 함 (x)"},
            {"_row": 3, "_tab": TAB, HEADER_SUBSTITUTE: f"{PREFIX} {URL_A}",
             HEADER_RAW_SUBSTITUTE: f"{PREFIX} {URL_A}"},
            {"_row": 4, "_tab": TAB, HEADER_SUBSTITUTE: "", HEADER_RAW_SUBSTITUTE: f"스마트블록 3위 {URL_B}"},
        ]
        client, ws = _client(headers)
        out = client.ensure_substitute_columns(TAB, rows, formula_mode=True)
        assert out["stale_cleared"] == 2
        clear_calls = [c for c in ws.batch_update.call_args_list
                       if all(item["range"].startswith("X") for item in c.args[0])]
        assert len(clear_calls) == 1
        assert {i["range"]: i["values"][0][0] for i in clear_calls[0].args[0]} == {"X2": "", "X4": ""}
        w = _written(ws)
        assert w["W2:W4"].startswith("=IF(")  # 보이는 칸은 수식 그대로

    def test_비우기_실패해도_회차는_계속(self):
        rows = _plain_rows({2: "확인 못 함 (x)"})
        client, ws = _client(PLAIN_HEADERS)
        _with_live_rules(client)
        ws.batch_update.side_effect = RuntimeError("500")
        out = client.ensure_substitute_columns(TAB, rows, formula_mode=False)
        assert out["stale_cleared"] == 0
        assert out["formats_added"] == 1  # 서식은 그대로 진행

    def test_칸을_이번에_새로_만들었으면_비울_것_없음(self):
        headers = ["키워드", "링크", "노출영역"]
        client, ws = _client(headers)
        out = client.ensure_substitute_columns(TAB, [{"_row": 2, "키워드": "kw"}], formula_mode=False)
        assert out["stale_cleared"] == 0
        assert _written(ws) == {"Q1": HEADER_SUBSTITUTE}

    def test_prepare_sheet_columns_가_비운_수를_모음(self):
        client = MagicMock()
        client.ensure_substitute_columns.return_value = {"headers_added": 0, "formula_rows": 0,
                                                         "formats_added": 0, "stale_cleared": 4}
        out = sub.prepare_sheet_columns(client, {TAB: [{"_row": 2}], "탭2": [{"_row": 2}]}, formula_mode=False)
        assert out["stale_cleared"] == 8


class TestScanSamePostBestRank:
    """지적 B."""

    def _scan(self, monkeypatch, found):
        idx = sub.build_index({"다른탭": [{"링크": URL_A}, {"링크": URL_B}]})
        monkeypatch.setattr(sub, "find_all_our_posts",
                            lambda html, is_ours: [h for h in found if is_ours(h.url)])
        return sub.scan("<html/>", idx, TAB, "kw", own_link=OWN)

    def test_위_구좌_2위_아래_구좌_1위인_같은_글이면_1위(self, monkeypatch):
        hits = self._scan(monkeypatch, [
            OurPostHit(area="스마트블록", integrated_rank=4, cafe_slot_rank=2, url=URL_A, block_name="b"),
            OurPostHit(area="인기글", integrated_rank=7, cafe_slot_rank=1, url=URL_A),
        ])
        assert sub.rank1_cell(hits) == f"{PREFIX} {URL_A}"
        assert len(hits) == 1  # 기록 형식 그대로: 같은 글은 한 줄
        assert hits[0]["area"] == "인기글" and hits[0]["cafe_rank"] == 1

    def test_같은_글_위가_더_좋으면_위쪽_그대로_순서도_그대로(self, monkeypatch):
        hits = self._scan(monkeypatch, [
            OurPostHit(area="AB", integrated_rank=1, cafe_slot_rank=1, url=URL_A),
            OurPostHit(area="스마트블록", integrated_rank=5, cafe_slot_rank=3, url=URL_B, block_name="b"),
            OurPostHit(area="인기글", integrated_rank=6, cafe_slot_rank=2, url=URL_A),
        ])
        assert [(h["url"], h["area"], h["cafe_rank"]) for h in hits] == [
            (URL_A, "AB", 1), (URL_B, "스마트블록", 3)]


def _our_rule(col=6, *, start_row=1, end_row=None, color=None, sheet_id=777):
    rg = {"sheetId": sheet_id, "startRowIndex": start_row, "startColumnIndex": col, "endColumnIndex": col + 1}
    if end_row is not None:
        rg["endRowIndex"] = end_row
    return {"ranges": [rg],
            "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": PREFIX}]},
                            "format": {"textFormat": {"foregroundColor": dict(color or GREEN)}}}}


class _LiveSheet:
    """조건부 서식 규칙을 실제 시트처럼 들고 add/update/delete 요청을 적용한다."""

    def __init__(self, client, rules, fail_after_apply=0):
        self.rules = list(rules)
        self.fail_after_apply = fail_after_apply  # 서버엔 들어갔는데 503 응답을 몇 번 돌려줄지
        client.spreadsheet.fetch_sheet_metadata.side_effect = self.fetch
        client.spreadsheet.batch_update.side_effect = self.batch

    def fetch(self, params=None):
        return {"sheets": [{"properties": {"sheetId": 777},
                            "conditionalFormats": [json.loads(json.dumps(r)) for r in self.rules]}]}

    def batch(self, body):
        import gspread
        for req in body["requests"]:
            if "addConditionalFormatRule" in req:
                a = req["addConditionalFormatRule"]
                self.rules.insert(a.get("index", 0), a["rule"])
            elif "updateConditionalFormatRule" in req:
                u = req["updateConditionalFormatRule"]
                assert u["sheetId"] == 777
                self.rules[u["index"]] = u["rule"]
            elif "deleteConditionalFormatRule" in req:
                d = req["deleteConditionalFormatRule"]
                assert d["sheetId"] == 777
                del self.rules[d["index"]]
        if self.fail_after_apply:
            self.fail_after_apply -= 1
            resp = MagicMock()
            resp.status_code = 503
            resp.json.return_value = {"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}}
            raise gspread.exceptions.APIError(resp)
        return {}

    def ours(self, col=6):
        return [r for r in self.rules
                if r["booleanRule"]["condition"].get("values") == [{"userEnteredValue": PREFIX}]
                and r["ranges"][0]["startColumnIndex"] == col]


@pytest.fixture
def _no_sleep(monkeypatch):
    monkeypatch.setattr("src.sheets.time.sleep", lambda s: None)


class TestRank1FormatRetryAndDedup:
    """지적 C · D."""

    def test_503_뒤_다시_보내도_규칙은_1개(self, _no_sleep):
        client, _ = _client(PLAIN_HEADERS)
        live = _LiveSheet(client, [], fail_after_apply=1)
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert len(live.ours()) == 1

    def test_같은_규칙이_둘이면_하나만_남김_다른_규칙은_그대로(self, _no_sleep):
        other = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}],
                 "booleanRule": {"condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "인기글"}]},
                                 "format": {"textFormat": {"bold": True}}}}
        client, _ = _client(PLAIN_HEADERS)
        live = _LiveSheet(client, [_our_rule(), other, _our_rule()])
        out = client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        assert len(live.ours()) == 1
        assert other in live.rules and len(live.rules) == 2
        assert out["formats_added"] == 0

    def test_범위가_일부_행뿐이면_2행부터_끝까지로_고침(self, _no_sleep):
        client, _ = _client(PLAIN_HEADERS)
        live = _LiveSheet(client, [_our_rule(end_row=50)])
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        (rule,) = live.ours()
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}]

    def test_색이_다르면_초록으로_고침(self, _no_sleep):
        client, _ = _client(PLAIN_HEADERS)
        live = _LiveSheet(client, [_our_rule(color={"red": 1.0, "green": 0.0, "blue": 0.0})])
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        (rule,) = live.ours()
        color = rule["booleanRule"]["format"]["textFormat"]["foregroundColor"]
        assert "#%02X%02X%02X" % tuple(round(color[c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_맞는_규칙_하나면_아무_요청도_안_보냄(self, _no_sleep):
        client, _ = _client(PLAIN_HEADERS)
        _LiveSheet(client, [_our_rule()])
        client.ensure_substitute_columns(TAB, [{"_row": 2}], formula_mode=False)
        client.spreadsheet.batch_update.assert_not_called()
