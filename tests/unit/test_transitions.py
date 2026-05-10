"""transitions 단위 테스트."""
import pytest

from src.transitions import compute_new_K, EXPOSED_VALUES


class TestComputeNewK:
    def test_first_run_not_exposed(self):
        """첫 추적 (prev_K = '') + 검색 0 → 빈 칸 (미노출)."""
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == ""

    def test_first_run_AB_exposure(self):
        """첫 추적 + 검색 found → 해당 블록."""
        assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="AB") == "AB"

    def test_first_run_popular_exposure(self):
        assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="인기글") == "인기글"

    def test_exposed_to_deleted_transition(self):
        """⭐ 핵심 차별화: 이전 AB → 지금 빠짐 → '삭제' 자동 표기."""
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "삭제"

    def test_popular_to_deleted_transition(self):
        """이전 인기글 → 지금 빠짐 → '삭제'."""
        assert compute_new_K(prev_K="인기글", search_found=False, url_alive=True) == "삭제"

    def test_unexposed_stays_unexposed(self):
        """이전 미노출 (빈 칸) → 지금도 검색 0 → 빈 칸 유지."""
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == ""

    def test_deleted_recovers_to_exposure(self):
        """삭제 상태에서 회복 — 다시 노출 잡힘 → 해당 블록."""
        assert compute_new_K(prev_K="삭제", search_found=True, url_alive=True, area="AB") == "AB"
        assert compute_new_K(prev_K="삭제", search_found=True, url_alive=True, area="인기글") == "인기글"

    def test_deleted_stays_deleted_when_still_missing(self):
        """삭제 상태 + 여전히 검색 0 → 삭제 유지."""
        assert compute_new_K(prev_K="삭제", search_found=False, url_alive=True) == "삭제"

    def test_url_dead_overrides_prev_state(self):
        """URL 자체 죽음 (404/비공개/카페삭제 등) → '삭제' (이전 상태 무관)."""
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=False) == "삭제"
        assert compute_new_K(prev_K="", search_found=False, url_alive=False) == "삭제"
        assert compute_new_K(prev_K="인기글", search_found=False, url_alive=False) == "삭제"
        # status 무시 (사장님 컨벤션 = 모두 '삭제' 통일)
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=False, status="deleted") == "삭제"
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=False, status="private") == "삭제"

    def test_exposed_values_constant(self):
        """사장님 컨벤션: 노출 단어 = 'AB' + '인기글' 만."""
        assert EXPOSED_VALUES == {"AB", "인기글", "스마트블록"}  # 스마트블록 = defensive (critic 2026-05-08 Major 4)

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
        assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "삭제"
        assert compute_new_K(prev_K="", search_found=False, url_alive=True) == ""
