"""주간 총괄 다이제스트 발송 (M11, 2026-06-23). 일일 보고와 별개, 주 1회.

최신 백업(오늘) vs ~7일 전 백업(지난주) → weekly_digest → notify.
⚠️ 기본 = dry-run(텍스트 print 만). 실제 텔레그램 발송은 인자 'send' 명시 시에만.
   (사장님 '켜' 전까지 자동발송 차단 — weekly-digest.yml 의 cron 도 주석 처리.)
"""
import os
import sys
from datetime import datetime, timedelta, timezone

# repo 루트 + scripts/ 를 path 에 (send_telegram_report.py 와 동일 패턴)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_yesterday_backup import (  # noqa: E402
    download_backup,
    list_success_runs,
    pick_run_near_hours,
)
from src.notify import send_report  # noqa: E402
from src.snapshot_diff import diff_backups, load_backup  # noqa: E402
from src.weekly_digest import (  # noqa: E402
    build_weekly_text,
    funnel_last_n_days,
    work_dates_last_n,
)

_KST = timezone(timedelta(hours=9))


def _date_range(today) -> str:
    start = today - timedelta(days=6)
    return f"{start.month}/{start.day}~{today.month}/{today.day}"


def build_text_from_paths(prev_path, curr_path, today=None) -> str:
    """백업 경로 2개 → 주간 보고 텍스트 (테스트 대상). prev_path None 허용(지난주 비교 없음)."""
    today = today or datetime.now(_KST).date()
    curr = load_backup(curr_path)
    prev = load_backup(prev_path) if prev_path else None
    reports = diff_backups(prev, curr)
    funnel = funnel_last_n_days(curr, work_dates_last_n(today, 7))
    return build_weekly_text(reports, funnel, _date_range(today))


def main() -> int:
    do_send = len(sys.argv) > 1 and sys.argv[1] == "send"
    # ⚠️ 주간(168h 전)은 일일(24h)보다 깊은 history 필요. rank-check ~8회/일 → 기본 30개는
    # ~3.75일치라 7일 전에 못 닿음(지난주 비교 누락). 150개 = ~19일치(14일 retention 충분 커버).
    runs = list_success_runs(limit=150)
    if not runs:
        print("[WEEKLY] 성공 run 없음 — 보고 생략")
        return 0
    runs_sorted = sorted(runs, key=lambda r: str(r.get("createdAt", "")), reverse=True)
    curr = runs_sorted[0]
    curr_id = str(curr.get("databaseId"))
    # 지난주 = 168h(7일) 전 ±24h 내 직전 성공 run (cron 누락에 강건). 없으면 None → 비교 생략.
    prev_id = pick_run_near_hours(
        runs, curr.get("createdAt"), hours=168, tolerance_h=24, exclude_run_id=curr_id
    )

    curr_path = download_backup(curr_id)
    if not curr_path:
        print("[WEEKLY] 오늘 백업 입수 실패 — 보고 생략")
        return 0
    prev_path = download_backup(prev_id) if prev_id else None

    text = build_text_from_paths(prev_path, curr_path)
    if do_send:
        return send_report(text)
    print("[WEEKLY][DRY-RUN] 아래 메시지 (발송 안 함 — 'send' 인자 주면 발송):\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
