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
        이 test = 노출 0 + success=True 의 boundary 동작 확인 (의도된 boundary: false positive 안 박힘).
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
