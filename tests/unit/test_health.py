"""health 단위 테스트."""
import pytest

from src.health import HealthMonitor


class TestHealthMonitorBasic:
    def test_empty_summary(self):
        h = HealthMonitor()
        s = h.summary()
        assert s["total"] == 0
        assert s["success_rate"] == 1.0  # 빈 = 정상 가정
        assert s["code_change_suspected"] is False

    def test_record_and_count(self):
        h = HealthMonitor()
        h.record(parser_confidence=0.9, success=True)
        h.record(parser_confidence=0.85, success=True)
        h.record(parser_confidence=0.0, success=False)
        s = h.summary()
        assert s["total"] == 3
        assert s["success_count"] == 2
        assert s["success_rate"] == pytest.approx(2 / 3)

    def test_avg_confidence(self):
        h = HealthMonitor()
        h.record(parser_confidence=0.9, success=True)
        h.record(parser_confidence=0.8, success=True)
        s = h.summary()
        assert s["avg_confidence"] == pytest.approx(0.85)

    def test_block_failures_tracked(self):
        h = HealthMonitor()
        h.record(0.0, success=False, block_type="AB")
        h.record(0.0, success=False, block_type="AB")
        h.record(0.0, success=False, block_type="인기글")
        s = h.summary()
        assert s["block_failures"] == {"AB": 2, "인기글": 1}


class TestHealthMonitorAlerts:
    def test_high_success_rate_no_alert(self):
        h = HealthMonitor()
        for _ in range(20):
            h.record(parser_confidence=0.9, success=True)
        assert h.summary()["code_change_suspected"] is False

    def test_low_success_rate_triggers_alert(self):
        """성공률 < 90% + 표본 ≥ 10 → 의심."""
        h = HealthMonitor()
        for _ in range(8):
            h.record(parser_confidence=0.0, success=False)
        for _ in range(2):
            h.record(parser_confidence=0.9, success=True)
        # 표본 10, 성공률 20% < 90%
        assert h.summary()["code_change_suspected"] is True

    def test_low_confidence_triggers_alert(self):
        """성공률은 OK 인데 avg confidence < 0.5 → 의심 (selector 변경 가능성)."""
        h = HealthMonitor()
        for _ in range(15):
            # 성공 처리됐지만 confidence 매우 낮음
            h.record(parser_confidence=0.3, success=True)
        s = h.summary()
        assert s["success_rate"] == 1.0
        assert s["avg_confidence"] < 0.5
        assert s["code_change_suspected"] is True

    def test_small_sample_no_alert(self):
        """표본 < 10 이면 판단 X (false positive 방지)."""
        h = HealthMonitor()
        for _ in range(5):
            h.record(parser_confidence=0.0, success=False)
        # 성공률 0% but 표본 5 < 10 → 미발동
        assert h.summary()["code_change_suspected"] is False

    def test_threshold_constants_match_spec(self):
        """spec 변경 시 알림 — 임계치 명시 검증."""
        assert HealthMonitor.SUCCESS_RATE_THRESHOLD == 0.90
        assert HealthMonitor.MIN_SAMPLES_FOR_DETECTION == 10

    def test_unexposed_dominant_no_false_alert(self):
        """2026-05-11 T-M9.2 회귀 방지: UNEXPOSED record (conf=0 + success=True) 우세 시 false alert 발동 X.

        시나리오: 사장님 시트 832 행 중 대부분 미노출 keyword (정상). 30 미노출 + 5 노출 (conf 0.9).
        옛 식: avg = (0*30 + 0.9*5) / 35 = 0.129 < 0.5 → suspected=True (false positive).
        신 식: 노출 record 만 평균 = 0.9*5 / 5 = 0.9 → suspected=False ✅.
        """
        h = HealthMonitor()
        for _ in range(30):
            h.record(parser_confidence=0.0, success=True)  # 의도된 미노출 (정상)
        for _ in range(5):
            h.record(parser_confidence=0.9, success=True)  # 정상 노출
        s = h.summary()
        assert s["avg_confidence"] == pytest.approx(0.9)
        assert s["code_change_suspected"] is False

    def test_all_unexposed_triggers_alert(self):
        """모든 keyword 미노출 (노출 0건) = 진짜 회귀 신호 → alert 발동.

        avg_conf = 0.0 + 노출 표본 = 0 → 노출 조건 충족 X. 다만 fetch 성공 success=True 면 rate 조건도 미충족.
        실제 회귀 시나리오 = success=False 누적 (차단/예외). 그건 rate 조건으로 검출.
        이 test = 노출 0 + success=True 의 boundary 동작 확인 (의도된 boundary: false positive 발생하지 않음).
        """
        h = HealthMonitor()
        for _ in range(20):
            h.record(parser_confidence=0.0, success=True)  # 모두 미노출 + fetch 성공
        s = h.summary()
        # 노출 0건이지만 fetch 모두 성공 = 시트가 통째 미노출 keyword 인 경우 자연스러운 상태
        # success_rate=1.0, 노출 표본 0 → 두 조건 다 미충족 → suspected=False
        assert s["avg_confidence"] == 0.0
        assert s["success_rate"] == 1.0
        assert s["code_change_suspected"] is False


class TestDetectKAnomaly:
    """T-M38 (2026-05-12): K 분포 anomaly 감지 — 이전 cron 대비 20% 이상 변동."""

    def test_no_anomaly_stable_distribution(self):
        """분포 변동 없음 = anomaly False."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        curr = {"AB": 28, "미노출": 72}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_anomaly_ab_drops_drastically(self):
        """AB 30% → 5% = -25% 변동 → threshold 20% 초과 = anomaly True."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        curr = {"AB": 5, "미노출": 95}
        assert h.detect_k_anomaly(prev, curr) is True

    def test_anomaly_new_key_appears(self):
        """이전에 없던 K 값 대거 등장 = anomaly True.

        운영 1 (2026-05-18) 정합 갱신: _NATURAL_NEW_ENUM 외 신규 enum 만 anomaly True.
        ('삭제' 등 자연 변경 enum = 신규 _NATURAL_NEW_ENUM 화이트리스트 = false alert 회피.)
        """
        h = HealthMonitor()
        prev = {"AB": 50, "미노출": 50}
        # "오류상태" = _NATURAL_NEW_ENUM 외 = 알 수 없는 변경 = anomaly True 유지
        curr = {"AB": 25, "미노출": 25, "오류상태": 50}
        assert h.detect_k_anomaly(prev, curr) is True

    def test_no_anomaly_within_threshold(self):
        """10% 변동 = threshold 20% 이하 = anomaly False."""
        h = HealthMonitor()
        prev = {"AB": 40, "미노출": 60}
        curr = {"AB": 30, "미노출": 70}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_empty_prev_returns_false(self):
        """이전 분포 없음 (첫 cron) = 비교 불가 = False."""
        h = HealthMonitor()
        assert h.detect_k_anomaly({}, {"AB": 10}) is False

    def test_empty_curr_returns_false(self):
        """현재 분포 없음 = False."""
        h = HealthMonitor()
        assert h.detect_k_anomaly({"AB": 10}, {}) is False

    def test_custom_threshold(self):
        """threshold 파라미터 커스텀 — 10% 임계치 설정."""
        h = HealthMonitor()
        prev = {"AB": 40, "미노출": 60}
        curr = {"AB": 28, "미노출": 72}
        # 12% 변동 > threshold=0.10 → True
        assert h.detect_k_anomaly(prev, curr, threshold=0.10) is True
        # 12% 변동 < threshold=0.20 → False
        assert h.detect_k_anomaly(prev, curr, threshold=0.20) is False


class TestDetectKAnomalyNaturalNewEnumMitigation:
    """운영 1 (2026-05-18): D-026/D-029 K enum 자연 변경 = false alert 회피.

    사장님 단호 시그널 = 신규 enum (= 중복노출 sub 3종 + 누락 + 미노출 + 삭제 + 스마트블록) 자연 변경 =
    anomaly 판정 X (= 메일 false alert 차단). 기존 enum 의 급변만 진짜 anomaly.
    """

    def test_natural_new_enum_중복노출_no_alert(self):
        """D-029 정합: prev 에 없던 '중복노출(AB)' curr 등장 = anomaly X (= 시스템 진화)."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        # D-029 부활 후 = 중복노출(AB) 대거 등장 = 자연 변경
        curr = {"AB": 30, "미노출": 40, "중복노출(AB)": 30}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_natural_new_enum_누락_no_alert(self):
        """D-026 정합: prev 에 없던 '누락' curr 등장 = anomaly X (= 시스템 진화)."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        curr = {"AB": 25, "미노출": 50, "누락": 25}  # 누락 신규 25%
        assert h.detect_k_anomaly(prev, curr) is False

    def test_natural_new_enum_스마트블록_no_alert(self):
        """D-026 정합: prev 에 없던 '스마트블록' curr 등장 = anomaly X (= 부활 자연 변경)."""
        h = HealthMonitor()
        prev = {"AB": 50, "미노출": 50}
        curr = {"AB": 25, "미노출": 50, "스마트블록": 25}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_natural_new_enum_삭제_no_alert(self):
        """D-026 Phase E+F 정합: prev 에 없던 '삭제' curr 등장 = anomaly X."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        curr = {"AB": 30, "미노출": 40, "삭제": 30}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_existing_enum_change_still_triggers_alert(self):
        """기존 enum (= AB / 미노출 등) 급변 = 진짜 anomaly 유지."""
        h = HealthMonitor()
        prev = {"AB": 50, "미노출": 50}
        # AB 50% → 5% = -45% 변동 = 진짜 anomaly (= 차단 / DOM 변경 신호)
        curr = {"AB": 5, "미노출": 95}
        assert h.detect_k_anomaly(prev, curr) is True

    def test_natural_new_enum_mixed_with_existing_change(self):
        """기존 enum 안정 + 신규 enum 등장 = anomaly X (= 자연 변경)."""
        h = HealthMonitor()
        prev = {"AB": 30, "미노출": 70}
        # AB 30% → 28% (안정) + 중복노출(인기글) 신규 등장 = 자연 변경
        curr = {"AB": 28, "미노출": 47, "중복노출(인기글)": 25}
        assert h.detect_k_anomaly(prev, curr) is False

    def test_non_natural_new_enum_still_triggers_alert(self):
        """_NATURAL_NEW_ENUM 외 신규 키 등장 = 진짜 anomaly 유지 (= 알 수 없는 변경 = 의심)."""
        h = HealthMonitor()
        prev = {"AB": 50, "미노출": 50}
        # 신규 enum "오류상태" = 화이트리스트 외 = anomaly True 유지
        curr = {"AB": 20, "미노출": 50, "오류상태": 30}
        assert h.detect_k_anomaly(prev, curr) is True


class TestHealthMonitorLogOutput:
    def test_log_summary_prints_warning_when_suspected(self, capsys):
        h = HealthMonitor()
        for _ in range(15):
            h.record(parser_confidence=0.0, success=False)
        h.log_summary()
        out = capsys.readouterr().out
        assert "CODE_CHANGE_SUSPECTED" in out

    def test_log_summary_no_warning_when_healthy(self, capsys):
        h = HealthMonitor()
        for _ in range(15):
            h.record(parser_confidence=0.9, success=True)
        h.log_summary()
        out = capsys.readouterr().out
        assert "CODE_CHANGE_SUSPECTED" not in out
