"""글 장부(이 PC 의 post_ledger.db) → 비공개 시트의 숨긴 탭 '우리글_장부' 로 옮기기.

왜: 순위체커는 GitHub 서버에서 돈다. 글 장부는 이 PC 에만 있고(team project .gitignore),
    이 저장소는 공개라 우리 글 목록을 저장소에 커밋하면 안 된다(2026-10-29 마에스트로 고침).
    그래서 순위체커가 이미 읽는 비공개 시트 안에 숨긴 탭을 두고, 서버는 회차마다 그 탭을 읽는다.

쓰는 법:
    # 1) 보기만(기본) — 시트에 아무것도 안 쓴다. 결과는 --out 폴더의 json 한 장.
    python scripts/ledger_to_sheet_tab.py --db <장부 사본 경로> --out <보관함 밖 폴더>

    # 2) 쓰기 — 사장님 승인 뒤에만. 환경값 SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 필요.
    python scripts/ledger_to_sheet_tab.py --db <장부 사본 경로> --write --i-have-approval

지키는 것:
  - 장부 원본은 열지 않는다: --db 에는 파일째 복사한 사본을 준다(읽기 전용 연결로 연다).
  - 시트에서는 이 탭 한 장만 쓴다(통째로 지우고 다시 씀 = 멱등). 다른 탭·행은 건드리지 않는다.
  - 탭은 숨김으로 둔다(사장님 작업 화면에 안 보이게).
  - 링크의 ?art=… 꼬리는 뗀다(글 하나를 가리키는 데 필요 없고 길다).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

LEDGER_TAB_NAME = "우리글_장부"
LEDGER_TAB_HEADER = ["탭", "키워드", "링크", "작업일", "장부키"]


def _clean_link(ref: str, key: str) -> str:
    ref = (ref or "").strip()
    if ref.startswith("http"):
        p = urlsplit(ref)
        return urlunsplit((p.scheme, p.netloc, p.path, "", ""))
    # 장부 키 = 'slug/글번호' — ref 가 없으면 키로 만든다
    if key and "/" in key:
        return f"https://cafe.naver.com/{key}"
    return ""


def read_ledger_rows(db_path: str, tab_suffix: str = "카외") -> list[list[str]]:
    """장부 사본 → 시트에 쓸 2차원 목록(머리줄 제외). 같은 (탭·키워드·링크)는 한 줄."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(
            "SELECT a.tab, a.keyword, p.ref, a.key, COALESCE(a.workdate, a.workdate_raw) "
            "FROM assignments a LEFT JOIN posts p ON p.key = a.key "
            "ORDER BY a.tab, a.keyword, a.workdate"
        )
        best: dict = {}
        for tab, keyword, ref, key, workdate in cur:
            tab = (tab or "").strip()
            if tab_suffix and not tab.endswith(tab_suffix):
                continue  # 순위체커가 보는 탭('…카외')만
            kw = " ".join(str(keyword or "").split())
            link = _clean_link(ref, key)
            if not kw or not link:
                continue
            ident = (tab, kw, link)
            wd = str(workdate or "")
            prev = best.get(ident)
            # 같은 (탭·키워드·글)은 한 줄 — 작업일은 가장 이른 것(처음 맡긴 날)
            if prev is None or (wd and (not prev[3] or wd < prev[3])):
                best[ident] = [tab, kw, link, wd, str(key or "")]
        return sorted(best.values(), key=lambda r: (r[0], r[1], r[3], r[2]))
    finally:
        con.close()


def write_tab(spreadsheet, rows: list[list[str]]) -> dict:
    """비공개 시트에 숨긴 탭 하나를 통째로 다시 쓴다. 다른 탭은 건드리지 않는다."""
    import gspread  # 쓰기 때만 필요

    try:
        ws = spreadsheet.worksheet(LEDGER_TAB_NAME)
        created = False
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=LEDGER_TAB_NAME, rows=len(rows) + 10,
                                       cols=len(LEDGER_TAB_HEADER))
        created = True
    ws.clear()
    if ws.row_count < len(rows) + 1:
        ws.add_rows(len(rows) + 1 - ws.row_count)
    values = [LEDGER_TAB_HEADER] + rows
    ws.update("A1", values, value_input_option="RAW")
    spreadsheet.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {"sheetId": ws.id, "hidden": True},
            "fields": "hidden",
        }
    }]})
    return {"tab": LEDGER_TAB_NAME, "rows_written": len(rows), "created": created, "hidden": True}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="글 장부 사본(파일째 복사한 것) 경로")
    ap.add_argument("--out", default="", help="보기만 할 때 결과 json 을 둘 폴더(보관함 밖)")
    ap.add_argument("--write", action="store_true", help="비공개 시트 숨긴 탭에 쓴다")
    ap.add_argument("--i-have-approval", action="store_true", help="운영 시트 쓰기 승인 확인(사장님)")
    args = ap.parse_args(argv)

    rows = read_ledger_rows(args.db)
    by_tab: dict = {}
    for r in rows:
        by_tab[r[0]] = by_tab.get(r[0], 0) + 1
    report = {"rows": len(rows), "by_tab": by_tab,
              "keywords": len({(r[0], r[1]) for r in rows})}

    if not args.write:
        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            p = Path(args.out) / "ledger_tab_preview.json"
            p.write_text(json.dumps({"header": LEDGER_TAB_HEADER, "report": report, "rows": rows},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
            report["preview_path"] = str(p)
        print(json.dumps({"mode": "보기만", **report}, ensure_ascii=False))
        return 0

    if not args.i_have_approval:
        print("쓰기 거절: 운영 시트 쓰기는 사장님 승인 뒤 --i-have-approval 를 함께 줄 때만 합니다.")
        return 2
    sid = os.environ.get("SPREADSHEET_ID", "")
    saj = os.environ.get("SERVICE_ACCOUNT_JSON", "")
    if not sid or not saj:
        print("쓰기 못 함: SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 환경값이 없습니다.")
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.sheets import SheetsClient

    client = SheetsClient(spreadsheet_id=sid, service_account_json=saj)
    res = write_tab(client.spreadsheet, rows)
    print(json.dumps({"mode": "쓰기", **report, **res}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
