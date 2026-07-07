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


def _all_type_change_dirs(reports: list[TabReport]) -> Counter:
    """탭 전체의 '바뀐 방향' 합산 {'AB→인기글': n}."""
    c: Counter = Counter()
    for t in reports:
        c.update(t.type_change_dirs)
    return c


def _sum(reports: list[TabReport], attr: str) -> int:
    return sum(getattr(t, attr) for t in reports)


def _build_full_report(reports: list[TabReport], kst: str, status_line: str, title: str, breakdown: list | None = None, lag_dist: Counter | None = None, exposure_trend=None, cohort=None) -> str:
    """상세 보고 본문 (저녁/아침 공통 — 헤더 title 만 다름).

    사장님 요청(2026-06-21): 아침도 저녁과 동일 형식으로 통일.
    """
    tot = _sum(reports, "total")
    now = _sum(reports, "exposed_now")
    jis_now = _sum(reports, "jisikin_now")
    has_base = any(t.baseline_available for t in reports)
    kc = _all_kinds(reports)

    L = [title, f"프로그램: {status_line}", ""]

    # 날짜별 발행 → 상위노출 (사장님 2026-07-02: '어제 작업 대비 노출' 대신 날짜별·제품별 발행분과 그중 상위노출)
    if breakdown:
        L.append("[① 날짜별 발행 → 상위노출]   · 작업한 날 기준(그 날 쓴 글이 지금 몇 개 떴나)")
        for ds, per, (dw, de) in breakdown:
            pct = round(de / dw * 100) if dw else 0
            seg = " · ".join(
                f"{t.replace(' 카외', '')} {w}→{e}"
                for t, (w, e) in per.items() if w
            )
            L.append(f"   {ds}  발행 {dw} → 상위노출 {de} ({pct}%)   [{seg}]")
        tw = sum(b[2][0] for b in breakdown)
        te = sum(b[2][1] for b in breakdown)
        L.append(f"   ── 최근 7일 합계: 발행 {tw} → 상위노출 {te} ({round(te / tw * 100) if tw else 0}%)")
        L.append("")

    # ② 노출 소요일 (발행 후 며칠 만에 떴나 — 지금 노출된 키워드 대상, 근사치=K스탬프 기준)
    if lag_dist and sum(lag_dist.values()):
        total_exp = sum(lag_dist.values())
        same = lag_dist.get("당일", 0)
        wk = lag_dist.get("+1일", 0) + lag_dist.get("+2일", 0) + lag_dist.get("+3~6일", 0)
        over = lag_dist.get("+7일+", 0)
        odd = lag_dist.get("음수(재노출)", 0) + lag_dist.get("미상", 0)
        L.append(f"[② 발행하고 며칠 만에 떴나]   · 지금 떠 있는 글 {total_exp}개 기준")
        L.append(f"   발행 당일 뜸 : {same}개")
        if wk:
            L.append(f"   1~6일 안에 뜸 : {wk}개")
        if over:
            L.append(f"   일주일 넘게 걸림 : {over}개")
        if odd:
            L.append(f"   애매(뗐다 다시 뜬 것) : {odd}개")
        L.append("")

    # 지금 상위노출 (현재 전체 스냅샷 — 하루 변화는 ③으로 분리)
    L.append("[지금 상위노출]")
    L.append(f"   전체 {tot}개 중 {now}개 노출 중")
    L.append("")

    # [추세] 최근 며칠 상위노출 개수 흐름 (사장님 2026-07-07: 매일 개수만 말고 흐름을 보고싶다)
    if exposure_trend and len(exposure_trend) >= 2:
        dates = list(exposure_trend.keys())
        L.append(f"[추세]  최근 {len(dates)}일 상위노출 개수 (→ 오른쪽이 오늘)")
        totals = [exposure_trend[d]["합계"] for d in dates]
        L.append("   합계     " + " → ".join(str(x) for x in totals))
        tabs = sorted({t for d in dates for t in exposure_trend[d] if t != "합계"})
        for t in tabs:
            seq = [exposure_trend[d].get(t, 0) for d in dates]
            L.append(f"   {t.replace(' 카외', '')}   " + " → ".join(str(x) for x in seq))
        prev_t, today_t = totals[-2], totals[-1]
        diff = today_t - prev_t
        word = f"{diff}개 늘음" if diff > 0 else (f"{-diff}개 줄음" if diff < 0 else "그대로")
        L.append(f"   ▶ 어제 {prev_t} → 오늘 {today_t} ({word})")
        L.append("")

    # [발행분 변화] 발행일별 코호트가 며칠 뒤 몇 개 떠 있나 (사장님 2026-07-07: 7/6 발행분의 변화)
    if cohort:
        L.append("[발행분 변화]  발행한 날 글이 며칠 뒤 몇 개 떠 있나")
        for md, total, steps in cohort:
            seq = " → ".join(f"{lab} {n}개" for lab, n in steps)
            L.append(f"   {md} 발행 {total}개  →  {seq}")
        L.append("")

    # ③ 어제 → 오늘 변화 (날짜 무관) + 정합: 노출 개수 변화를 완전 설명 (사장님 2026-07-07)
    if has_base:
        prev_now = _sum(reports, "exposed_prev")
        new_exp = _sum(reports, "new_exposed")
        vanished = _sum(reports, "vanished_exposed")
        other_exit = _sum(reports, "other_exit")
        gained = kc.get("신규노출", 0) + new_exp
        left = kc.get("누락", 0) + kc.get("삭제", 0) + other_exit + vanished
        L.append("[③ 어제 → 오늘 변화]   · 날짜 무관, 어제 대비 하루 사이")
        if kc.get("신규노출"):
            L.append(f"   새로 뜸(미노출→상위노출): {kc['신규노출']}개")
        if new_exp:
            L.append(f"   새 키워드 노출(어제 없던 글): {new_exp}개")
        if kc.get("누락"):
            L.append(f"   빠짐(상위노출→누락): {kc['누락']}개 (보통 다음 검사에 회복)")
        if kc.get("삭제"):
            L.append(f"   삭제(글 사라짐): {kc['삭제']}개  ← 점검")
        if other_exit:
            L.append(f"   기타 이탈(미노출/재검사 등): {other_exit}개")
        if vanished:
            L.append(f"   사라진 행(줄 자체 삭제): {vanished}개")
        if kc.get("오름"):
            L.append(f"   순위 상승: {kc['오름']}개")
        if kc.get("내림"):
            L.append(f"   순위 하락: {kc['내림']}개")
        if not (gained or left or kc.get("오름") or kc.get("내림")):
            L.append("   변화 없음")
        L.append(f"   ── 정합: 어제 {prev_now} + 들어옴 {gained} − 나감 {left} = 오늘 {now}")
        L.append("")

    # 제품별 노출 (현재 스냅샷)
    L.append("[제품별 노출]")
    for t in reports:
        L.append(f"   {t.tab}: {t.total}개 중 {t.exposed_now}개")
    L.append("")

    # 대표 노출 유형 (총 비율 + 어제→오늘 바뀐 방향)
    td = _all_type_dist(reports)
    if td:
        tot_t = sum(td.values())
        seg = " · ".join(
            f"{k} {td[k]}개({round(td[k] * 100 / tot_t)}%)"
            for k in ["AB", "스마트블록", "인기글"]
            if td.get(k)
        )
        L.append("[대표 노출 유형]")
        L.append(f"   전체 {tot_t}개 — {seg}")
        tch = _sum(reports, "type_changes")
        if tch:
            L.append(f"   유형 바뀐 키워드: {tch}개")
            dirs = _all_type_change_dirs(reports)
            for d, n in dirs.most_common(5):
                L.append(f"      {d.replace('→', ' → ')}: {n}개")
            if len(dirs) > 5:
                L.append(f"      그 외 {len(dirs) - 5}종")
        L.append("")

    # 지식인
    if jis_now or _sum(reports, "jisikin_prev"):
        L.append(f"[지식인]  지식인에 뜬 키워드: {jis_now}개")

    L += ["", _LEGEND]
    return "\n".join(L).rstrip()


def build_evening_report(reports: list[TabReport], kst: str, status_line: str = "정상", breakdown: list | None = None, lag_dist: Counter | None = None, exposure_trend=None, cohort=None) -> str:
    """저녁 마감 — 한글 말 중심, 섹션별."""
    if not reports:
        return f"📊 상노체크 · {kst} 저녁\n데이터 없음"
    return _build_full_report(reports, kst, status_line, f"📊 상노체크 · {kst} 저녁", breakdown, lag_dist, exposure_trend, cohort)


def build_morning_report(reports: list[TabReport], kst: str, status_line: str = "정상", breakdown: list | None = None, lag_dist: Counter | None = None, exposure_trend=None, cohort=None) -> str:
    """아침 보고 — 저녁과 동일 형식(사장님 요청 2026-06-21). 헤더만 ☀️ 아침."""
    if not reports:
        return f"☀️ 상노체크 아침 · {kst}\n데이터 없음"
    return _build_full_report(reports, kst, status_line, f"☀️ 상노체크 아침 · {kst}", breakdown, lag_dist, exposure_trend, cohort)
