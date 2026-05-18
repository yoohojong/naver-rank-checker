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

        # 2026-05-11 T-M9.2 fix: 노출된 record (conf > 0) 만 평균에 포함함.
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

    # 운영 1 (2026-05-18): D-026/D-029 K enum 자연 변경 = false alert 회피 화이트리스트.
    # 신규 enum 등장 = 시스템 진화 (= D-026 스마트블록 부활 / D-029 중복노출 sub 3종) = anomaly 판정 X.
    # 근거: 사장님 단호 시그널 = 신규 enum 자연 변경 = 메일 false alert 회피 의무.
    _NATURAL_NEW_ENUM = frozenset({
        "중복노출",
        "중복노출(AB)",
        "중복노출(스마트블록)",
        "중복노출(인기글)",
        "누락",
        "삭제",
        "스마트블록",  # D-026 부활 = 이전 cron 분포에 없을 수 있음
    })

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

        운영 1 (2026-05-18): D-026/D-029 K enum 자연 변경 = false alert 회피.
        prev 에 0 + curr 에 등장한 _NATURAL_NEW_ENUM 키 = 시스템 진화 (= 누락/중복노출/삭제 등).
        그 신규 enum 등장 = 기존 enum (예: 미노출) 자연 감소 = 자연 변경 = anomaly 판정 X.
        구현 = 신규 _NATURAL_NEW_ENUM 등장 시 = prev 분포 안 미노출 (등) 에 그 양 만큼 가상 분배 후 비교.

        D-030 (2026-05-18): K 값 + 시점 통합 표기 = "AB (5/10 03:00~)" 형식.
        분포 비교 = base 만 (= 시점 제거) — 시점 다를 뿐 같은 base = 동일 분포 의미.
        main.py 가 base 누적하지만, 외부 호출자 호환 정합 = 함수 안 base 추출 방어.
        """
        if not prev_k_distribution or not current_k_distribution:
            return False

        # D-030 (2026-05-18): base 추출 후 분포 재집계 (= 시점 다를 뿐 같은 base 통합)
        # parse_K_with_stamp import (= 순환 import 회피 = 함수 안 local import)
        from src.transitions import parse_K_with_stamp

        def _aggregate_by_base(dist: dict) -> dict:
            result: dict = {}
            for k_full, v in dist.items():
                base, _ = parse_K_with_stamp(k_full)
                base = base or "미노출"
                result[base] = result.get(base, 0) + v
            return result

        prev_k_distribution = _aggregate_by_base(prev_k_distribution)
        current_k_distribution = _aggregate_by_base(current_k_distribution)

        # 운영 1: curr 안 신규 _NATURAL_NEW_ENUM 키 검출 = 시스템 진화 흡수
        normalized_curr = dict(current_k_distribution)
        absorbed_total = 0
        for k in list(normalized_curr.keys()):
            if (
                prev_k_distribution.get(k, 0) == 0
                and normalized_curr.get(k, 0) > 0
                and k in self._NATURAL_NEW_ENUM
            ):
                absorbed_total += normalized_curr.pop(k)

        # 흡수된 양 = 자연 재분류 대상 키에 가상 분배 (= prev 대비 감소량 가장 큰 키들 비례 흡수).
        # 근거: 신규 _NATURAL_NEW_ENUM 등장 = 기존 enum 의 자연 재분류 (예: AB → 스마트블록 = AB 흡수,
        # 미노출 → 누락 = 미노출 흡수). 감소 추이로 자연 흡수 키 자동 추론.
        if absorbed_total > 0:
            # 각 기존 키별 감소량 (prev > curr 인 키) 산출
            decreases: dict[str, int] = {}
            for k_prev, v_prev in prev_k_distribution.items():
                v_curr = normalized_curr.get(k_prev, 0)
                if v_prev > v_curr:
                    decreases[k_prev] = v_prev - v_curr

            if decreases:
                total_decrease = sum(decreases.values())
                # 감소량 비례 분배 (= 자연 흡수)
                for k_dec, dec_amount in decreases.items():
                    share = int(round(absorbed_total * (dec_amount / total_decrease)))
                    normalized_curr[k_dec] = normalized_curr.get(k_dec, 0) + share
            else:
                # 감소 키 없음 (= 모든 prev 키 안정) = pivot fallback (미노출 우선)
                if "미노출" in prev_k_distribution and prev_k_distribution["미노출"] > 0:
                    pivot = "미노출"
                else:
                    pivot = max(prev_k_distribution.keys(), key=lambda kk: prev_k_distribution[kk])
                normalized_curr[pivot] = normalized_curr.get(pivot, 0) + absorbed_total

        total_prev = sum(prev_k_distribution.values()) or 1
        total_curr = sum(normalized_curr.values()) or 1
        keys = set(prev_k_distribution.keys()) | set(normalized_curr.keys())
        for k in keys:
            prev_pct = prev_k_distribution.get(k, 0) / total_prev
            curr_pct = normalized_curr.get(k, 0) / total_curr
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
