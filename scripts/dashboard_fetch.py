"""dashboard_fetch: 대시보드 스크립트 공용 — 백업 입수(로컬 디렉터리 / gh artifact). 2026-07-13.

⚠️ 순수 추가(inert). 기존 fetch_yesterday_backup / snapshot_diff 재사용만.
- load_local_dir(dir, days): day_YYYY-MM-DD.json(.gz) 파일들 → {date: backup}  (로컬 검증용)
- fetch_gh_daily(n_days): rank-check.yml 성공 run 을 KST 날짜별 1개씩 골라 다운로드 → {date: backup}
반환 dict 키 = 'YYYY-MM-DD' 문자열(report_metrics 가 최신일을 '오늘'로 사용).
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/

from fetch_yesterday_backup import download_backup, list_success_runs  # noqa: E402
from src.snapshot_diff import load_backup  # noqa: E402

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _date_from_name(name: str) -> Optional[str]:
    m = _DATE_RE.search(name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def load_local_dir(dirpath: str, days: Optional[int] = None) -> dict:
    """디렉터리의 day_YYYY-MM-DD.json(.gz) → {date: backup}. days 지정 시 최근 days 일만."""
    out: dict = {}
    for fn in sorted(os.listdir(dirpath)):
        if not (fn.endswith(".json") or fn.endswith(".json.gz")):
            continue
        d = _date_from_name(fn)
        if not d or d in out:  # 이미 있으면 첫(정렬상 .json) 유지
            continue
        try:
            out[d] = load_backup(os.path.join(dirpath, fn))
        except Exception as e:  # noqa: BLE001
            print(f"[DASH] 로컬 백업 로드 실패 {fn}: {type(e).__name__}")
    if days:
        keys = sorted(out)[-days:]
        out = {k: out[k] for k in keys}
    return out


def _kst_date(iso: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def fetch_gh_daily(n_days: int, repo: Optional[str] = None) -> dict:
    """성공 run 을 KST 날짜별 최신 1개로 압축 → 최근 n_days 일 다운로드 → {date: backup}."""
    runs = list_success_runs(limit=max(40, n_days * 5), repo=repo)
    by_date: dict = {}
    for r in runs:
        iso = r.get("createdAt")
        d = _kst_date(iso) if iso else None
        if not d:
            continue
        if d not in by_date or iso > by_date[d][0]:
            by_date[d] = (iso, str(r.get("databaseId")))
    out: dict = {}
    for d in sorted(by_date)[-n_days:]:
        path = download_backup(by_date[d][1], repo=repo)
        if path:
            try:
                out[d] = load_backup(path)
            except Exception as e:  # noqa: BLE001
                print(f"[DASH] gh 백업 로드 실패 {d}: {type(e).__name__}")
    return out
