"""archive: 상위노출 실적 일별 아카이빙 (검증판 · OFF 기본).

목적:
- 매 cron 이 시트에서 읽어온 data(탭별 행) 를 하루 1벌 스냅샷으로 **비공개 구글시트 탭**에 남긴다.
- 공개(PUBLIC) GitHub repo 라 데이터를 repo 에 커밋하지 않는다 → 아카이브는 시트에만.
- 순위/노출 상태의 날짜별 시계열이 쌓이면 "언제 올랐다 빠졌나" 사후 추적이 가능해진다.

설계 정합:
- build_archive_rows = 순수함수(gspread 의존 0) → 테스트/드라이런 용이.
- k_base_of/rank_of 는 snapshot_diff 의 검증된 헬퍼 재사용(raw 우선). 인자로 주입 가능.
- 시트 I/O(append_daily_archive)는 SheetsClient 를 통해서만. 로컬엔 서비스계정 키가 없어
  라이브 시트 R/W 는 못 하므로, I/O 는 fake client 로 테스트 가능하게 방어적으로 짠다.
- 날짜별 멱등: 하루 4번 cron 이 돌아도 그날 1벌만 남게(같은 date_str 블록만 지우고 새로 append).
  다른 날짜 데이터는 절대 안 건드린다.
"""
from __future__ import annotations

import gspread

from src.sheets import HEADER_KEYWORD
from src.snapshot_diff import k_base_of as _default_k_base_of
from src.snapshot_diff import rank_of as _default_rank_of

# 아카이브 탭 스키마 (고정). 날짜/탭/키워드/노출영역/통합순위.
ARCHIVE_HEADER = ["날짜", "탭", "키워드", "노출영역", "통합순위"]
ARCHIVE_TAB_NAME = "상위노출_이력"


def build_archive_rows(
    tabs: dict,
    date_str: str,
    *,
    k_base_of=_default_k_base_of,
    rank_of=_default_rank_of,
) -> list[list]:
    """탭별 행 dict → 시트 append 용 2D 리스트(헤더 제외) · 순수함수.

    각 탭·각 행마다 [date_str, tab_name, 키워드, 노출영역(k_base), 통합순위] 생성.

    Args:
        tabs: {탭이름: [row_dict, ...]}. row_dict = 헤더명 키(백업/시트 read 형식 동일).
        date_str: 아카이브 날짜 문자열(예 "2026-07-02"). 모든 행 1열.
        k_base_of: 행 → 노출영역 base 추출 함수(기본 snapshot_diff, 테스트서 교체 가능).
        rank_of: 행 → 통합순위 int/None 추출 함수(기본 snapshot_diff).

    Returns:
        2D 리스트. 각 행 = [date_str, tab_name, keyword, area, rank_str].
        - 키워드 공백/빈칸 행은 스킵(작업자 미기입 행 = 아카이브 의미 없음).
        - rank None → 빈 문자열 "".
    """
    out: list[list] = []
    for tab_name, rows in (tabs or {}).items():
        for row in rows or []:
            keyword = str(row.get(HEADER_KEYWORD, "") or "").strip()
            if not keyword:
                continue  # 빈 키워드 = 스킵
            area = k_base_of(row)
            rank = rank_of(row)
            rank_str = "" if rank is None else str(rank)
            out.append([date_str, tab_name, keyword, area, rank_str])
    return out


def _get_or_create_archive_ws(client, tab_name: str):
    """아카이브 탭 get-or-create. 없으면 생성 + 헤더행 기입.

    Returns:
        (worksheet, created: bool)
    """
    spreadsheet = client.spreadsheet
    try:
        ws = spreadsheet.worksheet(tab_name)
        # 탭은 있는데 헤더가 비었으면 헤더부터 기록(방어적).
        existing = ws.row_values(1)
        if not existing:
            ws.update("A1", [ARCHIVE_HEADER], value_input_option="RAW")
        return ws, False
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=tab_name, rows=1000, cols=max(len(ARCHIVE_HEADER), 5)
        )
        ws.update("A1", [ARCHIVE_HEADER], value_input_option="RAW")
        return ws, True


def _delete_date_block(ws, date_str: str) -> int:
    """아카이브 탭에서 date_str(1열) 이 일치하는 행만 삭제(멱등용).

    다른 날짜 행은 절대 건드리지 않는다. 헤더행(1행)도 보존.
    행 삭제로 번호가 밀리는 문제를 피하려 **아래→위** 순으로 지운다.

    Returns:
        삭제한 행 수.
    """
    all_values = ws.get_all_values()
    if not all_values:
        return 0
    # 1행 = 헤더. 2행부터 검사. 1열(날짜) 이 date_str 인 행만 대상.
    target_rows = [
        row_num
        for row_num, row_values in enumerate(all_values[1:], start=2)
        if row_values and str(row_values[0]).strip() == str(date_str).strip()
    ]
    if not target_rows:
        return 0
    for row_num in sorted(target_rows, reverse=True):
        ws.delete_rows(row_num)
    return len(target_rows)


def append_daily_archive(
    client,
    rows: list[list],
    date_str: str,
    *,
    tab_name: str = ARCHIVE_TAB_NAME,
) -> dict:
    """일별 아카이브 행을 비공개 시트 탭에 멱등 append.

    - 아카이브 탭 get-or-create(없으면 생성 + 헤더).
    - 날짜별 멱등: 같은 date_str 블록이 이미 있으면 그 블록만 지우고 새로 append.
      하루 4번 cron 이 돌아도 그날 1벌만 남는다(다른 날짜는 보존).
    - 실패해도 예외를 위로 던지지 않는다(안전 처리). 호출부도 try/except 로 격리.

    Args:
        client: SheetsClient(.spreadsheet 에 gspread Spreadsheet 보유).
        rows: build_archive_rows 결과(2D 리스트). 비어도 정상(0행 기록).
        date_str: 아카이브 날짜 문자열.
        tab_name: 아카이브 탭 이름(기본 ARCHIVE_TAB_NAME).

    Returns:
        {"rows_written": n, "date": date_str, "created_tab": bool}.
        실패 시 rows_written=0 + "error" 키 포함.
    """
    try:
        ws, created = _get_or_create_archive_ws(client, tab_name)
        # 멱등: 그 날짜 블록만 제거(신규 생성 탭이면 지울 게 없음).
        if not created:
            _delete_date_block(ws, date_str)
        if rows:
            ws.append_rows(
                rows, value_input_option="RAW", insert_data_option="INSERT_ROWS"
            )
        return {"rows_written": len(rows), "date": date_str, "created_tab": created}
    except Exception as e:  # noqa: BLE001 — 아카이브 실패가 cron 죽이면 안 됨
        return {"rows_written": 0, "date": date_str, "created_tab": False, "error": str(e)}
