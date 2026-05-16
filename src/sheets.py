"""sheets: Google Sheets I/O, 헤더 기반 매핑, 분야별 탭 순회."""
import json
import random
import time
from dataclasses import dataclass
from typing import Optional

import gspread


# 2026-05-12 T-M11: Google Sheets API 503 retry (document-specialist 외부 사실).
# gspread 6.1.4 default = retry X. 503 = Google 일시 장애 (quota X). cron 25683405754 fail 후 추가.
SHEETS_RETRY_MAX_ATTEMPTS = 3
SHEETS_RETRY_BASE_SEC = 5  # 5s, 10s, 20s + jitter
SHEETS_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}  # transient errors


def _sheets_api_retry(func, *, ctx: str = ""):
    """Google Sheets API call wrapper — 503/5xx retry (exponential backoff + jitter).

    cron 25683405754 (2026-05-12) 의 batch_update 503 fail 분석 결과 = gspread default
    retry 하지 않음. 한 번 fail 시 데이터 손실 (사장님 시트에 기록되지 않음).
    fix = 5s/10s/20s backoff + jitter. 총 마진 ~35초. 진짜 장기 장애면 cron 다음 schedule 에 처리됨.
    """
    last_error = None
    for attempt in range(SHEETS_RETRY_MAX_ATTEMPTS):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            last_error = e
            # 503/5xx/429 만 retry. 그 외 (4xx 사용자 잘못) 즉시 raise
            status = None
            try:
                status = e.response.status_code
            except Exception:
                pass
            if status not in SHEETS_RETRY_STATUS_CODES:
                raise
            if attempt < SHEETS_RETRY_MAX_ATTEMPTS - 1:
                backoff = SHEETS_RETRY_BASE_SEC * (2 ** attempt)
                jitter = random.uniform(-0.5, 0.5) * backoff * 0.2
                wait = max(0.5, backoff + jitter)
                print(f"  [SHEETS-RETRY {ctx}] HTTP {status}, {wait:.1f}s 후 재시도 (attempt {attempt+1}/{SHEETS_RETRY_MAX_ATTEMPTS}): {e}")
                time.sleep(wait)
            else:
                raise
    raise last_error

# 사장님 시트 헤더 명 (2026-05-08 확인 — 정확 매칭 필수)
HEADER_TYPE = "유형"  # C — 사장님 의도 기록 컬럼 (D-024 2026-05-14: 자동 갱신 절대 X)
HEADER_AREA = "노출영역"  # K — AB / 인기글 / 삭제 / 빈칸(미노출)
HEADER_L = "노출여부(통합탭 순위)"  # L — integrated_rank
HEADER_M = "노출여부(카페구좌순위)"  # M — cafe_slot_rank
HEADER_JISIKIN = "지식인탭"  # O — 'O' or 빈칸
HEADER_LINK = "링크"  # 사장님 입력 컬럼 (D-023 2026-05-14: 자동 갱신 절대 X — reference 용)

# D-023 (2026-05-14) 영구 룰: 사장님 시트 사용자 입력 컬럼 = 자동 갱신 절대 X.
# write_results 가 SYSTEM_OUTPUT_COLUMNS 외 컬럼 write 시도 시 = 거부 + log.
# 보호 대상 (사장님 입력): 작업일/작업자/키워드/검색량/작업아이디/카페/게시판/링크/유형(C) 등.
# 허용 갱신 (시스템 출력): K(노출영역) / L(통합탭) / M(카페구좌) / O(지식인).
# 근거: T-M14.2 commit 10c1ca5 = 사장님 작업 link silent 덮어쓰기 사고 → D-023 신규 영구 가드.
# D-024 (2026-05-14) 추가: 유형(C) = 사장님 의도 기록 = 보호 (T-M13 학습 정합 + D-005 폐기, D-024 적용).
# critic Opus 검증 후 사장님 단호 시그널 "ㄱ" (= B+예) 정합 일괄 적용.
SYSTEM_OUTPUT_COLUMNS = frozenset({HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN})

# D-026 Phase C+D (2026-05-16) 부분 완화: 빈 link 행 = 자동 채움 logic 허용.
# main.py 가 빈 link 행 + 키워드 검색 결과에 다른 행 우리 link 매치 시 = K="중복노출" + link 자동 채움.
# 사장님 시점 = 새 노출 자동 발견 = HEADER_LINK 채움 허용 (다만 기존 link 행 = D-023 가드 그대로 적용).
# 적용 규칙: write_results 가 행 현재 link 값 read 후 = 빈 link 행만 EMPTY_LINK 화이트리스트 사용.
SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK = frozenset({HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK})

# 데이터 탭 아닌 특수 탭 — load_all_data_tabs 가 skip.
# 사장님 시트의 "카페매핑" 등 메타 탭 제외용.
SPECIAL_TABS = frozenset({"카페매핑", "_meta", "설정", "config"})


class SheetsClient:
    """Google Sheets 서비스 계정 인증 + spreadsheet 열기.

    M5.2~M5.5 에서 헤더 매핑/탭 순회/배치 write 메서드 추가됨.
    """

    def __init__(self, spreadsheet_id: str, service_account_json: str):
        # 2026-05-11 defensive: PowerShell pipe / Windows 메모장 등이 UTF-8 BOM 을 secret 에 추가할 수 있음.
        # json.loads 는 BOM 거부 ("Unexpected UTF-8 BOM"). 사장님이 어떻게 set 하든 강건하게 처리.
        if service_account_json.startswith("﻿"):
            service_account_json = service_account_json[1:]
        creds_dict = json.loads(service_account_json)
        self.gc = gspread.service_account_from_dict(creds_dict)
        self.spreadsheet = self.gc.open_by_key(spreadsheet_id)

    def write_results(self, tab_name: str, updates: list["RowUpdate"]) -> int:
        """한 탭에 여러 행을 batch_update 1회 호출.

        Args:
            tab_name: 사장님 분야 탭 이름 (예: "샴푸 카외")
            updates: list of RowUpdate (각 행의 변경 사항)

        Returns:
            업데이트된 셀 수.

        사장님 컨벤션 (2026-05-08): 헤더에 명시된 컬럼만 갱신. 사장님이 안 쓰는 컬럼 (작업일/작업자/MB/PC 등) 절대 X.

        D-026 Phase C+D (2026-05-16) 부분 완화:
        - 행 현재 link 값 read → 빈 link 행만 SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK 사용 (HEADER_LINK write 허용).
        - 기존 link 행 = SYSTEM_OUTPUT_COLUMNS 그대로 적용 (= D-023 가드 유지, link 자동 갱신 X).
        """
        if not updates:
            return 0
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)

        # D-026 Phase C+D (2026-05-16): HEADER_LINK 컬럼 현재 값 read = 빈 link 행 분기 용.
        # gspread col_values 1-indexed.
        # 보수적 처리 (D-023 정합): link read 실패 또는 row 범위 외 = "non-empty" 가정 (= 엄격 가드)
        link_col_values: Optional[list[str]] = None
        link_read_ok = False
        if HEADER_LINK in mapping:
            try:
                link_col_values = _sheets_api_retry(
                    lambda: ws.col_values(mapping[HEADER_LINK] + 1),
                    ctx=f"{tab_name} (link read)",
                )
                # 정상 list 인지 검증 (= mock MagicMock 등 비정상 객체 = read 실패 간주)
                if isinstance(link_col_values, list):
                    link_read_ok = True
            except Exception as e:
                # link read 실패 시 = 보수적 = 전부 SYSTEM_OUTPUT_COLUMNS 적용 (D-023 가드)
                print(f"  [D-026-LINK-READ-FAIL] {tab_name}: {e} — SYSTEM_OUTPUT_COLUMNS 적용 (보수)")

        def _row_current_link(row_1based: int) -> str:
            """row_1based 의 현재 link 값. read 실패 / row 범위 외 = "non-empty" 보수 가정 ('SENTINEL')."""
            # read 실패 = 보수적 = "SENTINEL" 반환 (= 엄격 가드 적용)
            if not link_read_ok or link_col_values is None:
                return "SENTINEL"
            idx = row_1based - 1  # col_values = 1-indexed
            if 0 <= idx < len(link_col_values):
                return (link_col_values[idx] or "").strip()
            # row 범위 외 = 보수적 = "SENTINEL" 반환
            return "SENTINEL"

        cells = []
        for upd in updates:
            # D-026 Phase C+D (2026-05-16): 행 현재 link 값 read → 빈 link 행만 EMPTY_LINK 화이트리스트 사용
            current_link = _row_current_link(upd.row)
            use_columns = SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK if not current_link else SYSTEM_OUTPUT_COLUMNS

            for col_name, new_val in upd.columns.items():
                if col_name not in mapping:
                    continue  # 사장님 시트에 없는 컬럼은 skip (예: blog_slot_rank)
                # D-023 (2026-05-14) 영구 가드 + D-026 Phase C+D (2026-05-16) 부분 완화:
                # 빈 link 행 = SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK (HEADER_LINK 허용)
                # 기존 link 행 = SYSTEM_OUTPUT_COLUMNS (HEADER_LINK 거부, T-M14.2 사고 재발 방지)
                if col_name not in use_columns:
                    guard_name = "D-026-EMPTY-LINK-GUARD" if not current_link else "D-023-GUARD"
                    print(f"  [{guard_name}] '{col_name}' = write 거부 (행 {upd.row}, 현재 link 빈={not current_link})")
                    continue
                col_idx = mapping[col_name] + 1  # gspread 1-indexed
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(upd.row, col_idx),
                    "values": [[new_val]],
                })
        if cells:
            # 2026-05-12 T-M11: 503/5xx retry (document-specialist gspread default retry X).
            _sheets_api_retry(
                lambda: ws.batch_update(cells, value_input_option="RAW"),
                ctx=tab_name,
            )

        # D-026 Phase C+D+E+F (2026-05-16) 색상 5종:
        # - 삭제 = 노란 (T-M14 정합 유지)
        # - 누락 = 오렌지 (= 떨어짐 경고)
        # - 중복노출 = 파란 (= 신규 발견)
        # - 미노출 = 회색 (옅은 회색)
        # - AB / 스마트블록 / 인기글 / 빈 = 흰색 (= 정상 노출, reset)
        if HEADER_AREA in mapping:
            k_col = mapping[HEADER_AREA] + 1  # 1-indexed
            color_formats = []
            yellow = {"red": 1.0, "green": 1.0, "blue": 0.0}    # 삭제
            orange = {"red": 1.0, "green": 0.6, "blue": 0.2}    # 누락
            blue = {"red": 0.6, "green": 0.8, "blue": 1.0}      # 중복노출
            gray = {"red": 0.9, "green": 0.9, "blue": 0.9}      # 미노출
            white = {"red": 1.0, "green": 1.0, "blue": 1.0}     # AB / 스마트블록 / 인기글 / 빈
            color_map = {
                "삭제": yellow,
                "누락": orange,
                "중복노출": blue,
                "미노출": gray,
            }
            for upd in updates:
                if HEADER_AREA not in upd.columns:
                    continue
                k_value = upd.columns[HEADER_AREA]
                cell_range = gspread.utils.rowcol_to_a1(upd.row, k_col)
                bg = color_map.get(k_value, white)
                color_formats.append({"range": cell_range, "format": {"backgroundColor": bg}})
            if color_formats:
                _sheets_api_retry(
                    lambda: ws.batch_format(color_formats),
                    ctx=f"{tab_name} (색상)",
                )
        return len(cells)

    def write_timestamp(self, tab_name: str, kst_iso: str) -> None:
        """탭의 1행 16번째 컬럼(P열)에 'cron 갱신: YYYY-MM-DD HH:MM KST' 기록.

        T-M37 (2026-05-12): 사장님 시트 컨벤션 보존 — 헤더 행 직접 침범 X.
        1행 16번째 컬럼(P열, 헤더 영역 밖)에 기록.
        실패 시 log warn 후 무시 (시트 protected 등 방어).
        """
        import logging
        try:
            ws = self.spreadsheet.worksheet(tab_name)
            _sheets_api_retry(
                lambda: ws.update_cell(1, 16, f"cron 갱신: {kst_iso}"),
                ctx=f"{tab_name} (timestamp)",
            )
        except Exception as e:
            logging.warning(f"[{tab_name}] timestamp 기록 실패: {e}")

    def load_all_data_tabs(
        self,
        tab_filter: Optional[callable] = None,
    ) -> dict[str, list[dict]]:
        """데이터 탭 순회 read. 특수 탭 (카페매핑 등) 제외.

        Args:
            tab_filter: 탭 이름 → bool. True 인 탭만 처리. None 이면 모든 탭 (SPECIAL_TABS 외).
                        사장님 운영 시트에 시스템 처리 대상 외 탭 (PII 등) 있으면 명시 화이트리스트 권장.
                        예: `lambda t: t.endswith("카외")` — 사장님 분야 탭 컨벤션.

        Returns:
            {탭이름: [{헤더이름: 값, _row: 시트 행번호 (1-indexed), _tab: 탭이름}, ...]}

        헤더 매핑 실패한 탭은 skip (warning logged).
        빈 시트는 빈 list 로.
        """
        result: dict[str, list[dict]] = {}
        for ws in self.spreadsheet.worksheets():
            if ws.title in SPECIAL_TABS:
                continue
            if tab_filter is not None and not tab_filter(ws.title):
                continue
            all_values = ws.get_all_values()
            if not all_values:
                result[ws.title] = []
                continue
            headers = all_values[0]
            try:
                mapping = map_headers_to_columns(headers)
            except ValueError as e:
                print(f"[WARN] tab '{ws.title}' header issue: {e}, skipping")
                continue
            rows = []
            for row_idx, row_values in enumerate(all_values[1:], start=2):
                row_dict: dict = {
                    h: row_values[i] if i < len(row_values) else ""
                    for h, i in mapping.items()
                }
                row_dict["_row"] = row_idx
                row_dict["_tab"] = ws.title
                rows.append(row_dict)
            result[ws.title] = rows
        return result


@dataclass
class RowUpdate:
    """한 행의 변경 사항. SheetsClient.write_results 가 batch 처리."""
    row: int  # 시트 행번호 (1-indexed, _row 메타에서 가져옴)
    columns: dict[str, str]  # {헤더이름: 새 값}


def rank_result_to_columns(
    block_order: list[str],
    exposure_area: str,
    integrated_rank: Optional[int],
    cafe_slot_rank: Optional[int],
    in_jisikin: bool,
) -> dict[str, str]:
    """RankResult → 사장님 시트 컬럼 dict 변환 (D-026 사장님 컨벤션 정합).

    D-026 사장님 컨벤션 (2026-05-16):
    - 노출영역: AB / 스마트블록 / 인기글 / 미노출 / 누락 / 삭제 / 실패
    - "미노출" = **명시 텍스트 표기** (= 빈 칸 X = 사장님 시점 "조사 안 됨" 혼동 회피)
    - L/M: 숫자 또는 빈 칸
    - 지식인탭: 'O' or 빈 칸

    D-023 (2026-05-14): new_link 매개변수 폐기 — 링크 컬럼 자동 갱신 절대 X.
    사장님 입력 컬럼 신성 (T-M14.2 사고 재발 방지).

    D-024 (2026-05-14): 유형(C) 컬럼 = 사장님 의도 기록 = 우리 자동 갱신 X (T-M13 학습 정합).
    block_order 매개변수 = 호출 측 호환성 유지 위해 시그너처 보존 (값 = 미사용).

    D-026 Phase B (2026-05-16): "미노출" 빈칸 처리 폐기 → 명시 표기.
    근거: 빈칸 = 사장님 시점 "아직 조사 안 됨" 혼동 = sheets.py:241 결함 root cause fix.
    """
    cols: dict[str, str] = {}
    # D-024 (2026-05-14): cols[HEADER_TYPE] 채움 폐기 — 유형(C) = 사장님 의도 기록 = 보호.
    # D-026 Phase B (2026-05-16): "미노출" 명시 표기 (= 빈 칸 X, 사장님 시점 명확화).
    cols[HEADER_AREA] = exposure_area
    cols[HEADER_L] = str(integrated_rank) if integrated_rank is not None else ""
    cols[HEADER_M] = str(cafe_slot_rank) if cafe_slot_rank is not None else ""
    cols[HEADER_JISIKIN] = "O" if in_jisikin else ""
    return cols


def map_headers_to_columns(
    headers: list[str],
    required: Optional[list[str]] = None,
) -> dict[str, int]:
    """1행 헤더 list → {헤더이름: 0-indexed 컬럼 위치} 매핑.

    spec D-004 결정: 사장님이 시트 열 이동/추가 가능 → 고정 위치 X, 헤더 이름 기반.

    Args:
        headers: 시트 1행의 셀 값 list (왼→오른쪽 순서).
        required: 반드시 있어야 하는 헤더 이름 list. 없으면 ValueError.

    Returns:
        {정규화 헤더: idx} dict. 정규화 = strip + 양 끝 공백 제거.

    Raises:
        ValueError: required 헤더가 누락된 경우. 메시지에 누락 헤더 명시.
    """
    mapping: dict[str, int] = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        normalized = str(h).strip()
        if not normalized:
            continue
        # 첫 등장만 사용 (중복 헤더 시 더 왼쪽 우선)
        if normalized not in mapping:
            mapping[normalized] = idx

    if required:
        missing = [r for r in required if r not in mapping]
        if missing:
            raise ValueError(
                f"필수 헤더 누락: {missing}. 시트 1행 확인 필요."
            )

    return mapping
