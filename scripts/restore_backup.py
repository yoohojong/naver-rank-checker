"""scripts/restore_backup.py — 백업 JSON 복원 스크립트 (T-M82, D-027 2026-05-17).

사용 예:
    python scripts/restore_backup.py .harness/backups/{run_id}_{ts}.json
    python scripts/restore_backup.py .harness/backups/{run_id}_{ts}.json --dry-run

동작:
    1. 백업 파일 read = .harness/backups/{run_id}_{timestamp}.json
    2. 각 탭의 행마다 = 시트 직접 write (HEADER_AREA/L/M/JISIKIN/LINK 컬럼 복원)
    3. D-023 가드 = restore-mode = HEADER_LINK 도 복원 허용 (= 사고 복원 = 유일 예외)
    4. 매 탭 = 1회 batch_update API 호출 (gspread 효율)

진짜 사장님 사고 시:
    GitHub Actions workflow_run artifact 다운로드 → 로컬 복원 후 다시 push 의무.

근거: D-027 + shadow mode 폐기 정합 (= 시트 즉시 갱신 + 사고 시 백업 복원).
"""
import argparse
import json
import os
import sys
import time

# 부모 디렉토리 = src 안 모듈 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON
from src.sheets import (
    SheetsClient, RowUpdate, _sheets_api_retry,
    map_headers_to_columns,
    HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK,
)
import gspread


# 복원 시 = D-023/D-026 가드 우회 = HEADER_LINK 도 허용 (= 진짜 사고 복원 시 의무)
RESTORE_COLUMNS = (HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK)


def restore_backup(backup_path: str, dry_run: bool = False) -> dict:
    """백업 파일 → 사장님 시트 복원.

    Args:
        backup_path: 백업 JSON 경로 (예: .harness/backups/12345_20260517T180000.json)
        dry_run: True 시 실제 write 안 함 = 시뮬레이션 (사장님 검증 용)

    Returns:
        summary dict (탭별 행 수, 셀 수, 시간).
    """
    print(f"=== restore_backup 시작 (dry_run={dry_run}) ===")
    print(f"  backup: {backup_path}")

    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"백업 파일 없음: {backup_path}")

    with open(backup_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    print(f"  timestamp={payload.get('timestamp')}, run_id={payload.get('run_id')}")
    print(f"  spreadsheet_id={payload.get('spreadsheet_id')}")
    print(f"  tabs={list(payload.get('tabs', {}).keys())}")

    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("SPREADSHEET_ID 또는 SERVICE_ACCOUNT_JSON 환경 변수 누락")

    # 백업 시점 spreadsheet_id 와 현재 spreadsheet_id 일치 검증 (= 사고 방지)
    backup_spreadsheet_id = payload.get("spreadsheet_id")
    if backup_spreadsheet_id and backup_spreadsheet_id != SPREADSHEET_ID:
        print(f"⚠️ WARN: 백업 spreadsheet_id ({backup_spreadsheet_id}) ≠ 현재 SPREADSHEET_ID ({SPREADSHEET_ID})")
        print("   복원 진행 X = 사장님 확인 후 환경 변수 정합 의무.")
        return {"error": "spreadsheet_id_mismatch"}

    if dry_run:
        client = None
    else:
        client = SheetsClient(spreadsheet_id=SPREADSHEET_ID, service_account_json=SERVICE_ACCOUNT_JSON)

    summary: dict = {"tabs": {}, "total_rows": 0, "total_cells": 0}
    start = time.time()

    for tab_name, rows in payload.get("tabs", {}).items():
        if not rows:
            print(f"[{tab_name}] 0 행 = skip")
            continue

        print(f"\n[{tab_name}] {len(rows)} 행 복원")

        if dry_run:
            # dry_run = headers / mapping read X = 단순 카운트
            cells_n = sum(1 for r in rows for col in RESTORE_COLUMNS if r.get(col) not in (None, ""))
            summary["tabs"][tab_name] = {"rows": len(rows), "cells_estimate": cells_n}
            summary["total_rows"] += len(rows)
            summary["total_cells"] += cells_n
            print(f"  [DRY-RUN] {len(rows)} 행 / 셀 추정 {cells_n}")
            continue

        # 실제 복원 = headers / mapping read → row 단위 cells 구성 → batch_update 1회
        ws = client.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)

        cells = []
        skipped_no_row = 0
        for r in rows:
            row_1based = r.get("_row")
            if not isinstance(row_1based, int):
                skipped_no_row += 1
                continue
            for col_name in RESTORE_COLUMNS:
                if col_name not in mapping:
                    continue
                if col_name not in r:
                    continue
                col_idx = mapping[col_name] + 1
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(row_1based, col_idx),
                    "values": [[r[col_name]]],
                })

        if not cells:
            print(f"  cells 0 = skip")
            continue

        _sheets_api_retry(
            lambda: ws.batch_update(cells, value_input_option="RAW"),
            ctx=f"{tab_name} (restore)",
        )
        n = len(cells)
        summary["tabs"][tab_name] = {"rows": len(rows), "cells": n, "skipped_no_row": skipped_no_row}
        summary["total_rows"] += len(rows)
        summary["total_cells"] += n
        print(f"  → 복원: {n} 셀 / skip(_row 없음): {skipped_no_row}")

    elapsed = int(time.time() - start)
    summary["elapsed_seconds"] = elapsed
    print(f"\n=== restore_backup 완료 (총 {summary['total_rows']} 행 / {summary['total_cells']} 셀 / {elapsed}s) ===")
    return summary


def main():
    parser = argparse.ArgumentParser(description="naver-rank-checker 백업 복원 (D-027 T-M82)")
    parser.add_argument("backup_path", help="백업 JSON 경로 (.harness/backups/{run_id}_{ts}.json)")
    parser.add_argument("--dry-run", action="store_true", help="실제 write 안 함 = 시뮬레이션")
    args = parser.parse_args()
    summary = restore_backup(args.backup_path, dry_run=args.dry_run)
    if summary.get("error"):
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
