"""워치독 실패 알림 스크립트. rank-check 워크플로 실패 시 텔레그램으로 보고.

호출: scripts/notify_run_failure.py
환경변수:
  RUN_URL     — 실패한 run 의 GitHub 링크
  RUN_ATTEMPT — 실패 run 의 run_attempt 숫자 (문자열)
  RETRYING    — '1' 이면 자동 재시도 중, '0' 이면 재시도도 실패

비차단: 텔레그램 실패·환경변수 누락 시 0 exit (워치독 job 을 죽이지 않음).
민감정보 로그 노출 금지 — 예외 시 type(e).__name__ 만 출력.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify import send_report  # noqa: E402


def build_failure_alert(run_url: str, attempt: int, retrying: bool, streak: int = 0) -> str:
    """실패 알림 메시지 생성 (순수 함수 — 테스트 대상).

    P1a(2026-07-01) 연속실패 에스컬레이션: streak(최근 연속 실패 수)이 커질수록 심각도↑.
    = '9일 침묵'(똑같은 실패 알림을 사장님이 무시) 방지 — 3연속 🟠, 5연속+ 🔴로 시각 차등.
    빈도가 아니라 심각도를 올린다(알림 피로 회피). streak=0(미상)이면 기존 문구 그대로.

    Args:
        run_url:  실패한 GitHub Actions run 의 URL.
        attempt:  실패 run 의 run_attempt 번호.
        retrying: True → 자동 재시도 중 / False → 재시도도 실패, 사람 확인 필요.
        streak:   최근 연속 실패 run 수(워치독이 gh 이력으로 계산). 0=미상.

    Returns:
        사장님용 한국어 텔레그램 메시지 문자열.
    """
    if retrying:
        msg = (
            "⚠️ 상노 점검 실패 — 자동 재시도 중입니다.\n"
            f"실패 기록: {run_url}\n"
            "(재시도 결과는 곧 다시 알림)"
        )
        if streak >= 3:
            msg += f"\n※ 최근 {streak}연속 실패 — 일시적 장애가 아닐 수 있어요."
        return msg
    # 재시도도 실패 → 사람 확인 필요. streak 로 심각도 차등.
    if streak >= 5:
        head = f"🔴 상노 점검 {streak}연속 실패 — 구조적 문제일 수 있어요. 사람 확인이 필요해요.\n"
    elif streak >= 3:
        head = f"🟠 상노 점검 {streak}연속 실패 — 사람 확인이 필요해요.\n"
    else:
        head = f"🚨 상노 점검이 {attempt}차 시도까지 실패했습니다. 사람 확인이 필요해요.\n"
    return head + f"실패 기록: {run_url}"


def main() -> int:
    """env 읽어 알림 발송. 예외 전부 잡고 0 반환(비차단)."""
    try:
        run_url = os.environ.get("RUN_URL", "").strip()
        attempt_str = os.environ.get("RUN_ATTEMPT", "1").strip()
        retrying_str = os.environ.get("RETRYING", "0").strip()

        try:
            attempt = int(attempt_str)
        except ValueError:
            attempt = 1

        try:
            streak = int(os.environ.get("STREAK", "0").strip())
        except ValueError:
            streak = 0

        retrying = retrying_str == "1"

        if not run_url:
            run_url = "(링크 없음)"

        msg = build_failure_alert(run_url=run_url, attempt=attempt, retrying=retrying, streak=streak)
        send_report(msg)
    except Exception as e:  # noqa: BLE001 — 토큰/URL 등 민감정보 로그 노출 금지
        print(f"[WATCHDOG-NOTIFY] 예외 — 비차단 반환(0): {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
