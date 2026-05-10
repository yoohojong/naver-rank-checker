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
