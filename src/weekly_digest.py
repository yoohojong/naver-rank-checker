"""weekly_digest: 카페외부 주간 총괄 다이제스트 (총괄자용). M11 (2026-06-23).

일일 보고(현장용, telegram-report)와 별개 — 주 1회 '이번 주 괜찮나' 한 통.
데이터는 snapshot_diff 재사용: 지난주(~7일 전) 백업(prev) ↔ 오늘 백업(curr).
새 데이터·새 키 0 (rank-check sheet-backup artifact 14일 retention 재가공).

구성(사장님 "반드시 필요한 것만" 2026-06-23):
- [이번 주 한눈에]  지금 노출 + 지난주 대비 + 지난 7일 작업→노출 전환(헛수고 감지)
- [봐야 할 신호]    제품별 노출 급락 / 누락·삭제 폭증 (없으면 '특이사항 없음')
- [지난주 대비 변화] 신규/상승/하락/삭제 합계

보류(나중에 이 다이제스트에 끼워넣음): 카테고리·접촉지점 효율(B), 외부요인 가설(C).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from src.snapshot_diff import (  # noqa: F401 — _H_WORKDATE 는 의도적 재사용(헤더 drift 방지)
    EXPOSED_VALUES,
    TabReport,
    _H_WORKDATE,
    k_base_of,
)

# 비정상 신호 임계 (보수적 — 오탐 적게). 운영하며 데이터 보고 조정 가능.
_DROP_RATIO = 0.4    # 지난주 대비 40%+ 줄면 '급락'
_DROP_MIN_BASE = 3   # 지난주 노출 3개 미만 제품은 급락 판정 제외(소수 노이즈 차단)
_LOST_ALERT = 8      # 이번 주 누락+삭제 합계 이 이상이면 플래그


def _delta_word(prev: int, curr: int) -> str:
    d = curr - prev
    if d == 0:
        return "그대로"
    return f"{d}개 늘음" if d > 0 else f"{-d}개 줄음"


def work_dates_last_n(today: date, n: int = 7) -> set:
    """today 포함 최근 n일의 'M/D' 집합 (시트 작업일 칸 매칭용).

    연·월 경계 안전(date 연산). 작업일은 'M/D'(zero-pad 없음) 형식이라 동일 포맷으로 생성.
    """
    return {
        f"{(today - timedelta(days=i)).month}/{(today - timedelta(days=i)).day}"
        for i in range(n)
    }


def funnel_last_n_days(curr: dict, work_dates: set) -> tuple:
    """(worked, exposed): 작업일 ∈ work_dates 인 행 수 / 그중 현재 상위노출 수. 전 탭 합산.

    노출은 며칠 걸쳐 올라오므로 '어제'가 아닌 '지난 7일' 작업분을 누적 추적해
    '작업이 노출로 바뀌고 있나'(헛수고 여부)를 본다.
    """
    worked = exposed = 0
    for rows in (curr.get("tabs") or {}).values():
        for r in rows:
            wd = str(r.get(_H_WORKDATE, "") or "").strip()
            if wd in work_dates:
                worked += 1
                if k_base_of(r) in EXPOSED_VALUES:
                    exposed += 1
    return worked, exposed


def _all_kinds(reports: list[TabReport]) -> Counter:
    c: Counter = Counter()
    for t in reports:
        c.update(d.kind for d in t.diffs)
    return c


def detect_anomalies(reports: list[TabReport]) -> list:
    """봐야 할 신호 목록(사람 문장). 제품별 노출 급락 + 누락·삭제 폭증. 정상이면 빈 리스트.

    baseline(지난주 백업) 없으면 급락 판정 불가 → 신호 비움(오보 방지).
    """
    signals: list = []
    for t in reports:
        if not t.baseline_available:
            continue
        prev, now = t.exposed_prev, t.exposed_now
        if prev >= _DROP_MIN_BASE and now < prev and (prev - now) >= prev * _DROP_RATIO:
            signals.append(f"{t.tab}: 노출 {prev} → {now}개 급락  ← 점검")

    kc = _all_kinds(reports)
    lost = kc.get("누락", 0) + kc.get("삭제", 0)
    if lost >= _LOST_ALERT:
        parts = []
        if kc.get("누락"):
            parts.append(f"누락 {kc['누락']}건")
        if kc.get("삭제"):
            parts.append(f"삭제 {kc['삭제']}건")
        signals.append(f"이번 주 {' · '.join(parts)}  ← 평소보다 많으면 점검")
    return signals


def _sum(reports: list[TabReport], attr: str) -> int:
    return sum(getattr(t, attr) for t in reports)


def build_weekly_text(
    reports: list[TabReport],
    funnel: tuple,
    date_range: str,
    status_line: str = "정상",
) -> str:
    """주간 총괄 보고 텍스트 (순수 함수 — 테스트 대상). funnel=(worked, exposed).

    prev(지난주) 없으면 '지난주 대비'·신호는 생략하고 현재 스냅샷만 보고.
    """
    now = _sum(reports, "exposed_now")
    prev = _sum(reports, "exposed_prev")
    has_base = any(t.baseline_available for t in reports)
    worked, exposed = funnel
    kc = _all_kinds(reports)

    L = [f"📊 카페외부 주간 총괄 · {date_range}", f"프로그램: {status_line}", ""]

    # 이번 주 한눈에
    L.append("[이번 주 한눈에]")
    if has_base:
        L.append(f"   지금 노출: {now}개  (지난주 {prev}개 → {_delta_word(prev, now)})")
    else:
        L.append(f"   지금 노출: {now}개")
    if worked:
        pct = round(exposed / worked * 100)
        L.append(f"   작업 → 노출: 지난 7일 {worked}개 작업 → {exposed}개 떴어요 ({pct}%)")
    else:
        L.append("   작업 → 노출: 지난 7일 기록된 작업 없음")
    L.append("")

    # 봐야 할 신호
    L.append("[⚠️ 봐야 할 신호]")
    signals = detect_anomalies(reports)
    if signals:
        for s in signals:
            L.append(f"   • {s}")
    else:
        L.append("   이번 주 특이사항 없음")
    L.append("")

    # 지난주 대비 변화
    if has_base:
        L.append("[지난주 대비 변화]")
        seg = []
        if kc.get("신규노출"):
            seg.append(f"신규 노출 +{kc['신규노출']}")
        if kc.get("오름"):
            seg.append(f"순위 상승 {kc['오름']}")
        if kc.get("내림"):
            seg.append(f"순위 하락 {kc['내림']}")
        if kc.get("삭제"):
            seg.append(f"삭제 {kc['삭제']}")
        L.append("   " + (" · ".join(seg) if seg else "큰 변화 없음"))

    return "\n".join(L).rstrip()
