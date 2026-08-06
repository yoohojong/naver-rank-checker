"""워치독 실패 알림 스크립트. rank-check 워크플로 실패 시 텔레그램으로 보고.

호출: scripts/notify_run_failure.py
환경변수:
  RUN_URL     — 실패한 run 의 GitHub 링크
  RUN_ATTEMPT — 실패 run 의 run_attempt 숫자 (문자열)
  RETRYING    — '1' 이면 자동 재시도 중, '0' 이면 재시도도 실패
  STREAK      — 최근 연속 실패 수 (문자열, 미상이면 '0')
  CAUSE       — 'runner'(기계 미배정) / 'billing'(결제·한도) / 그 외(=우리 코드 실패)

비차단: 텔레그램 실패·환경변수 누락 시 0 exit (워치독 job 을 죽이지 않음).
민감정보 로그 노출 금지 — 예외 시 type(e).__name__ 만 출력.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify import send_report  # noqa: E402


def build_failure_alert(run_url: str, attempt: int, retrying: bool, streak: int = 0,
                        cause: str = "") -> str:
    """실패 알림 메시지 생성 (순수 함수 — 테스트 대상).

    P1a(2026-07-01) 연속실패 에스컬레이션: streak(최근 연속 실패 수)이 커질수록 심각도↑.
    = '9일 침묵'(똑같은 실패 알림을 사장님이 무시) 방지 — 3연속 🟠, 5연속+ 🔴로 시각 차등.
    빈도가 아니라 심각도를 올린다(알림 피로 회피). streak=0(미상)이면 기존 문구 그대로.

    Args:
        run_url:  실패한 GitHub Actions run 의 URL.
        attempt:  실패 run 의 run_attempt 번호.
        retrying: True → 자동 재시도 중 / False → 재시도도 실패, 사람 확인 필요.
        streak:   최근 연속 실패 run 수(워치독이 gh 이력으로 계산). 0=미상.
        cause:    'runner' = GitHub 이 실행할 기계를 못 붙임(일시적, 다음 회차가 이음).
                  'billing' = 결제·한도로 막힘(사람이 결제해야 풀림).
                  그 외('', 'code', 'unknown') = 평소대로 = 우리 코드 실패로 간주.

    Returns:
        사장님용 한국어 텔레그램 메시지 문자열. **어떤 경우에도 빈 문자열이 아니다.**
    """
    # ★2026-08-07 재설계(독립 리뷰 REJECT 반영). 하루 전 판단이 틀렸다:
    #   "기계 미배정이 1회면 알리지 않는다"고 만들었는데, 세 가지가 겹쳐 **영구 침묵**이 된다.
    #   ① 기계 미배정은 원래 드문드문 온다 → 연속 2회가 사실상 안 생긴다(오늘도 1회로 끝났다).
    #   ② 연속 수 계산이 실패하면 0으로 떨어지고, 0 은 '알리지 않음' 쪽이다(fail-open).
    #   ③ 재시도가 새 시도를 만들어, 사유 판별이 엉뚱한 시도를 본다.
    #   → 즉 "안 알림"이 기본값이 되어 있었다. 하루 8회 중 3회가 죽어도 아무 말이 없었을 것이다.
    #   그래서 **삼키는 설계 자체를 버린다.** 사유는 침묵 여부가 아니라 **말투만** 바꾼다.
    #   판별이 틀리거나 못 하면 평소 경보가 나간다(fail-closed). 근거: '단계 실패를 삼키지 말 것'.
    if cause == "billing":
        # 결제·한도는 저절로 낫지 않는다. 사람이 결제하기 전엔 영원히 막힌다 → 톤을 낮추지 않는다.
        return (f"🔴 상노 점검이 시작조차 못 했습니다 — GitHub Actions 결제·한도 문제입니다.\n"
                f"저절로 풀리지 않아요. 결제 상태 확인이 필요해요: {run_url}")
    if cause == "runner":
        # 기계 미배정은 우리 코드 문제가 아니고 다음 회차(하루 8회)가 잇는다 → 알리되 조용한 톤.
        if streak >= 2:
            return (f"🟠 상노 점검이 {streak}회 연속 시작조차 못 했습니다 "
                    f"(GitHub 이 실행할 기계를 못 붙임 — 우리 코드 문제 아님).\n"
                    f"이어지면 확인이 필요해요: {run_url}")
        return ("🟡 상노 점검이 시작조차 못 했습니다 "
                "(GitHub 이 실행할 기계를 못 붙임 — 우리 코드 문제 아님).\n"
                f"다음 회차가 이어받습니다. 조치는 필요 없어요: {run_url}")
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

        cause = os.environ.get("CAUSE", "").strip().lower()

        msg = build_failure_alert(run_url=run_url, attempt=attempt, retrying=retrying,
                                  streak=streak, cause=cause)
        # msg 는 절대 비지 않는다(test_어떤_조합에서도_침묵하지_않는다 가 지킨다).
        # 혹시라도 비면 그건 침묵이므로, 삼키지 말고 평소 경보로 되돌린다 — fail-closed.
        if not msg:
            msg = build_failure_alert(run_url=run_url, attempt=attempt,
                                      retrying=retrying, streak=streak)
        print(f"[notify] 사유={cause or 'code'} streak={streak} — 발송")
        send_report(msg)
    except Exception as e:  # noqa: BLE001 — 토큰/URL 등 민감정보 로그 노출 금지
        print(f"[WATCHDOG-NOTIFY] 예외 — 비차단 반환(0): {type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
