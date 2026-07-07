"""저녁/아침 요약 텔레그램 보고. M10 T-M10.7.

모드: argv[1] ∈ {evening, morning} (기본 evening).
최신 백업(오늘) vs ~24h 전 백업(어제) → snapshot_diff → report_builder → notify.
⚠️ 비즈니스 데이터(키워드/제품/분포) 포함 = 텔레그램 전용. 메시지 text 를 CLI 인자로 넘기지 않음(로그 노출 차단).
백업 부재/실패 = 비차단(return 0, '비교 기준 없음' 또는 생략).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

# repo 루트 + scripts/ 를 path 에
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_yesterday_backup import (  # noqa: E402
    download_backup,
    list_success_runs,
    pick_run_near_hours,
)
from src import report_builder as rb  # noqa: E402
from src.notify import send_report  # noqa: E402
from src.exposure_history import cohort_evolution, daily_trend, read_archive_rows  # noqa: E402
from src.snapshot_diff import diff_backups, exposure_lag_distribution, load_backup  # noqa: E402
from src.weekly_digest import daily_product_breakdown  # noqa: E402


def _kst_today() -> str:
    dt = datetime.now(timezone(timedelta(hours=9)))
    return f"{dt.month}/{dt.day}"


def _kst_yesterday() -> str:
    dt = datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)
    return f"{dt.month}/{dt.day}"


def build_report_text(
    prev_path,
    curr_path: str,
    mode: str = "evening",
    kst=None,
    status_line: str = "정상",
    work_date=None,
    today=None,
    archive_rows=None,
) -> str:
    """백업 경로 2개 → 보고 텍스트 (순수, 테스트 대상). prev_path None 허용(비교 기준 없음).
    work_date(M/D) = 집계 대상일(기본 KST 어제). today = 7일 breakdown 기준일(기본 KST 오늘).
    archive_rows = 상위노출_이력 행(있으면 [추세]+[발행분 변화] 계산, 없으면 생략)."""
    kst = kst or _kst_today()
    work_date = work_date or _kst_yesterday()
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    curr = load_backup(curr_path)
    prev = load_backup(prev_path) if prev_path else None
    reports = diff_backups(prev, curr, work_date=work_date)
    # 최근 7일 날짜별×제품별 발행→상위노출 (사장님 2026-07-02: '어제 작업' 1일 → 7일 업그레이드)
    breakdown = daily_product_breakdown(curr, today, 7)
    lag_dist = exposure_lag_distribution(curr, today)
    # 아카이브 기반: [추세] 일별 개수 흐름 + [발행분 변화] 코호트 (사장님 2026-07-07)
    exposure_trend = daily_trend(archive_rows, days=6) if archive_rows else None
    cohort = cohort_evolution(archive_rows, curr, n_cohorts=3) if archive_rows else None
    if mode == "morning":
        return rb.build_morning_report(reports, kst, status_line, breakdown=breakdown, lag_dist=lag_dist, exposure_trend=exposure_trend, cohort=cohort)
    return rb.build_evening_report(reports, kst, status_line, breakdown=breakdown, lag_dist=lag_dist, exposure_trend=exposure_trend, cohort=cohort)


def _load_archive_rows():
    """환경변수 SERVICE_ACCOUNT_JSON/SPREADSHEET_ID 있으면 아카이브(상위노출_이력) 행. 없으면 None(비차단)."""
    sid = os.environ.get("SPREADSHEET_ID")
    sa = os.environ.get("SERVICE_ACCOUNT_JSON")
    if not sid or not sa:
        return None
    try:
        from src.sheets import SheetsClient
        client = SheetsClient(sid, sa)
        return read_archive_rows(client) or None
    except Exception as e:
        print(f"[TG-REPORT] 아카이브 로드 실패(비차단): {e}")
        return None


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "evening"
    runs = list_success_runs()
    if not runs:
        print("[TG-REPORT] 성공 run 없음 — 보고 생략")
        return 0
    runs_sorted = sorted(runs, key=lambda r: str(r.get("createdAt", "")), reverse=True)
    curr = runs_sorted[0]
    curr_id = str(curr.get("databaseId"))
    prev_id = pick_run_near_hours(
        runs, curr.get("createdAt"), hours=24, tolerance_h=5, exclude_run_id=curr_id
    )

    curr_path = download_backup(curr_id)
    if not curr_path:
        print("[TG-REPORT] 오늘 백업 입수 실패 — 보고 생략")
        return 0
    prev_path = download_backup(prev_id) if prev_id else None

    archive_rows = _load_archive_rows()
    text = build_report_text(prev_path, curr_path, mode=mode, archive_rows=archive_rows)
    return send_report(text)


if __name__ == "__main__":
    sys.exit(main())
