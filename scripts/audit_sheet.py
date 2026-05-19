"""Read-only sheet audit helper for impossible K/L/M/link combinations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.audit import audit_sheet_rows
from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON
from src.sheets import SheetsClient


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Read-only audit for impossible sheet states.")
    ap.add_argument("--tab", help="Optional tab name to inspect, e.g. 바디워시 카외")
    ap.add_argument("--row", type=int, help="Optional 1-based sheet row number to inspect")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return ap.parse_args(argv)


def _filter_data(data: dict[str, list[dict]], tab: str | None, row_num: int | None) -> tuple[dict[str, list[dict]], dict | None]:
    if tab:
        if tab not in data:
            return {}, {
                "code": "TAB_NOT_FOUND",
                "message": f"tab not found: {tab}",
                "available_tabs": sorted(data.keys()),
            }
        data = {tab: list(data.get(tab, []))}
    if row_num is not None:
        data = {
            tab_name: [row for row in rows if int(row.get("_row") or 0) == row_num]
            for tab_name, rows in data.items()
        }
        if sum(len(rows) for rows in data.values()) == 0:
            return data, {
                "code": "ROW_NOT_FOUND",
                "message": f"row not found: {row_num}",
                "tab": tab,
            }
    return data, None


def _carea_filter(tab_name: str) -> bool:
    return tab_name.endswith("카외")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 환경변수 누락", file=sys.stderr)
        return 2

    client = SheetsClient(spreadsheet_id=SPREADSHEET_ID, service_account_json=SERVICE_ACCOUNT_JSON)
    data = client.load_all_data_tabs(tab_filter=_carea_filter)
    data, filter_error = _filter_data(data, args.tab, args.row)
    if filter_error:
        if args.json:
            print(json.dumps({"error": filter_error, "tabs": list(data.keys()), "rows_checked": 0, "issues": []}, ensure_ascii=False, indent=2))
        else:
            print(filter_error["message"], file=sys.stderr)
            if filter_error["code"] == "TAB_NOT_FOUND":
                print(f"available_tabs={', '.join(filter_error['available_tabs'])}", file=sys.stderr)
        return 2
    issues = audit_sheet_rows(data)

    payload = {
        "tabs": list(data.keys()),
        "rows_checked": sum(len(rows) for rows in data.values()),
        "issues": issues,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if issues else 0

    print(f"checked={payload['rows_checked']} issues={len(issues)}")
    for issue in issues:
        print(
            f"{issue['code']} tab={issue['tab']} row={issue['row']} "
            f"kw={issue.get('keyword')!r} K={issue.get('k_full')!r} L={issue.get('L')!r} M={issue.get('M')!r}"
        )
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
