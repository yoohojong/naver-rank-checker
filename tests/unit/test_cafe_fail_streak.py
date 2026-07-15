"""카페 구좌 1등 실패 재발행 횟수 카운터 + 키워드 셀 색 강도 표기 단위 테스트 (2026-07-16).

변경 이력:
- v1: run당 카운터
- v2: 하루당 카운터 (YYYY-MM-DD 게이트)
- v3: 재발행 횟수 (작업일 M/D 게이트) — 사장님 확정 의미

의미: 재발행(작업일 값이 바뀜)마다, 1일 지나도 1등 실패면 +1. 같은 발행분은 run 수에 무관 1회만.
색 임계: 1회=연노랑, 2회=주황, 3회+=빨강.

대상:
- 순수 로직: _next_cafe_fail_streak / _fail_streak_color / _parse_fail_streak / _parse_checked_date
- 통합: write_stale_formula_results 가 raw_카페1등실패횟수 + raw_카페실패마지막작업일 셀을 갱신하고
  키워드 셀에 강도색을 칠하는지 (라이브 write 없이 MagicMock 으로 검증).
"""
import json
from datetime import date
from unittest.mock import patch, MagicMock

from src.sheets import (
    SheetsClient,
    RowUpdate,
    COLOR_NONE,
    COLOR_FAIL_STREAK_1,
    COLOR_FAIL_STREAK_2,
    COLOR_FAIL_STREAK_3,
    COLOR_FAIL_HISTORY,
    _next_cafe_fail_streak,
    _fail_streak_color,
    _parse_fail_streak,
    _parse_checked_date,
    HEADER_M,
    HEADER_RAW_CAFE_FAIL_MAX,
)

# 사장님 예시 기준: 9일 발행→10일(오늘). ref = 10일.
REF_10 = date(2026, 9, 10)   # 오늘 = 9/10
REF_12 = date(2026, 9, 12)   # 오늘 = 9/12 (11일 재발행 → 12일 체크)
WD_9 = "9/9"                  # 9일 작업일
WD_11 = "9/11"                # 11일 재발행 작업일


# ── 순수 로직: _next_cafe_fail_streak ────────────────────────────────────────
# 반환: (new_counter: int, new_last_workdate: str)
# new_last_workdate = 현재 작업일(M/D) 또는 빈칸

class TestNextCafeFailCount:
    # ─── 사장님 예시 그대로 ───────────────────────────────────────────────────
    def test_9일발행_10일_1회(self):
        """9일 발행 → 1일 지나도(10일) 1등 실패 = 첫 번째 횟수 → 1"""
        cnt, wd = _next_cafe_fail_streak(0, "", WD_9, REF_10, last_count_date_str="")
        assert cnt == 1
        assert wd == WD_9

    def test_같은발행_재검사_유지(self):
        """위 상태서 10일에 run 재실행(마지막작업일 이미 9/9) → 1 유지 (중복 카운트 안 함)"""
        cnt, wd = _next_cafe_fail_streak(1, "", WD_9, REF_10, last_count_date_str=WD_9)
        assert cnt == 1   # 늘어나지 않음
        assert wd == WD_9

    def test_11일재발행_12일_2회(self):
        """마지막작업일=9/9 상태서 11일 재발행, 12일에 또 1등 실패 → 2"""
        cnt, wd = _next_cafe_fail_streak(1, "", WD_11, REF_12, last_count_date_str=WD_9)
        assert cnt == 2
        assert wd == WD_11

    # ─── 1등 리셋 ────────────────────────────────────────────────────────────
    def test_1등이면_0_리셋_마지막작업일_클리어(self):
        cnt, wd = _next_cafe_fail_streak(5, "1", WD_9, REF_10, last_count_date_str=WD_9)
        assert cnt == 0
        assert wd == ""

    def test_1등_공백_트림_후_리셋(self):
        cnt, wd = _next_cafe_fail_streak(3, " 1 ", WD_9, REF_10)
        assert cnt == 0
        assert wd == ""

    # ─── 유지(건드리지 않음) ─────────────────────────────────────────────────
    def test_작업일_빈칸이면_prev_유지(self):
        """경과 계산 불가 → (prev, last_wd) 그대로"""
        cnt, wd = _next_cafe_fail_streak(3, "", "", REF_10, last_count_date_str=WD_9)
        assert cnt == 3
        assert wd == WD_9

    def test_작업일_파싱불가면_prev_유지(self):
        cnt, wd = _next_cafe_fail_streak(2, "", "없음", REF_10, last_count_date_str=WD_9)
        assert cnt == 2
        assert wd == WD_9

    def test_1일_미경과면_prev_유지(self):
        """작업일==오늘(ref) = 0일 경과 = 아직 판단 전 → 유지"""
        wd_today = f"{REF_10.month}/{REF_10.day}"  # "9/10" — strftime %-m 윈도우 미지원
        cnt, wd = _next_cafe_fail_streak(2, "", wd_today, REF_10, last_count_date_str=WD_9)
        assert cnt == 2
        assert wd == WD_9

    def test_ref_date_없으면_prev_유지(self):
        cnt, wd = _next_cafe_fail_streak(3, "", WD_9, None, last_count_date_str=WD_9)
        assert cnt == 3
        assert wd == WD_9

    # ─── 경계/방어 ───────────────────────────────────────────────────────────
    def test_정확히_1일경과는_카운트_포함(self):
        """9/9 작업, 9/10 run = 정확히 1일 → 카운트"""
        cnt, _ = _next_cafe_fail_streak(0, "", WD_9, REF_10, last_count_date_str="")
        assert cnt == 1

    def test_2등이하도_실패(self):
        """카페순위 "3" = 1등 실패"""
        cnt, wd = _next_cafe_fail_streak(0, "3", WD_9, REF_10, last_count_date_str="")
        assert cnt == 1
        assert wd == WD_9

    def test_prev_음수_방어(self):
        cnt, _ = _next_cafe_fail_streak(-5, "", WD_9, REF_10, last_count_date_str="")
        assert cnt == 1   # max(0, -5) + 1

    def test_첫run_last_wd_없으면_첫카운트(self):
        """마지막작업일 빈칸(첫 마이그레이션) → 첫 카운트"""
        cnt, wd = _next_cafe_fail_streak(0, "", WD_9, REF_10, last_count_date_str="")
        assert cnt == 1
        assert wd == WD_9


# ── 순수 로직: _fail_streak_color ────────────────────────────────────────────
class TestFailStreakColor:
    def test_0이하는_색없음_None(self):
        assert _fail_streak_color(0) is None
        assert _fail_streak_color(-1) is None

    def test_1회_연노랑(self):
        assert _fail_streak_color(1) == COLOR_FAIL_STREAK_1

    def test_2회_주황(self):
        assert _fail_streak_color(2) == COLOR_FAIL_STREAK_2

    def test_3회이상_빨강(self):
        assert _fail_streak_color(3) == COLOR_FAIL_STREAK_3
        assert _fail_streak_color(50) == COLOR_FAIL_STREAK_3

    def test_강도_단조성_green_채널_감소(self):
        greens = [
            COLOR_FAIL_STREAK_1["green"],
            COLOR_FAIL_STREAK_2["green"],
            COLOR_FAIL_STREAK_3["green"],
        ]
        assert greens == sorted(greens, reverse=True)
        assert len(set(greens)) == 3

    def test_전적있으나_현재1등_회색(self):
        """counter=0 AND max>=1 → 옅은 회색(전적 있음 표시)"""
        assert _fail_streak_color(0, 1) == COLOR_FAIL_HISTORY
        assert _fail_streak_color(0, 3) == COLOR_FAIL_HISTORY

    def test_무전적_1등_색없음(self):
        """counter=0 AND max=0 → None(색 없음, 판단전/무전적)"""
        assert _fail_streak_color(0, 0) is None


# ── 순수 로직: 파서 ──────────────────────────────────────────────────────────
class TestParsers:
    def test_parse_fail_streak_빈칸_0(self):
        assert _parse_fail_streak("") == 0
        assert _parse_fail_streak(None) == 0

    def test_parse_fail_streak_숫자(self):
        assert _parse_fail_streak("3") == 3

    def test_parse_fail_streak_음수_0(self):
        assert _parse_fail_streak("-5") == 0
        assert _parse_fail_streak("abc") == 0

    def test_parse_checked_date(self):
        assert _parse_checked_date("2026-09-10 12:00 KST") == date(2026, 9, 10)

    def test_parse_checked_date_실패_None(self):
        assert _parse_checked_date("garbage") is None


# ── 통합: write_stale_formula_results 카운터/색칠/마지막작업일 ──────────────────
# 헤더: W = raw_카페1등실패횟수(idx 22), X = raw_카페실패마지막작업일(idx 23)
HEADERS = [
    "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
    "카페/게시글", "링크", "노출영역",
    "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
    "현재입력키", "마지막검사입력키", "raw_노출영역", "raw_통합순위",
    "raw_카페순위", "raw_지식인탭", "마지막검사시각",
    "raw_카페1등실패횟수",      # W = index 22
    "raw_카페실패마지막작업일", # X = index 23
    "raw_카페실패최대",         # Y = index 24 (역대 최대, 단조 비감소)
]
KEYWORD = "비듬샴푸추천"
LINK = "https://cafe.naver.com/workee/1325909"


def _make_client(prev_count: str, workdate: str, prev_last_wd: str = "", prev_max: str = "0"):
    fake_creds = json.dumps({
        "type": "service_account",
        "client_email": "x@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    row2 = [""] * len(HEADERS)
    row2[HEADERS.index("작업일")] = workdate
    row2[HEADERS.index("키워드")] = KEYWORD
    row2[HEADERS.index("링크")] = LINK
    row2[HEADERS.index("raw_카페1등실패횟수")] = prev_count
    row2[HEADERS.index("raw_카페실패마지막작업일")] = prev_last_wd
    row2[HEADERS.index("raw_카페실패최대")] = prev_max
    with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
        mock_gc = MagicMock()
        mock_sheet = MagicMock()
        mock_ws = MagicMock()
        mock_ws.id = 12345
        mock_ws.col_count = len(HEADERS)
        mock_ws.row_values.return_value = HEADERS
        mock_ws.get_all_values.return_value = [HEADERS, row2]
        mock_sheet.worksheet.return_value = mock_ws
        mock_gc.open_by_key.return_value = mock_sheet
        mock_auth.return_value = mock_gc
        client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
    return client, mock_ws


def _all_cells(ws) -> list:
    out = []
    for call in ws.batch_update.call_args_list:
        out.extend(call.args[0])
    return out


def _all_formats(ws) -> list:
    out = []
    for call in ws.batch_format.call_args_list:
        out.extend(call.args[0])
    return out


def _write(client, cafe_rank: str, checked_at: str = "2026-09-10 12:00 KST"):
    row = {"_row": 2, "키워드": KEYWORD, "링크": LINK}
    update = RowUpdate(row=2, columns={
        "노출영역": "미노출 (9/10 12:00~)" if cafe_rank != "1" else "AB (9/10 12:00~)",
        "노출여부(통합탭 순위)": "",
        HEADER_M: cafe_rank,
        "지식인탭": "",
    })
    return client.write_stale_formula_results(
        "샴푸 카외", [update], row_context={2: row}, checked_at=checked_at,
    )


class TestWriteStaleFormulaFailCount:
    # W2 = raw_카페1등실패횟수, X2 = raw_카페실패마지막작업일, D2 = 키워드

    def test_사장님예시_9일발행_10일_1회_연노랑(self):
        """9일 발행(작업일=9/9), 10일 run, 1등 실패 → W2=1, X2=9/9, D2=연노랑"""
        client, ws = _make_client(prev_count="0", workdate="9/9", prev_last_wd="")
        _write(client, cafe_rank="", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["1"]]} in cells
        assert {"range": "X2", "values": [["9/9"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_1}} in _all_formats(ws)

    def test_사장님예시_같은발행_재검사_유지(self):
        """10일 두 번째 run — 마지막작업일 이미 9/9 → W2=1 유지, D2=연노랑"""
        client, ws = _make_client(prev_count="1", workdate="9/9", prev_last_wd="9/9")
        _write(client, cafe_rank="", checked_at="2026-09-10 18:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["1"]]} in cells   # 유지
        assert {"range": "X2", "values": [["9/9"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_1}} in _all_formats(ws)

    def test_사장님예시_11일재발행_12일_2회_주황(self):
        """마지막작업일=9/9 상태, 11일 재발행(작업일=9/11), 12일 run → W2=2, 주황"""
        client, ws = _make_client(prev_count="1", workdate="9/11", prev_last_wd="9/9")
        _write(client, cafe_rank="", checked_at="2026-09-12 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["2"]]} in cells
        assert {"range": "X2", "values": [["9/11"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_2}} in _all_formats(ws)

    def test_3회이상_빨강(self):
        client, ws = _make_client(prev_count="2", workdate="9/11", prev_last_wd="9/9")
        _write(client, cafe_rank="", checked_at="2026-09-12 12:00 KST")

        assert {"range": "W2", "values": [["3"]]} in _all_cells(ws)
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_3}} in _all_formats(ws)

    def test_1등이면_카운터_0_리셋_날짜_클리어_키워드_흰색(self):
        client, ws = _make_client(prev_count="3", workdate="9/9", prev_last_wd="9/9")
        _write(client, cafe_rank="1", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["0"]]} in cells
        assert {"range": "X2", "values": [[""]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_NONE}} in _all_formats(ws)

    def test_작업일없음_prev_유지(self):
        """작업일 빈칸 → 횟수 3 유지, 빨강 유지"""
        client, ws = _make_client(prev_count="3", workdate="", prev_last_wd="9/9")
        _write(client, cafe_rank="")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["3"]]} in cells
        assert {"range": "X2", "values": [["9/9"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_3}} in _all_formats(ws)

    def test_1일미경과_prev_유지(self):
        """작업일==오늘(9/10), run도 9/10 → 0일 경과 → 2 유지, 주황"""
        client, ws = _make_client(prev_count="2", workdate="9/10", prev_last_wd="9/9")
        _write(client, cafe_rank="", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["2"]]} in cells
        assert {"range": "X2", "values": [["9/9"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_STREAK_2}} in _all_formats(ws)

    def test_1등_전적있음_회색(self):
        """현재 1등(streak=0) + 역대최대=2 → 키워드 셀 옅은 회색(전적 있음 표시)"""
        client, ws = _make_client(prev_count="0", workdate="9/9", prev_last_wd="", prev_max="2")
        _write(client, cafe_rank="1", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["0"]]} in cells   # streak 리셋
        assert {"range": "X2", "values": [[""]]} in cells    # 마지막작업일 클리어
        assert {"range": "Y2", "values": [["2"]]} in cells   # 최대 유지(줄어들지 않음)
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_HISTORY}} in _all_formats(ws)

    def test_1등_무전적_흰색(self):
        """현재 1등(streak=0) + 역대최대=0 → 키워드 셀 흰색(무전적/판단전)"""
        client, ws = _make_client(prev_count="0", workdate="9/9", prev_last_wd="", prev_max="0")
        _write(client, cafe_rank="1", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["0"]]} in cells
        assert {"range": "Y2", "values": [["0"]]} in cells
        assert {"range": "D2", "format": {"backgroundColor": COLOR_NONE}} in _all_formats(ws)

    def test_최대는_안줄어듦(self):
        """streak 3 → 1등 리셋 → streak=0 이지만 최대는 여전히 3, 키워드 셀 회색"""
        client, ws = _make_client(prev_count="3", workdate="9/9", prev_last_wd="9/9", prev_max="3")
        _write(client, cafe_rank="1", checked_at="2026-09-10 12:00 KST")

        cells = _all_cells(ws)
        assert {"range": "W2", "values": [["0"]]} in cells   # streak 리셋
        assert {"range": "X2", "values": [[""]]} in cells    # 마지막작업일 클리어
        assert {"range": "Y2", "values": [["3"]]} in cells   # 최대 여전히 3 (줄어들지 않음)
        assert {"range": "D2", "format": {"backgroundColor": COLOR_FAIL_HISTORY}} in _all_formats(ws)
