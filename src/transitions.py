"""transitions: K 컬럼 상태 전환 로직 (이전 vs 현재 비교).

사장님 차별화 기능 (D-009): 어제 노출됐는데 오늘 빠지면 자동으로 K = "누락" 표기.
사장님이 시트 보고 즉시 인지 가능 (외주본엔 없던 기능).

D-026 Phase C+D+E+F 사장님 컨벤션 (2026-05-16):
- 노출: "AB" / "스마트블록" / "인기글" / "중복노출"
- 미노출: "미노출" (= 첫 추적 또는 한 번도 노출 X)
- 누락: 이전 노출 → 지금 검색 결과 X (= 박스 빠짐, 다음 cron 자연 회복 가능)
- 중복노출: 빈 link 행 + 다른 행 우리 link 가 매치 (= 신규 발견, main.py 가 채움)
- 삭제: "게시글이 삭제되었습니다" 텍스트 검출 (= 진짜 글 사라짐, main.py 가 채움)

위험 1 fix (2026-05-16): prev_K = "삭제" + 검색 미노출 + 텍스트 검출 X
→ "삭제" 보존 (= 자동 변환 X) — 사장님 시트 832 행 보호.

D-022 ① 폐기 (2026-05-16): 이전 "노출 안 됨 = 모두 '삭제'" = 잘못 misread.
"""
from typing import Optional


# D-026 Phase C+D+E+F (2026-05-16): 중복노출 추가 = EXPOSED_VALUES 안 명시.
EXPOSED_VALUES = {"AB", "스마트블록", "인기글", "중복노출"}

# 우리 시스템이 K 컬럼에 쓰는 값 (D-026 사장님 컨벤션). 이 외 값은 사장님 수동 편집으로 간주 → 보존.
# 빈 문자열 "" 도 포함 (= 첫 cron 또는 사장님 시트 신규 행).
SYSTEM_K_VALUES = {"AB", "스마트블록", "인기글", "중복노출", "미노출", "누락", "삭제", "실패", ""}


def compute_new_K(
    prev_K: str,
    search_found: bool,
    url_alive: bool,
    area: Optional[str] = None,
    status: Optional[str] = None,
    deletion_detected: bool = False,
) -> str:
    """이전 K 값 + 현재 검색/URL/삭제 텍스트 상태 → 새 K 값 (D-026 사장님 컨벤션).

    Args:
        prev_K: 시트의 현재 K 컬럼 값 (이전 cron 결과). 빈 칸 = 첫 추적.
        search_found: 이번 cron 에 검색 결과에서 본인 cafe URL 발견했는가.
        url_alive: URL 자체가 살아있는가 (404 / 진짜 삭제 X). T-M10.5 폐기 후 = 항상 True.
        area: search_found=True 시 어느 블록 ('AB' / '스마트블록' / '인기글' / '중복노출').
        status: url_alive=False 시 사유 (현재 미사용).
        deletion_detected: D-026 Phase E+F (2026-05-16) — "게시글이 삭제되었습니다"
            텍스트 검출 시 True. 사장님 시점 = 진짜 글 사라짐 = 즉시 K="삭제".

    Returns:
        새 K 값 (D-026 사장님 컨벤션 단어).
        - "AB" / "스마트블록" / "인기글" / "중복노출" = 검색 노출
        - "미노출" = 검색 미노출 + 이전에 노출 X (= 첫 추적 또는 미노출 유지)
        - "누락" = 검색 미노출 + 이전에 노출 O (= 박스 빠짐)
        - "삭제" = "게시글이 삭제되었습니다" 텍스트 검출 (= 진짜 글 사라짐)
                  또는 prev_K = "삭제" + 검색 미노출 + 텍스트 검출 X → 보존
    """
    # 사장님 수동 편집 보존 (critic 2026-05-08 권장): 우리 시스템 외 값 = 사장님 수동 (예: "확인중")
    if prev_K and prev_K not in SYSTEM_K_VALUES:
        return prev_K  # 사장님 작업 덮어쓰기 X

    # D-026 Phase E+F (2026-05-16): "게시글이 삭제되었습니다" 텍스트 검출 = 즉시 "삭제"
    if deletion_detected:
        return "삭제"

    # URL 자체 죽음 — "삭제" (T-M10.5 폐기 후 = 항상 False, 호환성 유지)
    if not url_alive:
        return "삭제"

    # URL 살아있음 + 검색 found
    if search_found:
        return area or "AB"

    # URL 살아있음 + 검색 0
    if prev_K in EXPOSED_VALUES:
        # 이전엔 노출됐었음 → 박스 빠짐 = "누락" (D-026 Phase B+C 갱신, 중복노출 포함)
        return "누락"
    if prev_K == "누락":
        # 여전히 박스 빠진 상태 유지
        return "누락"
    if prev_K == "삭제":
        # D-026 Phase E+F (2026-05-16) 위험 1 fix:
        # prev "삭제" + 검색 미노출 + 텍스트 검출 X = "삭제" 보존 (= 자동 변환 X)
        # 근거: 사장님 시트 기존 "삭제" 값 = 진짜 삭제 = "누락" 자동 마이그레이션 X 의무
        return "삭제"

    # prev_K = "" 또는 "미노출" (= 첫 cron 또는 미노출 유지) → "미노출"
    return "미노출"
