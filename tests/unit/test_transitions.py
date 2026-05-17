"""transitions 단위 테스트."""
import pytest

from src.transitions import compute_new_K, EXPOSED_VALUES, SYSTEM_K_VALUES


class TestComputeNewK:
    """D-026 Phase B (2026-05-16) — K 3-enum (미노출 / 누락 / 삭제) 정합 갱신."""

    def test_first_run_not_exposed(self):
        """첫 추적 (prev_K = '') + 검색 0 → '미노출' (D-026: 명시 표기)."""
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == "미노출"

    def test_first_run_AB_exposure(self):
        """첫 추적 + 검색 found → 해당 블록."""
        assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="AB") == "AB"

    def test_first_run_popular_exposure(self):
        assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="인기글") == "인기글"

    def test_exposed_to_dropped_transition(self):
        """⭐ D-026 Phase B 핵심: 이전 AB → 지금 빠짐 → '누락' 자동 표기 (= 박스 빠짐)."""
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "누락"

    def test_popular_to_dropped_transition(self):
        """이전 인기글 → 지금 빠짐 → '누락' (D-026)."""
        assert compute_new_K(prev_K="인기글", search_found=False, url_alive=True) == "누락"

    def test_unexposed_stays_unexposed(self):
        """이전 미노출 → 지금도 검색 0 → '미노출' 유지."""
        assert compute_new_K(prev_K="미노출", search_found=False, url_alive=True) == "미노출"

    def test_dropped_recovers_to_exposure(self):
        """D-026 회복: 누락 상태에서 다시 노출 → 해당 블록."""
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="AB") == "AB"
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="인기글") == "인기글"
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="스마트블록") == "스마트블록"

    def test_dropped_stays_dropped_when_still_missing(self):
        """D-026: 누락 + 여전히 검색 0 → '누락' 유지."""
        assert compute_new_K(prev_K="누락", search_found=False, url_alive=True) == "누락"

    def test_url_dead_overrides_prev_state(self):
        """URL 자체 죽음 (404/진짜 삭제) → '삭제' (이전 상태 무관)."""
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=False) == "삭제"
        assert compute_new_K(prev_K="", search_found=False, url_alive=False) == "삭제"
        assert compute_new_K(prev_K="인기글", search_found=False, url_alive=False) == "삭제"
        assert compute_new_K(prev_K="스마트블록", search_found=False, url_alive=False) == "삭제"
        # status 매개변수 = 현재 미사용 (Phase E 텍스트 검출 도입 시 활용)
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=False, status="deleted") == "삭제"

    def test_exposed_values_constant(self):
        """D-029 (2026-05-18 — D-026 정정): 노출 단어 = AB / 스마트블록 / 인기글
        + 중복노출 (호환) + 중복노출(AB) / 중복노출(스마트블록) / 중복노출(인기글) (D-029 구좌 명시).
        모든 중복노출 sub-enum 도 EXPOSED 로 간주 = transitions = "누락" 자연 분기.
        """
        assert EXPOSED_VALUES == {
            "AB", "스마트블록", "인기글",
            "중복노출",
            "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",
        }

    def test_system_k_values_constant(self):
        """D-029 (2026-05-18 — D-026 정정): SYSTEM_K_VALUES = 우리 시스템 출력 값 (사장님 수동 편집 외 인식용).
        '중복노출(구좌)' 3종 신규 추가 (= 빈 link 행 자동 채움 + Pass 2 양방향 갱신 시 K 값).
        '중복노출' 호환 유지 (D-026 단일 값).
        """
        assert SYSTEM_K_VALUES == {
            "AB", "스마트블록", "인기글",
            "중복노출",
            "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",
            "미노출", "누락", "삭제", "실패", "",
        }

    def test_exposure_persists(self):
        """이전 AB + 지금도 AB → AB 유지 (찾았으면 area 그대로)."""
        assert compute_new_K(prev_K="AB", search_found=True, url_alive=True, area="AB") == "AB"

    def test_exposure_area_can_change(self):
        """이전 AB + 지금 인기글로 형태 변경 → 인기글."""
        assert compute_new_K(prev_K="AB", search_found=True, url_alive=True, area="인기글") == "인기글"

    def test_first_run_url_dead(self):
        """첫 추적인데 URL 이미 죽음 → '삭제'."""
        assert compute_new_K(prev_K="", search_found=False, url_alive=False) == "삭제"

    def test_manual_edit_preserved(self):
        """사장님 수동 편집 (시스템 외 값) → 보존. 우리가 덮어쓰기 X (critic 2026-05-08)."""
        # 사장님이 K 컬럼에 "확인중" 같이 수동 입력하면 우리 cron 이 그대로 유지
        assert compute_new_K(prev_K="확인중", search_found=False, url_alive=True) == "확인중"
        assert compute_new_K(prev_K="확인중", search_found=True, url_alive=True, area="AB") == "확인중"
        assert compute_new_K(prev_K="보류", search_found=False, url_alive=False) == "보류"
        # 우리 시스템 값은 정상 처리 (보존 X)
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "누락"
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == "미노출"


class TestK3EnumRegression:
    """D-026 Phase B 회귀 test 8개+ — 3-enum (미노출 / 누락 / 삭제) 정합 검증.

    사장님 plan Phase B acceptance:
    - EXPOSED_VALUES = {AB, 스마트블록, 인기글}
    - 검색 미노출 + 이전 노출 → "누락"
    - 검색 미노출 + 이전 미노출/빈 → "미노출"
    - 검색 미노출 + 이전 누락/삭제 → "누락" 유지 (자연 회복 가능)
    """

    def test_3enum_AB_to_dropped(self):
        """이전 AB → 현재 미노출 → '누락'."""
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "누락"

    def test_3enum_smart_block_to_dropped(self):
        """이전 스마트블록 → 미노출 → '누락' (D-026 부활 정합)."""
        assert compute_new_K(prev_K="스마트블록", search_found=False, url_alive=True) == "누락"

    def test_3enum_popular_to_dropped(self):
        """이전 인기글 → 미노출 → '누락'."""
        assert compute_new_K(prev_K="인기글", search_found=False, url_alive=True) == "누락"

    def test_3enum_dropped_stays_dropped(self):
        """이전 누락 → 미노출 → '누락' 유지."""
        assert compute_new_K(prev_K="누락", search_found=False, url_alive=True) == "누락"

    def test_3enum_dropped_recovers(self):
        """이전 누락 → 노출 회복 → area 그대로."""
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="AB") == "AB"
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="스마트블록") == "스마트블록"
        assert compute_new_K(prev_K="누락", search_found=True, url_alive=True, area="인기글") == "인기글"

    def test_3enum_first_run_unexposed(self):
        """첫 cron prev_K 빈 + 미노출 → '미노출' (명시 표기)."""
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == "미노출"

    def test_3enum_unexposed_stays_unexposed(self):
        """이전 '미노출' → 검색 0 → '미노출' 유지 (한 번도 노출 X)."""
        assert compute_new_K(prev_K="미노출", search_found=False, url_alive=True) == "미노출"

    def test_3enum_smart_block_exposure(self):
        """검색 = SMART_BLOCK area → '스마트블록' 표기 (D-026 부활)."""
        assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="스마트블록") == "스마트블록"
        assert compute_new_K(prev_K="미노출", search_found=True, url_alive=True, area="스마트블록") == "스마트블록"

    def test_3enum_manual_edit_preserved(self):
        """사장님 수동 입력 SYSTEM_K_VALUES 외 → 보존 (D-018 정합)."""
        assert compute_new_K(prev_K="확인중", search_found=False, url_alive=True) == "확인중"
        assert compute_new_K(prev_K="작업중", search_found=True, url_alive=True, area="AB") == "작업중"
        # SYSTEM_K_VALUES 안 값 = 보존 X (= 우리 시스템 값 = 정상 처리)
        assert compute_new_K(prev_K="누락", search_found=False, url_alive=True) == "누락"

    def test_3enum_deleted_to_dropped_recovery(self):
        """D-026 Phase E+F (2026-05-16) 위험 1 fix: prev='삭제' + 미노출 + 텍스트 검출 X → '삭제' 보존.
        근거: 사장님 시트 832 행 보호 — 기존 "삭제" 값 자동 "누락" 마이그레이션 X 의무.
        deletion_detected 인자 명시 X = False = 텍스트 검출 X = "삭제" 보존.
        """
        assert compute_new_K(prev_K="삭제", search_found=False, url_alive=True) == "삭제"


class TestD026PhaseCDEF:
    """D-026 Phase C+D+E+F (2026-05-16) 회귀 test — 중복노출 + 삭제 텍스트 검출 정합.

    신규 분기:
    - deletion_detected=True → "삭제" (즉시 적용)
    - 검색 노출 (search_found=True) + area="중복노출" → "중복노출"
    - 검색 미노출 + prev_K="중복노출" → "누락" (= 박스 빠짐)
    - 검색 미노출 + prev_K="삭제" + deletion_detected=False → "삭제" 보존 (위험 1 fix)
    """

    def test_deletion_detected_overrides_all(self):
        """D-026 Phase E+F: deletion_detected=True = 모든 분기 무시 = K='삭제'."""
        assert compute_new_K(
            prev_K="AB", search_found=False, url_alive=True, deletion_detected=True
        ) == "삭제"
        assert compute_new_K(
            prev_K="", search_found=False, url_alive=True, deletion_detected=True
        ) == "삭제"
        # search_found=True 여도 deletion_detected 가 더 우선
        assert compute_new_K(
            prev_K="AB", search_found=True, url_alive=True, area="AB", deletion_detected=True
        ) == "삭제"

    def test_3enum_DUPLICATE_exposure(self):
        """D-026 Phase C+D: 검색 = 중복노출 area → '중복노출' 표기."""
        assert compute_new_K(
            prev_K="", search_found=True, url_alive=True, area="중복노출"
        ) == "중복노출"

    def test_3enum_DUPLICATE_to_dropped(self):
        """D-026 Phase C+D: 이전 중복노출 → 미노출 → '누락' (= 박스 빠짐)."""
        assert compute_new_K(
            prev_K="중복노출", search_found=False, url_alive=True
        ) == "누락"

    def test_3enum_dropped_NOT_to_삭제(self):
        """위험 1 fix: prev='누락' + 미노출 + deletion_detected=False = '누락' 유지 (= '삭제' 자동 변환 X)."""
        assert compute_new_K(
            prev_K="누락", search_found=False, url_alive=True, deletion_detected=False
        ) == "누락"

    def test_삭제_보존_when_text_not_detected(self):
        """위험 1 fix 핵심: prev='삭제' + 미노출 + deletion_detected=False = '삭제' 보존.
        근거: 사장님 시트 832 행 보호.
        """
        assert compute_new_K(
            prev_K="삭제", search_found=False, url_alive=True, deletion_detected=False
        ) == "삭제"

    def test_중복노출_to_dropped(self):
        """D-026 Phase C+D: 이전 중복노출 → 검색 미노출 → '누락' (= EXPOSED_VALUES 안)."""
        assert compute_new_K(
            prev_K="중복노출", search_found=False, url_alive=True
        ) == "누락"

    def test_중복노출_recovers_to_AB(self):
        """D-026 Phase C+D: 이전 중복노출 → 검색 AB 노출 → 'AB' 그대로 회복."""
        assert compute_new_K(
            prev_K="중복노출", search_found=True, url_alive=True, area="AB"
        ) == "AB"

    def test_삭제_to_삭제_when_detected_again(self):
        """D-026 Phase E+F: prev='삭제' + 검색 미노출 + deletion_detected=True = '삭제' 유지."""
        assert compute_new_K(
            prev_K="삭제", search_found=False, url_alive=True, deletion_detected=True
        ) == "삭제"

    def test_manual_edit_preserves_over_deletion_detected(self):
        """D-018: 사장님 수동 편집 (SYSTEM_K_VALUES 외) = deletion_detected 무관 = 보존."""
        assert compute_new_K(
            prev_K="확인중", search_found=False, url_alive=True, deletion_detected=True
        ) == "확인중"


class TestD029DuplicateSubEnumTransitions:
    """D-029 (2026-05-18 — D-026 정정) 회귀 test — 중복노출(구좌) 3종 transitions 분기.

    사장님 5-18 명확 의도:
    - prev_K = "중복노출(AB)" / "중복노출(스마트블록)" / "중복노출(인기글)" = EXPOSED 로 간주
    - 검색 미노출 시 = "누락" 자연 분기 (= 박스 빠짐)
    - 검색 노출 회복 시 = area 그대로 (AB / 스마트블록 / 인기글)
    - SYSTEM_K_VALUES 안 = 사장님 수동 편집 X (= 자동 처리)
    """

    def test_d029_duplicate_AB_to_dropped(self):
        """이전 중복노출(AB) → 검색 미노출 → '누락' (= EXPOSED_VALUES 안)."""
        assert compute_new_K(
            prev_K="중복노출(AB)", search_found=False, url_alive=True
        ) == "누락"

    def test_d029_duplicate_smart_block_to_dropped(self):
        """이전 중복노출(스마트블록) → 검색 미노출 → '누락'."""
        assert compute_new_K(
            prev_K="중복노출(스마트블록)", search_found=False, url_alive=True
        ) == "누락"

    def test_d029_duplicate_popular_to_dropped(self):
        """이전 중복노출(인기글) → 검색 미노출 → '누락'."""
        assert compute_new_K(
            prev_K="중복노출(인기글)", search_found=False, url_alive=True
        ) == "누락"

    def test_d029_duplicate_AB_recovers_to_AB(self):
        """이전 중복노출(AB) → 검색 노출 AB → 'AB' 그대로 회복 (Pass 2 가 다시 갱신 가능)."""
        assert compute_new_K(
            prev_K="중복노출(AB)", search_found=True, url_alive=True, area="AB"
        ) == "AB"

    def test_d029_duplicate_popular_recovers_to_popular(self):
        """이전 중복노출(인기글) → 검색 노출 인기글 → '인기글' 그대로."""
        assert compute_new_K(
            prev_K="중복노출(인기글)", search_found=True, url_alive=True, area="인기글"
        ) == "인기글"

    def test_d029_duplicate_smart_block_deletion_detected(self):
        """이전 중복노출(스마트블록) + 삭제 텍스트 검출 = '삭제' (즉시 적용)."""
        assert compute_new_K(
            prev_K="중복노출(스마트블록)", search_found=False, url_alive=True, deletion_detected=True
        ) == "삭제"

    def test_d029_duplicate_sub_enums_in_SYSTEM_K_VALUES(self):
        """D-029 sub-enum 3종 + 호환 단일 = 모두 SYSTEM_K_VALUES 안 (= 사장님 수동 편집 X 인식)."""
        assert "중복노출(AB)" in SYSTEM_K_VALUES
        assert "중복노출(스마트블록)" in SYSTEM_K_VALUES
        assert "중복노출(인기글)" in SYSTEM_K_VALUES
        assert "중복노출" in SYSTEM_K_VALUES  # D-026 호환 유지

    def test_d029_duplicate_sub_enums_in_EXPOSED_VALUES(self):
        """D-029 sub-enum 3종 + 호환 단일 = 모두 EXPOSED_VALUES 안 (= "누락" 분기 정합)."""
        assert "중복노출(AB)" in EXPOSED_VALUES
        assert "중복노출(스마트블록)" in EXPOSED_VALUES
        assert "중복노출(인기글)" in EXPOSED_VALUES
        assert "중복노출" in EXPOSED_VALUES  # D-026 호환 유지

    def test_d029_DUPLICATE_to_DUPLICATE_persists(self):
        """이전 중복노출(AB) → 검색 노출 area = 중복노출(AB) → 그대로 유지 (Pass 2 결과 정합)."""
        # search_found=True + area="중복노출(AB)" = 그대로 (사장님 수동 편집 X = SYSTEM_K_VALUES 안)
        assert compute_new_K(
            prev_K="중복노출(AB)", search_found=True, url_alive=True, area="중복노출(AB)"
        ) == "중복노출(AB)"
