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

        def fake_send_report(text: str) -> int:
            captured_calls.append(text)
            return 0

        with mock.patch.dict(os.environ, base_env, clear=False):
            with mock.patch(
                "scripts.notify_run_failure.send_report", side_effect=fake_send_report
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

    def test_send_report_exception_nonblocking(self):
        """send_report 가 예외를 던져도 main() 은 0 반환(비차단)."""
        with mock.patch.dict(os.environ, {"RUN_URL": "https://x", "RETRYING": "1"}):
            with mock.patch(
                "scripts.notify_run_failure.send_report", side_effect=RuntimeError("boom")
            ):
                rc = main()
        assert rc == 0
