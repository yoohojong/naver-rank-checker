"""cron 사이클 완료 후 cycle_summary.json 을 GitHub Issue #1 의 comment 로 게시.

GitHub Actions workflow 의 "Post summary" step 에서 호출됨.
실패해도 workflow 영향 X (exit 0 강제).
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

ISSUE_NUMBER = "1"
REPO = "yoohojong/naver-rank-checker"
OWNER_MENTION = "@yoohojong"  # mention = GitHub 가 사장님에게 자동 이메일 (Settings 무관)


def format_kst() -> str:
    """현재 시각 (KST) 한 줄."""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")


def build_failure_comment(reason: str) -> str:
    return f"""{OWNER_MENTION} ## ❌ cron 실패 — {format_kst()}

**원인**: {reason}

실 로그 확인: [GitHub Actions Run](https://github.com/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')})

Claude 에게 보고 권장."""


def build_success_comment(summary: dict) -> str:
    total = summary.get("total", 0)
    success_rate = summary.get("success_rate", 0)
    success_pct = f"{success_rate * 100:.1f}%"
    avg_conf = summary.get("avg_confidence", 0)
    avg_conf_str = f"{avg_conf:.2f}"
    cells = summary.get("total_cells_written", 0)
    rows = summary.get("total_rows_processed", 0)
    seconds = summary.get("cycle_seconds", 0)
    minutes = seconds // 60
    sec_remain = seconds % 60
    retry_left = summary.get("retry_queue_remaining", 0)
    tabs = summary.get("tabs_processed", [])
    k_dist = summary.get("k_distribution", {})
    code_change = summary.get("code_change_suspected", False)

    health_status = "🚨 code_change_suspected" if code_change else "✅ 정상"

    k_lines = []
    k_order = ["AB", "인기글", "삭제", "미노출"]
    for k in k_order:
        if k in k_dist:
            k_lines.append(f"- {k}: {k_dist[k]} 행")
    for k, v in k_dist.items():
        if k not in k_order:
            k_lines.append(f"- {k}: {v} 행")
    k_block = "\n".join(k_lines) if k_lines else "_(데이터 없음)_"

    tabs_str = ", ".join(tabs) if tabs else "_(없음)_"

    return f"""{OWNER_MENTION} ## ✅ cron 완료 — {format_kst()}

**처리 시간**: {minutes}분 {sec_remain}초
**대상 탭**: {tabs_str}
**처리 행**: {rows} 행 (네이버 검색 + parser)
**시트 갱신**: {cells} 셀

### Health
- 성공률: **{success_pct}** ({summary.get('success_count', 0)}/{total})
- avg parser confidence: {avg_conf_str}
- 재시도 큐 남음: {retry_left}
- 상태: {health_status}

### K 컬럼 분포 (이번 갱신)
{k_block}

---
실 로그: [GitHub Actions Run](https://github.com/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')})
"""


def main() -> int:
    run_status = os.environ.get("RUN_STATUS", "unknown")  # workflow 에서 전달

    if os.path.exists("cycle_summary.json"):
        try:
            with open("cycle_summary.json", encoding="utf-8") as f:
                summary = json.load(f)
            comment = build_success_comment(summary)
        except Exception as e:
            comment = build_failure_comment(f"cycle_summary.json 읽기 실패: {e}")
    else:
        # main.py 가 summary 작성 전 죽음 (env 누락, json BOM, 인증 실패 등)
        comment = build_failure_comment(
            f"cycle_summary.json 미생성. run_status={run_status}. main.py 가 사이클 시작 전 실패한 듯."
        )

    # gh issue comment via stdin (CLAUDE.md prohibited_actions 영역 X — 본인 repo own issue comment)
    proc = subprocess.run(
        ["gh", "issue", "comment", ISSUE_NUMBER, "--repo", REPO, "--body", comment],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"[WARN] gh issue comment 실패: {proc.stderr}", file=sys.stderr)
        # workflow 영향 없게 0 반환
        return 0
    print(f"✅ comment posted to issue #{ISSUE_NUMBER}: {proc.stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
