"""send_telegram_summary.build_brief 단위 테스트.

핵심 검증(2026-07-20): code_change_suspected 시 알림이 원인을 구분한다 —
  · 일시 차단(circuit_breaker)  → '자동 재시도'(사람 점검 불필요)
  · 구조 신호(대량변경/무결성/성공률급락/K분포) → '파서 점검 필요'
네트워크 0 — build_brief 에 summary dict 를 직접 주입한다.
"""

from scripts.send_telegram_summary import build_brief

TS = "7/20 15:07"


def _brief(summary: dict) -> str:
    return build_brief(summary=summary, ts=TS)


# ---------------------------------------------------------------------------
# 정상
# ---------------------------------------------------------------------------
class TestSuccess:
    def test_clean_success(self):
        msg = _brief({"success_rate": 1.0, "total_rows_processed": 400})
        assert msg.startswith("✅")
        assert "성공률 100%" in msg
        assert "점검 필요" not in msg

    def test_success_with_transient_block_note(self):
        msg = _brief(
            {"success_rate": 0.95, "total_rows_processed": 400, "circuit_breaker_blocks": 3}
        )
        assert msg.startswith("✅")
        assert "차단 3회" in msg


# ---------------------------------------------------------------------------
# 일시 차단(회로차단) — '자동 재시도', '점검 필요' 아님  ← 이번 수정의 핵심
# ---------------------------------------------------------------------------
class TestTransientBlock:
    def test_circuit_breaker_is_transient_not_inspection(self):
        msg = _brief(
            {
                "success_rate": 0.0,
                "code_change_suspected": True,
                "circuit_breaker_tripped": True,
                "circuit_breaker_blocks": 5,
            }
        )
        assert "자동 재시도" in msg
        assert "점검 필요" not in msg  # 헛알람 방지 = 이번 수정의 목적
        assert "파서" not in msg

    def test_circuit_breaker_shows_block_count(self):
        msg = _brief(
            {
                "success_rate": 0.1,
                "code_change_suspected": True,
                "circuit_breaker_tripped": True,
                "circuit_breaker_blocks": 5,
            }
        )
        assert "5회" in msg


# ---------------------------------------------------------------------------
# 구조변경 — '파서 점검 필요'
# ---------------------------------------------------------------------------
class TestStructuralChange:
    def test_bulk_guard_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.8,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
                "type_preview_write_blocked_by_bulk_guard": True,
            }
        )
        assert msg.startswith("🔴")
        assert "파서 점검 필요" in msg
        assert "대량변경 가드" in msg

    def test_low_success_without_block_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.1,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
            }
        )
        assert "파서 점검 필요" in msg
        assert "성공률 급락" in msg

    def test_invariant_violation_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.85,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
                "post_write_audit_violations": 2,
            }
        )
        assert "파서 점검 필요" in msg
        assert "데이터 무결성" in msg

    def test_k_anomaly_only_is_structural(self):
        """성공률 정상이어도 K분포 급변만으로 code_change → 구조 점검."""
        msg = _brief(
            {
                "success_rate": 0.95,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
            }
        )
        assert "파서 점검 필요" in msg


# ---------------------------------------------------------------------------
# 부분 실패(코드변경 아님) + 파일 폴백
# ---------------------------------------------------------------------------
class TestPartialAndFallback:
    def test_partial_fail_no_code_change(self):
        msg = _brief({"success_rate": 0.7, "code_change_suspected": False})
        assert "일부 실패" in msg
        assert "점검 필요" not in msg

    def test_missing_file_fallback(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # cycle_summary.json 없음
        msg = build_brief(ts=TS)
        assert "시작 전 중단" in msg
