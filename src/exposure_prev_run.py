"""노출 급감 '바로 앞 실행' 확인 (2026-10-30 품질 3차 지적 3-1).

왜 만들었나
    '멈춤은 한 회차만'(정책 A)은 앞 회차 기록 파일(Actions 캐시)만 보고 '바로 앞 회차가 멈춤'이라고 믿었다.
    그 사이에 기록을 못 남긴 회차(기록 저장 실패 · 기록 전에 죽음 · 캐시 저장 실패)가 끼면 옛 멈춤 기록이
    그대로 남아, 다음 새 급감을 '두 회차 연속 같은 급감'으로 풀어 써 버렸다.
    이제 '바로 앞 회차'는 기록이 아니라 실행 순서로 확인한다.

바로 앞 실행 = 이 워크플로에서 실행 번호(run_number)가 이번 실행보다 하나 작은 실행.
    실행 번호는 워크플로마다 1씩 늘고 다시 돌려도(rerun) 그대로다. 그 실행이 목록에 딱 하나 있고 끝나 있을 때만
    '<실행 id>:<마지막 시도 번호>' 를 낸다. 못 찾으면(조회 실패 · 열쇠 없음 · 목록에 없음 · 안 끝남) 빈 값 + 이유.
    대기 중에 취소돼 한 번도 안 돈 실행도 번호를 하나 먹는다 — 그 실행은 기록이 없으니 다음 회차는 멈춤(안전 쪽).
    결과는 EXPOSURE_DROP_PREV_RUN · EXPOSURE_DROP_PREV_RUN_WHY 두 환경값($GITHUB_ENV)으로 다음 단계에 넘긴다.
    조회는 GitHub API 두 번(GITHUB_TOKEN · permissions actions: read — 이미 있음). 키워드 · 링크는 오가지 않는다.

쓰는 법(rank-check.yml)
    python -m src.exposure_prev_run find           → $GITHUB_ENV 에 위 두 값
    python -m src.exposure_prev_run own <기록 경로> → $GITHUB_OUTPUT 에 own=true|false
        기록 파일이 이번 실행 · 이번 시도가 쓴 것일 때만 true — 저장 실패 · 기록 전 죽음으로 남은 옛 기록을
        이번 실행 열쇠로 다시 캐시에 보관하지 않게(전에는 always()+파일 존재만 봤다).

스위치 · 되돌리기: 이 파일과 워크플로의 'Find previous run' · 'Check own exposure-drop state' 두 단계를 지우면
    앞 실행 확인이 꺼져 급감은 늘 멈춤(EXPOSURE_DROP_PREV_RUN 이 비면 재확인 안 함). 주인: 순위체커 운영 담당.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable, Optional

ENV_PREV_RUN = "EXPOSURE_DROP_PREV_RUN"
ENV_PREV_RUN_WHY = "EXPOSURE_DROP_PREV_RUN_WHY"

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")   # exposure_drop_guard 의 기록 실행 번호와 같은 모양
_NUM_RE = re.compile(r"^[0-9]{1,20}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PER_PAGE = 30
TIMEOUT_SEC = 20


def format_prev(run_id: object, attempt: object) -> str:
    return f"{run_id}:{attempt}"


def parse_prev(value: object) -> Optional[tuple[str, int]]:
    """'<실행 id>:<시도 번호>' → (실행 id, 시도 번호). 비었거나 모양이 다르면 None(= 확인 못 함)."""
    s = str(value or "").strip()
    if s.count(":") != 1:
        return None
    rid, att = s.split(":")
    if not RUN_ID_RE.match(rid) or not _NUM_RE.match(att) or int(att) < 1:
        return None
    return rid, int(att)


def _http_get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "naver-rank-checker-exposure-drop",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_previous_run(
    repo: str,
    run_id: str,
    get_json: Callable[[str], dict],
    api: str = "https://api.github.com",
) -> tuple[str, str]:
    """반환 (값, 이유). 값 = '<실행 id>:<시도 번호>' 또는 ''(확인 못 함 — 이유에 까닭)."""
    if not _REPO_RE.match(str(repo or "")):
        return "", "저장소 이름 없음"
    if not _NUM_RE.match(str(run_id or "")):
        return "", "이번 실행 번호 없음"
    try:
        me = get_json(f"{api}/repos/{repo}/actions/runs/{run_id}")
        wf = int(me["workflow_id"])
        my_no = int(me["run_number"])
        page = get_json(f"{api}/repos/{repo}/actions/workflows/{wf}/runs?per_page={PER_PAGE}")
        runs = list(page["workflow_runs"])
    except Exception as e:  # noqa: BLE001 — 조회 실패는 '확인 못 함'(멈춤 쪽)
        return "", f"앞 실행 조회 실패({type(e).__name__})"
    want = my_no - 1
    if want < 1:
        return "", "이번이 이 워크플로의 첫 실행"
    hits = [r for r in runs if isinstance(r, dict) and r.get("run_number") == want
            and str(r.get("id")) != str(run_id)]
    if len(hits) != 1:
        return "", f"바로 앞 실행(번호 {want})을 목록에서 {len(hits)}개 찾음"
    prev = hits[0]
    if prev.get("status") != "completed":
        return "", f"바로 앞 실행(번호 {want})이 아직 안 끝남({prev.get('status')})"
    pid, att = str(prev.get("id")), prev.get("run_attempt")
    if not _NUM_RE.match(pid) or isinstance(att, bool) or not isinstance(att, int) or att < 1:
        return "", f"바로 앞 실행(번호 {want})의 번호 모양이 다름"
    return format_prev(pid, att), f"바로 앞 실행 = 번호 {want}(결과 {prev.get('conclusion')})"


def is_own_record(path: str, run_id: str, attempt: str) -> bool:
    """기록 파일이 이번 실행 · 이번 시도가 쓴 것인가. 못 읽으면 False(캐시에 안 남김)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return (
            isinstance(raw, dict)
            and str(raw.get("run_id")) == str(run_id)
            and str(raw.get("run_attempt")) == str(attempt)
        )
    except Exception:  # noqa: BLE001
        return False


def _append(target: Optional[str], lines: list[str]) -> None:
    if not target:
        for ln in lines:
            print(ln)
        return
    with open(target, "a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln.replace("\n", " ").replace("\r", " ") + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    if cmd == "find":
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if not token:
            value, why = "", "앞 실행 조회 열쇠 없음"
        else:
            api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
            value, why = find_previous_run(
                os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", ""),
                lambda url: _http_get_json(url, token), api=api,
            )
        _append(os.environ.get("GITHUB_ENV"), [f"{ENV_PREV_RUN}={value}", f"{ENV_PREV_RUN_WHY}={why}"])
        print(f"[노출급감] 바로 앞 실행: {value or '확인 못 함'} — {why}")
        return 0
    if cmd == "own" and len(argv) >= 2:
        own = is_own_record(argv[1], os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        _append(os.environ.get("GITHUB_OUTPUT"), [f"own={'true' if own else 'false'}"])
        print(f"[노출급감] 기록이 이번 실행 · 이번 시도 것: {own}")
        return 0
    print("쓰는 법: python -m src.exposure_prev_run find | own <기록 경로>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
