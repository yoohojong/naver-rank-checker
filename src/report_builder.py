"""report_builder: snapshot_diff 결과 → 텔레그램 요약 보고 텍스트. M10 (D-052 요약형 재설계).

⚠️ 비공개 채널(텔레그램 DM) 전용. plain text(마크다운 escape 불필요).
사장님 2026-06-20 요청: 키워드 나열 X → **숫자 요약 중심**.
구성: 손실 경보 → 어제 작업/적중 → 전체 상위노출·변화 → 제품별 1줄 → 지식인 → 내일 추천.
"""
from __future__ import annotations

from collections import Counter

from src.snapshot_diff import TabReport


def _arrow(prev: int, curr: int) -> str:
    d = curr - prev
    return f"▲{d}" if d > 0 else (f"▼{-d}" if d < 0 else "–")


def _kinds(tr: TabReport) -> Counter:
    return Counter(d.kind for d in tr.diffs)


def _change_icons(c: Counter) -> str:
    order = [("신규노출", "🟦"), ("오름", "🔺"), ("내림", "🔻"), ("누락", "⚠️"), ("삭제", "❌")]
    return " ".join(f"{ic}{c[k]}" for k, ic in order if c.get(k))


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


def _all_type_dirs(reports: list[TabReport]) -> Counter:
    c: Counter = Counter()
    for t in reports:
        c.update(t.type_change_dirs)
    return c


def _sum(reports: list[TabReport], attr: str) -> int:
    return sum(getattr(t, attr) for t in reports)


def build_evening_report(reports: list[TabReport], kst: str, status_line: str = "✅정상") -> str:
    """저녁 마감 요약."""
    if not reports:
        return f"📊 상노체크 · {kst} 마감 · {status_line}\n데이터 없음"
    tot = _sum(reports, "total")
    now = _sum(reports, "exposed_now")
    prev = _sum(reports, "exposed_prev")
    worked = _sum(reports, "worked")
    worked_exp = _sum(reports, "worked_exposed")
    jis_now = _sum(reports, "jisikin_now")
    jis_prev = _sum(reports, "jisikin_prev")
    has_base = any(t.baseline_available for t in reports)
    kc = _all_kinds(reports)
    lost = kc.get("누락", 0) + kc.get("삭제", 0)

    L = [f"📊 상노체크 · {kst} 마감 · {status_line}", ""]
    if lost:
        L += [f"🚨 빠진 키워드 {lost}개 (점검!)", ""]
    if worked:
        L.append(f"🔧 어제 작업  {worked}개 → {worked_exp}개 떴음 (적중 {round(worked_exp / worked * 100)}%)")
    rate = round(now / tot * 100) if tot else 0
    L.append(f"📈 전체 (키워드 {tot}개)")
    if has_base:
        L.append(f"   상위노출  {now}개 ({rate}%) · 어제 {_arrow(prev, now)}")
        tc = sum(kc.values())
        if tc:
            L.append(f"   순위변화 {tc}건 · {_change_icons(kc)}")
    else:
        L.append(f"   상위노출  {now}개 ({rate}%) · 어제 비교 기준 없음")

    td = _all_type_dist(reports)
    if td:
        seg = " · ".join(f"{k} {td[k]}" for k in ["AB", "스마트블록", "인기글"] if td.get(k))
        for k in td:
            if k not in ("AB", "스마트블록", "인기글"):
                seg += f" · {k} {td[k]}"
        L.append(f"🔀 유형(대표구좌)  {seg}")
        tch = _sum(reports, "type_changes")
        if tch:
            dirs = " · ".join(f"{d} {n}" for d, n in _all_type_dirs(reports).most_common(4))
            L.append(f"   변경 {tch}건 · {dirs}")

    L += ["", "🧴 제품별 (상위노출 / 변화)"]
    for t in reports:
        arrow = _arrow(t.exposed_prev, t.exposed_now) if t.baseline_available else "–"
        ic = _change_icons(_kinds(t))
        L.append(f"   {t.tab}  {t.exposed_now}/{t.total}  {arrow}" + (f"   {ic}" if ic else ""))
    if jis_now or jis_prev:
        extra = f" ({_arrow(jis_prev, jis_now)})" if has_base and jis_now != jis_prev else ""
        L.append(f"   지식인 노출  {jis_now}개{extra}")

    recs = []
    if lost:
        recs.append(f"빠진 {lost}개 점검")
    unworked = _sum(reports, "unworked")
    if unworked:
        recs.append(f"미작업 {unworked}개 중 우선 작업")
    if recs:
        L += ["", "💡 내일  " + " · ".join(recs)]
    return "\n".join(L).rstrip()


def build_morning_report(reports: list[TabReport], kst: str, status_line: str = "✅정상") -> str:
    """아침 요약 — 챙길 것(빠짐) + 어제 작업 + 전체·제품별 상위노출."""
    if not reports:
        return f"☀️ 상노체크 아침요약 · {kst} · {status_line}\n데이터 없음"
    now = _sum(reports, "exposed_now")
    tot = _sum(reports, "total")
    worked = _sum(reports, "worked")
    worked_exp = _sum(reports, "worked_exposed")
    kc = _all_kinds(reports)
    lost = kc.get("누락", 0) + kc.get("삭제", 0)

    L = [f"☀️ 상노체크 아침요약 · {kst} · {status_line}", ""]
    L.append(f"🚨 챙길 것(빠짐): {lost}개" if lost else "🚨 챙길 것: 없음")
    if worked:
        L.append(f"🔧 어제 작업  {worked}개 → {worked_exp}개 떴음 (적중 {round(worked_exp / worked * 100)}%)")
    L.append(f"📈 상위노출  {now}/{tot}")
    for t in reports:
        L.append(f"   {t.tab}  {t.exposed_now}/{t.total}")
    return "\n".join(L).rstrip()
