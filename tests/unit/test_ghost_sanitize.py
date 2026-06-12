"""T-M9.2 (2026-06-12, D-047) 회귀 test — 행 복사 잔해(유령 검사값) 검출.

배경: 마케터가 기존 행을 통째로 복사해 신규 행을 만들면 숨김 시스템 칸
(마지막검사입력키/raw_*/마지막검사시각)까지 복사돼 "검사한 척"하는 유령 값이 생긴다.
2026-06-12 사건: 07:52 백업에서 신규 30행이 입력키 빈칸 + 검사시각 복사 상태로 실증.

Codex 태클 반영:
- Major 5: "migration" 검사시각 = 마이그레이션 backfill = 잔해 아님.
- Major 5: 사장님 수동 K("확인중" 등)가 raw 에 보존된 행 = 잔해 아님.
- Major 6: raw_노출영역 = "재검사필요" 글자 = 시스템이 절대 raw 에 쓰지 않는 값 = 잔해.
"""
from src.main import _detect_ghost_stale_rows


def _row(num, **overrides):
    base = {
        "_row": num,
        "키워드": "알라딘필링후기",
        "링크": "https://cafe.naver.com/llchyll/2449021",
        "마지막검사입력키": "",
        "raw_노출영역": "",
        "raw_통합순위": "",
        "raw_카페순위": "",
        "raw_지식인탭": "",
        "마지막검사시각": "",
    }
    base.update(overrides)
    return base


class TestDetectGhostStaleRows:
    def test_orphan_raw_without_input_key_is_ghost(self):
        """입력키 빈칸 + raw 값 존재 = 행 복사 잔해."""
        rows = [_row(2, raw_노출영역="미노출 (6/11 12:00~)")]
        assert _detect_ghost_stale_rows(rows) == [2]

    def test_orphan_timestamp_without_input_key_is_ghost(self):
        """입력키 빈칸 + 검사시각 존재 = 잔해 (2026-06-12 실증 케이스)."""
        rows = [_row(2, 마지막검사시각="2026-06-12 07:09 KST")]
        assert _detect_ghost_stale_rows(rows) == [2]

    def test_migration_timestamp_is_not_ghost(self):
        """Codex Major 5: 'migration' 시각 = backfill 산출물 = 잔해 아님."""
        rows = [_row(2, 마지막검사시각="migration")]
        assert _detect_ghost_stale_rows(rows) == []

    def test_stale_marker_in_raw_is_ghost_even_with_key(self):
        """Codex Major 6: raw 에 '재검사필요' 글자 = 키 일치 여부 무관 = 잔해."""
        rows = [_row(2, 마지막검사입력키="v1|알라딘필링후기|cafe.naver.com/llchyll/2449021",
                     raw_노출영역="재검사필요", 마지막검사시각="2026-06-12 07:09 KST")]
        assert _detect_ghost_stale_rows(rows) == [2]

    def test_healthy_checked_row_is_not_ghost(self):
        """정상 검사 행 (키+raw+시각 한 묶음) = 잔해 아님."""
        rows = [_row(2, 마지막검사입력키="v1|알라딘필링후기|cafe.naver.com/llchyll/2449021",
                     raw_노출영역="AB (6/8 17:19~)", raw_통합순위="1", raw_카페순위="1",
                     마지막검사시각="2026-06-12 07:09 KST")]
        assert _detect_ghost_stale_rows(rows) == []

    def test_never_checked_clean_row_is_not_ghost(self):
        """신규 깨끗한 행 (숨김 칸 전부 빈칸) = 잔해 아님."""
        rows = [_row(2)]
        assert _detect_ghost_stale_rows(rows) == []

    def test_row_without_keyword_and_link_is_protected(self):
        """키워드/링크 없는 행 = 사장님 수동 메모 영역 = 잔해 판정 제외."""
        rows = [_row(2, 키워드="", 링크="", raw_노출영역="이상한값", 마지막검사시각="2026-06-12 07:09 KST")]
        assert _detect_ghost_stale_rows(rows) == []

    def test_manual_k_preserved_in_raw_is_not_ghost(self):
        """Codex Major 5: 사장님 수동 K('확인중')가 transitions 보존 경로로 raw 에 있는 행 = 잔해 아님."""
        rows = [_row(2, 마지막검사입력키="v1|알라딘필링후기|cafe.naver.com/llchyll/2449021",
                     raw_노출영역="확인중", 마지막검사시각="2026-06-12 07:09 KST")]
        assert _detect_ghost_stale_rows(rows) == []

    def test_multiple_rows_mixed(self):
        rows = [
            _row(2, 마지막검사입력키="v1|x|y", raw_노출영역="AB (6/8 17:19~)", 마지막검사시각="2026-06-12 07:09 KST"),
            _row(3, raw_노출영역="미노출 (6/11 12:00~)", 마지막검사시각="2026-06-12 07:09 KST"),
            _row(4),
            _row(5, 마지막검사입력키="v1|x|y", raw_노출영역="재검사필요"),
        ]
        assert _detect_ghost_stale_rows(rows) == [3, 5]
