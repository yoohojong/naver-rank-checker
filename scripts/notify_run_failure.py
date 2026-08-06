"""워치독 실패 알림 스크립트. rank-check 워크플로 실패 시 텔레그램으로 보고.

호출: scripts/notify_run_failure.py
환경변수:
  RUN_URL     — 실패한 run 의 GitHub 링크
  RUN_ATTEMPT — 실패 run 의 run_attempt 숫자 (문자열)
  RETRYING    — '1' 이면 자동 재시도 중, '0' 이면 재시도도 실패
  STREAK      — 최근 연속 실패 수 (문자열, 미상이면 '0')
  CAUSE       — 'runner'(기계 미배정) / 'billing'(결제·한도) / 그 외(=우리 코드 실패)
  CONCLUSION  — run 의 결론('failure'/'cancelled'/'timed_out'/'startup_failure')

★2026-08-07 종료코드 의미가 바뀌었다: **한 통도 못 보냈으면 1 로 끝난다.**
  예전엔 무조건 0 이라, 봇 토큰이 회전되거나 시크릿이 지워져 한 통도 안 나가도
  워크플로는 초록이었고 curl 최후수단도 안 돌았다(로그에 [SKIP] 만 쌓였다).
  워치독 스텝은 continue-on-error 라 1 을 내도 job 은 안 죽는다 — 대신 최후수단이 이어받는다.
민감정보 로그 노출 금지 — 예외 시 type(e).__name__ 만 출력.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify import send_telegram, split_message  # noqa: E402


def build_failure_alert(run_url: str, attempt: int, retrying: bool, streak: int = 0,
                        cause: str = "", conclusion: str = "") -> str:
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
        conclusion: run 의 결론. 'failure' 가 아니면(cancelled 등) 문구에 그대로 밝힌다.

    Returns:
        사장님용 한국어 텔레그램 메시지 문자열. **어떤 경우에도 빈 문자열이 아니다.**
    """
    # 'failure' 가 아닌 결론도 이제 여기로 온다(cancelled/timed_out/startup_failure).
    # 무슨 일이 있었는지는 사장님이 알아야 하므로 문구 끝에 한 줄로 덧붙인다.
    꼬리 = ""
    if conclusion and conclusion != "failure":
        _한글 = {"cancelled": "중단됨", "timed_out": "시간 초과",
                 "startup_failure": "시작 실패"}.get(conclusion, conclusion)
        꼬리 = f"\n(실패가 아니라 '{_한글}' 로 끝났습니다)"
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
                f"저절로 풀리지 않아요. 결제 상태 확인이 필요해요: {run_url}" + 꼬리)
    if cause == "runner":
        # 기계 미배정은 우리 코드 문제가 아니고 다음 회차(하루 8회)가 잇는다 → 알리되 조용한 톤.
        # ★단, 하루치가 통째로 날아가는 지점(5회)에서는 사다리를 끝까지 올린다.
        #   순위는 그 시각에만 잴 수 있어 나중에 못 채운다 — 그 정도면 수동 실행이 필요하다.
        if streak >= 5:
            return (f"🔴 상노 점검이 {streak}회 연속 시작조차 못 했습니다 "
                    f"(GitHub 이 계속 실행할 기계를 못 붙이고 있습니다).\n"
                    f"이 정도면 하루치 순위가 통째로 빕니다. 수동 실행이 필요해요: {run_url}" + 꼬리)
        if streak >= 2:
            return (f"🟠 상노 점검이 {streak}회 연속 시작조차 못 했습니다 "
                    f"(GitHub 이 실행할 기계를 못 붙임 — 우리 코드 문제 아님).\n"
                    f"이어지면 확인이 필요해요: {run_url}" + 꼬리)
        # ★'조치는 필요 없어요' 라고 단언하지 않는다 — 다음 회차가 실제로 돌았는지 확인하는
        #   코드가 어디에도 없다. 확인 안 된 미래를 약속하면 사장님이 잘못 안심한다.
        return ("🟡 상노 점검 1회가 시작조차 못 했습니다 "
                "(GitHub 이 실행할 기계를 못 붙임 — 우리 코드 문제 아님).\n"
                f"다음 회차 결과를 다시 알려드립니다: {run_url}" + 꼬리)
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
    return head + f"실패 기록: {run_url}" + 꼬리


def main() -> int:
    """env 읽어 알림 발송. **한 통도 못 보냈으면 1** (최후수단이 이어받도록)."""
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
        conclusion = os.environ.get("CONCLUSION", "").strip().lower()

        msg = build_failure_alert(run_url=run_url, attempt=attempt, retrying=retrying,
                                  streak=streak, cause=cause, conclusion=conclusion)
        # msg 는 절대 비지 않는다(test_어떤_조합에서도_침묵하지_않는다 가 지킨다).
        # 혹시라도 비면 그건 침묵이므로, 삼키지 말고 평소 경보로 되돌린다 — fail-closed.
        if not msg:
            msg = build_failure_alert(run_url=run_url, attempt=attempt,
                                      retrying=retrying, streak=streak)
        print(f"[notify] 사유={cause or 'code'} streak={streak} 결론={conclusion or '-'} — 발송")

        # ★send_report 를 안 쓰는 이유: 그것은 발송 실패를 읽지 않고 무조건 0 을 돌려준다.
        #   그러면 봇 토큰이 회전돼 한 통도 안 나가도 스텝이 성공으로 보이고,
        #   뒤에 둔 curl 최후수단이 영원히 안 돈다 = 통로가 둘이 아니라 하나였던 셈.
        chunks = split_message(msg) or [msg]
        보냄 = sum(1 for c in chunks if send_telegram(c))
        if 보냄 == 0:
            print("[WATCHDOG-NOTIFY] 텔레그램 0건 발송 — 실패로 끝낸다(최후수단이 이어받는다)")
            return 1
    except Exception as e:  # noqa: BLE001 — 토큰/URL 등 민감정보 로그 노출 금지
        print(f"[WATCHDOG-NOTIFY] 예외 — 최후수단으로 넘긴다: {type(e).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
