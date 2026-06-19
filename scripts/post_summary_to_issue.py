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
    """운영 3 (2026-05-18): 차단 의심 키워드 포함 시 = 명시 ⚠️ 강조 + 자동 회복 안내."""
    blocked_signal = any(
        kw in reason.lower()
        for kw in ("blocked", "circuit", "차단", "circuitbreakeropen", "ratelimit", "rate limit", "429")
    )
    circuit_note = ""
    if blocked_signal:
        circuit_note = (
            "\n\n⚠️ **네이버 차단 검출 의심** "
            "(= 다음 cron 자동 회복 시도 / 6시간 cycle 안 최대 4회 재시도 윈도우)"
        )
    return f"""{OWNER_MENTION} ## ❌ cron 실패 — {format_kst()}

**원인**: {reason}{circuit_note}

실 로그 확인: [GitHub Actions Run](https://github.com/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')})

Claude 에게 보고 권장."""


def build_success_comment(summary: dict) -> str:
    """2026-05-11 CRITICAL fix: K 분포 + 탭 이름 제거 (사장님 비즈니스 데이터 노출 방지).
    단순 메타 (시간/행수/셀수/성공률/상태) 만 기록. 자세한 내용 = Actions log 링크 클릭.

    D-024 (2026-05-14): d024_skipped_rows 추가 (예외 시 시트 보존 skip 카운트 가시성).
    운영 3 (2026-05-18): circuit_breaker_blocks 추가 (네이버 차단 검출 횟수 = 사장님 메일 알림 강화).
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
    # 운영 3 (2026-05-18): 네이버 차단 검출 카운트 = 사장님 메일 알림 강화.
    circuit_breaker_blocks = summary.get("circuit_breaker_blocks", 0)
    circuit_breaker_tripped = summary.get("circuit_breaker_tripped", False)
    # D-032 (2026-05-19): 시트 불가능 조합 가시성. 행/키워드 상세는 artifact/log 로만 남김.
    prewrite_violations = summary.get("prewrite_invariant_violations", 0)
    post_write_violations = summary.get("post_write_audit_violations", 0)
    post_write_preexisting = summary.get("post_write_audit_preexisting_issues", 0)
    post_write_audit_error = summary.get("post_write_audit_error", "")
    trace_name = os.path.basename(summary.get("row_trace_path", ""))
    audit_name = os.path.basename(summary.get("post_write_audit_path", ""))
    type_preview_name = os.path.basename(summary.get("type_preview_path", ""))
    type_preview_summary_name = os.path.basename(summary.get("type_preview_summary_path", ""))
    type_preview_rows = summary.get("type_preview_rows", 0)
    type_preview_would_update = summary.get("type_preview_would_update_rows", 0)
    type_preview_bulk_guard = summary.get("type_preview_bulk_guard_triggered", False)
    type_preview_write_confirmed = summary.get("type_preview_write_confirmed", False)
    type_preview_write_requested = summary.get("type_preview_write_requested_rows", 0)
    type_preview_write_rows = summary.get("type_preview_write_rows", 0)
    type_preview_write_cells = summary.get("type_preview_write_cells", 0)
    type_preview_write_blocked = summary.get("type_preview_write_blocked_by_bulk_guard", False)
    type_preview_write_audit_violations = summary.get("type_preview_write_audit_violations", 0)
    type_preview_write_audit_name = os.path.basename(summary.get("type_preview_write_audit_path", ""))
    stale_preview_name = os.path.basename(summary.get("stale_preview_path", ""))
    stale_preview_summary_name = os.path.basename(summary.get("stale_preview_summary_path", ""))
    stale_preview_rows = summary.get("stale_preview_rows", 0)
    stale_preview_initialized = summary.get("stale_preview_initialized_rows", 0)
    stale_preview_stale = summary.get("stale_preview_stale_rows", 0)
    stale_preview_no_baseline = summary.get("stale_preview_no_baseline_rows", 0)
    stale_preview_mask = summary.get("stale_preview_would_mask_rows", 0)
    stale_formula_mode_enabled = summary.get("stale_formula_mode_enabled", False)
    stale_formula_mode_cells = summary.get("stale_formula_mode_cells_written", 0)
    stale_formula_setup = summary.get("stale_formula_mode_setup", {}) or {}

    health_status = "🚨 code_change_suspected" if code_change else "✅ 정상"

    if cafe_whitelist_size == 0:
        whitelist_line = "\n⚠️ **CAFE_WHITELIST_SLUGS secrets 미설정** — D-026 빈 link 자동 채움 비활성 상태. GitHub Settings → Secrets → CAFE_WHITELIST_SLUGS 등록 의무."
    else:
        whitelist_line = f"\n**D-026 화이트리스트**: {cafe_whitelist_size} slug / 매치 link {all_known_links_count}건"

    # 운영 3 (2026-05-18): 네이버 차단 검출 시 = 명시 ⚠️ 강조 + 다음 cron 자동 회복 시도 안내.
    if circuit_breaker_tripped or circuit_breaker_blocks > 0:
        circuit_line = (
            f"\n⚠️ **네이버 차단 검출**: {circuit_breaker_blocks}회 "
            f"(= 다음 cron 자동 회복 시도 / 6시간 cycle 안 최대 4회 재시도 윈도우)"
        )
    else:
        circuit_line = ""

    if prewrite_violations or post_write_violations:
        audit_line = (
            f"\n⚠️ **시트 불가능 조합**: write 전 {prewrite_violations}건 / write 후 {post_write_violations}건"
            f"\n**진단 artifact**: `{trace_name}` / `{audit_name}`"
        )
    elif post_write_preexisting:
        audit_line = (
            f"\nℹ️ **기존 시트 불가능 조합**: {post_write_preexisting}건 "
            f"(이번 실행 신규 오류 아님, 진단 artifact `{audit_name}`)"
        )
    elif post_write_audit_error:
        audit_line = f"\n⚠️ **시트 사후 감사 실패**: Actions log 확인 필요"
    else:
        audit_line = ""

    if type_preview_rows:
        bulk_note = " / ⚠️ 대량 변경 guard 감지" if type_preview_bulk_guard else ""
        if type_preview_write_blocked:
            write_note = (
                f"\n⚠️ **C열 유형 write**: 대량 변경 guard로 미반영 "
                f"(후보 {type_preview_would_update}행)"
            )
        elif type_preview_write_confirmed:
            audit_note = (
                f" / ⚠️ 사후감사 불일치 {type_preview_write_audit_violations}건 (`{type_preview_write_audit_name}`)"
                if type_preview_write_audit_violations
                else ""
            )
            write_note = (
                f"\n**C열 유형 write**: 요청 {type_preview_write_requested}행 / "
                f"실제 {type_preview_write_rows}행 / {type_preview_write_cells}셀 반영 완료{audit_note}"
            )
        else:
            write_note = "\n**C열 유형 write**: preview-only (미반영)"
        confirm_note = (
            "\n**문제없으면 댓글 문구**: `preview 확인했어. C열 write 허용 단계 진행해.`"
            if not type_preview_write_confirmed
            else ""
        )
        type_preview_line = (
            f"\n**유형 preview**: {type_preview_rows}행 / C열 변경 후보 {type_preview_would_update}행"
            f"{bulk_note}\n**type-preview artifact**: `{type_preview_name}`"
            f"\n**사장님 확인용 요약**: `{type_preview_summary_name}`"
            f"{write_note}"
            f"{confirm_note}"
        )
    else:
        type_preview_line = "\n**유형 preview**: 0행"

    if stale_preview_rows:
        stale_preview_line = (
            f"\n**stale-output preview**: {stale_preview_rows}행 / "
            f"초기화 {stale_preview_initialized}행 / stale {stale_preview_stale}행 / "
            f"no-baseline {stale_preview_no_baseline}행 / mask {stale_preview_mask}행"
            f"\n**stale-preview artifact**: `{stale_preview_name}`"
            f"\n**stale-preview 요약**: `{stale_preview_summary_name}`"
        )
    else:
        stale_preview_line = "\n**stale-output preview**: 0행"

    if stale_formula_mode_enabled:
        stale_formula_line = (
            f"\n**K/L/M/O stale 공식 모드**: ON / raw·입력키 write {stale_formula_mode_cells}셀"
            f" / headers+{stale_formula_setup.get('headers_added', 0)}"
            f" / backfill {stale_formula_setup.get('rows_backfilled', 0)}행"
        )
    else:
        stale_formula_line = "\n**K/L/M/O stale 공식 모드**: OFF"

    return f"""{OWNER_MENTION} ## ✅ cron 완료 — {format_kst()}

**처리 시간**: {minutes}분 {sec_remain}초
**처리 행**: {rows} 행
**시트 갱신**: {cells} 셀
**성공률**: {success_pct}
**재시도 큐 남음**: {retry_left}
**예외 시 시트 보존 (D-024)**: {d024_skipped} 행
**상태**: {health_status}{whitelist_line}{circuit_line}{audit_line}{type_preview_line}{stale_preview_line}{stale_formula_line}

---
자세한 내역 (탭별 / K 분포 등) = Actions log 링크 클릭:
[GitHub Actions Run](https://github.com/{REPO}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')})
"""


def build_comment_from_cycle() -> str:
    """cycle_summary.json → issue/telegram 공유 본문 (success/failure).

    M10 (2026-06-19): 기존 main() 본문 생성부를 그대로 이관 — 동작 불변(회귀 test).
    ⚠️ 이 함수는 **메타 전용**(시간/행수/셀수/성공률/상태). 키워드·탭명·K분포 등
    비즈니스 데이터는 절대 추가 X (공개 issue 공유분 = 텔레그램 즉시보고 공유). D-048 가드.
    """
    run_status = os.environ.get("RUN_STATUS", "unknown")  # workflow 에서 전달

    if os.path.exists("cycle_summary.json"):
        try:
            with open("cycle_summary.json", encoding="utf-8") as f:
                summary = json.load(f)
            return build_success_comment(summary)
        except Exception as e:
            return build_failure_comment(f"cycle_summary.json 읽기 실패: {e}")
    # main.py 가 summary 작성 전 죽음 (env 누락, json BOM, 인증 실패 등)
    return build_failure_comment(
        f"cycle_summary.json 미생성. run_status={run_status}. main.py 가 사이클 시작 전 실패한 듯."
    )


def main() -> int:
    comment = build_comment_from_cycle()

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
