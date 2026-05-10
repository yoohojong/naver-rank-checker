"""retry: 1차 실패 행 재시도 큐 (슬로우다운 강화 후 1회).

main.py 흐름 (T-M7.2):
1. 시트 read → 각 행 검색 + parser → 결과 누적
2. 차단/네트워크 실패 시 RetryQueue.add(row, error="...")
3. 본 사이클 끝나면 RetryQueue.process(processor_fn, slowdown_multiplier=2.0) 로 1회 재시도
4. 그래도 실패면 K = "실패" 로 시트 write (사장님 인지)
"""
import time
from typing import Callable


class RetryQueue:
    """1차 실패 행 보존 + 슬로우다운 강화 후 1회 재시도."""

    def __init__(self):
        self._items: list[dict] = []

    def add(self, row: dict, error: str) -> None:
        """실패 행 큐에 추가. row = 시트 데이터 dict, error = 실패 원인 (예: 'rate_limited')."""
        self._items.append({"row": row, "error": error})

    def items(self) -> list[dict]:
        """현재 큐 항목 list (read-only copy)."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def process(
        self,
        processor_fn: Callable[[dict], dict],
        slowdown_multiplier: float = 2.0,
    ) -> list[dict]:
        """큐의 모든 행을 슬로우다운 강화 간격으로 1회 재시도.

        Args:
            processor_fn: row dict → update dict (예: {"노출영역": "AB", ...}).
                          실패 시 raise.
            slowdown_multiplier: 재시도 시 sleep 배수 (기본 2.0 = 2배 느리게).

        Returns:
            list of {"row": dict, "update": dict | None, "ok": bool, "error": str (실패 시)}
        """
        results: list[dict] = []
        base_delay = 1.0  # 1초 base × multiplier
        for item in self._items:
            time.sleep(base_delay * slowdown_multiplier)
            try:
                update = processor_fn(item["row"])
                results.append({"row": item["row"], "update": update, "ok": True})
            except Exception as e:
                results.append({
                    "row": item["row"],
                    "update": None,
                    "ok": False,
                    "error": str(e),
                })
        return results

    def clear(self) -> None:
        """큐 비우기 (process 후 정리용)."""
        self._items.clear()
