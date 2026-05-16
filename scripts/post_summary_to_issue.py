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
    """2026-05-11 CRITICAL fix: K 분포 + 탭 이름 제거 (사장님 비즈니스 데이터 노출 방지).
    단순 메타 (시간/행수/셀수/성공률/상태) 만 기록. 자세한 내용 = Actions log 링크 클릭.

    D-024 (2026-05-14): d024_skipped_rows 추가 (예외 시 시트 보존 skip 카운트 가시성).
    """
    success_rate = summary.get("success_rate", 0)
    success_pct = f"{success_rate * 100:.1f}%"
    cells = summary.get("total_cells_written", 0)
    rows = summary.get("total_rows_processed", 0)
    seconds = summary.get("cycle_seconds", 0)
    minutes = seconds // 60
    sec_remain = seconds % 60
    retry_left = summary.get("retry_queue_remaining", 0)
    code_change = summary.get("code_change_suspected", False)
    d024_skipped = summary.get("d024_skipped_rows", 0)
    # T-M90 (D-027 보강 2026-05-17) architect Opus C1 fix: 사장님 가시성 = CAFE_WHITELIST 미설정 시 즉시 인지.
    cafe_whitelist_size = summary.get("cafe_whitelist_size", 0)
    all_known_links_count = summary.get("all_known_links_count", 0)

    health_status = "🚨 code_change_suspected" if code_change else "✅ 정상"

    if cafe_whitelist_size == 0:
        whitelist_line = "\n⚠️ **CAFE_WHITELIST_SLUGS secrets 미설정** — D-026 빈 link 자동 채움 비활성 상태. GitHub Settings → Secrets → CAFE_WHITELIST_SLUGS 등록 의무."
    else:
        whitelist_line = f"\n**D-026 화이트리스트**: {cafe_whitelist_size} slug / 매치 link {all_known_links_count}건"

    return f"""{OWNER_MENTION} ## ✅ cron 완료 — {format_kst()}

**처리 시간**: {minutes}분 {sec_remain}초
**처리 행**: {rows} 행
**시트 갱신**: {cells} 셀
**성공률**: {success_pct}
**재시도 큐 남음**: {retry_left}
**예외 시 시트 보존 (D-024)**: {d024_skipped} 행
**상태**: {health_status}{whitelist_line}

---
자세한 내역 (탭별 / K 분포 등) = Actions log 링크 클릭:
[GitHub Actions Run](https://github.com/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')})
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
