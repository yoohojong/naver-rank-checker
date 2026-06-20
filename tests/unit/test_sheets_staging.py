"""sheets.py 스테이징 헬퍼(read_tab_records / append_staging_rows) 단위 테스트.

C3 적재용 신규 메서드 — gspread worksheet 를 mock 해 행동만 검증(네트워크 0).
"""
import json
from unittest.mock import MagicMock, patch

import gspread
import pytest

from src.sheets import HEADER_COLLECT_STATUS, RowUpdate, SheetsClient

_FAKE_CREDS = json.dumps({
    "type": "service_account", "project_id": "x", "private_key_id": "x",
    "private_key": "x", "client_email": "x@x.iam", "client_id": "1",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def _make_client(spreadsheet):
    """gspread 인증을 mock 한 SheetsClient — spreadsheet 만 주입."""
    with patch("src.sheets.gspread.service_account_from_dict") as mock_sa:
        gc = MagicMock()
        gc.open_by_key.return_value = spreadsheet
        mock_sa.return_value = gc
        return SheetsClient(spreadsheet_id="abc", service_account_json=_FAKE_CREDS)


def test_read_tab_records_missing_tab_returns_empty():
    ss = MagicMock()
    ss.worksheet.side_effect = gspread.exceptions.WorksheetNotFound("nope")
    client = _make_client(ss)
    assert client.read_tab_records("수집결과_지식인") == []


def test_read_tab_records_parses_header_and_rows():
    ws = MagicMock()
    ws.get_all_values.return_value = [
        ["키워드", "단계", "수집일"],
        ["두피", "3 증상", "2026-06-20"],
        ["탈모", "3 증상", "2026-06-19"],
    ]
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    recs = client.read_tab_records("수집결과_지식인")
    assert len(recs) == 2
    assert recs[0]["키워드"] == "두피"
    assert recs[0]["수집일"] == "2026-06-20"
    assert recs[0]["_row"] == 2
    assert recs[1]["_row"] == 3


def test_read_tab_records_empty_sheet():
    ws = MagicMock()
    ws.get_all_values.return_value = []
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)
    assert client.read_tab_records("수집결과_리뷰") == []


def test_append_staging_rows_existing_tab_with_header():
    ws = MagicMock()
    ws.row_values.return_value = ["키워드", "단계", "제목", "본문", "수집일", "source_url", "적재완료"]
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    header = ["키워드", "단계", "제목", "본문", "수집일", "source_url", "적재완료"]
    rows = [["두피", "3 증상", "t", "d", "2026-06-20", "L", ""]]
    n = client.append_staging_rows("수집결과_지식인", header, rows)

    assert n == 1
    ws.append_rows.assert_called_once_with(rows, value_input_option="RAW")
    # 헤더 이미 있으므로 update 호출 안 함
    ws.update.assert_not_called()


def test_append_staging_rows_creates_tab_when_missing():
    new_ws = MagicMock()
    ss = MagicMock()
    ss.worksheet.side_effect = gspread.exceptions.WorksheetNotFound("nope")
    ss.add_worksheet.return_value = new_ws
    client = _make_client(ss)

    header = ["키워드", "단계", "제목", "본문", "수집일", "source_url", "적재완료"]
    rows = [["두피", "3 증상", "t", "d", "2026-06-20", "L", ""]]
    n = client.append_staging_rows("수집결과_지식인", header, rows)

    assert n == 1
    ss.add_worksheet.assert_called_once()
    # 새 탭이면 헤더부터 기록
    new_ws.update.assert_called_once_with("A1", [header], value_input_option="RAW")
    new_ws.append_rows.assert_called_once_with(rows, value_input_option="RAW")


def test_append_staging_rows_writes_header_when_tab_empty():
    ws = MagicMock()
    ws.row_values.return_value = []  # 탭은 있는데 헤더 비어 있음
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    header = ["키워드", "단계", "제목", "본문", "수집일", "source_url", "적재완료"]
    rows = [["두피", "3 증상", "t", "d", "2026-06-20", "L", ""]]
    client.append_staging_rows("수집결과_지식인", header, rows)

    ws.update.assert_called_once_with("A1", [header], value_input_option="RAW")
    ws.append_rows.assert_called_once()


def test_append_staging_rows_empty_no_call():
    ss = MagicMock()
    client = _make_client(ss)
    assert client.append_staging_rows("수집결과_지식인", ["키워드"], []) == 0
    ss.worksheet.assert_not_called()


# ── write_collect_status: 카페외부 자료수집 '자료조사' 칸 write-back ──────────


def test_write_collect_status_writes_status_column_only():
    """'자료조사' 칸이 있으면 그 칸에만 표시 write. 다른 칸은 가드로 거부."""
    ws = MagicMock()
    ws.row_values.return_value = ["키워드", "키워드 분류", "보관함", HEADER_COLLECT_STATUS]
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    updates = [
        RowUpdate(row=2, columns={HEADER_COLLECT_STATUS: "✅ 2026-06-21 수집(12건)"}),
        RowUpdate(row=5, columns={HEADER_COLLECT_STATUS: "✅ 2026-06-21 수집(0건)"}),
    ]
    n = client.write_collect_status("샴푸 카외", updates)

    assert n == 2
    ws.batch_update.assert_called_once()
    cells = ws.batch_update.call_args.args[0]
    # 자료조사 = 4번째 컬럼(0-idx 3) → D열.
    assert cells[0]["range"] == "D2"
    assert cells[0]["values"] == [["✅ 2026-06-21 수집(12건)"]]
    assert cells[1]["range"] == "D5"


def test_write_collect_status_rejects_other_columns():
    """HEADER_COLLECT_STATUS 외 컬럼은 거부(K/L/M/O 등 시스템 칸 보호 — write_results 미완화)."""
    ws = MagicMock()
    ws.row_values.return_value = ["키워드", "노출영역", HEADER_COLLECT_STATUS]
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    updates = [RowUpdate(row=2, columns={"노출영역": "AB", HEADER_COLLECT_STATUS: "✅ x"})]
    n = client.write_collect_status("샴푸 카외", updates)

    # 노출영역은 거부, 자료조사만 기록 → 셀 1개.
    assert n == 1
    cells = ws.batch_update.call_args.args[0]
    assert len(cells) == 1
    assert cells[0]["range"] == "C2"  # 자료조사 = 3번째 컬럼


def test_write_collect_status_missing_column_skips():
    """탭에 '자료조사' 칸이 아직 없으면 skip(수집 자체는 진행) — batch_update 호출 안 함."""
    ws = MagicMock()
    ws.row_values.return_value = ["키워드", "키워드 분류"]  # 자료조사 없음
    ss = MagicMock()
    ss.worksheet.return_value = ws
    client = _make_client(ss)

    n = client.write_collect_status(
        "샴푸 카외", [RowUpdate(row=2, columns={HEADER_COLLECT_STATUS: "✅ x"})]
    )
    assert n == 0
    ws.batch_update.assert_not_called()


def test_write_collect_status_empty_no_call():
    ss = MagicMock()
    client = _make_client(ss)
    assert client.write_collect_status("샴푸 카외", []) == 0
    ss.worksheet.assert_not_called()
