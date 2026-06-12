"""sheets 단위 테스트."""
import json
import pytest
from unittest.mock import patch, MagicMock, ANY

from src.sheets import (
    SheetsClient, map_headers_to_columns, SPECIAL_TABS,
    RowUpdate, rank_result_to_columns,
    HEADER_TYPE, HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN,
    HEADER_LINK, SYSTEM_OUTPUT_COLUMNS, SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK,
)

COLOR_EXPOSED = {"red": 0.8, "green": 1.0, "blue": 0.8}
COLOR_NEGATIVE = {"red": 1.0, "green": 0.8, "blue": 0.8}
COLOR_NONE = {"red": 1.0, "green": 1.0, "blue": 1.0}
ALIGNMENT_CENTER_MIDDLE = {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}


def _rows_from_link_col(headers, link_col_values):
    rows = [list(headers)]
    if HEADER_LINK not in headers:
        return rows
    link_idx = headers.index(HEADER_LINK)
    for link_value in link_col_values[1:]:
        row = [""] * len(headers)
        row[link_idx] = link_value
        rows.append(row)
    return rows


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

    def test_미노출_명시_표기(self):
        """D-026 Phase B (2026-05-16): '미노출' = 명시 텍스트 표기 (= 빈 칸 X).
        근거: 사장님 시점 빈 칸 = '조사 안 됨' 혼동 = sheets.py:241 결함 root cause fix.
        """
        cols = rank_result_to_columns(
            block_order=["AB"],
            exposure_area="미노출",
            integrated_rank=None,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        assert cols[HEADER_AREA] == "미노출"  # D-026: 빈 칸 X = 명시 표기
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

    def test_d026_미노출_명시_텍스트_표기(self):
        """D-026 Phase B (2026-05-16) 신규 회귀 test: 미노출 = 명시 텍스트 표기.
        rank_result_to_columns(exposure_area="미노출") → cols[HEADER_AREA] = "미노출" (빈 칸 X).
        근거: 사장님 시점 빈 칸 = "조사 안 됨" 혼동 회피 root cause fix.
        """
        cols = rank_result_to_columns(
            block_order=[],
            exposure_area="미노출",
            integrated_rank=None,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        # D-026 핵심: 빈 칸 X (= 사장님 시점 혼동 회피)
        assert cols[HEADER_AREA] == "미노출"
        assert cols[HEADER_AREA] != ""

    def test_d026_빈칸_처리_X(self):
        """D-026 Phase B 회귀: 다양한 exposure_area 케이스 = 빈 칸 처리 X.
        모든 K enum 값 = 그대로 cols[HEADER_AREA] 에 기록 (= 명시 표기 정합).
        """
        for area in ["미노출", "누락", "AB", "스마트블록", "인기글", "삭제"]:
            cols = rank_result_to_columns(
                block_order=[],
                exposure_area=area,
                integrated_rank=None,
                cafe_slot_rank=None,
                in_jisikin=False,
            )
            assert cols[HEADER_AREA] == area, f"area={area!r} 케이스 = 빈 칸 처리 X 검증 실패"

    def test_d026_누락_표기(self):
        """D-026 Phase B 신규: '누락' = 사장님 시각 알림 (= 박스 빠짐) 명시 표기."""
        cols = rank_result_to_columns(
            block_order=[],
            exposure_area="누락",
            integrated_rank=None,
            cafe_slot_rank=None,
            in_jisikin=False,
        )
        assert cols[HEADER_AREA] == "누락"

    def test_d026_smart_block_표기(self):
        """D-026 Phase A 부활: '스마트블록' = 별도 표기 (D-022 ① 폐기 정합)."""
        cols = rank_result_to_columns(
            block_order=["스마트블록"],
            exposure_area="스마트블록",
            integrated_rank=2,
            cafe_slot_rank=1,
            in_jisikin=False,
        )
        assert cols[HEADER_AREA] == "스마트블록"
        assert cols[HEADER_L] == "2"
        assert cols[HEADER_M] == "1"

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


class TestStaleFormulaMode:
    def _make_client_with_ws(self, headers, *, col_count=None):
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
            mock_ws.id = 12345
            mock_ws.col_count = col_count if col_count is not None else len(headers)
            mock_ws.row_values.return_value = headers
            mock_ws.get_all_values.return_value = [
                headers,
                [
                    "5/21", "한수연", "AB", "지루성두피염원인", "", "", "", "", "",
                    "https://cafe.naver.com/workee/1325909", "AB", "2", "2", "", "",
                ],
            ]
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws, client.spreadsheet

    def test_ensure_stale_formula_mode_adds_hidden_headers_backfills_and_formulas(self):
        from src.sheets import (
            HEADER_CURRENT_INPUT_KEY,
            HEADER_LAST_CHECKED_INPUT_KEY,
            HEADER_RAW_AREA,
            HEADER_RAW_L,
            STALE_DISPLAY_K,
        )

        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시글", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
        ]
        client, ws, spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))

        summary = client.ensure_stale_formula_mode(
            "샴푸 카외",
            [{
                "_row": 2,
                "키워드": "지루성두피염원인",
                "링크": "https://cafe.naver.com/workee/1325909",
                "노출영역": "AB",
                "노출여부(통합탭 순위)": "2",
                "노출여부(카페구좌순위)": "2",
                "지식인탭": "",
            }],
        )

        assert summary["headers_added"] >= 7
        assert summary["rows_backfilled"] == 1
        ws.add_cols.assert_called_once()
        raw_calls = [call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "RAW"]
        formula_calls = [call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "USER_ENTERED"]
        assert raw_calls
        assert formula_calls
        raw_payload = str(raw_calls)
        assert HEADER_LAST_CHECKED_INPUT_KEY in raw_payload
        assert HEADER_RAW_AREA in raw_payload
        assert HEADER_RAW_L in raw_payload
        formula_payload = str(formula_calls)
        assert HEADER_CURRENT_INPUT_KEY not in formula_payload
        assert STALE_DISPLAY_K in formula_payload
        assert '( \\\\(|$)' in formula_payload
        assert "P1" not in raw_payload
        assert "Q1" in raw_payload
        spreadsheet.batch_update.assert_called_once()

    def test_write_stale_formula_results_writes_raw_and_key_not_visible_k(self):
        from src.stale_preview import build_input_key
        from src.sheets import (
            HEADER_LAST_CHECKED_AT,
            HEADER_LAST_CHECKED_INPUT_KEY,
            HEADER_RAW_AREA,
            HEADER_RAW_JISIKIN,
            HEADER_RAW_L,
            HEADER_RAW_M,
        )

        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시글", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
            "현재입력키", "마지막검사입력키", "raw_노출영역", "raw_통합순위",
            "raw_카페순위", "raw_지식인탭", "마지막검사시각",
        ]
        client, ws, _spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))
        row = {
            "_row": 2,
            "키워드": "지루성두피염원인",
            "링크": "https://cafe.naver.com/workee/1325909",
        }
        update = RowUpdate(row=2, columns={
            "노출영역": "누락 (5/21 20:00~)",
            "노출여부(통합탭 순위)": "",
            "노출여부(카페구좌순위)": "",
            "지식인탭": "",
        })

        cells = client.write_stale_formula_results(
            "샴푸 카외",
            [update],
            row_context={2: row},
            checked_at="2026-05-21 20:00 KST",
        )

        assert cells == 6
        payload = ws.batch_update.call_args.args[0]
        ranges = {item["range"] for item in payload}
        assert "K2" not in ranges
        assert "R2" in ranges
        values = [item["values"][0][0] for item in payload]
        assert "누락 (5/21 20:00~)" in values
        assert build_input_key(row) in values
        assert "2026-05-21 20:00 KST" in values
        expected_ranges = {
            "Q2",  # 마지막검사입력키
            "R2",  # raw_노출영역
            "S2",  # raw_통합순위
            "T2",  # raw_카페순위
            "U2",  # raw_지식인탭
            "V2",  # 마지막검사시각
        }
        assert expected_ranges.issubset(ranges)
        formats = ws.batch_format.call_args.args[0]
        assert {"range": "K2", "format": {"backgroundColor": COLOR_NEGATIVE}} in formats
        aligned_ranges = {
            item["range"]
            for item in formats
            if item.get("format") == ALIGNMENT_CENTER_MIDDLE
        }
        assert aligned_ranges == {"L2", "M2"}
        assert {HEADER_RAW_AREA, HEADER_RAW_L, HEADER_RAW_M, HEADER_RAW_JISIKIN, HEADER_LAST_CHECKED_INPUT_KEY, HEADER_LAST_CHECKED_AT}

    def test_write_stale_formula_results_skips_if_link_changed_after_load(self):
        from src.sheets import (
            HEADER_CURRENT_INPUT_KEY,
            HEADER_KEYWORD,
            HEADER_LAST_CHECKED_AT,
            HEADER_LAST_CHECKED_INPUT_KEY,
            HEADER_RAW_AREA,
            HEADER_RAW_JISIKIN,
            HEADER_RAW_L,
            HEADER_RAW_M,
        )

        headers = [
            "작업일", "작업자", HEADER_TYPE, HEADER_KEYWORD, "MB", "PC", "총합", "작업아이디",
            "카페/게시글", HEADER_LINK, HEADER_AREA,
            HEADER_L, HEADER_M, "블로그", HEADER_JISIKIN,
            HEADER_CURRENT_INPUT_KEY, HEADER_LAST_CHECKED_INPUT_KEY, HEADER_RAW_AREA, HEADER_RAW_L,
            HEADER_RAW_M, HEADER_RAW_JISIKIN, HEADER_LAST_CHECKED_AT,
        ]
        client, ws, _spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))
        loaded_row = {
            "_row": 2,
            HEADER_KEYWORD: "닥터브러너스",
            HEADER_LINK: "",
        }
        current_sheet_row = [""] * len(headers)
        current_sheet_row[headers.index(HEADER_KEYWORD)] = "닥터브러너스"
        current_sheet_row[headers.index(HEADER_LINK)] = "https://naver.me/G3vPZzJ8"
        ws.get_all_values.return_value = [headers, current_sheet_row]
        update = RowUpdate(row=2, columns={
            HEADER_AREA: "미노출 (5/19 00:00~)",
            HEADER_L: "",
            HEADER_M: "",
            HEADER_JISIKIN: "",
        })

        cells = client.write_stale_formula_results(
            "샴푸 카외",
            [update],
            row_context={2: loaded_row},
            checked_at="2026-05-22 17:05 KST",
        )

        assert cells == 0
        ws.batch_update.assert_not_called()
        ws.batch_format.assert_not_called()

    def test_stale_formula_headers_do_not_collide_with_timestamp_cell_p1(self):
        from src.sheets import HEADER_CURRENT_INPUT_KEY

        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시글", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
        ]
        client, ws, _spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))

        client.ensure_stale_formula_mode("샴푸 카외", [])
        client.write_timestamp("샴푸 카외", "2026-05-21 20:00 KST")

        header_payload = str([call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "RAW"])
        assert "P1" not in header_payload
        assert "Q1" in header_payload
        assert HEADER_CURRENT_INPUT_KEY in header_payload
        ws.update_cell.assert_called_once_with(1, 16, "cron 갱신: 2026-05-21 20:00 KST")

    def test_partial_stale_formula_migration_backfills_only_new_columns(self):
        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시글", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
            "cron 갱신", "현재입력키", "마지막검사입력키", "raw_노출영역",
            "raw_통합순위", "raw_카페순위", "raw_지식인탭",
        ]
        client, ws, _spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))

        client.ensure_stale_formula_mode(
            "샴푸 카외",
            [{
                "_row": 2,
                "키워드": "지루성두피염원인",
                "링크": "https://cafe.naver.com/workee/1325909",
                "노출영역": "재검사필요",
                "노출여부(통합탭 순위)": "",
                "노출여부(카페구좌순위)": "",
                "지식인탭": "",
            }],
        )

        raw_calls = [call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "RAW"]
        raw_payload = str(raw_calls)
        assert "W1" in raw_payload
        assert "W2" in raw_payload
        assert "R2" not in raw_payload
        assert "재검사필요" not in raw_payload

    def test_missing_jisikin_header_still_initializes_k_l_m_formula_mode(self):
        headers = [
            "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
            "카페/게시글", "링크", "노출영역",
            "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그",
        ]
        client, ws, _spreadsheet = self._make_client_with_ws(headers, col_count=len(headers))

        summary = client.ensure_stale_formula_mode(
            "두드러기 카외",
            [{
                "_row": 2,
                "키워드": "지루성두피염원인",
                "링크": "https://cafe.naver.com/workee/1325909",
                "노출영역": "AB",
                "노출여부(통합탭 순위)": "2",
                "노출여부(카페구좌순위)": "2",
            }],
        )

        assert summary["formula_rows"] == 1
        assert summary["rows_backfilled"] == 1
        raw_calls = [call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "RAW"]
        formula_calls = [call for call in ws.batch_update.call_args_list if call.kwargs.get("value_input_option") == "USER_ENTERED"]
        assert raw_calls
        assert formula_calls
        formula_payload = str(formula_calls)
        assert "K2:K2" in formula_payload
        assert "L2:L2" in formula_payload
        assert "M2:M2" in formula_payload
        assert "O2:O2" not in formula_payload


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


    def test_write_type_results_writes_HEADER_TYPE_explicitly(self):
        headers = ["키워드", HEADER_TYPE, HEADER_AREA]
        client, ws = self._make_client_with_ws(headers)
        updates = [
            RowUpdate(row=5, columns={HEADER_TYPE: "AB"}),
            RowUpdate(row=6, columns={HEADER_TYPE: "스마트블록"}),
        ]

        n = client.write_type_results("샴푸 카외", updates)

        assert n == 2
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        assert call_args == [
            {"range": "B5", "values": [["AB"]]},
            {"range": "B6", "values": [["스마트블록"]]},
        ]

    def test_write_type_results_rejects_non_type_columns(self):
        headers = ["키워드", HEADER_TYPE, HEADER_AREA]
        client, ws = self._make_client_with_ws(headers)
        updates = [RowUpdate(row=5, columns={HEADER_TYPE: "AB", HEADER_AREA: "인기글"})]

        n = client.write_type_results("샴푸 카외", updates)

        assert n == 1
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        assert call_args == [{"range": "B5", "values": [["AB"]]}]


class TestD026EmptyLinkColumnGuard:
    """D-026 Phase C+D (2026-05-16) 회귀 test — 빈 link 행만 HEADER_LINK write 허용.

    부분 완화 규칙:
    - 빈 link 행 = SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK 화이트리스트 (HEADER_LINK 포함)
    - 기존 link 행 = SYSTEM_OUTPUT_COLUMNS 화이트리스트 (HEADER_LINK 제외, D-023 가드 유지)
    """

    def _make_client_with_link_col(self, headers, link_col_values, ws_title="샴푸 카외"):
        """헬퍼: ws.col_values 가 link 컬럼 값 반환하도록 mock 구성."""
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
            # link col_values = list 반환 (정상)
            mock_ws.col_values.return_value = link_col_values
            mock_ws.get_all_values.return_value = _rows_from_link_col(headers, link_col_values)
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_d026_empty_link_HEADER_LINK_write_allowed(self):
        """D-026 Phase C+D: 빈 link 행 = HEADER_LINK write 허용 (= 자동 채움 logic)."""
        headers = ["키워드", "링크", "노출영역"]
        # link 컬럼: header + row2 빈 + row3 빈
        link_col_values = ["링크", "", ""]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "중복노출",
            HEADER_LINK: "https://cafe.naver.com/cosmania/9999",  # 빈 link 행 = 자동 채움
        })
        n = client.write_results("샴푸 카외", [upd])
        # 빈 link 행 = HEADER_LINK write 허용 = 2 셀
        assert n == 2
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        written_values = [cell["values"][0][0] for cell in call_args]
        # HEADER_LINK 값 (자동 채움) 검증
        assert "https://cafe.naver.com/cosmania/9999" in written_values
        assert "중복노출" in written_values

    def test_d026_existing_link_HEADER_LINK_write_rejected(self):
        """D-026 Phase C+D 정합: 기존 link 행 = HEADER_LINK write 거부 (D-023 가드 유지).

        T-M14.2 사고 (사장님 link silent 덮어쓰기) 재발 방지.
        """
        headers = ["키워드", "링크", "노출영역"]
        # link 컬럼: header + row2 사장님 작업 link + row3 빈
        existing_link = "https://cafe.naver.com/cosmania/12345"
        link_col_values = ["링크", existing_link, ""]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={  # row=2 = 사장님 link 있는 행
            HEADER_AREA: "AB",
            HEADER_LINK: "https://cafe.naver.com/other/9999",  # 사장님 작업 link 덮어쓰기 시도
        })
        n = client.write_results("샴푸 카외", [upd])
        # 기존 link 행 = HEADER_LINK write 거부 = HEADER_AREA 1 셀만
        assert n == 1
        ws.batch_update.assert_called_once()
        call_args = ws.batch_update.call_args[0][0]
        written_values = [cell["values"][0][0] for cell in call_args]
        # HEADER_LINK 덮어쓰기 X 검증
        assert "https://cafe.naver.com/other/9999" not in written_values
        assert "AB" in written_values

    def test_d033_empty_link_detection_uses_row_snapshot_not_compacted_col_values(self):
        headers = [HEADER_LINK, HEADER_AREA, HEADER_L, HEADER_M]
        compacted_link_col = [HEADER_LINK] + ["https://cafe.naver.com/shifted/1"] * 120
        client, ws = self._make_client_with_link_col(headers, compacted_link_col)
        rows = [headers] + [["", "", "", ""] for _ in range(97)] + [["", "", "", ""]]
        ws.get_all_values.return_value = rows
        new_link = "https://cafe.naver.com/mindy7857/5153525"
        upd = RowUpdate(row=99, columns={
            HEADER_AREA: "\uc911\ubcf5\ub178\ucd9c(AB) (5/19 00:00~)",
            HEADER_LINK: new_link,
            HEADER_L: "1",
            HEADER_M: "1",
        })

        n = client.write_results("두드러기 카외", [upd])

        assert n == 4
        ws.col_values.assert_not_called()
        call_args = ws.batch_update.call_args[0][0]
        written_values = [cell["values"][0][0] for cell in call_args]
        assert new_link in written_values

    def test_empty_link_plain_exposed_rank_row_rejected(self):
        """빈 link 행에 plain 노출 K/L/M만 쓰는 불가능 조합은 row 전체 거부."""
        headers = ["키워드", "링크", HEADER_AREA, HEADER_L, HEADER_M]
        # link 컬럼: header + row2 빈
        link_col_values = ["링크", ""]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "인기글 (5/19 00:00~)",
            HEADER_L: "2",
            HEADER_M: "1",
        })

        n = client.write_results("샴푸 카외", [upd])

        assert n == 0
        ws.batch_update.assert_not_called()
        ws.batch_format.assert_not_called()

    def test_d026_link_read_fail_strict_mode(self):
        """D-026 Phase C+D: link read 실패 (예외) = 보수적 = SYSTEM_OUTPUT_COLUMNS 적용 (= HEADER_LINK 거부)."""
        headers = ["키워드", "링크", "노출영역"]
        client, ws = self._make_client_with_link_col(headers, ["링크", ""])
        # col_values 호출 시 예외 raise
        ws.get_all_values.side_effect = Exception("API error")
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "중복노출",
            HEADER_LINK: "https://cafe.naver.com/cosmania/9999",
        })
        n = client.write_results("샴푸 카외", [upd])
        # link read 실패 = 보수적 = HEADER_LINK 거부 = HEADER_AREA 1 셀만
        assert n == 1

    def test_d026_SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK_constant(self):
        """D-026 Phase C+D frozenset 정합 검증."""
        # HEADER_LINK 포함 (= 빈 link 행 자동 채움 허용)
        assert HEADER_LINK in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        # 시스템 출력 4 컬럼도 포함
        assert HEADER_AREA in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        assert HEADER_L in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        assert HEADER_M in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        assert HEADER_JISIKIN in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        # HEADER_TYPE 포함 X (= D-024 가드 유지)
        assert HEADER_TYPE not in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        # 정확히 5 컬럼 (4 시스템 + HEADER_LINK)
        assert len(SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK) == 5


class TestExposureResultAlignment:
    def _make_client_with_link_col(self, headers, link_col_values, ws_title="샴푸 카외"):
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
            mock_ws.get_all_values.return_value = _rows_from_link_col(headers, link_col_values)
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def test_write_results_centers_exposure_result_columns(self):
        headers = [HEADER_LINK, HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN]
        client, ws = self._make_client_with_link_col(
            headers,
            [HEADER_LINK, "https://cafe.naver.com/cosmania/12345"],
        )
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "AB",
            HEADER_L: "1",
            HEADER_M: "2",
            HEADER_JISIKIN: "O",
        })

        n = client.write_results("샴푸 카외", [upd])

        assert n == 4
        formats = ws.batch_format.call_args[0][0]
        aligned_ranges = {
            item["range"]
            for item in formats
            if item.get("format") == ALIGNMENT_CENTER_MIDDLE
        }
        assert aligned_ranges == {"C2", "D2"}

    def test_write_stale_formula_results_centers_visible_exposure_result_columns(self):
        from src.sheets import (
            HEADER_KEYWORD,
            HEADER_LAST_CHECKED_AT,
            HEADER_LAST_CHECKED_INPUT_KEY,
            HEADER_RAW_AREA,
            HEADER_RAW_JISIKIN,
            HEADER_RAW_L,
            HEADER_RAW_M,
        )

        headers = [
            HEADER_KEYWORD,
            HEADER_LINK,
            HEADER_AREA,
            HEADER_L,
            HEADER_M,
            HEADER_JISIKIN,
            HEADER_LAST_CHECKED_INPUT_KEY,
            HEADER_RAW_AREA,
            HEADER_RAW_L,
            HEADER_RAW_M,
            HEADER_RAW_JISIKIN,
            HEADER_LAST_CHECKED_AT,
        ]
        client, ws = self._make_client_with_link_col(
            headers,
            [HEADER_LINK, "https://cafe.naver.com/cosmania/12345"],
        )
        # T-M9.1 재배치 정합: write 직전 시트에도 같은 (키워드, 링크) 행이 있어야 기록된다
        sheet_row = [""] * len(headers)
        sheet_row[headers.index(HEADER_KEYWORD)] = "바디워시"
        sheet_row[headers.index(HEADER_LINK)] = "https://cafe.naver.com/cosmania/12345"
        ws.get_all_values.return_value = [list(headers), sheet_row]
        source_row = {
            "_row": 2,
            HEADER_KEYWORD: "바디워시",
            HEADER_LINK: "https://cafe.naver.com/cosmania/12345",
        }
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "AB",
            HEADER_L: "1",
            HEADER_M: "2",
            HEADER_JISIKIN: "",
        })

        cells = client.write_stale_formula_results(
            "샴푸 카외",
            [upd],
            row_context={2: source_row},
            checked_at="2026-06-02 12:00 KST",
        )

        assert cells > 0
        formats = ws.batch_format.call_args[0][0]
        aligned_ranges = {
            item["range"]
            for item in formats
            if item.get("format") == ALIGNMENT_CENTER_MIDDLE
        }
        assert aligned_ranges == {"D2", "E2"}


class TestD026ColorFiveTypes:
    """D-026 Phase C+D+E+F (2026-05-16) 회귀 test — 색상 5종 batch_format 검증.

    사장님 명시 컨벤션:
    - AB / 스마트블록 / 인기글 / 중복노출 = 초록색
    - 미노출 / 누락 / 삭제 = 같은 붉은색
    - 빈 값 / 실패 / 수동 메모 = 무색
    """

    def _make_client_with_link_col(self, headers, link_col_values, ws_title="샴푸 카외"):
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
            mock_ws.col_values.return_value = link_col_values
            mock_ws.get_all_values.return_value = _rows_from_link_col(headers, link_col_values)
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def _get_color_for_value(self, ws, k_value):
        """write_results 호출 후 batch_format 에서 k_value 의 backgroundColor 추출."""
        headers = ["키워드", "링크", "노출영역"]
        link_col_values = ["링크", "https://cafe.naver.com/cosmania/12345"]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={HEADER_AREA: k_value})
        client.write_results("샴푸 카외", [upd])
        # batch_format 호출 1회 (색상 적용)
        assert ws.batch_format.call_count == 1
        formats = ws.batch_format.call_args[0][0]
        assert len(formats) == 1
        return formats[0]["format"]["backgroundColor"]

    def test_color_삭제_red(self):
        """D-043: K='삭제' = 붉은색."""
        bg = self._get_color_for_value(None, "삭제")
        assert bg == COLOR_NEGATIVE

    def test_color_누락_red(self):
        """D-043: K='누락' = 붉은색."""
        bg = self._get_color_for_value(None, "누락")
        assert bg == COLOR_NEGATIVE

    def test_color_중복노출_green(self):
        """D-043: K='중복노출' = 초록색."""
        bg = self._get_color_for_value(None, "중복노출")
        assert bg == COLOR_EXPOSED

    def test_color_미노출_red(self):
        """D-043: K='미노출' = 붉은색."""
        bg = self._get_color_for_value(None, "미노출")
        assert bg == COLOR_NEGATIVE

    def test_color_AB_green(self):
        """D-043: K='AB' = 초록색."""
        bg = self._get_color_for_value(None, "AB")
        assert bg == COLOR_EXPOSED

    def test_color_스마트블록_green(self):
        """D-043: K='스마트블록' = 초록색."""
        bg = self._get_color_for_value(None, "스마트블록")
        assert bg == COLOR_EXPOSED

    def test_color_인기글_green(self):
        """D-043: K='인기글' = 초록색."""
        bg = self._get_color_for_value(None, "인기글")
        assert bg == COLOR_EXPOSED

    def test_color_blank_no_fill(self):
        """D-043: K='' = 무색."""
        bg = self._get_color_for_value(None, "")
        assert bg == COLOR_NONE


class TestD029DuplicateSubEnumColors:
    """D-029 (2026-05-18 — D-026 정정) 회귀 test — 중복노출(구좌) 3종 = 모두 초록.

    사장님 5-18 명확 의도:
    - 중복노출(AB) / 중복노출(스마트블록) / 중복노출(인기글) = 모두 초록 (= 노출 상태 일관)
    - 색상 = "구좌 무관 = 중복노출 자체가 신규 발견" 통합 가시성.
    """

    def _make_client_with_link_col(self, headers, link_col_values, ws_title="샴푸 카외"):
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
            mock_ws.col_values.return_value = link_col_values
            mock_ws.get_all_values.return_value = _rows_from_link_col(headers, link_col_values)
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def _get_color_for_value(self, k_value):
        headers = ["키워드", "링크", "노출영역"]
        link_col_values = ["링크", "https://cafe.naver.com/cosmania/12345"]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={HEADER_AREA: k_value})
        client.write_results("샴푸 카외", [upd])
        assert ws.batch_format.call_count == 1
        formats = ws.batch_format.call_args[0][0]
        assert len(formats) == 1
        return formats[0]["format"]["backgroundColor"]

    def test_color_중복노출_AB_green(self):
        """D-043: K='중복노출(AB)' = 초록색."""
        bg = self._get_color_for_value("중복노출(AB)")
        assert bg == COLOR_EXPOSED

    def test_color_중복노출_스마트블록_green(self):
        """D-043: K='중복노출(스마트블록)' = 초록색."""
        bg = self._get_color_for_value("중복노출(스마트블록)")
        assert bg == COLOR_EXPOSED

    def test_color_중복노출_인기글_green(self):
        """D-043: K='중복노출(인기글)' = 초록색."""
        bg = self._get_color_for_value("중복노출(인기글)")
        assert bg == COLOR_EXPOSED

    def test_color_중복노출_legacy_green(self):
        """D-043: K='중복노출' (단일 값) = 초록색."""
        bg = self._get_color_for_value("중복노출")
        assert bg == COLOR_EXPOSED


class TestD030ColorStartswithMatching:
    """D-030 (2026-05-18) 회귀 test — K 값 + 시점 통합 = startswith 색상 매핑 정합.

    사장님 결정 정합 (= K = "AB (5/10 03:00~)" 형식 = exact match X):
    - "AB (5/10 03:00~)" prefix "AB" → green
    - "미노출 (5/10 03:00~)" prefix "미노출" → red
    - "누락 (5/14 03:00~)" prefix "누락" → red
    - "삭제 (5/16 03:00)" prefix "삭제" → red
    - "중복노출(AB) (5/10 03:00~)" prefix "중복노출" → green
    """

    def _make_client_with_link_col(self, headers, link_col_values, ws_title="샴푸 카외"):
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
            mock_ws.col_values.return_value = link_col_values
            mock_ws.get_all_values.return_value = _rows_from_link_col(headers, link_col_values)
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def _get_color_for_value(self, k_value):
        headers = ["키워드", "링크", "노출영역"]
        link_col_values = ["링크", "https://cafe.naver.com/cosmania/12345"]
        client, ws = self._make_client_with_link_col(headers, link_col_values)
        upd = RowUpdate(row=2, columns={HEADER_AREA: k_value})
        client.write_results("샴푸 카외", [upd])
        assert ws.batch_format.call_count == 1
        formats = ws.batch_format.call_args[0][0]
        assert len(formats) == 1
        return formats[0]["format"]["backgroundColor"]

    def test_d030_color_AB_with_stamp_green(self):
        """D-043: "AB (5/10 03:00~)" = AB prefix = 초록색."""
        bg = self._get_color_for_value("AB (5/10 03:00~)")
        assert bg == COLOR_EXPOSED

    def test_d030_color_미노출_with_stamp_red(self):
        """D-043: "미노출 (5/10 03:00~)" = 미노출 prefix = 붉은색."""
        bg = self._get_color_for_value("미노출 (5/10 03:00~)")
        assert bg == COLOR_NEGATIVE

    def test_d030_color_누락_with_stamp_red(self):
        """D-043: "누락 (5/14 03:00~)" = 누락 prefix = 붉은색."""
        bg = self._get_color_for_value("누락 (5/14 03:00~)")
        assert bg == COLOR_NEGATIVE

    def test_d030_color_삭제_with_stamp_red(self):
        """D-043: "삭제 (5/16 03:00)" = 삭제 prefix = 붉은색."""
        bg = self._get_color_for_value("삭제 (5/16 03:00)")
        assert bg == COLOR_NEGATIVE

    def test_d030_color_중복노출_AB_with_stamp_green(self):
        """D-043: "중복노출(AB) (5/10 03:00~)" = 중복노출 prefix = 초록색."""
        bg = self._get_color_for_value("중복노출(AB) (5/10 03:00~)")
        assert bg == COLOR_EXPOSED

    def test_d030_color_중복노출_인기글_with_stamp_green(self):
        """D-043: "중복노출(인기글) (5/10 03:00~)" = 중복노출 prefix = 초록색."""
        bg = self._get_color_for_value("중복노출(인기글) (5/10 03:00~)")
        assert bg == COLOR_EXPOSED

    def test_d030_color_스마트블록_with_stamp_green(self):
        """D-043: "스마트블록 (5/10 03:00~)" = 초록색."""
        bg = self._get_color_for_value("스마트블록 (5/10 03:00~)")
        assert bg == COLOR_EXPOSED

    def test_d030_color_인기글_with_stamp_green(self):
        """D-043: "인기글 (5/10 03:00~)" = 초록색."""
        bg = self._get_color_for_value("인기글 (5/10 03:00~)")
        assert bg == COLOR_EXPOSED

    def test_d030_color_실패_white(self):
        """D-030: "실패" = 시점 X = 흰색 (= 일시 상태 = reset)."""
        bg = self._get_color_for_value("실패")
        assert bg == COLOR_NONE

    def test_d030_color_legacy_base_only_compatibility(self):
        """D-030: 기존 시트 base 만 (= 시점 X) 호환 = startswith 정합 유지."""
        # 832 행 마이그레이션 전 = base 만 = 동일 색상 매핑
        assert self._get_color_for_value("AB") == COLOR_EXPOSED
        assert self._get_color_for_value("미노출") == COLOR_NEGATIVE
        assert self._get_color_for_value("누락") == COLOR_NEGATIVE
        assert self._get_color_for_value("삭제") == COLOR_NEGATIVE


class TestStaleFormulaRelocation:
    """T-M9.1 (2026-06-12, D-047) 회귀 test — write 직전 (키워드, 링크) 행 재탐색.

    배경: 검사 70분 사이 마케터 행 삽입/정렬로 행 번호가 밀리면, 종전에는 D-041 가드가
    그 행을 통째로 skip → 한 사이클 `재검사필요` 표류. 이제는 행을 다시 찾아 기록한다.
    """

    HEADERS = [
        "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
        "카페/게시글", "링크", "노출영역",
        "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
        "현재입력키", "마지막검사입력키", "raw_노출영역", "raw_통합순위",
        "raw_카페순위", "raw_지식인탭", "마지막검사시각",
    ]

    def _sheet_row(self, keyword="", link=""):
        row = [""] * len(self.HEADERS)
        row[3] = keyword
        row[9] = link
        return row

    def _make_client(self, sheet_rows):
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
            mock_ws.id = 1
            mock_ws.col_count = len(self.HEADERS)
            mock_ws.row_values.return_value = list(self.HEADERS)
            mock_ws.get_all_values.return_value = [list(self.HEADERS)] + sheet_rows
            mock_sheet.worksheet.return_value = mock_ws
            mock_gc.open_by_key.return_value = mock_sheet
            mock_auth.return_value = mock_gc
            client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        return client, mock_ws

    def _update(self, row, k="AB (6/12 12:00~)", L="1", M="1"):
        return RowUpdate(row=row, columns={
            HEADER_AREA: k,
            HEADER_L: L,
            HEADER_M: M,
            HEADER_JISIKIN: "",
        })

    def test_relocates_write_to_shifted_row(self):
        """읽기 시점 행 2 였던 행이 write 시점 행 5 로 밀림 → 행 5 에 기록 (행 2 X)."""
        sheet_rows = [
            self._sheet_row("새행1", "https://cafe.naver.com/x/1"),
            self._sheet_row("새행2", "https://cafe.naver.com/x/2"),
            self._sheet_row("새행3", "https://cafe.naver.com/x/3"),
            self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021"),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded = {
            "_row": 2,
            "키워드": "알라딘필링후기",
            # 쿼리스트링은 identity 정규화로 제거됨 = 시트의 깨끗한 링크와 매치
            "링크": "https://cafe.naver.com/llchyll/2449021?art=xyz",
        }
        stats = {}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [self._update(2)],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST", stats_out=stats,
        )
        assert cells == 6
        payload = ws.batch_update.call_args.args[0]
        ranges = {item["range"] for item in payload}
        assert all(r.endswith("5") for r in ranges)
        assert stats["relocation_miss_rows"] == 0
        assert stats["relocation_conflict_keys"] == 0

    def test_fanout_writes_same_result_to_duplicate_rows(self):
        """같은 (키워드, 링크) 행 2개 (= 마케터 일자별 중복 행) = 둘 다 갱신."""
        sheet_rows = [
            self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021"),
            self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021"),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "알라딘필링후기", "링크": "https://cafe.naver.com/llchyll/2449021"}
        stats = {}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [self._update(2)],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST", stats_out=stats,
        )
        assert cells == 12
        payload = ws.batch_update.call_args.args[0]
        ranges = {item["range"] for item in payload}
        assert any(r.endswith("2") for r in ranges)
        assert any(r.endswith("3") for r in ranges)
        assert stats["relocation_fanout_rows"] == 1

    def test_conflicting_duplicate_updates_are_quarantined(self):
        """Codex Critical 1: 같은 identity 의 update payload 가 다르면 = 충돌 = 전체 보류."""
        sheet_rows = [
            self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021"),
            self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021"),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded_2 = {"_row": 2, "키워드": "알라딘필링후기", "링크": "https://cafe.naver.com/llchyll/2449021"}
        loaded_3 = {"_row": 3, "키워드": "알라딘필링후기", "링크": "https://cafe.naver.com/llchyll/2449021"}
        stats = {}
        cells = client.write_stale_formula_results(
            "바디워시 카외",
            [self._update(2, k="AB (6/8 17:19~)"), self._update(3, k="AB (6/12 12:00~)")],
            row_context={2: loaded_2, 3: loaded_3}, checked_at="2026-06-12 13:00 KST", stats_out=stats,
        )
        assert cells == 0
        ws.batch_update.assert_not_called()
        assert stats["relocation_conflict_keys"] == 1

    def test_miss_skips_when_input_edited_midrun(self):
        """identity 미발견 (입력이 검사 도중 변경/삭제) = skip = 다음 cron 재검사 (D-041 의미 유지)."""
        sheet_rows = [self._sheet_row("알라딘필링후기", "https://naver.me/NEWLINK1")]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "알라딘필링후기", "링크": "https://naver.me/OLDLINK9"}
        stats = {}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [self._update(2)],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST", stats_out=stats,
        )
        assert cells == 0
        ws.batch_update.assert_not_called()
        assert stats["relocation_miss_rows"] == 1

    def test_naverme_short_link_relocation_is_case_sensitive(self):
        """Codex Major 3: naver.me 단축링크 = 경로 대소문자 구분 = 재배치 충돌 방지."""
        sheet_rows = [
            self._sheet_row("일리윤립앤아이리무버", "https://naver.me/IDk3rxSi"),
            self._sheet_row("일리윤립앤아이리무버", "https://naver.me/idk3rxsi"),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "일리윤립앤아이리무버", "링크": "https://naver.me/IDk3rxSi"}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [self._update(2)],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST",
        )
        assert cells == 6
        payload = ws.batch_update.call_args.args[0]
        ranges = {item["range"] for item in payload}
        assert all(r.endswith("2") for r in ranges)

    def test_clear_stale_formula_cells_clears_hidden_columns_only(self):
        """T-M9.2: 잔해 소독 = 숨김 시스템 칸 6개만 빈 값으로 초기화 (보이는 칸 X)."""
        sheet_rows = [
            self._sheet_row("kw1", "https://cafe.naver.com/x/1"),
            self._sheet_row("kw2", "https://cafe.naver.com/x/2"),
        ]
        client, ws = self._make_client(sheet_rows)
        cells = client.clear_stale_formula_cells("바디워시 카외", [2, 3])
        assert cells == 12
        payload = ws.batch_update.call_args.args[0]
        assert all(item["values"] == [[""]] for item in payload)
        ranges = {item["range"] for item in payload}
        # 숨김 칸 (Q~V = 마지막검사입력키/raw_*/마지막검사시각) 만 — 보이는 K(열 11=K) 침범 X
        assert "K2" not in ranges and "K3" not in ranges
        assert "Q2" in ranges and "Q3" in ranges

    def test_normalize_input_link_matches_sheet_formula_rule(self):
        """Codex Major 4: Python input_key 링크 정규화 = 시트 수식과 동일 (끝 슬래시만 제거)."""
        from src.sheets import _normalize_input_link
        # 내부 이중 슬래시 보존 (수식 REGEXREPLACE "/+$" 정합)
        assert _normalize_input_link("https://cafe.naver.com/a//b/") == "cafe.naver.com/a//b"
        assert _normalize_input_link("https://m.cafe.naver.com/X/1?art=z") == "cafe.naver.com/x/1"

    def test_relocation_matches_case_only_difference_in_cafe_url(self):
        """Codex 사후 Minor 2: 일반 cafe URL = 대소문자 차이는 같은 행으로 재배치."""
        sheet_rows = [self._sheet_row("알라딘필링후기", "https://cafe.naver.com/llchyll/2449021")]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "알라딘필링후기", "링크": "https://Cafe.Naver.com/LLchyll/2449021"}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [self._update(2)],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST",
        )
        assert cells == 6

    def test_blank_link_autofill_requires_unique_match(self):
        """Codex 사후 Major 1: 빈 link + 같은 키워드 행 다수 = 모호 = link 자동 채움 보류."""
        sheet_rows = [
            self._sheet_row("도브바디스크럽", ""),
            self._sheet_row("도브바디스크럽", ""),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "도브바디스크럽", "링크": ""}
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "중복노출(AB) (6/12 12:00~)",
            HEADER_L: "1", HEADER_M: "1", HEADER_JISIKIN: "",
            HEADER_LINK: "https://cafe.naver.com/llchyll/9999999",
        })
        stats = {}
        cells = client.write_stale_formula_results(
            "바디워시 카외", [upd],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST", stats_out=stats,
        )
        assert cells == 0
        ws.batch_update.assert_not_called()
        assert stats["relocation_conflict_keys"] == 1

    def test_blank_link_autofill_unique_match_fills_link(self):
        """빈 link + 같은 키워드 행 1개 = 그 행에만 raw 기록 + link 자동 채움 (D-026 유지)."""
        sheet_rows = [
            self._sheet_row("다른키워드", "https://cafe.naver.com/x/1"),
            self._sheet_row("도브바디스크럽", ""),
        ]
        client, ws = self._make_client(sheet_rows)
        loaded = {"_row": 2, "키워드": "도브바디스크럽", "링크": ""}
        upd = RowUpdate(row=2, columns={
            HEADER_AREA: "중복노출(AB) (6/12 12:00~)",
            HEADER_L: "1", HEADER_M: "1", HEADER_JISIKIN: "",
            HEADER_LINK: "https://cafe.naver.com/llchyll/9999999",
        })
        cells = client.write_stale_formula_results(
            "바디워시 카외", [upd],
            row_context={2: loaded}, checked_at="2026-06-12 13:00 KST",
        )
        # 숨김 6칸 + link 자동 채움 1칸 = 7칸, 전부 행 3 (재배치)
        assert cells == 7
        payload = ws.batch_update.call_args.args[0]
        ranges = {item["range"] for item in payload}
        assert all(r.endswith("3") for r in ranges)
        values = [item["values"][0][0] for item in payload]
        assert "https://cafe.naver.com/llchyll/9999999" in values
