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
