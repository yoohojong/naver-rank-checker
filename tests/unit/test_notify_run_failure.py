"""워치독 실패 알림 스크립트 단위 테스트.

테스트 대상:
  - build_failure_alert(): retrying True/False 각 분기 메시지 검증
  - main(): send_report monkeypatch → 호출 인자 검증 (네트워크 0)
"""

import os
from unittest import mock

import pytest

from scripts.notify_run_failure import build_failure_alert, main


# ---------------------------------------------------------------------------
# build_failure_alert — 순수 함수
# ---------------------------------------------------------------------------

class TestBuildFailureAlert:
    def test_retrying_true_contains_run_url(self):
        url = "https://github.com/example/repo/actions/runs/12345"
        msg = build_failure_alert(run_url=url, attempt=1, retrying=True)
        assert url in msg

    def test_retrying_true_keyword(self):
        msg = build_failure_alert(run_url="https://x", attempt=1, retrying=True)
        assert "자동 재시도" in msg

    def test_retrying_false_contains_run_url(self):
        url = "https://github.com/example/repo/actions/runs/99999"
        msg = build_failure_alert(run_url=url, attempt=2, retrying=False)
        assert url in msg

    def test_retrying_false_keyword(self):
        msg = build_failure_alert(run_url="https://x", attempt=2, retrying=False)
        assert "사람 확인" in msg

    def test_retrying_true_no_human_check_phrase(self):
        """재시도 중 메시지에는 '사람 확인'이 없어야 한다."""
        msg = build_failure_alert(run_url="https://x", attempt=1, retrying=True)
        assert "사람 확인" not in msg

    def test_retrying_false_no_retry_phrase(self):
        """재시도 실패 메시지에는 '자동 재시도 중' 문구가 없어야 한다."""
        msg = build_failure_alert(run_url="https://x", attempt=2, retrying=False)
        # '자동 재시도까지 실패'는 있지만 '자동 재시도 중'은 없어야 함
        assert "자동 재시도 중" not in msg


# ---------------------------------------------------------------------------
# main() — env 분기 + send_report 호출 검증
# ---------------------------------------------------------------------------

class TestMain:
    def _run_main(self, env_overrides: dict) -> tuple:
        """env 세팅 후 main() 실행. (return_code, send_report 호출 인자 리스트) 반환."""
        base_env = {
            "RUN_URL": "https://github.com/example/repo/actions/runs/111",
            "RUN_ATTEMPT": "1",
            "RETRYING": "1",
            # 텔레그램 secret 은 monkeypatch 로 막으므로 불필요하지만 안전하게 제거
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }
        base_env.update(env_overrides)

        captured_calls = []

        def fake_send_telegram(text: str, **kw) -> bool:
            captured_calls.append(text)
            return True

        with mock.patch.dict(os.environ, base_env, clear=False):
            with mock.patch(
                "scripts.notify_run_failure.send_telegram", side_effect=fake_send_telegram
            ):
                rc = main()

        return rc, captured_calls

    def test_main_returns_zero(self):
        rc, _ = self._run_main({})
        assert rc == 0

    def test_retrying_branch_send_report_called(self):
        _, calls = self._run_main({"RETRYING": "1", "RUN_ATTEMPT": "1"})
        assert len(calls) == 1

    def test_retrying_branch_message_contains_url(self):
        url = "https://github.com/example/repo/actions/runs/222"
        _, calls = self._run_main({"RETRYING": "1", "RUN_URL": url})
        assert url in calls[0]

    def test_retrying_branch_message_keyword(self):
        _, calls = self._run_main({"RETRYING": "1"})
        assert "자동 재시도" in calls[0]

    def test_non_retrying_branch_send_report_called(self):
        _, calls = self._run_main({"RETRYING": "0", "RUN_ATTEMPT": "2"})
        assert len(calls) == 1

    def test_non_retrying_branch_message_contains_url(self):
        url = "https://github.com/example/repo/actions/runs/333"
        _, calls = self._run_main({"RETRYING": "0", "RUN_URL": url, "RUN_ATTEMPT": "2"})
        assert url in calls[0]

    def test_non_retrying_branch_message_keyword(self):
        _, calls = self._run_main({"RETRYING": "0", "RUN_ATTEMPT": "2"})
        assert "사람 확인" in calls[0]

    def test_missing_run_url_does_not_raise(self):
        """RUN_URL 미설정 시 예외 없이 0 반환."""
        rc, calls = self._run_main({"RUN_URL": ""})
        assert rc == 0
        assert len(calls) == 1

    def test_invalid_attempt_str_does_not_raise(self):
        """RUN_ATTEMPT 가 숫자가 아닐 때도 예외 없이 0 반환."""
        rc, _ = self._run_main({"RUN_ATTEMPT": "bad"})
        assert rc == 0

    def test_발송이_터지면_1을_반환한다(self):
        """★예외를 삼켜 0 을 돌려주면 curl 최후수단이 안 돈다 = 완전 침묵(2026-08-07)."""
        with mock.patch.dict(os.environ, {"RUN_URL": "https://x", "RETRYING": "1"}):
            with mock.patch(
                "scripts.notify_run_failure.send_telegram", side_effect=RuntimeError("boom")
            ):
                rc = main()
        assert rc == 1, "발송이 터졌는데 성공으로 끝냈다 — 최후수단이 이어받지 못한다"

    def test_한_통도_못_보내면_1을_반환한다(self):
        """봇 토큰 회전·시크릿 삭제 — 이때 초록으로 끝나면 며칠을 모른다."""
        with mock.patch.dict(os.environ, {"RUN_URL": "https://x", "RETRYING": "1"}):
            with mock.patch("scripts.notify_run_failure.send_telegram", return_value=False):
                rc = main()
        assert rc == 1

    def test_보냈으면_0을_반환한다(self):
        with mock.patch.dict(os.environ, {"RUN_URL": "https://x", "RETRYING": "1"}):
            with mock.patch("scripts.notify_run_failure.send_telegram", return_value=True):
                rc = main()
        assert rc == 0


class Test실패_사유는_말투만_바꾼다:
    """GitHub 이 실행할 기계를 못 붙여 '시작조차 못 한' 실패 (2026-08-06 실사고).

    그날 상노 점검이 실패했고, 그걸 고치려던 워치독까지 **같은 이유로** 죽었다
    (워치독 job 은 스텝 0개로 15분 02초 만에 cancelled — run 31122290959 실측).

    ★2026-08-07: 처음엔 '1회면 알리지 않는다'로 만들었다가 독립 리뷰에서 뒤집혔다.
      기계 미배정은 드문드문 오기 때문에 연속 2회가 거의 안 생기고, 연속 수 계산이
      실패하면 0으로 떨어져 또 침묵한다 — '안 알림'이 사실상 기본값이 되어 있었다.
      그래서 **사유는 침묵 여부가 아니라 말투만 바꾼다.** 여기 검사들이 그걸 지킨다.
    """

    def test_어떤_조합에서도_침묵하지_않는다(self):
        """★이 검사가 이 파일의 핵심이다. 빈 메시지 = 사장님이 아무것도 못 받음."""
        for cause in ("", "code", "unknown", "runner", "billing", "이상한값"):
            for streak in (0, 1, 2, 3, 5, 9):
                for retrying in (True, False):
                    msg = build_failure_alert(run_url="u", attempt=1, retrying=retrying,
                                              streak=streak, cause=cause)
                    assert msg, f"침묵했다: cause={cause} streak={streak} retrying={retrying}"

    def test_기계_미배정은_1회여도_알린다(self):
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=1, cause="runner")
        assert "기계를 못 붙임" in msg
        assert "우리 코드 문제 아님" in msg

    def test_기계_미배정_1회는_사람을_부르지_않는다(self):
        """다음 회차가 잇는 상황이다 — 지금 뭘 해야 하는 것처럼 읽히면 안 된다.

        ★단 '조치는 필요 없다'고 단언하지도 않는다. 다음 회차가 실제로 돌았는지
          확인하는 코드가 없어서, 확인 안 된 미래를 약속하면 잘못 안심시킨다.
        """
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=1, cause="runner")
        assert "사람 확인이 필요" not in msg
        assert "조치는 필요 없" not in msg
        assert "다시 알려드립니다" in msg

    def test_기계_미배정도_이어지면_톤이_올라간다(self):
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=3, cause="runner")
        assert "3회 연속" in msg
        assert "확인이 필요해요" in msg

    def test_결제_한도는_1회여도_사람을_부른다(self):
        """저절로 안 낫는다 — 기계 미배정과 같은 통에 넣으면 안 된다."""
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=1, cause="billing")
        assert "결제" in msg
        assert "확인이 필요해요" in msg
        assert "조치는 필요 없어요" not in msg

    def test_진짜_코드_실패는_그대로_알린다(self):
        """과잉 완화 금지 — 사유가 아니면 예전대로 경보가 나가야 한다."""
        msg = build_failure_alert(run_url="u", attempt=2, retrying=False, streak=1, cause="code")
        assert "사람 확인" in msg

    def test_사유를_모르면_평소대로_알린다(self):
        """판별 실패가 침묵이 되면 안 된다(fail-closed)."""
        for cause in ("", "unknown", "알수없음"):
            msg = build_failure_alert(run_url="u", attempt=2, retrying=False,
                                      streak=1, cause=cause)
            assert "사람 확인" in msg, f"cause={cause} 에서 평소 경보가 사라졌다"

    def test_시작조차_못_했으면_재시도중_문구를_덮어쓴다(self):
        msg = build_failure_alert(run_url="u", attempt=1, retrying=True, streak=3, cause="runner")
        assert "기계를 못 붙임" in msg

    def test_기본값은_기존_동작(self):
        """cause 인자를 안 주면 예전과 똑같아야 한다(회귀 방지)."""
        assert "자동 재시도" in build_failure_alert(run_url="u", attempt=1, retrying=True)
        assert "사람 확인" in build_failure_alert(run_url="u", attempt=2, retrying=False)


class Test환경변수_배선이_살아있는가:
    """★순수 함수만 검사하면 배선이 끊겨도 전부 초록이다(2026-08-07 리뷰 지적).

    실제로 `cause = os.environ.get("CAUSE",...)` 를 `cause = ""` 로 바꿔도 검사가
    전부 통과했다. main() 이 env 를 읽어 실제로 다른 메시지를 보내는지 여기서 본다.
    """

    def _send(self, env: dict) -> str:
        base = {"RUN_URL": "https://x/1", "RUN_ATTEMPT": "1", "RETRYING": "0",
                "STREAK": "1", "CAUSE": "", "CONCLUSION": "failure",
                "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
        base.update(env)
        sent = []

        def 받음(t, **kw):
            sent.append(t)
            return True

        with mock.patch.dict(os.environ, base, clear=False):
            with mock.patch("scripts.notify_run_failure.send_telegram", side_effect=받음):
                rc = main()
        assert rc == 0
        assert len(sent) == 1, f"발송이 1건이 아니다({len(sent)}건) — 침묵했거나 중복 발송"
        return sent[0]

    def test_CAUSE_runner_가_메시지에_반영된다(self):
        assert "기계를 못 붙임" in self._send({"CAUSE": "runner"})

    def test_CAUSE_billing_이_메시지에_반영된다(self):
        assert "결제" in self._send({"CAUSE": "billing"})

    def test_CAUSE_없으면_평소_경보(self):
        assert "사람 확인" in self._send({"CAUSE": ""})

    def test_CAUSE_unknown_도_평소_경보(self):
        assert "사람 확인" in self._send({"CAUSE": "unknown"})

    def test_대소문자_공백이_섞여도_읽는다(self):
        """워크플로 출력이 ' Runner\\n' 처럼 와도 분류가 살아야 한다."""
        assert "기계를 못 붙임" in self._send({"CAUSE": "  RUNNER  "})

    def test_STREAK_가_메시지에_반영된다(self):
        assert "4회 연속" in self._send({"CAUSE": "runner", "STREAK": "4"})

    def test_STREAK_를_못_재도_알린다(self):
        """연속 수 계산 스텝이 실패해 빈 값이 와도 침묵하면 안 된다."""
        assert self._send({"CAUSE": "runner", "STREAK": ""})

    def test_CONCLUSION_이_failure_가_아니면_문구에_밝힌다(self):
        """cancelled 로 끝난 점검도 이제 여기로 온다 — 뭉뚱그려 '실패'라 하면 안 된다."""
        msg = self._send({"CONCLUSION": "cancelled"})
        assert "중단됨" in msg

    def test_CONCLUSION_이_failure_면_군더더기가_없다(self):
        assert "중단됨" not in self._send({"CONCLUSION": "failure"})


class Test하루치가_날아가는_지점에서는_사다리를_끝까지_올린다:
    """★회귀 방지. cause=runner 를 넣으면서 기존 5연속 🔴 층이 사라져 있었다.

    하루 8회 중 5회가 죽으면 그날 순위는 통째로 빈다. 순위는 그 시각에만 잴 수 있고
    나중에 채워 넣지 못한다 — '이어지면 확인' 정도로 넘길 일이 아니다.
    """

    def test_5연속이면_runner_도_빨간불(self):
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=5, cause="runner")
        assert "🔴" in msg
        assert "수동 실행" in msg

    def test_2연속은_아직_주황(self):
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=2, cause="runner")
        assert "🟠" in msg

    def test_1회는_노랑이고_미래를_단언하지_않는다(self):
        """'조치는 필요 없어요' 는 확인 안 된 미래 약속이었다 — 잘못 안심시킨다."""
        msg = build_failure_alert(run_url="u", attempt=1, retrying=False, streak=1, cause="runner")
        assert "🟡" in msg
        assert "조치는 필요 없" not in msg

    def test_코드_실패_사다리는_그대로(self):
        """cause 도입이 기존 층을 건드리지 않았는지."""
        assert "🔴" in build_failure_alert(run_url="u", attempt=2, retrying=False, streak=5)
        assert "🟠" in build_failure_alert(run_url="u", attempt=2, retrying=False, streak=3)
        assert "🚨" in build_failure_alert(run_url="u", attempt=2, retrying=False, streak=1)
