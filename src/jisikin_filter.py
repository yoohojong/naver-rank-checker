"""jisikin_filter: 지식iN 수집 결과에서 '쓰레기'만 보수적으로 걸러낸다.

설계 철학(사장님 확정):
  "공격적으로 안 버린다. 진짜 선별은 사람이 수작업."
  → 아래 *명백한 것*만 True(버림). 헷갈리면 False(남김).

판정 기준:
  1. title·description 둘 다 공백/빈값
  2. (title + description) 정제 길이 < 15자
  3. '순수 광고' = 전화번호 패턴 AND URL(http/https) 동시 포함
  4. URL 이 2개 이상

업체명·홍보수식어 같은 '약한 신호' 로는 버리지 않는다.
"""
from __future__ import annotations

import re

# 전화번호 — '명백한 전화 형식'만 잡는다(사장님 "헷갈리면 남긴다": 가격 1500원·연도 1999년 오인 방지).
#  · 휴대폰/일반전화: 0XX(-)XXX(X)(-)XXXX (010-1234-5678, 02-123-4567 등)
#  · 대표번호: 15xx~19xx + 뒤 4자리 필수 (1588-1234). 바로 앞뒤에 숫자 없을 때만(부분매치 차단).
_PHONE_RE = re.compile(
    r"(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
    r"|(?<!\d)1[5-9]\d{2}[-\s]?\d{4}(?!\d)"
)

# URL: http 또는 https 로 시작하는 링크.
_URL_RE = re.compile(r"https?://")


def _strip(text: str) -> str:
    """공백·줄바꿈 제거한 순수 텍스트 길이 계산용."""
    return re.sub(r"\s+", "", text or "")


def is_junk(title: str, description: str) -> tuple[bool, str]:
    """지식iN 항목이 '쓰레기'인지 보수적으로 판정.

    Args:
        title: 질문 제목 (이미 HTML 태그 제거된 텍스트).
        description: 질문 요약 (이미 HTML 태그 제거된 텍스트).

    Returns:
        (is_junk: bool, reason: str)
        - True  → 버림. reason 에 어떤 규칙인지.
        - False → 남김. reason 은 빈 문자열.
    """
    t = (title or "").strip()
    d = (description or "").strip()

    # 규칙 1: 제목·설명 둘 다 빈값.
    if not t and not d:
        return True, "제목·설명 모두 빈값"

    # 규칙 2: 정제 길이 < 15자 (너무 짧아 재료 가치 없음).
    combined_len = len(_strip(t)) + len(_strip(d))
    if combined_len < 15:
        return True, f"내용 너무 짧음 ({combined_len}자 < 15자)"

    # 이하 규칙은 제목+설명 합산 텍스트 기준.
    combined = t + " " + d

    # 규칙 3: 전화번호 AND URL 동시 포함 → 순수 광고.
    has_phone = bool(_PHONE_RE.search(combined))
    url_matches = _URL_RE.findall(combined)
    if has_phone and url_matches:
        return True, "전화번호+URL 동시 포함 (순수 광고)"

    # 규칙 4: URL 이 2개 이상.
    if len(url_matches) >= 2:
        return True, f"URL {len(url_matches)}개 포함 (링크 도배)"

    return False, ""
