"""transitions: K 컬럼 상태 전환 로직 (이전 vs 현재 비교).

사장님 차별화 기능 (D-009): 어제 노출됐는데 오늘 빠지면 자동으로 K = "누락" 표기.
사장님이 시트 보고 즉시 인지 가능 (외주본엔 없던 기능).

D-029 사장님 컨벤션 (2026-05-18 — D-026 정정):
- 노출: "AB" / "스마트블록" / "인기글"
- 중복노출(구좌): "중복노출(AB)" / "중복노출(스마트블록)" / "중복노출(인기글)" (D-029 양방향 갱신)
- 호환 유지: "중복노출" (D-026 단일 값, Pass 2 전 또는 구좌 미상)
- 미노출: "미노출" (= 첫 추적 또는 한 번도 노출 X)
- 누락: 이전 노출 → 지금 검색 결과 X (= 박스 빠짐, 다음 cron 자연 회복 가능)
- 삭제: "게시글이 삭제되었습니다" 텍스트 검출 (= 진짜 글 사라짐, main.py 가 채움)

위험 1 fix (2026-05-16): prev_K = "삭제" + 검색 미노출 + 텍스트 검출 X
→ "삭제" 보존 (= 자동 변환 X) — 사장님 시트 832 행 보호.

D-022 ① 폐기 (2026-05-16): 이전 "노출 안 됨 = 모두 '삭제'" = 잘못 misread.

D-030 (2026-05-18): K 값 + 시점 통합 표기 = "AB (5/10 03:00~)" 형식.
사장님 결정 (= AskUserQuestion 답 3) 정합:
- 시점 형식 = "5/10 03:00" (= 시각까지)
- "미노출" 표기 = "미노출 (5/10 03:00~)" (= 명시 일관성)
- 832 행 마이그레이션 = today 자동 기록 (= 첫 D-030 cron = 모든 행 = 오늘 시점 기록)
- "삭제" 신규 = "삭제 (5/16 03:00)" (= 단일 시점, "~" X)
- "실패" = 시점 X (= 일시 상태)
- 상태 전환 시점만 새 기록 + 유지 동안 보존 의무 (= K base 동일 시 prev 시점 보존)
"""
import re
from typing import Optional


# D-029 (2026-05-18): 중복노출(구좌) 3종 + 호환용 "중복노출" 단일 = EXPOSED_VALUES 안 명시.
# 모든 중복노출 sub-enum 도 EXPOSED 로 간주 = transitions = "누락" 자연 분기.
EXPOSED_VALUES = {
    "AB", "스마트블록", "인기글",
    "중복노출",  # D-026 호환 유지 (Pass 2 전 또는 구좌 미상)
    "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",  # D-029 (2026-05-18)
}

# 세는 잣대가 언제 무엇으로 바뀌었나 (이력 — 지우지 말 것)
#   2026-07-28  카페 구좌 1~3위를 '진짜 상위노출'로 셈.
#   2026-09-03  카페 구좌 **1위만** 셈. 사장님 원문:
#               "이거 기준을 아예 카페구좌에서 1위 - 초록색 / 2~3위 - 노란색 /
#                그 밖 - 빨간색 이렇게 변경 부탁할게."
#               "그리고 상위노출 키워드 추적하는것도 카페구좌 1위만 세줘."
#               "그래 누락. 미노출. 4위 이하 전부 빨강이야"
# 색칠(sheets)·집계(리포트) 공용 기준. team project 저장소의
# cafe-external/reports/exposure_rule.py 와 뜻이 같아야 한다(저장소가 달라 코드는 따로 산다).
CAFE_SLOT_COUNTED = 1      # 세는 자리 = 초록
CAFE_SLOT_NEAR_MAX = 3     # 노랑 구간의 끝(2~3위). 안 세지만 한 칸만 올리면 되는 자리

# 옛 이름 — 2026-09-03 이전 기준. 쓰는 곳은 없다. 이 값이 3이었다는 사실이 위 이력과 짝이다.
CAFE_SLOT_EXPOSED_MAX_구기준_20260728 = 3


def cafe_slot_rank_value(raw: object) -> Optional[int]:
    """M열(카페구좌순위) 값에서 정수 순위 추출. 없거나 숫자 아니면 None."""
    m = re.search(r"\d+", str(raw or ""))
    return int(m.group()) if m else None


def cafe_slot_qualifies(raw: object) -> bool:
    """카페 구좌 순위가 '세는 자격'인가 = 1위인가 (사장님 2026-09-03).

    빈칸/미상(None) = True(배제하지 않음) — 구좌를 못 읽었다고 노출에서 빼면
    조용한 과소집계가 됨. 실측: 2026-07-28 이후 노출행의 구좌순위 빈칸은 0건이고,
    그 전 날짜는 M열 자체가 없었다.
    """
    n = cafe_slot_rank_value(raw)
    return n is None or n <= CAFE_SLOT_COUNTED


def cafe_slot_band(raw: object) -> str:
    """그 칸을 무슨 색으로 칠할지 — 판정은 여기 한 곳에서만 한다.

      "1위"        초록 — 상위노출로 센다
      "2~3위"      노랑 — 안 세지만 한 칸만 올리면 되는 자리
      "그 밖"      빨강 — 구좌 4위 이하
      "구좌 못 잼" 구좌를 잰 기록이 없다(빈칸). 세는 쪽에서는 자격을 유지한다
    """
    n = cafe_slot_rank_value(raw)
    if n is None:
        return "구좌 못 잼"
    if n <= CAFE_SLOT_COUNTED:
        return "1위"
    if n <= CAFE_SLOT_NEAR_MAX:
        return "2~3위"
    return "그 밖"


def is_real_exposure(k_base: str, cafe_slot_raw: object = None) -> bool:
    """진짜 상위노출 = 노출 블록(EXPOSED_VALUES) AND 카페 구좌 1위 (사장님 2026-09-03)."""
    return k_base in EXPOSED_VALUES and cafe_slot_qualifies(cafe_slot_raw)

# 우리 시스템이 K 컬럼에 쓰는 값 (D-029 사장님 컨벤션). 이 외 값은 사장님 수동 편집으로 간주 → 보존.
# 빈 문자열 "" 도 포함 (= 첫 cron 또는 사장님 시트 신규 행).
SYSTEM_K_VALUES = {
    "AB", "스마트블록", "인기글",
    "중복노출",  # D-026 호환 유지
    "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",  # D-029 구좌 명시
    "미노출", "누락", "삭제", "실패", "재검사필요", "",
}


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
        새 K 값 (D-029 사장님 컨벤션 단어).
        - "AB" / "스마트블록" / "인기글" = 검색 노출
        - "중복노출" / "중복노출(AB)" / "중복노출(스마트블록)" / "중복노출(인기글)"
          = 중복노출 (D-026 호환 유지 + D-029 구좌 명시)
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


# D-030 (2026-05-18): K 값 + 시점 통합 logic.
# 사장님 결정 (= AskUserQuestion 답 3) 정합:
# - 시점 형식 = "5/10 03:00" (= 시각까지, %m/%d %H:%M KST)
# - "~" 가 붙는 enum = 상태 지속 (예: "AB (5/10 03:00~)", "미노출 (5/10 03:00~)")
# - "~" 없는 enum = 단일 시점 (예: "삭제 (5/16 03:00)")
# - "실패" = 시점 X (= 일시 상태)
# - 사장님 수동 (= "확인중" 등) = 시점 X = base 그대로

# 정규식: "(stamp~)" 또는 "(stamp)" 둘 다 match.
# 사장님 시점 형식 = "5/10 03:00" 또는 "5/10 03:00~" (= 양방향 지원).
_K_STAMP_RE = re.compile(r"^(.*?)\s*\((\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})~?\)$")


def parse_K_with_stamp(k_str: str) -> tuple[str, Optional[str]]:
    """K 값 (= base + 선택적 시점) 파싱 → (base, stamp).

    D-030 (2026-05-18) helper — K 값 + 시점 통합 표기 분리.

    Args:
        k_str: K 컬럼 값. 예 "AB (5/10 03:00~)" / "삭제 (5/16 03:00)" / "AB" / "확인중".

    Returns:
        (base, stamp) tuple.
        - "AB (5/10 03:00~)" → ("AB", "5/10 03:00")
        - "삭제 (5/16 03:00)" → ("삭제", "5/16 03:00")  # ~ 없음 정상 처리
        - "중복노출(AB) (5/10 03:00~)" → ("중복노출(AB)", "5/10 03:00")
        - "AB" → ("AB", None)
        - "확인중" → ("확인중", None)  # 사장님 수동
        - "" → ("", None)

    Note:
        괄호 안 패턴이 시점 형식 (= "M/D HH:MM") 매치 X 시 = base 그대로 반환.
        예: "중복노출(AB)" → ("중복노출(AB)", None) (= sub-enum 자체가 괄호 포함, 시점 X)
    """
    if not k_str:
        return ("", None)
    s = k_str.strip()
    m = _K_STAMP_RE.match(s)
    if m:
        base = m.group(1).strip()
        stamp = m.group(2).strip()
        return (base, stamp)
    return (s, None)


def compute_new_K_with_stamp(
    prev_K_full: str,
    new_K_raw_base: str,
    today_stamp: str,
) -> str:
    """이전 K (= base + 시점 가능) + 신규 K base + 오늘 시점 → 새 K 통합 표기.

    D-030 (2026-05-18) wrapper — K 값 + 시점 통합 표기 결정.

    사장님 결정 (= AskUserQuestion 답 3) 정합:
    - prev_K_base == new_K_raw_base + prev_stamp 있음 → prev_K_full 그대로 (= 시점 보존)
    - prev_K_base != new_K_raw_base 또는 prev_stamp 없음 → "{new_K_raw_base} ({today_stamp}~)" (= 새 기록)
    - new_K_raw_base == "삭제" → "{new_K_raw_base} ({today_stamp})" (= ~ 없음)
    - new_K_raw_base == "실패" → "실패" (= 시점 X)
    - new_K_raw_base 가 사장님 수동 (= SYSTEM_K_VALUES 외) → new_K_raw_base 그대로 (= 시점 X)

    Args:
        prev_K_full: 시트 현재 K 컬럼 값 (= base + 시점 가능). 예 "AB (5/10 03:00~)".
        new_K_raw_base: compute_new_K 결과 base (= 시점 X). 예 "AB", "누락", "삭제", "미노출".
        today_stamp: 오늘 KST 시각 (= "%m/%d %H:%M"). 예 "5/18 03:00".

    Returns:
        통합 표기 K 값. 예:
        - "AB (5/10 03:00~)" 유지 (= base 동일, 시점 보존)
        - "누락 (5/18 03:00~)" 신규 (= base 전환, 새 시점)
        - "삭제 (5/18 03:00)" 신규 (= "삭제" 단일 시점 ~ 없음)
        - "실패" (= 시점 X)
        - "확인중" (= 사장님 수동, 그대로)

    Note:
        new_K_raw_base = "" (빈) 시 = "" 반환 (= 호출처 처리).
    """
    if not new_K_raw_base:
        return ""

    # 사장님 수동 편집 = SYSTEM_K_VALUES 외 = 시점 X = 그대로 반환
    # (= compute_new_K 가 이미 보존했지만 = wrapper 도 safe-guard)
    if new_K_raw_base not in SYSTEM_K_VALUES:
        return new_K_raw_base

    # "실패" = 일시 상태 = 시점 X
    if new_K_raw_base == "실패":
        return "실패"

    # "삭제" = 단일 시점 (= "~" 없음)
    # 사장님 결정 정합: "삭제 (5/16 03:00)" (= 진짜 글 사라진 그 시점)
    if new_K_raw_base == "삭제":
        # prev base 도 "삭제" + 시점 있음 = 시점 보존 (= 첫 검출 시점 유지)
        prev_base, prev_stamp = parse_K_with_stamp(prev_K_full)
        if prev_base == "삭제" and prev_stamp:
            return f"삭제 ({prev_stamp})"
        # 신규 "삭제" = today 시점 기록
        return f"삭제 ({today_stamp})"

    # 일반 enum (= AB / 스마트블록 / 인기글 / 중복노출(*) / 미노출 / 누락)
    # = "~" 붙는 형식 = 상태 지속 의미
    prev_base, prev_stamp = parse_K_with_stamp(prev_K_full)

    # base 동일 + prev stamp 있음 = 시점 보존 (= 사장님 결정: "상태 전환 시점만 새 기록")
    if prev_base == new_K_raw_base and prev_stamp:
        return f"{new_K_raw_base} ({prev_stamp}~)"

    # base 전환 또는 prev stamp 없음 = 새 시점 기록 (= 832 행 마이그레이션 = today 자동 기록 정합)
    return f"{new_K_raw_base} ({today_stamp}~)"
