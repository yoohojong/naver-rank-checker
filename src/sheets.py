"""sheets: Google Sheets I/O, 헤더 기반 매핑, 분야별 탭 순회."""
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

import gspread

from src.transitions import parse_K_with_stamp


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
HEADER_KEYWORD = "키워드"
HEADER_AREA = "노출영역"  # K — AB / 인기글 / 삭제 / 빈칸(미노출)
HEADER_L = "노출여부(통합탭 순위)"  # L — integrated_rank
HEADER_M = "노출여부(카페구좌순위)"  # M — cafe_slot_rank
HEADER_JISIKIN = "지식인탭"  # O — 'O' or 빈칸
HEADER_LINK = "링크"  # 사장님 입력 컬럼 (D-023 2026-05-14: 자동 갱신 절대 X — reference 용)
HEADER_CURRENT_INPUT_KEY = "현재입력키"
HEADER_LAST_CHECKED_INPUT_KEY = "마지막검사입력키"
HEADER_RAW_AREA = "raw_노출영역"
HEADER_RAW_L = "raw_통합순위"
HEADER_RAW_M = "raw_카페순위"
HEADER_RAW_JISIKIN = "raw_지식인탭"
HEADER_LAST_CHECKED_AT = "마지막검사시각"

STALE_DISPLAY_K = "재검사필요"
INPUT_KEY_VERSION = "v1"
STALE_FORMULA_HEADERS = (
    HEADER_CURRENT_INPUT_KEY,
    HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_RAW_AREA,
    HEADER_RAW_L,
    HEADER_RAW_M,
    HEADER_RAW_JISIKIN,
    HEADER_LAST_CHECKED_AT,
)
STALE_FORMULA_WRITE_COLUMNS = frozenset({
    HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_RAW_AREA,
    HEADER_RAW_L,
    HEADER_RAW_M,
    HEADER_RAW_JISIKIN,
    HEADER_LAST_CHECKED_AT,
})

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
PLAIN_EXPOSED_BASES = frozenset({"AB", "스마트블록", "인기글"})

# 데이터 탭 아닌 특수 탭 — load_all_data_tabs 가 skip.
# 사장님 시트의 "카페매핑" 등 메타 탭 제외용.
SPECIAL_TABS = frozenset({"카페매핑", "_meta", "설정", "config"})


def _column_letter(col_1based: int) -> str:
    return re.sub(r"\d+$", "", gspread.utils.rowcol_to_a1(1, col_1based))


def _normalize_input_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _normalize_input_link(value: object) -> str:
    # T-M9.1 (D-047, Codex Major 4): 시트 수식(현재입력키)과 동일 규칙 의무 —
    # 수식은 끝 슬래시만 제거하므로 Python 도 내부 슬래시 압축 없이 끝 슬래시만 제거.
    # (이전 내부 "/+" 압축은 수식과 어긋나 영구 키 불일치 = 영구 재검사필요 위험)
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^m\.", "", text)
    text = re.sub(r"[\?#].*$", "", text)
    return re.sub(r"/+$", "", text)


def _normalize_link_for_relocation(value: object) -> str:
    # T-M9.1 (D-047, Codex Major 3 + 사후 리뷰 Minor 2): 행 재배치용 링크 정규화.
    # - 호스트 = 항상 소문자 (대소문자 무관)
    # - naver.me 단축링크 경로 = 대소문자 구분이므로 보존 (서로 다른 글 충돌 방지)
    # - 일반 cafe URL 경로 = 수식 input_key 와 동일하게 대소문자 무시
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^m\.", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\?#].*$", "", text)
    text = re.sub(r"/+$", "", text)
    host, sep, path = text.partition("/")
    host = host.casefold()
    if host == "naver.me":
        return host + sep + path
    return host + sep + path.casefold()


def _relocation_identity(keyword: object, link: object) -> Optional[tuple[str, str]]:
    """T-M9.1 (D-047): write 직전 행 재탐색용 identity = (정규화 키워드, 대소문자 보존 링크)."""
    kw = _normalize_input_text(keyword)
    lk = _normalize_link_for_relocation(link)
    if not kw and not lk:
        return None
    return (kw, lk)


def _build_input_key_for_sheet(row: dict) -> str:
    keyword = _normalize_input_text(row.get(HEADER_KEYWORD, ""))
    link = _normalize_input_link(row.get(HEADER_LINK, ""))
    if not keyword and not link:
        return ""
    return f"{INPUT_KEY_VERSION}|{keyword}|{link}"


COLOR_NONE = {"red": 1.0, "green": 1.0, "blue": 1.0}
COLOR_EXPOSED = {"red": 0.8, "green": 1.0, "blue": 0.8}
COLOR_NEGATIVE = {"red": 1.0, "green": 0.8, "blue": 0.8}
COLOR_RECHECK = {"red": 1.0, "green": 0.85, "blue": 0.4}
EXPOSED_COLOR_PREFIXES = ("AB", "스마트블록", "인기글", "중복노출")
NEGATIVE_COLOR_PREFIXES = ("미노출", "누락", "삭제")
EXPOSURE_RESULT_ALIGNMENT_HEADERS = (HEADER_L, HEADER_M)
EXPOSURE_RESULT_ALIGNMENT_FORMAT = {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"}


def _background_color_for_k(k_value: str) -> dict:
    if not k_value:
        return COLOR_NONE
    s = str(k_value or "").strip()
    if s.startswith(EXPOSED_COLOR_PREFIXES):
        return COLOR_EXPOSED
    if s.startswith(NEGATIVE_COLOR_PREFIXES):
        return COLOR_NEGATIVE
    if s.startswith(STALE_DISPLAY_K):
        return COLOR_RECHECK
    return COLOR_NONE


def _exposure_result_alignment_formats(mapping: dict, rows) -> list[dict]:
    formats = []
    seen_rows = set()
    for row in rows:
        if row in seen_rows:
            continue
        seen_rows.add(row)
        for header in EXPOSURE_RESULT_ALIGNMENT_HEADERS:
            if header not in mapping:
                continue
            formats.append({
                "range": gspread.utils.rowcol_to_a1(row, mapping[header] + 1),
                "format": dict(EXPOSURE_RESULT_ALIGNMENT_FORMAT),
            })
    return formats


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

    def _build_current_input_key_formula(self, mapping: dict[str, int], row: int) -> str:
        keyword_ref = gspread.utils.rowcol_to_a1(row, mapping[HEADER_KEYWORD] + 1)
        link_ref = gspread.utils.rowcol_to_a1(row, mapping[HEADER_LINK] + 1)
        return (
            f'=IF(AND(LEN(TRIM({keyword_ref}))=0,LEN(TRIM({link_ref}))=0),"",'
            f'"{INPUT_KEY_VERSION}|"&LOWER(REGEXREPLACE(TRIM({keyword_ref}),"\\s+"," "))&"|"&'
            f'LOWER(REGEXREPLACE(REGEXREPLACE(REGEXREPLACE(REGEXREPLACE(TRIM({link_ref}),'
            f'"^https?://",""),"^m\\.",""),"[\\?#].*$",""),"/+$","")))'
        )

    def _build_visible_output_formula(self, mapping: dict[str, int], row: int, raw_header: str, *, k_column: bool = False) -> str:
        current_ref = gspread.utils.rowcol_to_a1(row, mapping[HEADER_CURRENT_INPUT_KEY] + 1)
        last_ref = gspread.utils.rowcol_to_a1(row, mapping[HEADER_LAST_CHECKED_INPUT_KEY] + 1)
        raw_ref = gspread.utils.rowcol_to_a1(row, mapping[raw_header] + 1)
        if k_column:
            system_k_pattern = r"^(AB|스마트블록|인기글|미노출|누락|삭제|실패|중복노출)( \(|$)"
            return (
                f'=IF(LEN({current_ref})=0,'
                f'IF(AND(LEN({raw_ref})>0,NOT(REGEXMATCH({raw_ref},"{system_k_pattern}"))),{raw_ref},""),'
                f'IF({current_ref}={last_ref},{raw_ref},"{STALE_DISPLAY_K}"))'
            )
        return f'=IF(AND(LEN({current_ref})>0,{current_ref}={last_ref}),{raw_ref},"")'

    def ensure_stale_formula_mode(self, tab_name: str, rows: list[dict]) -> dict:
        """Ensure hidden raw/input-key columns and visible K/L/M/O formulas exist."""
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)
        required_for_formula = [HEADER_KEYWORD, HEADER_LINK, HEADER_AREA, HEADER_L, HEADER_M]
        missing_required = [header for header in required_for_formula if header not in mapping]
        if missing_required:
            print(f"  [STALE-FORMULA] {tab_name}: required headers missing {missing_required}, skip")
            return {"headers_added": 0, "rows_backfilled": 0, "formula_rows": 0}

        missing_headers = [header for header in STALE_FORMULA_HEADERS if header not in mapping]
        if missing_headers:
            try:
                col_count = int(getattr(ws, "col_count", len(headers)) or len(headers))
            except (TypeError, ValueError):
                col_count = len(headers)
            append_start_col = max(len(headers) + 1, 17)  # keep P1 reserved for timestamp
            needed_cols = max(0, append_start_col + len(missing_headers) - 1 - col_count)
            if needed_cols:
                _sheets_api_retry(lambda: ws.add_cols(needed_cols), ctx=f"{tab_name} (stale formula add cols)")
            header_cells = [
                {
                    "range": gspread.utils.rowcol_to_a1(1, append_start_col + offset - 1),
                    "values": [[header]],
                }
                for offset, header in enumerate(missing_headers, start=1)
            ]
            _sheets_api_retry(
                lambda: ws.batch_update(header_cells, value_input_option="RAW"),
                ctx=f"{tab_name} (stale formula headers)",
            )
            expanded_headers = list(headers)
            while len(expanded_headers) < append_start_col - 1:
                expanded_headers.append("")
            expanded_headers.extend(missing_headers)
            headers = expanded_headers
            mapping = map_headers_to_columns(headers)

        rows = list(rows)
        max_row = max([int(row.get("_row") or 0) for row in rows] + [1])
        rows_backfilled = 0
        if missing_headers and rows:
            backfill_cells = []
            newly_created_headers = set(missing_headers)
            for row in rows:
                row_num = int(row.get("_row") or 0)
                if row_num < 2:
                    continue
                values_by_header = {
                    HEADER_LAST_CHECKED_INPUT_KEY: _build_input_key_for_sheet(row),
                    HEADER_RAW_AREA: str(row.get(HEADER_AREA, "") or ""),
                    HEADER_RAW_L: str(row.get(HEADER_L, "") or ""),
                    HEADER_RAW_M: str(row.get(HEADER_M, "") or ""),
                    HEADER_RAW_JISIKIN: str(row.get(HEADER_JISIKIN, "") or ""),
                    HEADER_LAST_CHECKED_AT: "migration",
                }
                for header, value in values_by_header.items():
                    if header not in newly_created_headers:
                        continue
                    backfill_cells.append({
                        "range": gspread.utils.rowcol_to_a1(row_num, mapping[header] + 1),
                        "values": [[value]],
                    })
                rows_backfilled += 1
            if backfill_cells:
                _sheets_api_retry(
                    lambda: ws.batch_update(backfill_cells, value_input_option="RAW"),
                    ctx=f"{tab_name} (stale formula backfill)",
                )

        if max_row >= 2:
            formula_ranges = []
            formula_specs = [
                (HEADER_CURRENT_INPUT_KEY, None, False),
                (HEADER_AREA, HEADER_RAW_AREA, True),
                (HEADER_L, HEADER_RAW_L, False),
                (HEADER_M, HEADER_RAW_M, False),
            ]
            if HEADER_JISIKIN in mapping:
                formula_specs.append((HEADER_JISIKIN, HEADER_RAW_JISIKIN, False))
            for target_header, raw_header, is_k in formula_specs:
                col = mapping[target_header] + 1
                col_letter = _column_letter(col)
                values = []
                for row_num in range(2, max_row + 1):
                    formula = (
                        self._build_current_input_key_formula(mapping, row_num)
                        if target_header == HEADER_CURRENT_INPUT_KEY
                        else self._build_visible_output_formula(mapping, row_num, raw_header, k_column=is_k)
                    )
                    values.append([formula])
                formula_ranges.append({"range": f"{col_letter}2:{col_letter}{max_row}", "values": values})
            _sheets_api_retry(
                lambda: ws.batch_update(formula_ranges, value_input_option="USER_ENTERED"),
                ctx=f"{tab_name} (stale formula visible formulas)",
            )

        hide_requests = []
        for header in STALE_FORMULA_HEADERS:
            if header not in mapping:
                continue
            idx = mapping[header]
            hide_requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"hiddenByUser": True},
                    "fields": "hiddenByUser",
                }
            })
        if hide_requests:
            _sheets_api_retry(
                lambda: self.spreadsheet.batch_update({"requests": hide_requests}),
                ctx=f"{tab_name} (stale formula hide columns)",
            )
        return {"headers_added": len(missing_headers), "rows_backfilled": rows_backfilled, "formula_rows": max(0, max_row - 1)}

    def write_stale_formula_results(
        self,
        tab_name: str,
        updates: list["RowUpdate"],
        *,
        row_context: dict,
        checked_at: str,
        stats_out: Optional[dict] = None,
    ) -> int:
        """Write cron outputs to hidden raw columns for formula-mode sheets.

        T-M9.1 (2026-06-12, D-047): 행 번호가 아니라 write 직전 시트 re-read 에서
        (키워드, 링크) identity 로 행을 다시 찾아 기록 — 검사 도중 행 삽입/삭제/정렬 면역.
        - 같은 identity 행 여러 개 = 같은 검색 결과 = 전부 갱신 (fan-out).
        - 같은 identity 의 update payload 가 서로 다름 = 충돌 = 그 identity 보류 (Codex Critical 1).
        - identity 미발견 = skip + log (입력이 도중 변경/삭제 = 다음 cron 자연 재검사, D-041 의미 유지).
        - re-read 실패 = 종전 행 번호 기준 write (가드 불가 시 기존 보수 경로 유지).
        - 잔여 TOCTOU (re-read ~ batch_update 사이 편집) = 창이 70분 → 수 초로 축소될 뿐
          0 은 아님 (Codex Major 2) — post-write audit + 다음 cron 재검사가 최후 방어선.
        """
        if not updates:
            return 0
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)

        stats = stats_out if stats_out is not None else {}
        stats.setdefault("relocation_miss_rows", 0)
        stats.setdefault("relocation_conflict_keys", 0)
        stats.setdefault("relocation_fanout_rows", 0)

        sheet_rows: Optional[list[list[str]]] = None
        sheet_read_ok = False
        if HEADER_LINK in mapping and HEADER_KEYWORD in mapping:
            try:
                sheet_rows = _sheets_api_retry(lambda: ws.get_all_values(), ctx=f"{tab_name} (stale formula relocation read)")
                if isinstance(sheet_rows, list):
                    sheet_read_ok = True
            except Exception as e:
                print(f"  [STALE-FORMULA-RELOCATION-READ-FAIL] {tab_name}: {e} — 행 번호 기준 write 진행")

        kw_idx = mapping.get(HEADER_KEYWORD)
        link_idx = mapping.get(HEADER_LINK)

        def _cell(row_values, idx) -> str:
            if idx is None or not isinstance(row_values, list) or idx >= len(row_values):
                return ""
            return str(row_values[idx] or "")

        # write 직전 시트의 identity → 행 번호 목록 (재배치 index)
        identity_to_rows: dict[tuple[str, str], list[int]] = {}
        if sheet_read_ok and sheet_rows:
            for row_num, row_values in enumerate(sheet_rows[1:], start=2):
                identity = _relocation_identity(_cell(row_values, kw_idx), _cell(row_values, link_idx))
                if identity is None:
                    continue
                identity_to_rows.setdefault(identity, []).append(row_num)

        def _row_current_link(row_1based: int) -> str:
            if not sheet_read_ok or sheet_rows is None:
                return "SENTINEL"
            row_idx = row_1based - 1
            if 0 <= row_idx < len(sheet_rows):
                return _cell(sheet_rows[row_idx], link_idx).strip()
            return ""

        def _row_identity_matches(row_1based: int, identity: tuple[str, str]) -> bool:
            # 위치 fallback 용 D-047 동시편집 면역: 측정된 원본 행(upd.row)의 재read identity 가
            # 측정 당시 identity 와 같을 때만 그 위치에 기록. 다르면(=검사 도중 사장님이 그 행 변경)
            # skip → 다음 cron 자연 재검사 (relocation MISS 와 동일 의미).
            if not sheet_read_ok or sheet_rows is None:
                return False
            row_idx = row_1based - 1
            if not (0 <= row_idx < len(sheet_rows)):
                return False
            current = _relocation_identity(
                _cell(sheet_rows[row_idx], kw_idx), _cell(sheet_rows[row_idx], link_idx)
            )
            return current == identity

        # 1차: update 별 payload 계산 + identity 재배치 + 충돌 검출 (Codex Critical 1)
        planned: dict[tuple[str, str], dict] = {}
        conflicted: set = set()
        legacy_writes: list[tuple[int, dict, str]] = []  # re-read 실패 시 (행, payload, output_link)
        # 만성버그 fix (2026-06-18): identity 충돌/모호로 fan-out 매칭이 보류될 때,
        # 각 측정 행(upd.row)을 자기 위치에 1:1 로 닫는다 (위치 fallback).
        # link 자동 채움은 모호하므로 하지 않고(output_link=""), 숨김 baseline 만 자기 위치에 기록.
        # re-read 에서 그 행의 identity 가 측정 당시와 같을 때만 기록(D-047 동시편집 면역 보존).
        positional_writes: list[tuple[int, dict, tuple[str, str]]] = []  # (행, payload, 측정당시 identity)
        for upd in updates:
            source_row = row_context.get(upd.row) or row_context.get((tab_name, upd.row)) or {"_row": upd.row, "_tab": tab_name}
            source_link = str(source_row.get(HEADER_LINK, "") or "").strip()
            output_link = str(upd.columns.get(HEADER_LINK, "") or "").strip()
            effective_row = dict(source_row)
            if output_link:
                effective_row[HEADER_LINK] = output_link
            payload = {
                HEADER_LAST_CHECKED_INPUT_KEY: _build_input_key_for_sheet(effective_row),
                HEADER_RAW_AREA: str(upd.columns.get(HEADER_AREA, "") or ""),
                HEADER_RAW_L: str(upd.columns.get(HEADER_L, "") or ""),
                HEADER_RAW_M: str(upd.columns.get(HEADER_M, "") or ""),
                HEADER_RAW_JISIKIN: str(upd.columns.get(HEADER_JISIKIN, "") or ""),
                HEADER_LAST_CHECKED_AT: checked_at,
            }
            if not sheet_read_ok:
                legacy_writes.append((upd.row, payload, output_link))
                continue

            source_keyword = str(source_row.get(HEADER_KEYWORD, "") or "")
            identity = _relocation_identity(source_keyword, source_link)
            if not source_link:
                # 빈 link 행 (Codex 사후 리뷰 Major 1): link 자동 채움 fan-out 금지.
                # 1순위 = output_link 로 이미 채워진 행 (write 전에 link 가 채워진 경우)
                # 2순위 = 빈 link + 같은 키워드 행이 정확히 1개일 때만 (다수 = 모호 = 보류)
                targets: list = []
                if output_link:
                    alt_identity = _relocation_identity(source_keyword, output_link)
                    if alt_identity:
                        filled_targets = list(identity_to_rows.get(alt_identity, []))
                        if filled_targets:
                            identity, targets = alt_identity, filled_targets
                if not targets and identity:
                    blank_targets = list(identity_to_rows.get(identity, []))
                    if len(blank_targets) > 1:
                        # 빈 link 동일 키워드 다수 = link 자동 채움은 모호 = 보류(D-026 fan-out 금지).
                        # 그러나 각 측정 행(upd.row)의 숨김 baseline 은 자기 위치에 닫는다 (영구 재검사필요 해소).
                        stats["relocation_conflict_keys"] += 1
                        print(
                            f"  [STALE-FORMULA-RELOCATION-AMBIGUOUS] row {upd.row} "
                            f"빈 link 동일 키워드 행 {len(blank_targets)}개 = link 자동채움 보류, "
                            f"숨김 baseline 만 자기 위치 기록"
                        )
                        positional_writes.append((upd.row, payload, identity))
                        continue
                    targets = blank_targets
            else:
                targets = list(identity_to_rows.get(identity, [])) if identity else []
            if identity is None or not targets:
                stats["relocation_miss_rows"] += 1
                print(
                    f"  [STALE-FORMULA-RELOCATION-MISS] row {upd.row} skip raw write "
                    f"(입력 변경/삭제 감지 — 다음 cron 재검사)"
                )
                continue
            if identity in conflicted:
                # 이미 충돌로 전환된 identity = 각 측정 행을 자기 위치에 1:1 로 닫는다.
                positional_writes.append((upd.row, payload, identity))
                continue
            existing = planned.get(identity)
            if existing is not None:
                if existing["payload"] != payload:
                    # 같은 identity 인데 측정 payload 가 다름 = 서로 다른 행이 각자 독립 측정됨
                    # (fan-out 전파가 아님). fan-out 매칭을 취소하고 각 측정 행을 자기 위치에 닫는다.
                    conflicted.add(identity)
                    dropped = planned.pop(identity, None)
                    stats["relocation_conflict_keys"] += 1
                    print(
                        f"  [STALE-FORMULA-RELOCATION-CONFLICT] identity 충돌 = "
                        f"각 측정 행 자기 위치 기록 "
                        f"(rows {dropped['source_rows'] if dropped else '?'} vs {upd.row})"
                    )
                    # 이미 planned 였던 측정 행들 + 현재 upd.row = 전부 위치 fallback 으로 이관.
                    if dropped is not None:
                        for src_row in dropped["source_rows"]:
                            positional_writes.append((src_row, dropped["payload"], identity))
                    positional_writes.append((upd.row, payload, identity))
                else:
                    existing["source_rows"].append(upd.row)
                continue
            planned[identity] = {
                "payload": payload,
                "output_link": output_link,
                "targets": targets,
                "source_rows": [upd.row],
            }

        cells = []
        color_formats = []
        alignment_rows = []

        def _emit(target_row: int, payload: dict, output_link: str) -> None:
            current_link = _row_current_link(target_row)
            columns = dict(payload)
            if output_link and current_link != "SENTINEL" and not current_link:
                columns[HEADER_LINK] = output_link
            for col_name, new_val in columns.items():
                if col_name == HEADER_LINK:
                    if current_link:
                        print(f"  [STALE-FORMULA-LINK-GUARD] '{col_name}' write 거부 (row {target_row}, 현재 link 비어있지 않음)")
                        continue
                elif col_name not in STALE_FORMULA_WRITE_COLUMNS:
                    print(f"  [STALE-FORMULA-GUARD] '{col_name}' write 거부 (row {target_row})")
                    continue
                if col_name not in mapping:
                    continue
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(target_row, mapping[col_name] + 1),
                    "values": [[new_val]],
                })
            if HEADER_AREA in mapping:
                color_formats.append({
                    "range": gspread.utils.rowcol_to_a1(target_row, mapping[HEADER_AREA] + 1),
                    "format": {"backgroundColor": _background_color_for_k(payload.get(HEADER_RAW_AREA, ""))},
                })
            alignment_rows.append(target_row)

        for plan in planned.values():
            stats["relocation_fanout_rows"] += max(0, len(plan["targets"]) - len(plan["source_rows"]))
            for target_row in plan["targets"]:
                _emit(target_row, plan["payload"], plan["output_link"])
        for row_num, payload, output_link in legacy_writes:
            _emit(row_num, payload, output_link)
        # 위치 fallback: 충돌/모호로 fan-out 매칭이 보류된 각 측정 행을 자기 위치에 1:1 기록.
        # D-047 동시편집 면역: 재read 에서 그 행 identity 가 측정 당시와 같을 때만 기록.
        # output_link="" (link 자동 채움 안 함 = D-023/링크가드 정합). 같은 행 중복 기록 방지.
        positional_emitted: set = set()
        for row_num, payload, identity in positional_writes:
            if row_num in positional_emitted:
                continue
            if not _row_identity_matches(row_num, identity):
                stats["relocation_miss_rows"] += 1
                print(
                    f"  [STALE-FORMULA-POSITIONAL-MISS] row {row_num} skip "
                    f"(재read identity 불일치 = 검사 도중 입력 변경 — 다음 cron 재검사)"
                )
                continue
            positional_emitted.add(row_num)
            _emit(row_num, payload, "")

        # Codex Major 7: fan-out 시 payload 폭증 대비 — 셀 500개 단위 청크
        for chunk_start in range(0, len(cells), 500):
            chunk = cells[chunk_start:chunk_start + 500]
            _sheets_api_retry(lambda c=chunk: ws.batch_update(c, value_input_option="RAW"), ctx=f"{tab_name} (stale formula raw write)")
        format_payload = color_formats + _exposure_result_alignment_formats(mapping, alignment_rows)
        for chunk_start in range(0, len(format_payload), 500):
            chunk = format_payload[chunk_start:chunk_start + 500]
            _sheets_api_retry(lambda c=chunk: ws.batch_format(c), ctx=f"{tab_name} (stale formula formats)")
        return len(cells)

    def clear_stale_formula_cells(self, tab_name: str, row_numbers: list[int]) -> int:
        """T-M9.2 (2026-06-12, D-047): 행 복사 잔해 행의 숨김 시스템 칸만 초기화.

        대상 = STALE_FORMULA_WRITE_COLUMNS (마지막검사입력키 / raw_* / 마지막검사시각).
        사장님 입력 컬럼(A~J/N)과 보이는 K/L/M/O 수식은 건드리지 않는다 (D-023 정합).
        초기화 후 해당 행은 "검사한 적 없는 행"으로 취급되어 같은 run 에서 정상 재검사된다.
        """
        if not row_numbers:
            return 0
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)
        cells = []
        for row_num in sorted({int(r) for r in row_numbers if int(r) >= 2}):
            for col_name in sorted(STALE_FORMULA_WRITE_COLUMNS):
                if col_name not in mapping:
                    continue
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(row_num, mapping[col_name] + 1),
                    "values": [[""]],
                })
        for chunk_start in range(0, len(cells), 500):
            chunk = cells[chunk_start:chunk_start + 500]
            _sheets_api_retry(lambda c=chunk: ws.batch_update(c, value_input_option="RAW"), ctx=f"{tab_name} (stale formula ghost clear)")
        return len(cells)

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
        link_rows: Optional[list[list[str]]] = None
        link_read_ok = False
        if HEADER_LINK in mapping:
            try:
                link_rows = _sheets_api_retry(
                    lambda: ws.get_all_values(),
                    ctx=f"{tab_name} (link read)",
                )
                # 정상 list 인지 검증 (= mock MagicMock 등 비정상 객체 = read 실패 간주)
                if isinstance(link_rows, list):
                    link_read_ok = True
            except Exception as e:
                # link read 실패 시 = 보수적 = 전부 SYSTEM_OUTPUT_COLUMNS 적용 (D-023 가드)
                print(f"  [D-026-LINK-READ-FAIL] {tab_name}: {e} — SYSTEM_OUTPUT_COLUMNS 적용 (보수)")

        def _row_current_link(row_1based: int) -> str:
            """row_1based 의 현재 link 값. read 실패 / row 범위 외 = "non-empty" 보수 가정 ('SENTINEL')."""
            # read 실패 = 보수적 = "SENTINEL" 반환 (= 엄격 가드 적용)
            if not link_read_ok or link_rows is None:
                return "SENTINEL"
            row_idx = row_1based - 1  # sheet rows are 1-indexed
            link_idx = mapping[HEADER_LINK]
            if 0 <= row_idx < len(link_rows):
                row_values = link_rows[row_idx]
                if not isinstance(row_values, list):
                    return "SENTINEL"
                if link_idx < len(row_values):
                    return (row_values[link_idx] or "").strip()
                return ""
            # row 범위 외 = 보수적 = "SENTINEL" 반환
            return "SENTINEL"

        cells = []
        color_updates = []
        alignment_rows = []
        for upd in updates:
            # D-026 Phase C+D (2026-05-16): 행 현재 link 값 read → 빈 link 행만 EMPTY_LINK 화이트리스트 사용
            current_link = _row_current_link(upd.row)
            use_columns = SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK if not current_link else SYSTEM_OUTPUT_COLUMNS
            if not current_link:
                k_base, _ = parse_K_with_stamp((upd.columns.get(HEADER_AREA) or "").strip())
                has_rank = bool(upd.columns.get(HEADER_L) or upd.columns.get(HEADER_M))
                has_output_link = bool((upd.columns.get(HEADER_LINK) or "").strip())
                invalid_plain_exposed = k_base in PLAIN_EXPOSED_BASES
                invalid_rank_without_duplicate = has_rank and not k_base.startswith("중복노출")
                invalid_duplicate_without_link = k_base.startswith("중복노출") and not has_output_link
                if invalid_plain_exposed or invalid_rank_without_duplicate or invalid_duplicate_without_link:
                    print(
                        f"  [D-032-INVARIANT-GUARD] row={upd.row} write 거부 "
                        f"(빈 link + K={upd.columns.get(HEADER_AREA)!r}, L={upd.columns.get(HEADER_L)!r}, "
                        f"M={upd.columns.get(HEADER_M)!r}, output_link={upd.columns.get(HEADER_LINK)!r})"
                    )
                    continue
            row_cell_count_before = len(cells)
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
            if len(cells) > row_cell_count_before:
                color_updates.append(upd)
                if HEADER_AREA in upd.columns or HEADER_L in upd.columns or HEADER_M in upd.columns:
                    alignment_rows.append(upd.row)
        if cells:
            # 2026-05-12 T-M11: 503/5xx retry (document-specialist gspread default retry X).
            _sheets_api_retry(
                lambda: ws.batch_update(cells, value_input_option="RAW"),
                ctx=tab_name,
            )

        # D-043 (2026-05-23): 노출 상태는 초록, 미노출/누락/삭제는 같은 붉은색,
        # 빈 값/실패/수동 메모는 무색. 시점이 포함된 K 값도 base prefix 로 매핑.
        format_payload = []
        if HEADER_AREA in mapping:
            k_col = mapping[HEADER_AREA] + 1  # 1-indexed

            for upd in color_updates:
                if HEADER_AREA not in upd.columns:
                    continue
                k_value = upd.columns[HEADER_AREA]
                cell_range = gspread.utils.rowcol_to_a1(upd.row, k_col)
                bg = _background_color_for_k(k_value)
                format_payload.append({"range": cell_range, "format": {"backgroundColor": bg}})
        format_payload.extend(_exposure_result_alignment_formats(mapping, alignment_rows))
        if format_payload:
            _sheets_api_retry(
                lambda: ws.batch_format(format_payload),
                ctx=f"{tab_name} (format)",
            )
        return len(cells)

    def write_type_results(self, tab_name: str, updates: list["RowUpdate"]) -> int:
        """Write confirmed type-preview rows to the C column only.

        This deliberately does not relax write_results(). The general output
        writer still rejects HEADER_TYPE; C writes are allowed only through this
        explicit preview-confirmation path.
        """
        if not updates:
            return 0
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)
        if HEADER_TYPE not in mapping:
            print(f"  [TYPE-WRITE] {tab_name}: HEADER_TYPE column missing, skip")
            return 0

        type_col = mapping[HEADER_TYPE] + 1
        cells = []
        for upd in updates:
            for col_name, new_val in upd.columns.items():
                if col_name != HEADER_TYPE:
                    print(f"  [TYPE-WRITE-GUARD] '{col_name}' write 거부 (row {upd.row})")
                    continue
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(upd.row, type_col),
                    "values": [[new_val]],
                })

        if cells:
            _sheets_api_retry(
                lambda: ws.batch_update(cells, value_input_option="RAW"),
                ctx=f"{tab_name} (type write)",
            )
        return len(cells)

    def write_timestamp(self, tab_name: str, kst_iso: str) -> None:
        """⚠️ DEPRECATED·미사용 (D-058): 호출 금지.

        T-M37 가정("1행 16열 = 헤더 영역 밖")이 사장님 실제 시트에선 틀림 — 16열 = 지식인탭.
        매 cron 이 지식인 헤더를 'cron 갱신: 날짜'로 덮어써 '지식인 0개' 오답을 유발했음.
        신선도는 텔레그램 보고 + 마지막검사시각으로 충분 → main.py 호출 제거됨. 재활성화 금지.
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

    def read_tab_records(self, tab_name: str) -> list[dict]:
        """스테이징 탭 1개를 [{헤더이름: 값, _row: 행번호}] 로 read.

        탭이 없으면 빈 list (= 아직 안 만들어짐 = 적재 전 정상 상태).
        헤더 매핑 실패(빈 탭 등) 시에도 빈 list.

        C3 (수집결과_지식인 / 수집결과_리뷰) 중복방지용 — 기존 행을 읽어
        같은 키워드+수집일이 이미 적재됐는지 확인한다.
        """
        try:
            ws = self.spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            return []
        all_values = _sheets_api_retry(lambda: ws.get_all_values(), ctx=f"{tab_name} (read records)")
        if not all_values:
            return []
        headers = all_values[0]
        try:
            mapping = map_headers_to_columns(headers)
        except ValueError:
            return []
        records: list[dict] = []
        for row_idx, row_values in enumerate(all_values[1:], start=2):
            rec = {h: (row_values[i] if i < len(row_values) else "") for h, i in mapping.items()}
            rec["_row"] = row_idx
            records.append(rec)
        return records

    def append_staging_rows(
        self,
        tab_name: str,
        header: list[str],
        rows: list[list],
    ) -> int:
        """스테이징 탭에 행을 append. 탭/헤더 없으면 자동 생성.

        C3 적재용 — 수집 코어(지식인/리뷰) 결과를 고정 스키마로 시트에 쌓는다.
        사장님 입력 탭(카외)이 아니라 **수집 전용 탭**이라 자유롭게 행 추가 가능.

        Args:
            tab_name: 대상 스테이징 탭 이름 (예: '수집결과_지식인').
            header: 고정 헤더 list (탭/헤더가 없을 때만 1행에 기록).
            rows: append 할 행들 (각 행 = header 와 같은 길이의 값 list).

        Returns:
            실제 append 한 행 수.
        """
        if not rows:
            return 0
        try:
            ws = self.spreadsheet.worksheet(tab_name)
            existing = _sheets_api_retry(lambda: ws.row_values(1), ctx=f"{tab_name} (header check)")
            if not existing:
                # 탭은 있는데 헤더가 비었음 → 헤더부터 기록.
                _sheets_api_retry(
                    lambda: ws.update("A1", [header], value_input_option="RAW"),
                    ctx=f"{tab_name} (header write)",
                )
        except gspread.exceptions.WorksheetNotFound:
            ws = _sheets_api_retry(
                lambda: self.spreadsheet.add_worksheet(
                    title=tab_name, rows=1000, cols=max(len(header), 7)
                ),
                ctx=f"{tab_name} (create tab)",
            )
            _sheets_api_retry(
                lambda: ws.update("A1", [header], value_input_option="RAW"),
                ctx=f"{tab_name} (header write)",
            )
        _sheets_api_retry(
            lambda: ws.append_rows(rows, value_input_option="RAW"),
            ctx=f"{tab_name} (append {len(rows)} rows)",
        )
        return len(rows)


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
