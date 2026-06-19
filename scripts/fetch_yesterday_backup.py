"""직전 성공 cron 백업(sheet-backup artifact) 입수. M10 T-M10.6.

저녁/아침 요약 보고가 "어제 대비" 변화를 계산하려면 이전 백업이 필요하다.
critic 정합:
- "어제" = 절대 24h 아님 → **status=success 인 직전 run** 의 백업(cron 누락에 강건).
- 다운로드는 **artifact·로그 경로 밖 임시 디렉터리**(RUNNER_TEMP/tempfile)로 격리 → 실데이터 재업로드/로그 노출 차단.
- 실패(첫 운영/retention 14일 경계/인증)는 None 반환 → 보고측이 "비교 기준 없음" 처리.

gh CLI 권한: 별 워크플로(telegram-report.yml)에서 rank-check.yml artifact 입수 시
`permissions: actions: read` + `ACTIONS_PAT || github.token` 필요(yml 측 처리).
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from typing import Optional

WORKFLOW = "rank-check.yml"
ARTIFACT_PREFIX = "sheet-backup-"


def _run_gh(args: list, *, capture_json: bool = False):
    """gh CLI 호출. 실패 시 capture_json=True → [], else (returncode, stdout, stderr)."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if capture_json:
        if proc.returncode != 0:
            print(f"[FETCH-BACKUP] gh 실패: {proc.stderr.strip()[:200]}")  # 로그 노출 절단
            return []
        try:
            return json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            print("[FETCH-BACKUP] gh JSON 파싱 실패")
            return []
    return proc


def list_success_runs(workflow: str = WORKFLOW, limit: int = 30, repo: Optional[str] = None) -> list:
    """status=success 인 최근 run 목록 (databaseId, createdAt, headSha)."""
    args = [
        "run", "list", "--workflow", workflow, "--status", "success",
        "--limit", str(limit), "--json", "databaseId,createdAt,headSha",
    ]
    if repo:
        args += ["--repo", repo]
    return _run_gh(args, capture_json=True)


def pick_previous_success(runs: list, exclude_run_id: Optional[str] = None) -> Optional[str]:
    """가장 최근 성공 run id (현재 run 제외). createdAt 내림차순 정렬 — 순수 함수(테스트 대상)."""
    candidates = [r for r in runs if str(r.get("databaseId")) != str(exclude_run_id or "")]
    if not candidates:
        return None
    candidates.sort(key=lambda r: str(r.get("createdAt", "")), reverse=True)
    return str(candidates[0].get("databaseId"))


def download_backup(run_id: str, dest_dir: Optional[str] = None, repo: Optional[str] = None) -> Optional[str]:
    """run_id 의 sheet-backup artifact 다운로드 → .json.gz 경로. 임시경로 격리."""
    dest = dest_dir or tempfile.mkdtemp(prefix="ydaybackup_", dir=os.environ.get("RUNNER_TEMP") or None)
    args = ["run", "download", str(run_id), "-n", f"{ARTIFACT_PREFIX}{run_id}", "-D", dest]
    if repo:
        args += ["--repo", repo]
    proc = _run_gh(args)
    if proc.returncode != 0:
        print(f"[FETCH-BACKUP] download 실패(run={run_id}): {proc.stderr.strip()[:200]}")
        return None
    # gh run download 가 아티팩트명 하위 디렉터리를 만들 수 있어 재귀 탐색(code-review HIGH)
    for root, _dirs, files in os.walk(dest):
        for fn in sorted(files):
            if fn.endswith(".json.gz") or fn.endswith(".json"):
                return os.path.join(root, fn)
    print(f"[FETCH-BACKUP] artifact 안에 백업 파일 없음(run={run_id})")
    return None


def fetch_previous_backup(exclude_run_id: Optional[str] = None, repo: Optional[str] = None) -> Optional[str]:
    """직전 성공 백업 .json.gz 경로. 없으면 None(비교 기준 없음)."""
    run_id = pick_previous_success(list_success_runs(repo=repo), exclude_run_id=exclude_run_id)
    if not run_id:
        print("[FETCH-BACKUP] 직전 성공 run 없음 (첫 운영/retention 경계) → 비교 기준 없음")
        return None
    return download_backup(run_id, repo=repo)


def _parse_iso(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def pick_run_near_hours(
    runs: list,
    reference_iso: Optional[str],
    hours: float = 24.0,
    tolerance_h: float = 5.0,
    exclude_run_id: Optional[str] = None,
) -> Optional[str]:
    """reference 기준 hours 전에 가장 가까운 성공 run id (±tolerance). 없으면 None — 순수 함수.

    일일 보고(저녁/아침)의 "어제" = 24h 전 같은 시간대 슬롯(cron 4슬롯/6h 간격).
    cron 누락으로 ±tolerance 안에 없으면 None → 보고측이 "비교 기준 없음" 처리.
    """
    ref = _parse_iso(reference_iso)
    if ref is None:
        return None
    target = ref - timedelta(hours=hours)
    best_id = None
    best_delta = None
    for r in runs:
        if str(r.get("databaseId")) == str(exclude_run_id or ""):
            continue
        t = _parse_iso(r.get("createdAt"))
        if t is None:
            continue
        delta = abs((t - target).total_seconds())
        if delta <= tolerance_h * 3600 and (best_delta is None or delta < best_delta):
            best_delta = delta
            best_id = str(r.get("databaseId"))
    return best_id
