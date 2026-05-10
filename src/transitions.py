"""transitions: K 컬럼 상태 전환 로직 (이전 vs 현재 비교).

사장님 차별화 기능 (D-009): 어제 노출됐는데 오늘 빠지면 자동으로 K = "삭제" 표기.
사장님이 시트 보고 즉시 인지 가능 (외주본엔 없던 기능).

사장님 컨벤션 (2026-05-08):
- 노출: "AB" / "인기글"
- 미노출: 빈 칸 ""
- 글 빠짐 / 삭제 / 비공개 / 차단 등 모든 X 케이스: "삭제"
"""
from typing import Optional


EXPOSED_VALUES = {"AB", "인기글", "스마트블록"}  # "스마트블록" = defensive (deprecated 사장님 컨벤션 but parser 변경 시 latent bug 방지, critic 2026-05-08 Major 4)

# 우리 시스템이 K 컬럼에 쓰는 값 (사장님 컨벤션). 이 외 값은 사장님 수동 편집으로 간주 → 보존.
SYSTEM_K_VALUES = {"AB", "인기글", "삭제", "스마트블록", ""}


def compute_new_K(
    prev_K: str,
    search_found: bool,
    url_alive: bool,
    area: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """이전 K 값 + 현재 검색/URL 상태 → 새 K 값 (사장님 컨벤션).

    Args:
        prev_K: 시트의 현재 K 컬럼 값 (이전 cron 결과). 빈 칸 = 첫 추적 또는 미노출.
        search_found: 이번 cron 에 검색 결과에서 본인 cafe URL 발견했는가.
        url_alive: URL 자체가 살아있는가 (404 / 로그인벽 / 카페비공개 X).
        area: search_found=True 시 어느 블록 ('AB' / '인기글').
        status: url_alive=False 시 사유 (사장님 컨벤션상 모두 '삭제' 통일이라 미사용).

    Returns:
        새 K 값 (사장님 컨벤션 단어).
    """
    # 사장님 수동 편집 보존 (critic 2026-05-08 권장): 우리 시스템 외 값 = 사장님 수동 (예: "확인중")
    if prev_K and prev_K not in SYSTEM_K_VALUES:
        return prev_K  # 사장님 작업 덮어쓰기 X

    # URL 자체 죽음 — 모두 "삭제"
    if not url_alive:
        return "삭제"

    # URL 살아있음 + 검색 found
    if search_found:
        return area or "AB"

    # URL 살아있음 + 검색 0
    if prev_K in EXPOSED_VALUES:
        # 이전엔 노출됐었음 → 빠짐 = 사장님 인지 신호
        return "삭제"
    if prev_K == "삭제":
        # 여전히 빠진 상태 유지
        return "삭제"

    # prev_K = "" (미노출 또는 첫 추적) → 미노출 (빈 칸)
    return ""
