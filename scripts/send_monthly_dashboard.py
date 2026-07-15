"""send_monthly_dashboard: 카페외부 월간 이미지 대시보드(HTML) 생성 + 텔레그램 전송. 2026-07-13.

⚠️ inert — 워크플로 배선 없음(사람이 나중에). 순수 추가.
사용:
  python scripts/send_monthly_dashboard.py
  python scripts/send_monthly_dashboard.py --local <dir> --no-send --out <path>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard_fetch import fetch_gh_daily, load_local_dir  # noqa: E402
from src.notify import send_document  # noqa: E402
from src.report_html import monthly_html  # noqa: E402
from src.report_metrics import monthly_context  # noqa: E402

DAYS = 30


def build(backups_by_date: dict) -> tuple:
    ctx = monthly_context(backups_by_date)
    return ctx, monthly_html(ctx)


def caption(ctx: dict) -> str:
    if ctx.get("empty"):
        return "카페외부 월간 · 데이터 없음"
    return (f"카페외부 월간 {ctx['date_range']} · "
            f"상위노출 {ctx['exposed']}/{ctx['total']} ({ctx['achieve_pct']}%) · "
            f"대량하락 {len(ctx['mass_drops'])}회 · 체류 {ctx['avg_dwell']}일")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="로컬 백업 디렉터리(검증용)")
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--out", help="HTML 저장 경로(기본 cafe_monthly_YYYYMMDD.html)")
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    backups = load_local_dir(args.local, args.days) if args.local else fetch_gh_daily(args.days)
    if not backups:
        print("[MONTHLY] 백업 입수 실패 — 대시보드 생략")
        return 0

    ctx, html = build(backups)
    filename = f"cafe_monthly_{ctx['date_full'].replace('-', '')}.html"
    out = args.out or filename
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[MONTHLY] HTML 저장: {os.path.abspath(out)}")

    if not args.no_send:
        cap = caption(ctx)
        ok = send_document(html.encode("utf-8"), filename, caption=cap)
        print(f"[MONTHLY] 전송 {'성공' if ok else '건너뜀/실패'}")
        # 슬랙 DM(한수연) 추가 발송 — import/미설정/실패가 텔레그램 흐름 안 깨게 격리.
        try:
            from src.slack_notify import send_slack_document  # noqa: E402
            sok = send_slack_document(html.encode("utf-8"), filename, initial_comment=cap)
            print(f"[MONTHLY][SLACK] 전송 {'성공' if sok else '건너뜀/실패'}")
        except Exception as e:  # noqa: BLE001 — 슬랙 실패 비차단
            print(f"[MONTHLY][SLACK][WARN] 슬랙 발송 생략: {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
