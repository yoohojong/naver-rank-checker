"""report_builder: snapshot_diff 결과 → 텔레그램 보고 텍스트. M10 (D-052c 말 중심 재설계).

⚠️ 비공개 채널(텔레그램 DM) 전용. plain text.
사장님 2026-06-20 요청: **기호 최소화 → 한글 말로**(인지부담↓). 키워드 나열 X.
구성: 어제 작업(제품별) → 지금 상위노출 → 어제→오늘 변화 → 제품별 노출 → 대표 유형 → 지식인.
"""
from __future__ import annotations

from collections import Counter

from src.snapshot_diff import TabReport

# 상노 프로그램(시트)이 쓰는 용어 그대로 + 설명 (사장님 인지부담↓)
_LEGEND = (
    "ℹ️ 용어\n"
    "   AB·인기글·스마트블록 = 검색에 노출되는 자리(구좌) 종류\n"
    "   누락 = 노출됐다 사라짐(회복 가능) · 삭제 = 글이 없어짐 · 미노출 = 아직 안 뜸\n"
    "   유형 = 그 키워드 검색 대표 구좌 · 지식인 = 지식iN 노출"
)


def _delta_word(prev: int, curr: int) -> str:
    d = curr - prev
    if d == 0:
        return "그대로"
    return f"{d}개 늘음" if d > 0 else f"{-d}개 줄음"


def _kinds(tr: TabReport) -> Counter:
    return Counter(d.kind for d in tr.diffs)


def _all_kinds(reports: list[TabReport]) -> Counter:
    c: Counter = Counter()
    for t in reports:
        c.update(_kinds(t))
    return c


def _all_type_dist(reports: list[TabReport]) -> Counter:
    c: Counter = Counter()
    for t in reports:
        c.update(t.type_dist)
    return c


def _sum(reports: list[TabReport], attr: str) -> int:
    return sum(getattr(t, attr) for t in reports)


def build_evening_report(reports: list[TabReport], kst: str, status_line: str = "정상") -> str:
    """저녁 마감 — 한글 말 중심, 섹션별."""
    if not reports:
        return f"📊 상노체크 · {kst} 저녁\n데이터 없음"
    tot = _sum(reports, "total")
    now = _sum(reports, "exposed_now")
    prev = _sum(reports, "exposed_prev")
    worked = _sum(reports, "worked")
    worked_exp = _sum(reports, "worked_exposed")
    jis_now = _sum(reports, "jisikin_now")
    has_base = any(t.baseline_available for t in reports)
    kc = _all_kinds(reports)
    lost = kc.get("누락", 0) + kc.get("삭제", 0)

    L = [f"📊 상노체크 · {kst} 저녁", f"프로그램: {status_line}", ""]

    # 어제 한 작업 (제품별)
    if worked:
        L.append("[어제 한 작업]")
        for t in reports:
            if t.worked:
                L.append(f"   {t.tab}: {t.worked}개 작업 → {t.worked_exposed}개 떴어요")
        L.append(f"   합계: {worked}개 작업 → {worked_exp}개 노출")
        L.append("")

    # 지금 상위노출
    L.append("[지금 상위노출]")
    if has_base:
        L.append(f"   전체 {tot}개 중 {now}개 노출 중 (어제보다 {_delta_word(prev, now)})")
    else:
        L.append(f"   전체 {tot}개 중 {now}개 노출 중")
    L.append("")

    # 어제 → 오늘 변화
    if has_base:
        L.append("[어제→오늘 변화]")
        if kc.get("신규노출"):
            L.append(f"   신규 노출: {kc['신규노출']}개")
        if kc.get("오름"):
            L.append(f"   순위 상승: {kc['오름']}개")
        if kc.get("내림"):
            L.append(f"   순위 하락: {kc['내림']}개")
        if kc.get("누락"):
            L.append(f"   누락: {kc['누락']}개  ← 점검!")
        if kc.get("삭제"):
            L.append(f"   삭제: {kc['삭제']}개  ← 점검!")
        if not (kc.get("신규노출") or kc.get("오름") or kc.get("내림") or lost):
            L.append("   변화 없음")
        L.append("")

    # 제품별 노출
    L.append("[제품별 노출]")
    for t in reports:
        tail = f" ({_delta_word(t.exposed_prev, t.exposed_now)})" if t.baseline_available else ""
        L.append(f"   {t.tab}: {t.total}개 중 {t.exposed_now}개{tail}")
    L.append("")

    # 대표 노출 유형
    td = _all_type_dist(reports)
    if td:
        seg = " · ".join(f"{k} {td[k]}" for k in ["AB", "스마트블록", "인기글"] if td.get(k))
        L.append("[대표 노출 유형]")
        L.append(f"   {seg}")
        tch = _sum(reports, "type_changes")
        if tch:
            L.append(f"   유형 바뀐 키워드: {tch}개")
        L.append("")

    # 지식인
    if jis_now or _sum(reports, "jisikin_prev"):
        L.append(f"[지식인]  지식인에 뜬 키워드: {jis_now}개")

    L += ["", _LEGEND]
    return "\n".join(L).rstrip()


def build_morning_report(reports: list[TabReport], kst: str, status_line: str = "정상") -> str:
    """아침 요약 — 한글 말, 짧게."""
    if not reports:
        return f"☀️ 상노체크 아침 · {kst}\n데이터 없음"
    now = _sum(reports, "exposed_now")
    tot = _sum(reports, "total")
    worked = _sum(reports, "worked")
    worked_exp = _sum(reports, "worked_exposed")
    kc = _all_kinds(reports)
    lost = kc.get("누락", 0) + kc.get("삭제", 0)

    L = [f"☀️ 상노체크 아침 · {kst}", f"프로그램: {status_line}", ""]
    L.append(f"누락·삭제(사라짐): {lost}개  ← 점검!" if lost else "누락·삭제(사라짐): 없음")
    if worked:
        L.append(f"어제 작업: {worked}개 → {worked_exp}개 떴어요")
    L.append(f"지금 상위노출: 전체 {tot}개 중 {now}개")
    L.append("")
    L.append("[제품별 노출]")
    for t in reports:
        L.append(f"   {t.tab}: {t.total}개 중 {t.exposed_now}개")
    L += ["", _LEGEND]
    return "\n".join(L).rstrip()
