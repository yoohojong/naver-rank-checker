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

        # 2026-05-11 T-M9.2 fix: 노출된 record (conf > 0) 만 평균에 박음.
        # UNEXPOSED record (conf = 0 + success=True) = 의도된 정상 상태 = noise 아님.
        # 옛 식 (all records 평균) = 미노출 우세 시트 (832 행 중 다수) 시 평균 자연스럽게 ↓ → false positive 알림.
        # 진단: probe v4 2026-05-11 — 5/5 keyword parser 정확 (4 미노출 + 1 노출), conf 평균 0.18.
        # 노출 keyword 만 평균 = 0.9 = 정상.
        exposed_records = [r for r in self.records if r["confidence"] > 0]
        if exposed_records:
            avg_conf = sum(r["confidence"] for r in exposed_records) / len(exposed_records)
        else:
            avg_conf = 0.0  # 노출 0건 = 진짜 회귀 신호 (모든 keyword 미노출 = 차단/DOM 변경 의심)

        # 코드 변경 의심 조건:
        # 1) 성공률 < 90% (네이버 차단 + 예외 누적)
        # 2) avg confidence < 0.5 + 노출 표본 ≥ 10 (노출 keyword 의 매칭 정확도 회귀)
        suspected = (
            (total >= self.MIN_SAMPLES_FOR_DETECTION and rate < self.SUCCESS_RATE_THRESHOLD)
            or (len(exposed_records) >= self.MIN_SAMPLES_FOR_DETECTION and avg_conf < self.LOW_CONFIDENCE_THRESHOLD)
        )

        return {
            "total": total,
            "success_count": success_count,
            "success_rate": rate,
            "avg_confidence": avg_conf,
            "block_failures": dict(self.block_failures),
            "code_change_suspected": suspected,
        }

    def detect_k_anomaly(
        self,
        prev_k_distribution: dict,
        current_k_distribution: dict,
        threshold: float = 0.20,
    ) -> bool:
        """이전 cron K 분포 vs 현재 비교 — threshold 이상 변동 시 anomaly 의심.

        T-M38 (2026-05-12): AB 30% → 5% 같은 급변 = 네이버 DOM 변경 / 차단 신호.
        threshold 기본값 = 20% (절대 비율 차이). 빈 분포 입력 시 False (판단 불가).

        예: prev={"AB": 30, "미노출": 70}, curr={"AB": 5, "미노출": 95}
            AB 비율 30%→5% = -25% 변동 → threshold 20% 초과 → True
        """
        if not prev_k_distribution or not current_k_distribution:
            return False
        total_prev = sum(prev_k_distribution.values()) or 1
        total_curr = sum(current_k_distribution.values()) or 1
        keys = set(prev_k_distribution.keys()) | set(current_k_distribution.keys())
        for k in keys:
            prev_pct = prev_k_distribution.get(k, 0) / total_prev
            curr_pct = current_k_distribution.get(k, 0) / total_curr
            if abs(prev_pct - curr_pct) > threshold:
                return True
        return False

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
