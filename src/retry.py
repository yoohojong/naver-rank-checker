"""retry: 1차 실패 행 재시도 큐 (슬로우다운 강화 후 최대 2회).

main.py 흐름 (T-M7.2 + T-M39):
1. 시트 read → 각 행 검색 + parser → 결과 누적
2. 차단/네트워크 실패 시 RetryQueue.add(row, error="...")
3. 본 사이클 끝나면 RetryQueue.process(processor_fn) 로 최대 2회 재시도
   - 1차 retry: slowdown_multiplier=2.0
   - 2차 retry: slowdown_multiplier=4.0 (T-M39: 추가 재시도)
4. 그래도 실패면 K 보존 (시트 write 안 함, 다음 cron 자연 재처리)
"""
import time
from typing import Callable


class RetryQueue:
    """1차 실패 행 보존 + 슬로우다운 강화 후 최대 2회 재시도 (T-M39)."""

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
        """큐의 모든 행을 슬로우다운 강화 간격으로 최대 2회 재시도 (T-M39).

        Args:
            processor_fn: row dict → update dict (예: {"노출영역": "AB", ...}).
                          실패 시 raise.
            slowdown_multiplier: 1차 재시도 sleep 배수 (기본 2.0).
                                 2차 재시도는 자동으로 2배 추가 (4.0).

        Returns:
            list of {"row": dict, "update": dict | None, "ok": bool, "error": str (실패 시)}

        T-M39: 1차 retry (multiplier×1) → 실패 시 2차 retry (multiplier×2).
        2차도 실패면 ok=False로 반환 (호출자가 K 보존 결정).
        """
        results: list[dict] = []
        base_delay = 1.0  # 1초 base × multiplier
        # T-M39: (1차 multiplier, 2차 multiplier) 순서
        retry_multipliers = (slowdown_multiplier, slowdown_multiplier * 2)
        for item in self._items:
            last_error: str = ""
            success = False
            update = None
            for attempt, multiplier in enumerate(retry_multipliers, start=1):
                time.sleep(base_delay * multiplier)
                try:
                    update = processor_fn(item["row"])
                    success = True
                    break
                except Exception as e:
                    last_error = str(e)
            if success:
                results.append({"row": item["row"], "update": update, "ok": True})
            else:
                results.append({
                    "row": item["row"],
                    "update": None,
                    "ok": False,
                    "error": last_error,
                })
        return results

    def clear(self) -> None:
        """큐 비우기 (process 후 정리용)."""
        self._items.clear()
