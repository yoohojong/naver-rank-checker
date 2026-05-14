"""sheets 단위 테스트."""
import json
import pytest
from unittest.mock import patch, MagicMock, ANY

from src.sheets import (
    SheetsClient, map_headers_to_columns, SPECIAL_TABS,
    RowUpdate, rank_result_to_columns,
    HEADER_TYPE, HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN,
    HEADER_LINK, SYSTEM_OUTPUT_COLUMNS,
)


class TestSheetsClient:
    def test_authenticates_with_json_string(self):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "test@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
            mock_auth.assert_called_once()
            mock_gc.open_by_key.assert_called_once_with("abc")

    def test_invalid_json_raises(self):
        import pytest
        with pytest.raises(json.JSONDecodeError):
            SheetsClient(spreadsheet_id="abc", service_account_json="not json")

    def test_bom_prefix_stripped(self):
        """2026-05-11 defensive: UTF-8 BOM 이 secret 에 있어도 인증 통과.
        Reason: PowerShell pipe / 메모장 등이 BOM 추가 가능. GitHub Actions 첫 실행에서 발견된 케이스."""
        fake_creds = "﻿" + json.dumps({
            "type": "service_account",
            "client_email": "test@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
            mock_auth.assert_called_once()

    def test_empty_credentials_raises(self):
        import pytest
        with pytest.raises((json.JSONDecodeError, ValueError)):
            SheetsClient(spreadsheet_id="abc", service_account_json="")

    def test_spreadsheet_attribute_accessible(self):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "test@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
            assert client.spreadsheet is mock_sheet


class TestMapHeadersToColumns:
    """T-M5.2: 헤더 이름 기반 매핑 (D-004 — 열 이동/추가 강건)."""

    def test_basic_mapping(self):
        headers = ["작업일", "작업자", "키워드", "링크", "노출영역"]
        m = map_headers_to_columns(headers)
        assert m["작업일"] == 0
        assert m["키워드"] == 2
        assert m["링크"] == 3
        assert m["노출영역"] == 4

    def test_extra_columns_dont_break_mapping(self):
        """사장님이 중간에 새 컬럼 추가해도 헤더 이름으로 정확히 매핑."""
        headers = ["작업일", "메모", "작업자", "신규컬럼", "키워드", "링크"]
        m = map_headers_to_columns(headers)
        assert m["작업일"] == 0
        assert m["키워드"] == 4
        assert m["링크"] == 5

    def test_required_header_missing_raises(self):
        headers = ["작업일", "작업자"]
        with pytest.raises(ValueError, match="키워드"):
            map_headers_to_columns(headers, required=["키워드"])

    def test_required_all_present_no_raise(self):
        headers = ["작업일", "키워드", "링크"]
        m = map_headers_to_columns(headers, required=["키워드", "링크"])
        assert m["키워드"] == 1
        assert m["링크"] == 2

    def test_whitespace_normalized(self):
        """헤더 양 끝 공백/줄바꿈 자동 strip."""
        headers = ["  작업일  ", "키워드\n"]
        m = map_headers_to_columns(headers)
        assert m["작업일"] == 0
        assert m["키워드"] == 1

    def test_empty_or_none_cells_skipped(self):
        headers = ["작업일", "", None, "키워드"]
        m = map_headers_to_columns(headers)
        assert m["작업일"] == 0
        assert m["키워드"] == 3
        assert "" not in m

    def test_duplicate_header_first_wins(self):
        """같은 헤더 두 번 있으면 더 왼쪽 (첫번째) 사용."""
        headers = ["키워드", "메모", "키워드"]
        m = map_headers_to_columns(headers)
        assert m["키워드"] == 0  # 첫번째

    def test_spec_4_2_headers_full(self):
        """사장님 실 시트 헤더 (2026-05-07 확인) 매핑 검증."""
        # 사장님이 직접 보낸 첫 행 텍스트 그대로 (탭 구분)
        headers = [
            "작업일", "작업자", "유형", "키워드",
            "MB", "PC", "총합", "작업아이디",
            "카페/게시판", "링크",
            "노출영역",
            "노출여부(통합탭 순위)",   # L — 괄호 안 공백 있음 (사장님 컨벤션)
            "노출여부(카페구좌순위)",  # M — 공백 없음
            "노출여부(블로그구좌순위)", # N — 공백 없음
            "지식인탭",
        ]
        required = [
            "키워드", "링크", "노출영역",
            "노출여부(통합탭 순위)",
            "노출여부(카페구좌순위)",
            "노출여부(블로그구좌순위)",
            "지식인탭",
        ]
        m = map_headers_to_columns(headers, required=required)
        assert m["키워드"] == 3
        assert m["링크"] == 9
        assert m["노출영역"] == 10
        assert m["노출여부(통합탭 순위)"] == 11
        assert m["노출여부(카페구좌순위)"] == 12
        assert m["노출여부(블로그구좌순위)"] == 13
        assert m["지식인탭"] == 14


class TestLoadAllDataTabs:
    """T-M5.3: 모든 데이터 탭 순회 read."""

    def _make_client(self):
        """SheetsClient 생성 (gspread mock)."""
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_sheet

    def _fake_ws(self, title: str, values: list[list[str]]):
        ws = MagicMock()
        ws.title = title
        ws.get_all_values.return_value = values
        return ws

    def test_returns_data_tab_rows_with_metadata(self):
        client, sheet = self._make_client()
        ws = self._fake_ws("샴푸 카외", [
            ["키워드", "링크"],
            ["탈모샴푸", "https://cafe.naver.com/x/1"],
            ["볼륨샴푸", "https://cafe.naver.com/y/2"],
        ])
        sheet.worksheets.return_value = [ws]

        result = client.load_all_data_tabs()

        assert "샴푸 카외" in result
        rows = result["샴푸 카외"]
        assert len(rows) == 2
        assert rows[0]["키워드"] == "탈모샴푸"
        assert rows[0]["링크"] == "https://cafe.naver.com/x/1"
        assert rows[0]["_row"] == 2  # 1행은 헤더, 데이터 첫 행 = 2
        assert rows[0]["_tab"] == "샴푸 카외"
        assert rows[1]["_row"] == 3

    def test_skips_special_tabs(self):
        client, sheet = self._make_client()
        data_ws = self._fake_ws("샴푸 카외", [["키워드"], ["a"]])
        cafe_map_ws = self._fake_ws("카페매핑", [["slug"], ["x"]])
        meta_ws = self._fake_ws("_meta", [["k"], ["v"]])
        sheet.worksheets.return_value = [data_ws, cafe_map_ws, meta_ws]

        result = client.load_all_data_tabs()

        assert "샴푸 카외" in result
        assert "카페매핑" not in result
        assert "_meta" not in result

    def test_사장님_3_tabs_real_setup(self):
        """사장님 실 시트의 3개 탭 (2026-05-07 확인)."""
        client, sheet = self._make_client()
        tabs = [
            self._fake_ws("샴푸 카외", [["키워드", "링크"], ["탈모", "https://cafe.naver.com/a/1"]]),
            self._fake_ws("바디워시카외", [["키워드", "링크"], ["트러블", "https://cafe.naver.com/b/2"]]),
            self._fake_ws("두드러기카외", [["키워드", "링크"], ["피부", "https://cafe.naver.com/c/3"]]),
        ]
        sheet.worksheets.return_value = tabs

        result = client.load_all_data_tabs()

        assert set(result.keys()) == {"샴푸 카외", "바디워시카외", "두드러기카외"}
        assert all(len(rows) == 1 for rows in result.values())

    def test_empty_sheet_returns_empty_list(self):
        client, sheet = self._make_client()
        ws = self._fake_ws("빈탭", [])
        sheet.worksheets.return_value = [ws]

        result = client.load_all_data_tabs()

        assert result["빈탭"] == []

    def test_short_row_padded_with_empty(self):
        """데이터 행이 헤더보다 짧으면 빈 문자열로 채움."""
        client, sheet = self._make_client()
        ws = self._fake_ws("샴푸 카외", [
            ["키워드", "링크", "노출영역"],
            ["탈모"],  # 1개 셀만
        ])
        sheet.worksheets.return_value = [ws]

        result = client.load_all_data_tabs()
        row = result["샴푸 카외"][0]
        assert row["키워드"] == "탈모"
        assert row["링크"] == ""
        assert row["노출영역"] == ""

    def test_special_tabs_constant_includes_카페매핑(self):
        assert "카페매핑" in SPECIAL_TABS

    def test_tab_filter_whitelist_only_카외(self):
        """tab_filter 로 사장님 분야 탭 (카외 ending) 만 처리. PII 탭 자동 skip."""
        client, sheet = self._make_client()
        tabs = [
            self._fake_ws("샴푸 카외", [["키워드"], ["a"]]),
            self._fake_ws("바디워시 카외", [["키워드"], ["b"]]),
            self._fake_ws("두드러기 카외", [["키워드"], ["c"]]),
            self._fake_ws("카페 발행작업", [["키워드"], ["d"]]),  # 다른 운영 탭
            self._fake_ws("한수연님", [["명의", "ID", "PW"], ["x", "y", "z"]]),  # PII
            self._fake_ws("틱톡", [["유형"], ["e"]]),
        ]
        sheet.worksheets.return_value = tabs

        result = client.load_all_data_tabs(tab_filter=lambda t: t.endswith("카외"))

        assert set(result.keys()) == {"샴푸 카외", "바디워시 카외", "두드러기 카외"}
        # PII 탭은 절대 결과에 포함되면 안 됨
        assert "한수연님" not in result
        assert "카페 발행작업" not in result
        assert "틱톡" not in result

    def test_tab_filter_none_returns_all_non_special(self):
        """tab_filter=None 이면 SPECIAL_TABS 외 모든 탭 (구버전 동작)."""
        client, sheet = self._make_client()
        tabs = [
            self._fake_ws("샴푸 카외", [["키워드"], ["a"]]),
            self._fake_ws("아무탭", [["키워드"], ["b"]]),
        ]
        sheet.worksheets.return_value = tabs

        result = client.load_all_data_tabs()

        assert "샴푸 카외" in result
        assert "아무탭" in result


class TestRankResultToColumns:
    """T-M5.4: RankResult → 사장님 시트 컬럼 dict 변환 (컨벤션 정합).

    D-024 (2026-05-14): 유형(C) 컬럼 = 사장님 의도 기록 = 자동 갱신 X.
    cols dict 에 HEADER_TYPE 키 없음 (block_order 매개변수 = 호환성 유지 미사용).
    """

    def test_AB_노출_full_data(self):
        cols = rank_result_to_columns(
            block_order=["AB", "인기글"],
            exposure_area="AB",
            integrated_rank=1,
            cafe_slot_rank=2,
            in_jisikin=False,
        )
        # D-024: HEADER_TYPE 키 없음 (사장님 의도 기록 = 보호)
        assert HEADER_TYPE not in cols
        assert cols[HEADER_AREA] == "AB"
        assert cols[HEADER_L] == "1"
        assert cols[HEADER_M] == "2"
        assert cols[HEADER_JISIKIN] == ""

    def test_인기글_노출(self):
        cols = rank_result_to_columns(
            block_order=["인기글", "AB"],
            exposure_area="인기글",
            integrated_rank=3,
            cafe_slot_rank=3,
            in_jisikin=True,
        )
        # D-024: HEADER_TYPE 키 없음
        assert HEADER_TYPE not in cols
        assert cols[HEADER_AREA] == "인기글"
        assert cols[HEADER_L] == "3"
        assert cols[HEADER_M] == "3"
        assert cols[HEADER_JISIKIN] == "O"

    def test_미노출_empty_string(self):
        """사장님 컨벤션: 미노출 = 빈 칸 (모든 컬럼)."""
        cols = rank_result_to_columns(
            block_order=["AB"],
            exposure_area="미노출",
            integrated_rank=None,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        assert cols[HEADER_AREA] == ""  # '미노출' → '' 변환
        assert cols[HEADER_L] == ""
        assert cols[HEADER_M] == ""
        assert cols[HEADER_JISIKIN] == ""
        # D-024: HEADER_TYPE 키 없음 (block_order ["AB"] 있어도 우리 자동 갱신 X)
        assert HEADER_TYPE not in cols

    def test_삭제_표기(self):
        """노출중지/삭제됨/비공개 모두 → '삭제' 단일."""
        cols = rank_result_to_columns(
            block_order=[],
            exposure_area="삭제",
            integrated_rank=None,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        assert cols[HEADER_AREA] == "삭제"
        # D-024: HEADER_TYPE 키 없음
        assert HEADER_TYPE not in cols

    def test_no_blog_slot_rank_in_columns(self):
        """blog_slot_rank 는 시트 write 안 함 (사장님 N 컬럼 삭제 예정).

        D-024 (2026-05-14): cols 4 컬럼 (노출영역/L/M/지식인탭). 유형(C) = 사장님 보호.
        """
        cols = rank_result_to_columns(
            block_order=["AB"],
            exposure_area="AB",
            integrated_rank=1,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        # D-024 (2026-05-14): 4 컬럼만 (노출영역/L/M/지식인탭). HEADER_TYPE 폐기 + blog_slot_rank 키 없음.
        assert len(cols) == 4
        assert "노출여부(블로그구좌순위)" not in cols
        assert HEADER_TYPE not in cols

    def test_d024_rank_result_to_columns_HEADER_TYPE_미포함(self):
        """D-024 (2026-05-14) 신규 회귀 test: 모든 block_order 케이스 = HEADER_TYPE 키 절대 없음.

        critic Opus 발견 Critical 1 정합 (유형(C) = 사장님 의도 기록 = 자동 갱신 X).
        block_order 매개변수 = 호출 측 호환성 유지 위해 시그너처 보존, 값 = 미사용.
        """
        # 다양한 block_order 케이스 모두 HEADER_TYPE 키 없음 검증
        for block_order in [[], ["AB"], ["인기글"], ["AB", "인기글"], ["인기글", "AB", "스마트블록"]]:
            cols = rank_result_to_columns(
                block_order=block_order,
                exposure_area="AB",
                integrated_rank=1,
                cafe_slot_rank=1,
                in_jisikin=False,
            )
            assert HEADER_TYPE not in cols, f"block_order={block_order!r} 케이스에서 HEADER_TYPE 키 발견 (D-024 위반)"


class TestWriteResults:
    """T-M5.4: SheetsClient.write_results — 한 탭 batch_update."""

    def _make_client_with_ws(self, headers, ws_title="샴푸 카외"):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_ws = MagicMock()
            mock_ws.row_values.return_value = headers
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_write_single_row_one_column(self):
        headers = ["작업일", "키워드", "유형", "노출영역", "노출여부(통합탭 순위)"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=5, columns={"노출영역": "AB"})
        n = client.write_results("샴푸 카외", [upd])
        assert n == 1
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["values"] == [["AB"]]

    def test_write_skips_columns_not_in_sheet(self):
        """사장님 시트에 없는 컬럼 (예: 노출여부(블로그구좌순위)) 은 자동 skip.

        D-024 (2026-05-14): 유형(C) = 사장님 의도 기록 = 가드 거부 (=시트에 있어도 write X).
        """
        headers = ["키워드", "유형", "노출영역"]  # M/N 없음
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=3, columns={
            "유형": "AB",  # D-024: 사장님 보호 = 시트에 있어도 가드 거부
            "노출영역": "AB",
            "노출여부(통합탭 순위)": "1",  # 시트에 없음
            "노출여부(블로그구좌순위)": "X",  # 시트에 없음
        })
        n = client.write_results("샴푸 카외", [upd])
        # D-024: 유형 가드 거부 + L/N 시트 없음 skip = 노출영역만 write = 1개
        assert n == 1

    def test_write_multiple_rows_single_batch_call(self):
        """여러 행 변경도 batch_update 1회만 호출 (API quota 효율)."""
        headers = ["키워드", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        updates = [
            RowUpdate(row=2, columns={"노출영역": "AB"}),
            RowUpdate(row=3, columns={"노출영역": "인기글"}),
            RowUpdate(row=4, columns={"노출영역": ""}),
        ]
        n = client.write_results("샴푸 카외", updates)
        assert n == 3
        ws.batch_update.assert_called_once()

    def test_empty_updates_no_api_call(self):
        headers = ["키워드"]
        client, ws = self._make_client_with_ws(headers)
        n = client.write_results("샴푸 카외", [])
        assert n == 0
        ws.batch_update.assert_not_called()

    def test_write_사장님_컨벤션_real_row(self):
        """T-M5.3 의 dict 출력 → T-M5.4 입력 으로 흐름.

        D-024 (2026-05-14): rank_result_to_columns 가 HEADER_TYPE 채움 X = 4 컬럼만 write.
        """
        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시판", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "노출여부(블로그구좌순위)", "지식인탭",
        ]
        client, ws = self._make_client_with_ws(headers)
        cols = rank_result_to_columns(
            block_order=["인기글", "AB"], exposure_area="인기글",
            integrated_rank=2, cafe_slot_rank=1, in_jisikin=True,
        )
        upd = RowUpdate(row=10, columns=cols)
        n = client.write_results("샴푸 카외", [upd])
        # D-024 (2026-05-14): 4개 컬럼 (노출영역/L/M/지식인탭) write. 유형(C) = 사장님 보호.
        assert n == 4


class TestWriteTimestamp:
    """T-M37 (2026-05-12): 탭 1행 16번째 컬럼에 cron 갱신 timestamp 기록."""

    def _make_client_with_ws(self):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_ws = MagicMock()
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_write_timestamp_calls_update_cell(self):
        """write_timestamp 호출 시 1행 16열에 값 기록."""
        client, ws = self._make_client_with_ws()
        client.write_timestamp("샴푸 카외", "2026-05-12 06:00 KST")
        ws.update_cell.assert_called_once_with(1, 16, "cron 갱신: 2026-05-12 06:00 KST")

    def test_write_timestamp_failure_is_silenced(self):
        """update_cell 예외 발생 시 무시 (log warn 후 통과). 시트 보호 등 상황."""
        client, ws = self._make_client_with_ws()
        ws.update_cell.side_effect = Exception("시트 보호됨")
        # 예외가 밖으로 나오지 않아야 함
        client.write_timestamp("샴푸 카외", "2026-05-12 06:00 KST")  # 예외 없이 통과

    def test_write_timestamp_correct_tab(self):
        """올바른 탭 이름으로 worksheet 접근."""
        client, ws = self._make_client_with_ws()
        client.write_timestamp("바디워시카외", "2026-05-12 12:00 KST")
        # spreadsheet.worksheet 가 올바른 탭 이름으로 호출됐는지 확인
        client.spreadsheet.worksheet.assert_called_with("바디워시카외")


class TestSheetsApiRetry:
    """T-M11 (2026-05-12): Google Sheets API 503/5xx retry.
    cron 25683405754 fail 분석 결과 = gspread default retry X. document-specialist 검증.
    """

    def _make_client_with_ws(self, headers):
        # TestWriteResults 와 동일 헬퍼 (분리 위해 복제)
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_ws = MagicMock()
            mock_ws.row_values.return_value = headers
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def _make_api_error(self, status_code):
        import gspread as _gs
        resp = MagicMock()
        resp.status_code = status_code
        return _gs.exceptions.APIError(resp)

    def test_retry_503_then_success(self):
        """503 2회 fail → 3회차 성공 = 결과 기록됨."""
        headers = ["키워드", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        err = self._make_api_error(503)
        ws.batch_update.side_effect = [err, err, None]  # 2 fail + 1 success
        with patch("src.sheets.time.sleep") as mock_sleep:
            n = client.write_results("샴푸 카외", [RowUpdate(row=2, columns={"노출영역": "AB"})])
        assert n == 1
        assert ws.batch_update.call_count == 3
        assert mock_sleep.call_count == 2  # 2회 sleep 실행됨 (5s, 10s)

    def test_retry_503_3_times_then_raise(self):
        """503 3회 연속 fail → 마지막 attempt 후 APIError raise."""
        import gspread as _gs
        headers = ["키워드", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        err = self._make_api_error(503)
        ws.batch_update.side_effect = [err, err, err]  # 3 fail
        with patch("src.sheets.time.sleep"):
            with pytest.raises(_gs.exceptions.APIError):
                client.write_results("샴푸 카외", [RowUpdate(row=2, columns={"노출영역": "AB"})])
        assert ws.batch_update.call_count == 3

    def test_no_retry_on_4xx_user_error(self):
        """403/404 등 4xx 사용자 잘못 = retry X (즉시 raise). 차단 회피 + 디버깅 ↑."""
        import gspread as _gs
        headers = ["키워드", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        err = self._make_api_error(403)
        ws.batch_update.side_effect = err
        with patch("src.sheets.time.sleep") as mock_sleep:
            with pytest.raises(_gs.exceptions.APIError):
                client.write_results("샴푸 카외", [RowUpdate(row=2, columns={"노출영역": "AB"})])
        assert ws.batch_update.call_count == 1  # retry X
        assert mock_sleep.call_count == 0

    def test_retry_429_quota_also(self):
        """429 (quota) 도 retry — Google API 일반 권장."""
        headers = ["키워드", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        err = self._make_api_error(429)
        ws.batch_update.side_effect = [err, None]  # 1 fail + 1 success
        with patch("src.sheets.time.sleep"):
            n = client.write_results("샴푸 카외", [RowUpdate(row=2, columns={"노출영역": "AB"})])
        assert n == 1
        assert ws.batch_update.call_count == 2


class TestD023Guard:
    """D-023 (2026-05-14) 영구 가드 회귀 test — 사장님 입력 컬럼 자동 갱신 절대 X.

    T-M14.2 commit 10c1ca5 사고 (사장님 link silent 덮어쓰기) 재발 방지 메커니즘 검증.
    """

    def _make_client_with_ws(self, headers, ws_title="샴푸 카외"):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_ws = MagicMock()
            mock_ws.row_values.return_value = headers
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_header_link_write_거부(self):
        """HEADER_LINK ('링크') write 시도 시 = batch_update 에 포함되지 않는다.

        D-023 핵심 가드 — 사장님 마케팅 작업 흔적 (링크 컬럼) silent 덮어쓰기 재발 방지.
        """
        headers = ["키워드", "링크", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=5, columns={HEADER_LINK: "https://cafe.naver.com/x/1"})
        n = client.write_results("샴푸 카외", [upd])
        # 링크 컬럼 = 사장님 입력 = 가드 거부 = 0 셀 write
        assert n == 0
        ws.batch_update.assert_not_called()

    def test_사용자_입력_컬럼_전부_거부(self):
        """사용자 입력 컬럼 (작업일/작업자/키워드/검색량) write 시도 시 = 전부 거부.

        SYSTEM_OUTPUT_COLUMNS 외 모든 컬럼 = 사장님 입력 영역 = 자동 갱신 절대 X.
        """
        headers = ["작업일", "작업자", "키워드", "검색량", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=3, columns={
            "작업일": "2026-05-14",
            "작업자": "홍길동",
            "키워드": "탈모샴푸",
            "검색량": "1000",
        })
        n = client.write_results("샴푸 카외", [upd])
        # 4개 컬럼 전부 사장님 입력 = 전부 거부
        assert n == 0
        ws.batch_update.assert_not_called()

    def test_시스템_출력_컬럼_write_정상(self):
        """시스템 출력 컬럼 (노출영역/L/M/지식인탭) write = 정상 진행.

        SYSTEM_OUTPUT_COLUMNS 화이트리스트 = write 허용 대상.

        D-024 (2026-05-14): HEADER_TYPE 폐기 (= 사장님 의도 기록 보호). 4 컬럼만 시스템 출력.
        """
        headers = [
            "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "지식인탭",
        ]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=7, columns={
            HEADER_AREA: "AB",
            HEADER_L: "1",
            HEADER_M: "2",
            HEADER_JISIKIN: "O",
        })
        n = client.write_results("샴푸 카외", [upd])
        # D-024 (2026-05-14): 4개 컬럼 전부 시스템 출력 = 전부 허용
        assert n == 4
        ws.batch_update.assert_called_once()

    def test_입력_출력_mix_update_시_출력만_write(self):
        """입력 컬럼 + 출력 컬럼 mix update 시 = 출력 컬럼만 write, 입력 컬럼 거부.

        실제 사고 재현 패턴 — 링크(입력) + 노출영역(출력) 동시 갱신 시도.
        """
        headers = ["링크", "노출영역", "노출여부(통합탭 순위)"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=10, columns={
            HEADER_LINK: "https://cafe.naver.com/x/1",  # 입력 컬럼 = 거부
            HEADER_AREA: "AB",                          # 출력 컬럼 = 허용
            HEADER_L: "3",                              # 출력 컬럼 = 허용
        })
        n = client.write_results("샴푸 카외", [upd])
        # 출력 2개만 write (링크 1개 거부)
        assert n == 2
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        # batch_update 에 링크 컬럼 포함 X 검증
        written_values = [cell["values"][0][0] for cell in call_args]
        assert "https://cafe.naver.com/x/1" not in written_values


class TestD024Guard:
    """D-024 (2026-05-14) 영구 가드 회귀 test — 유형(C) 컬럼 = 사장님 의도 기록 = 자동 갱신 절대 X.

    critic Opus 발견 Critical 1 (= D-005 자동 갱신 vs T-M13 학습 모순 미해소) 정합.
    SYSTEM_OUTPUT_COLUMNS 에서 HEADER_TYPE 제거 + write_results 가드 검증.
    """

    def _make_client_with_ws(self, headers, ws_title="샴푸 카외"):
        fake_creds = json.dumps({
            "type": "service_account",
            "client_email": "x@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        })
        with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
            mock_gc = MagicMock()
            mock_sheet = MagicMock()
            mock_ws = MagicMock()
            mock_ws.row_values.return_value = headers
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_HEADER_TYPE_write_거부(self):
        """HEADER_TYPE ('유형') write 시도 시 = batch_update 에 포함되지 않는다.

        D-024 핵심 가드 — 사장님 의도 기록 (유형 C 컬럼) 자동 갱신 절대 X.
        T-M13 학습 정합 (= "C 컬럼 = 사장님 의도 기록 = K 와 분리").
        """
        headers = ["키워드", "유형", "노출영역"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=5, columns={HEADER_TYPE: "AB"})
        n = client.write_results("샴푸 카외", [upd])
        # 유형 컬럼 = 사장님 의도 기록 = 가드 거부 = 0 셀 write
        assert n == 0
        ws.batch_update.assert_not_called()

    def test_HEADER_TYPE_not_in_SYSTEM_OUTPUT_COLUMNS(self):
        """SYSTEM_OUTPUT_COLUMNS frozenset 에 HEADER_TYPE 절대 없음 검증.

        D-024 (2026-05-14): 직접 frozenset 검증 = 미래 회귀 방지 가드.
        """
        assert HEADER_TYPE not in SYSTEM_OUTPUT_COLUMNS
        # 허용 4 컬럼만 남음
        assert SYSTEM_OUTPUT_COLUMNS == frozenset({HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN})

    def test_HEADER_TYPE_in_mix_update_거부(self):
        """유형(입력) + 노출영역(출력) mix update 시 = 노출영역만 write.

        실제 D-005 자동 갱신 패턴 재현 — 우리 코드 가드 거부 검증.
        """
        headers = ["유형", "노출영역", "노출여부(통합탭 순위)"]
        client, ws = self._make_client_with_ws(headers)
        upd = RowUpdate(row=10, columns={
            HEADER_TYPE: "인기글",   # 사장님 의도 기록 = 거부
            HEADER_AREA: "AB",       # 시스템 출력 = 허용
            HEADER_L: "1",           # 시스템 출력 = 허용
        })
        n = client.write_results("샴푸 카외", [upd])
        # 출력 2개만 write (유형 1개 거부)
        assert n == 2
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        # batch_update 에 유형 값 "인기글" 포함 X 검증
        written_values = [cell["values"][0][0] for cell in call_args]
        assert "인기글" not in written_values
