# -*- coding: utf-8 -*-
"""10-31 15:2x 임시 진단 — 화면엔 링크가 보이는데 프로그램은 빈칸으로 읽는 까닭 (읽기 전용)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.sheets import SheetsClient  # noqa: E402

sc = SheetsClient(os.environ["SPREADSHEET_ID"], os.environ["SERVICE_ACCOUNT_JSON"])
ss = sc.spreadsheet
for ws in ss.worksheets():
    if not ws.title.endswith("카외"):
        continue
    head = ws.row_values(1)
    print("TAB", ws.title, "머리줄", json.dumps(head[:16], ensure_ascii=False), flush=True)
    rng = f"'{ws.title}'!A2:P4"
    print("  FORMATTED", json.dumps(ws.get("A2:P4"), ensure_ascii=False)[:900], flush=True)
    print("  FORMULA", json.dumps(ws.get("A2:P4", value_render_option="FORMULA"), ensure_ascii=False)[:900], flush=True)
    meta = ss.fetch_sheet_metadata(params={"ranges": [rng], "includeGridData": "true",
                                           "fields": "sheets(data(rowData(values(formattedValue,hyperlink,chipRuns,userEnteredValue))))"})
    print("  GRID", json.dumps(meta, ensure_ascii=False)[:1500], flush=True)
