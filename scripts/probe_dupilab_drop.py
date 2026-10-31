# -*- coding: utf-8 -*-
"""10-31 15:1x 임시 진단 — 지금 시트 '링크' 칸이 몇 줄 차 있나 (읽기 전용 · 시트에 쓰지 않음)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.sheets import SheetsClient  # noqa: E402

sc = SheetsClient(os.environ["SPREADSHEET_ID"], os.environ["SERVICE_ACCOUNT_JSON"])
for ws in sc.spreadsheet.worksheets():
    if not ws.title.endswith("카외"):
        continue
    rows = ws.get_all_values()
    head = rows[0]
    i = head.index("링크") if "링크" in head else -1
    filled = sum(1 for r in rows[1:] if i >= 0 and i < len(r) and r[i].strip())
    print("TAB", ws.title, "줄", len(rows) - 1, "링크칸", i, "링크있음", filled, flush=True)
