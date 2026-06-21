"""apply_keyword_classify: CSV 키워드 분류를 라이브 시트 '키워드 분류' 칸에 일괄 반영.

카페외부(카외) 탭의 각 키워드 행을 CSV 분류 맵에서 찾아 '키워드 분류' 칸에
`"{단계} {유형}"`(예: '3 증상', '5 브랜드제품') 형식 값을 batch_update 1회로 기록한다.
맨 앞 숫자(3/4/5)가 단계라서 integration_runner 의 단계 라우팅과 호환된다.

추가로 '키워드 분류' 칸 범위에 데이터확인(드롭다운) 목록을 CSV 분류값 집합으로 갱신해
새 값이 빨간 경고 없이 들어가도록 한다.

env:
  SPREADSHEET_ID         : 대상 스프레드시트 id (필수)
  SERVICE_ACCOUNT_JSON   : 서비스 계정 JSON 문자열 (필수)
  TARGET_TAB             : 대상 탭 이름 (기본 '샴푸 카외')
  CSV_PATH               : 분류 CSV 경로 (기본 data/keyword_classify_shampoo.csv)
  DRY_RUN                : '1' 이면 시트에 쓰지 않고 매칭 결과만 출력 (기본 빈값=실반영)

순수 로직(CSV 파싱·맵·업데이트 계산)과 I/O(시트 read/write)를 분리해 테스트는
실제 네트워크 0 (시트 클라이언트 주입/mock) 으로 검증한다.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from typing import Optional

import gspread

from src.sheets import (
    SheetsClient,
    _sheets_api_retry,
    map_headers_to_columns,
)

# 사장님 시트 칸 이름 — 이름으로 정확 매칭 (위치 고정 X, D-004 정합).
HEADER_KEYWORD = "키워드"
HEADER_CLASSIFY = "키워드 분류"

DEFAULT_TARGET_TAB = "샴푸 카외"
DEFAULT_CSV_PATH = "data/keyword_classify_shampoo.csv"

# CSV 컬럼 이름 (키워드-접촉지점-분류.csv).
CSV_COL_KEYWORD = "키워드"
CSV_COL_STAGE = "단계"
CSV_COL_TYPE = "유형"


def _normalize_keyword(value: object) -> str:
    """키워드 매칭용 정규화 — 앞뒤 공백 제거. 시트/CSV 양쪽 동일 규칙."""
    return str(value or "").strip()


def build_classify_value(stage: object, type_: object) -> str:
    """'키워드 분류' 칸에 넣을 값 = '{단계} {유형}' (예: '3 증상', '5 브랜드제품').

    단계/유형 각각 trim 후 단일 공백으로 결합. 기존 '3 증상' 공백 형식과 호환.
    """
    s = str(stage or "").strip()
    t = str(type_ or "").strip()
    return f"{s} {t}".strip()


def load_classify_map(csv_path: str) -> dict[str, str]:
    """CSV → {정규화 키워드: '{단계} {유형}'} 맵.

    BOM(utf-8-sig) 안전 디코딩. 빈 키워드 행은 건너뛴다.
    같은 키워드가 중복되면 마지막 값으로 덮어쓴다(로그는 호출부 책임 아님 — 입력 정합 가정).
    """
    mapping: dict[str, str] = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keyword = _normalize_keyword(row.get(CSV_COL_KEYWORD, ""))
            if not keyword:
                continue
            value = build_classify_value(
                row.get(CSV_COL_STAGE, ""), row.get(CSV_COL_TYPE, "")
            )
            mapping[keyword] = value
    return mapping


def classify_value_set(classify_map: dict[str, str]) -> list[str]:
    """드롭다운 목록용 — 분류값 집합을 안정 정렬로 반환(중복 제거)."""
    return sorted(set(classify_map.values()))


@dataclass
class CellUpdate:
    """batch_update 1셀 — A1 표기 range + 값 + (로그용) 키워드/기존값."""

    row: int  # 1-indexed 시트 행
    a1: str  # '키워드 분류' 칸 A1 좌표 (예: 'F12')
    value: str  # 새 분류값
    keyword: str
    old_value: str  # 기존 셀 값 (덮어쓰기 로그용)


@dataclass
class MatchPlan:
    """매칭 계산 결과 — 실제 쓸 업데이트 목록 + 통계."""

    updates: list[CellUpdate]
    overwrites: list[CellUpdate]  # 기존 값이 있고 새 값과 다른 셀 (덮어쓰기)
    sheet_only: list[str]  # 시트에만 있고 CSV 에 없는 키워드 (미분류)
    csv_only: list[str]  # CSV 에만 있고 시트에 없는 키워드


def compute_updates(
    *,
    headers: list[str],
    sheet_rows: list[dict],
    classify_map: dict[str, str],
) -> MatchPlan:
    """헤더 + 시트 행 데이터 + CSV 맵 → (셀좌표, 값) 업데이트 목록 계산.

    Args:
        headers: 시트 1행 헤더 list (왼→오른쪽).
        sheet_rows: 각 행 = {'_row': 1-indexed 행번호, 헤더이름: 값, ...}.
        classify_map: {정규화 키워드: '{단계} {유형}'}.

    Returns:
        MatchPlan — updates(쓸 셀들) / overwrites / sheet_only / csv_only.

    Raises:
        ValueError: '키워드' 또는 '키워드 분류' 헤더가 시트에 없을 때.
    """
    mapping = map_headers_to_columns(headers)
    if HEADER_KEYWORD not in mapping:
        raise ValueError(
            f"대상 탭에 '{HEADER_KEYWORD}' 칸이 없습니다. 시트 1행 헤더 확인 필요."
        )
    if HEADER_CLASSIFY not in mapping:
        raise ValueError(
            f"대상 탭에 '{HEADER_CLASSIFY}' 칸이 없습니다. "
            f"(칸을 자동 생성하지 않음 — 사장님 칸 구조 보호) 시트 1행에 '{HEADER_CLASSIFY}' 칸을 먼저 추가하세요."
        )

    keyword_col = mapping[HEADER_KEYWORD]  # 0-indexed
    classify_col = mapping[HEADER_CLASSIFY]  # 0-indexed

    updates: list[CellUpdate] = []
    overwrites: list[CellUpdate] = []
    sheet_only: list[str] = []
    matched_keywords: set[str] = set()

    for row in sheet_rows:
        row_num = int(row.get("_row") or 0)
        if row_num < 2:  # 1행 = 헤더
            continue
        keyword = _normalize_keyword(row.get(HEADER_KEYWORD, ""))
        if not keyword:
            continue
        if keyword not in classify_map:
            sheet_only.append(keyword)
            continue
        new_value = classify_map[keyword]
        matched_keywords.add(keyword)
        old_value = str(row.get(HEADER_CLASSIFY, "") or "").strip()
        a1 = gspread.utils.rowcol_to_a1(row_num, classify_col + 1)
        upd = CellUpdate(
            row=row_num,
            a1=a1,
            value=new_value,
            keyword=keyword,
            old_value=old_value,
        )
        # 이미 같은 값이면 굳이 쓰지 않음 (API 효율 + 불필요 변경 로그 회피).
        if old_value == new_value:
            continue
        updates.append(upd)
        if old_value:  # 기존 값이 있고 새 값과 다름 = 덮어쓰기
            overwrites.append(upd)

    csv_only = sorted(set(classify_map.keys()) - matched_keywords)
    return MatchPlan(
        updates=updates,
        overwrites=overwrites,
        sheet_only=sheet_only,
        csv_only=csv_only,
    )


def build_data_validation_request(
    *,
    sheet_id: int,
    classify_col: int,
    start_row: int,
    end_row: int,
    values: list[str],
) -> dict:
    """'키워드 분류' 칸 범위에 requireValueInList(분류값) 데이터확인 적용 request.

    gspread spreadsheet.batch_update({"requests":[...]}) 로 보내는 Sheets API setDataValidation.
    showCustomUi=True → 드롭다운 표시. strict=False → 목록 외 값도 빨간 경고 없이 허용
    (사장님 시트엔 미분류 키워드도 있을 수 있으므로 막지 않음 — 경고만 회피가 목표).

    Args:
        sheet_id: 워크시트 id (ws.id).
        classify_col: '키워드 분류' 0-indexed 컬럼.
        start_row: 1-indexed 시작 행 (보통 2 = 헤더 다음).
        end_row: 1-indexed 끝 행 (포함).
        values: 드롭다운 목록 값.
    """
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start_row - 1,  # 0-indexed, inclusive
                "endRowIndex": end_row,  # 0-indexed, exclusive
                "startColumnIndex": classify_col,
                "endColumnIndex": classify_col + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in values],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }


def _read_sheet_rows(ws) -> tuple[list[str], list[dict]]:
    """워크시트 → (헤더 list, 행 dict list). 각 행 dict 에 '_row'(1-indexed) 포함."""
    all_values = _sheets_api_retry(lambda: ws.get_all_values(), ctx=f"{ws.title} (read)")
    if not all_values:
        return [], []
    headers = all_values[0]
    rows: list[dict] = []
    for idx, raw in enumerate(all_values[1:], start=2):
        row = {"_row": idx}
        for col, header in enumerate(headers):
            if not header:
                continue
            row[str(header).strip()] = raw[col] if col < len(raw) else ""
        rows.append(row)
    return headers, rows


def apply(
    *,
    spreadsheet_id: str,
    service_account_json: str,
    target_tab: str,
    csv_path: str,
    dry_run: bool,
    client: Optional[SheetsClient] = None,
) -> MatchPlan:
    """엔드투엔드 — CSV 로드 → 시트 read → 매칭 계산 → (dry_run 아니면) batch_update + 데이터확인.

    client 를 주입하면 인증을 건너뛴다(테스트용). 미주입 시 SheetsClient 생성.
    """
    classify_map = load_classify_map(csv_path)
    values = classify_value_set(classify_map)

    if client is None:
        client = SheetsClient(spreadsheet_id, service_account_json)
    ws = client.spreadsheet.worksheet(target_tab)

    headers, sheet_rows = _read_sheet_rows(ws)
    plan = compute_updates(
        headers=headers, sheet_rows=sheet_rows, classify_map=classify_map
    )

    _print_report(plan, classify_map, values, target_tab, dry_run)

    if dry_run:
        print("\n[DRY-RUN] 시트에 쓰지 않음 — 매칭 결과만 출력.")
        return plan

    if not plan.updates:
        print("\n[반영] 쓸 셀 없음(모두 이미 같은 값이거나 미매칭). 데이터확인만 갱신 시도.")

    # 1) 셀 값 batch_update 1회 (셀별 호출 금지).
    if plan.updates:
        cells = [
            {"range": upd.a1, "values": [[upd.value]]} for upd in plan.updates
        ]
        _sheets_api_retry(
            lambda: ws.batch_update(cells, value_input_option="RAW"),
            ctx=f"{target_tab} (keyword classify batch)",
        )
        print(f"\n[반영] {len(plan.updates)}개 셀 batch_update 완료.")

    # 2) 데이터확인(드롭다운) 갱신 — '키워드 분류' 칸 범위에 분류값 집합 적용.
    mapping = map_headers_to_columns(headers)
    classify_col = mapping[HEADER_CLASSIFY]
    last_row = max((r["_row"] for r in sheet_rows), default=1)
    if values and last_row >= 2:
        req = build_data_validation_request(
            sheet_id=ws.id,
            classify_col=classify_col,
            start_row=2,
            end_row=last_row,
            values=values,
        )
        _sheets_api_retry(
            lambda: client.spreadsheet.batch_update({"requests": [req]}),
            ctx=f"{target_tab} (keyword classify validation)",
        )
        print(
            f"[데이터확인] '{HEADER_CLASSIFY}' 칸 2~{last_row}행 드롭다운 목록 갱신: {values}"
        )

    return plan


def _print_report(
    plan: MatchPlan,
    classify_map: dict[str, str],
    values: list[str],
    target_tab: str,
    dry_run: bool,
) -> None:
    """반영 N / 미분류 M / CSV전용 K + 샘플 출력."""
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"=== 키워드 분류 반영 ({mode}) — 탭 '{target_tab}' ===")
    print(f"CSV 분류값 집합: {values}")
    print(f"반영(쓸 셀) N = {len(plan.updates)}개")
    print(f"  ↳ 그중 덮어쓰기(기존값≠새값) = {len(plan.overwrites)}개")
    print(f"시트에만 있고 CSV에 없음(미분류) M = {len(plan.sheet_only)}개")
    print(f"CSV에만 있고 시트에 없음 K = {len(plan.csv_only)}개")

    if plan.updates:
        print("  [반영 샘플]")
        for upd in plan.updates[:5]:
            print(f"    {upd.a1}  '{upd.keyword}' -> '{upd.value}'"
                  + (f"  (덮어씀: '{upd.old_value}')" if upd.old_value else ""))
    if plan.overwrites:
        print("  [덮어쓰기 샘플]")
        for upd in plan.overwrites[:5]:
            print(f"    {upd.a1}  '{upd.keyword}': '{upd.old_value}' -> '{upd.value}'")
    if plan.sheet_only:
        print("  [미분류 샘플(시트에만)]")
        for kw in plan.sheet_only[:5]:
            print(f"    '{kw}'")
    if plan.csv_only:
        print("  [CSV전용 샘플(시트에 없음)]")
        for kw in plan.csv_only[:5]:
            print(f"    '{kw}'")


def main(argv: Optional[list[str]] = None) -> int:
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "")
    service_account_json = os.environ.get("SERVICE_ACCOUNT_JSON", "")
    target_tab = os.environ.get("TARGET_TAB", DEFAULT_TARGET_TAB)
    csv_path = os.environ.get("CSV_PATH", DEFAULT_CSV_PATH)
    dry_run = os.environ.get("DRY_RUN", "").strip() == "1"

    if not os.path.exists(csv_path):
        print(f"[ERROR] CSV 경로 없음: {csv_path}", file=sys.stderr)
        return 2

    if not dry_run:
        if not spreadsheet_id:
            print("[ERROR] SPREADSHEET_ID 미설정 (실반영 모드).", file=sys.stderr)
            return 2
        if not service_account_json:
            print("[ERROR] SERVICE_ACCOUNT_JSON 미설정 (실반영 모드).", file=sys.stderr)
            return 2

    try:
        apply(
            spreadsheet_id=spreadsheet_id,
            service_account_json=service_account_json,
            target_tab=target_tab,
            csv_path=csv_path,
            dry_run=dry_run,
        )
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
