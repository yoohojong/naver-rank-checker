"""send_weekly_dashboard: 카페외부 주간 대시보드 인라인 이미지(PNG) 생성 + 텔레그램 발송. 2026-07-13.

⚠️ 순수 추가. 주간도 파일이 아니라 채팅에 바로 뜨는 이미지(sendPhoto).
사용:
  python scripts/send_weekly_dashboard.py
  python scripts/send_weekly_dashboard.py --local <dir> --no-send --out <path.png>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard_fetch import fetch_gh_daily, load_local_dir  # noqa: E402
from src.notify import send_photo  # noqa: E402
from src.report_html import weekly_html  # noqa: E402
from src.report_metrics import weekly_context  # noqa: E402
from src.report_render import html_to_png  # noqa: E402

DAYS = 8  # 주 시작(첫날) ↔ 오늘 비교 위해 8일 확보


def build(backups_by_date: dict) -> tuple:
    ctx = weekly_context(backups_by_date)
    return ctx, weekly_html(ctx)


def caption(ctx: dict) -> str:
    """핵심 3줄(달성률·발행·필요발행 대응). 텔레그램 caption(≤1024)."""
    if ctx.get("empty"):
        return "카페외부 주간 · 데이터 없음"
    g = ctx.get("week_gain")
    gain = "비교없음" if g is None else (f"+{g}" if g > 0 else (f"{g}" if g < 0 else "±0"))
    eff = "-" if ctx.get("efficiency_pct") is None else f"{ctx['efficiency_pct']}%"
    return (
        f"카페외부 주간 {ctx['date_range']}\n"
        f"달성률 {ctx['achieve_pct']}% · 상위노출 {ctx['exposed']}/{ctx['total']} (주 순증 {gain})\n"
        f"주 발행 {ctx['week_published']}개 · 발행효율 {eff}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", help="로컬 백업 디렉터리(검증용)")
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--out", help="PNG 저장 경로(기본 cafe_weekly_YYYYMMDD.png)")
    ap.add_argument("--no-send", action="store_true", help="이미지만 생성, 발송 안 함")
    args = ap.parse_args()

    backups = load_local_dir(args.local, args.days) if args.local else fetch_gh_daily(args.days)
    if not backups:
        print("[WEEKLY] 백업 입수 실패 — 대시보드 생략")
        return 0

    ctx, html = build(backups)
    filename = f"cafe_weekly_{ctx['date_full'].replace('-', '')}.png"
    png = html_to_png(html)
    out = args.out or filename
    with open(out, "wb") as f:
        f.write(png)
    print(f"[WEEKLY] PNG 저장: {os.path.abspath(out)} ({len(png)} bytes)")

    if not args.no_send:
        cap = caption(ctx)
        ok = send_photo(png, caption=cap, filename=filename)
        print(f"[WEEKLY] 발송 {'성공' if ok else '건너뜀/실패'}")
        # 슬랙 DM(한수연) 추가 발송 — import/미설정/실패가 텔레그램 흐름 안 깨게 격리.
        try:
            from src.slack_notify import send_slack_photo  # noqa: E402
            sok = send_slack_photo(png, filename=filename, initial_comment=cap)
            print(f"[WEEKLY][SLACK] 발송 {'성공' if sok else '건너뜀/실패'}")
        except Exception as e:  # noqa: BLE001 — 슬랙 실패 비차단
            print(f"[WEEKLY][SLACK][WARN] 슬랙 발송 생략: {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
