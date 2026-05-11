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
    retry 박지 X. 한 번 fail 박으면 데이터 손실 (사장님 시트 안 박힘).
    fix = 5s/10s/20s backoff + jitter. 총 마진 ~35초. 진짜 장기 장애면 cron 다음 schedule 박힘.
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
HEADER_TYPE = "유형"  # C — block_order[0] 만 (최상단 1위)
HEADER_AREA = "노출영역"  # K — AB / 인기글 / 삭제 / 빈칸(미노출)
HEADER_L = "노출여부(통합탭 순위)"  # L — integrated_rank
HEADER_M = "노출여부(카페구좌순위)"  # M — cafe_slot_rank
HEADER_JISIKIN = "지식인탭"  # O — 'O' or 빈칸

# 데이터 탭 아닌 특수 탭 — load_all_data_tabs 가 skip.
# 사장님 시트의 "카페매핑" 등 메타 탭 제외용.
SPECIAL_TABS = frozenset({"카페매핑", "_meta", "설정", "config"})


class SheetsClient:
    """Google Sheets 서비스 계정 인증 + spreadsheet 열기.

    M5.2~M5.5 에서 헤더 매핑/탭 순회/배치 write 메서드 추가됨.
    """

    def __init__(self, spreadsheet_id: str, service_account_json: str):
        # 2026-05-11 defensive: PowerShell pipe / Windows 메모장 등이 UTF-8 BOM 을 secret 에 박을 수 있음.
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
        """
        if not updates:
            return 0
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)

        cells = []
        for upd in updates:
            for col_name, new_val in upd.columns.items():
                if col_name not in mapping:
                    continue  # 사장님 시트에 없는 컬럼은 skip (예: blog_slot_rank)
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

        # 2026-05-12 T-M14: K="삭제" 박힌 셀 = 노란색 배경 (사장님 시각 ↑)
        # 사장님 명시: 마케터 시트 봤을 때 즉시 "삭제됐다" 인식.
        # K = "AB"/"인기글"/빈 박힌 셀 = 흰색 (reset) — 이전 박힌 노란색 정리.
        if HEADER_AREA in mapping:
            k_col = mapping[HEADER_AREA] + 1  # 1-indexed
            color_formats = []
            yellow = {"red": 1.0, "green": 1.0, "blue": 0.0}
            white = {"red": 1.0, "green": 1.0, "blue": 1.0}
            for upd in updates:
                if HEADER_AREA not in upd.columns:
                    continue
                k_value = upd.columns[HEADER_AREA]
                cell_range = gspread.utils.rowcol_to_a1(upd.row, k_col)
                bg = yellow if k_value == "삭제" else white
                color_formats.append({"range": cell_range, "format": {"backgroundColor": bg}})
            if color_formats:
                _sheets_api_retry(
                    lambda: ws.batch_format(color_formats),
                    ctx=f"{tab_name} (색상)",
                )
        return len(cells)

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
    """RankResult → 사장님 시트 컬럼 dict 변환 (사장님 컨벤션 정합).

    사장님 컨벤션 (2026-05-08):
    - 유형: block_order[0] 만 (최상단 1위)
    - 노출영역: AB / 인기글 / 삭제. UNEXPOSED 는 빈 칸.
    - L/M: 숫자 또는 빈 칸
    - 지식인탭: 'O' or 빈 칸
    """
    cols: dict[str, str] = {}
    cols[HEADER_TYPE] = block_order[0] if block_order else ""
    cols[HEADER_AREA] = exposure_area if exposure_area != "미노출" else ""
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
