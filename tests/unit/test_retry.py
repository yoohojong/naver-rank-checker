"""retry 단위 테스트."""
import pytest
from unittest.mock import patch

from src.retry import RetryQueue


class TestRetryQueueBasic:
    def test_empty_queue(self):
        q = RetryQueue()
        assert len(q) == 0
        assert q.items() == []

    def test_add_single_row(self):
        q = RetryQueue()
        q.add({"_row": 5, "키워드": "test"}, error="rate_limited")
        assert len(q) == 1
        items = q.items()
        assert items[0]["row"]["_row"] == 5
        assert items[0]["error"] == "rate_limited"

    def test_add_multiple_preserves_order(self):
        q = RetryQueue()
        q.add({"_row": 2}, "err_a")
        q.add({"_row": 7}, "err_b")
        q.add({"_row": 4}, "err_c")
        items = q.items()
        assert [it["row"]["_row"] for it in items] == [2, 7, 4]

    def test_clear_empties_queue(self):
        q = RetryQueue()
        q.add({"_row": 1}, "err")
        q.clear()
        assert len(q) == 0

    def test_items_returns_copy_not_reference(self):
        """items() 결과를 수정해도 내부 큐 영향 X."""
        q = RetryQueue()
        q.add({"_row": 1}, "err")
        snapshot = q.items()
        snapshot.append({"row": {"_row": 999}, "error": "fake"})
        assert len(q) == 1  # 원본 큐 그대로


class TestRetryQueueProcess:
    def test_process_all_success(self):
        q = RetryQueue()
        q.add({"_row": 2, "키워드": "a"}, "err")
        q.add({"_row": 5, "키워드": "b"}, "err")

        with patch("src.retry.time.sleep"):
            results = q.process(lambda r: {"K": "AB"}, slowdown_multiplier=0)
        assert len(results) == 2
        assert all(r["ok"] for r in results)
        assert results[0]["update"] == {"K": "AB"}

    def test_process_mixed_success_failure(self):
        q = RetryQueue()
        q.add({"_row": 2, "키워드": "good"}, "err")
        q.add({"_row": 3, "키워드": "bad"}, "err")

        def processor(row):
            if row["키워드"] == "bad":
                raise RuntimeError("재시도도 실패")
            return {"K": "AB"}

        with patch("src.retry.time.sleep"):
            results = q.process(processor, slowdown_multiplier=0)
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert "재시도도 실패" in results[1]["error"]

    def test_process_slowdown_multiplier_applied(self):
        """slowdown_multiplier 가 sleep 호출 인자에 반영."""
        q = RetryQueue()
        q.add({"_row": 1}, "err")
        with patch("src.retry.time.sleep") as mock_sleep:
            q.process(lambda r: {}, slowdown_multiplier=3.0)
        # base_delay 1.0 * 3.0 = 3.0
        mock_sleep.assert_called_with(3.0)

    def test_process_empty_queue_returns_empty_list(self):
        q = RetryQueue()
        results = q.process(lambda r: {})
        assert results == []

    def test_process_doesnt_clear_queue(self):
        """process 가 자동으로 queue clear 안 함 (호출자가 clear 결정)."""
        q = RetryQueue()
        q.add({"_row": 1}, "err")
        with patch("src.retry.time.sleep"):
            q.process(lambda r: {})
        assert len(q) == 1  # 여전히 있음


class TestRetryQueueTwoAttempts:
    """T-M39 (2026-05-12): 2회 retry — 1차(×2.0) + 2차(×4.0) 강화."""

    def test_two_attempts_on_first_failure(self):
        """1차 실패 → 2차 재시도 → 성공 = ok=True."""
        q = RetryQueue()
        q.add({"_row": 1, "키워드": "test"}, "err")

        call_count = 0
        def processor(row):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("1차 실패")
            return {"K": "AB"}

        with patch("src.retry.time.sleep"):
            results = q.process(processor, slowdown_multiplier=2.0)

        assert results[0]["ok"] is True
        assert call_count == 2  # 2회 시도

    def test_both_attempts_fail_returns_false(self):
        """1차 + 2차 모두 실패 = ok=False, error 기록."""
        q = RetryQueue()
        q.add({"_row": 2, "키워드": "bad"}, "err")

        def always_fail(row):
            raise RuntimeError("계속 실패")

        with patch("src.retry.time.sleep"):
            results = q.process(always_fail, slowdown_multiplier=2.0)

        assert results[0]["ok"] is False
        assert "계속 실패" in results[0]["error"]

    def test_sleep_called_twice_per_item(self):
        """항목 1개당 sleep 2회 (1차 + 2차) 호출."""
        q = RetryQueue()
        q.add({"_row": 1}, "err")

        def always_fail(row):
            raise RuntimeError("fail")

        with patch("src.retry.time.sleep") as mock_sleep:
            q.process(always_fail, slowdown_multiplier=2.0)

        assert mock_sleep.call_count == 2

    def test_sleep_multipliers_correct(self):
        """1차 sleep = base×2.0, 2차 sleep = base×4.0."""
        import unittest.mock as mock_mod
        q = RetryQueue()
        q.add({"_row": 1}, "err")

        sleep_calls = []

        def always_fail(row):
            raise RuntimeError("fail")

        with patch("src.retry.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            q.process(always_fail, slowdown_multiplier=2.0)

        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(2.0)   # base(1.0) × 2.0
        assert sleep_calls[1] == pytest.approx(4.0)   # base(1.0) × 4.0

    def test_two_items_each_gets_two_attempts(self):
        """항목 2개 모두 실패 → 총 sleep 4회 (항목당 2회)."""
        q = RetryQueue()
        q.add({"_row": 1}, "err")
        q.add({"_row": 2}, "err")

        with patch("src.retry.time.sleep") as mock_sleep:
            q.process(lambda r: (_ for _ in ()).throw(RuntimeError("fail")), slowdown_multiplier=1.0)

        assert mock_sleep.call_count == 4

    def test_first_item_success_second_fails(self):
        """항목1 1차 성공, 항목2 2차도 실패 = 각각 ok/fail."""
        q = RetryQueue()
        q.add({"_row": 1, "키워드": "good"}, "err")
        q.add({"_row": 2, "키워드": "bad"}, "err")

        def processor(row):
            if row["키워드"] == "bad":
                raise RuntimeError("bad row")
            return {"K": "AB"}

        with patch("src.retry.time.sleep"):
            results = q.process(processor, slowdown_multiplier=1.0)

        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
