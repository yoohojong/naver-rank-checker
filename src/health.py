"""health: 파싱 성공률 모니터링, 네이버 selector/코드 변경 자동 감지.

출력 = GitHub Actions logs (사장님이 Actions 탭에서 봄). 5회 연속 실패 시 시트에 알림 가능 (T-M7.2).

2026-05-08 사례: 네이버가 `desktop_mode` → `fds-default-mode` 변경. 만약 사전에 health check
있었다면 변경 즉시 감지 + 사장님 알림 가능 (사후 디버그 X).
"""
from typing import Optional


class HealthMonitor:
    """파싱 결과 누적 + 임계치 기반 코드 변경 의심 신호."""

    SUCCESS_RATE_THRESHOLD = 0.90  # 90% 미만이면 의심
    LOW_CONFIDENCE_THRESHOLD = 0.5  # avg confidence < 0.5 + 표본 ≥ 10
    MIN_SAMPLES_FOR_DETECTION = 10  # 표본 부족하면 판단 X

    def __init__(self):
        self.records: list[dict] = []
        self.block_failures: dict[str, int] = {}

    def record(
        self,
        parser_confidence: float,
        success: bool,
        block_type: Optional[str] = None,
    ) -> None:
        """한 키워드 처리 결과 기록.

        Args:
            parser_confidence: parser 의 confidence (0.0 ~ 1.0)
            success: 검색 성공 여부 (차단/네트워크 실패는 False)
            block_type: 실패 시 어떤 블록 종류였나 (예: 'AB', '인기글')
        """
        self.records.append({"confidence": parser_confidence, "success": success})
        if not success and block_type:
            self.block_failures[block_type] = self.block_failures.get(block_type, 0) + 1

    def summary(self) -> dict:
        """전체 요약. code_change_suspected = True 면 사장님께 알림 권장."""
        total = len(self.records)
        if total == 0:
            return {
                "total": 0,
                "success_count": 0,
                "success_rate": 1.0,
                "avg_confidence": 0.0,
                "block_failures": {},
                "code_change_suspected": False,
            }

        success_count = sum(1 for r in self.records if r["success"])
        rate = success_count / total
        avg_conf = sum(r["confidence"] for r in self.records) / total

        # 코드 변경 의심 조건:
        # 1) 성공률 < 90% (네이버 차단 + selector 변경 둘 다 포함)
        # 2) avg confidence < 0.5 + 표본 ≥ 10 (검색은 성공하는데 매칭 거의 X)
        suspected = (
            (total >= self.MIN_SAMPLES_FOR_DETECTION and rate < self.SUCCESS_RATE_THRESHOLD)
            or (total >= self.MIN_SAMPLES_FOR_DETECTION and avg_conf < self.LOW_CONFIDENCE_THRESHOLD)
        )

        return {
            "total": total,
            "success_count": success_count,
            "success_rate": rate,
            "avg_confidence": avg_conf,
            "block_failures": dict(self.block_failures),
            "code_change_suspected": suspected,
        }

    def log_summary(self) -> None:
        """GitHub Actions logs 출력."""
        s = self.summary()
        print(f"=== Health Summary ===")
        print(f"Total: {s['total']}, Success: {s['success_count']} ({s['success_rate']*100:.1f}%)")
        print(f"Avg parser confidence: {s['avg_confidence']:.2f}")
        if s["block_failures"]:
            print(f"Block failures: {s['block_failures']}")
        if s["code_change_suspected"]:
            print("⚠️ CODE_CHANGE_SUSPECTED — 네이버 selector 변경 의심. 디버그 필요.")
