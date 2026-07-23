"""report_metrics: 백업(sheet-backup)들 → 대시보드용 context dict 계산 (일·주·월). 2026-07-13.

⚠️ 순수 계산 모듈(파일 I/O 없음, 테스트 대상). snapshot_diff / weekly_digest 재사용 = 새 데이터 0.
- 입력 backups_by_date = {'2026-07-10': backup_dict, ...}  (load_backup 결과 dict, 최신일이 '오늘')
- 출력 = report_html 이 그대로 렌더링하는 순수 dict (숫자 반올림은 렌더 단계에서, 여기선 raw + 일부 pct)
- 대상 = 이름에 '카외' 포함 탭(샴푸/바디워시/두드러기 카외). 그 외 탭 무시.
- 데이터로 계산 안 되는 값은 넣지 않는다(추측 금지). 평균체류일(W)은 코호트 관측 spell 로만,
  표본 부족 시 3.0 기본 + 출처 표기('cohort'/'default').

이 모듈은 기존 라이브 흐름(report_builder/weekly_digest/send_telegram_report)을 건드리지 않는 순수 추가.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from src.metric_guards import audit_daily, audit_monthly, audit_weekly
from src.snapshot_diff import (  # noqa: F401 — _H_WORKDATE 는 헤더 drift 방지 위해 의도적 재사용
    EXPOSED_VALUES,
    _H_WORKDATE,
    diff_backups,
    k_base_of,
    rank_of,
    row_identity,
)

# 평문 읽기 헤더(raw 게이트 불필요 — 시트 원본 그대로). snapshot_diff 헤더명과 동일 유지.
_H_LINK = "링크"
_H_KWCLASS = "키워드 분류"
_H_KEYWORD = "키워드"

GOAL_PCT = 75  # 목표 달성률(70~80% 중앙값). 게이지/필요발행 계산 기준.
_DEFAULT_DWELL = 3.0  # 평균체류일 표본 부족 시 기본값(추측 아닌 명시 fallback)
_MIN_DWELL_SPELLS = 5  # (구식 spell 방식) W 채택 최소 표본
_MIN_DWELL_COHORTS = 5  # 코호트 방식 W 채택 최소 발행배치(작업일) 표본
_MAX_DWELL_LAG = 14  # 코호트 생존곡선 최대 관측 lag. 60은 백업창(~2주)보다 커서 좌측절단·재발행
# 작업일 재스탬프로 S(L)가 비단조 반등→W 과대추정(실측 W=9.1 vs 실제 체류 ~2.5~4일, 필요발행 53 vs ~120~170).
# 창 이내(14)로 상한해 완화. (2026-07-16 진단·수정)
_MASS_DROP_MIN = 8  # 대량하락 이벤트 최소 절대 감소
_MASS_DROP_RATIO = 0.10  # + 전일 대비 이 비율 이상 감소해야 이벤트로 인정

_D2E_BUCKETS = ["당일", "1일", "2일", "3일", "4일", "5일", "6일", "일주일+"]


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _is_cafe(tab: str) -> bool:
    return "카외" in str(tab)


def _short(tab: str) -> str:
    return str(tab).replace("카외", "").strip()


def _cafe_rows(backup: dict) -> list:
    out: list = []
    for tab, rows in (backup.get("tabs") or {}).items():
        if _is_cafe(tab):
            out.extend(rows)
    return out


def _exposed(rows: list) -> int:
    return sum(1 for r in rows if k_base_of(r) in EXPOSED_VALUES)


def _iso_to_date(s: str) -> date:
    y, m, d = str(s).split("-")
    return date(int(y), int(m), int(d))


def _date_to_md(dt: date) -> str:
    return f"{dt.month}/{dt.day}"


def _md(iso: str) -> str:
    return _date_to_md(_iso_to_date(iso))


def _md_to_date(md, ref: date):
    """작업일(M/D, 연도 없음) → date. ref(오늘)보다 미래면 전년으로 해석(12월 wrap)."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})", str(md or ""))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        cand = date(ref.year, mo, d)
    except ValueError:
        return None
    if cand > ref:
        try:
            cand = date(ref.year - 1, mo, d)
        except ValueError:
            return None
    return cand


def _funnel_for_date(rows: list, md: str) -> tuple:
    """(발행, 노출): 작업일==md & 링크有 인 행 수 / 그중 현재 상위노출 수. (task 정의 = 링크 필수)"""
    pub = exp = 0
    for r in rows:
        wd = str(r.get(_H_WORKDATE, "") or "").strip()
        link = str(r.get(_H_LINK, "") or "").strip()
        if wd == md and link:
            pub += 1
            if k_base_of(r) in EXPOSED_VALUES:
                exp += 1
    return pub, exp


def _days_to_expose(rows: list, ref: date) -> dict:
    """현재 상위노출 행들을 (오늘 − 작업일) 기준 버킷 분류."""
    b = {k: 0 for k in _D2E_BUCKETS}
    for r in rows:
        if k_base_of(r) not in EXPOSED_VALUES:
            continue
        dt = _md_to_date(str(r.get(_H_WORKDATE, "") or "").strip(), ref)
        if dt is None:
            continue
        diff = (ref - dt).days
        if diff < 0:
            continue
        if diff == 0:
            b["당일"] += 1
        elif diff <= 6:
            b[f"{diff}일"] += 1
        else:
            b["일주일+"] += 1
    return b


def _category_rates(rows: list) -> list:
    """키워드 분류(3 증상/4 대안/5 브랜드제품/5 카테고리…)별 달성률."""
    tot: Counter = Counter()
    exp: Counter = Counter()
    for r in rows:
        c = str(r.get(_H_KWCLASS, "") or "").strip() or "미분류"
        tot[c] += 1
        if k_base_of(r) in EXPOSED_VALUES:
            exp[c] += 1
    out = []
    for c in sorted(tot, key=lambda k: (-tot[k], k)):
        out.append({
            "cat": c, "total": tot[c], "exposed": exp[c],
            "pct": round(exp[c] / tot[c] * 100) if tot[c] else 0,
        })
    return out


def _avg_dwell(backups_by_date: dict) -> tuple:
    """평균체류일 W = 관측된 노출 유지 spell(연속 노출 구간) 길이의 평균.

    창 안 각 키워드의 maximal 노출 run 길이를 모아 평균(우측검열 spell 포함 = 표준 코호트).
    ⚠️ 이 데이터는 누락↔회복 깜빡임이 잦아 run 이 짧게 관측될 수 있음(HTML 에 출처·공식 투명 표기).
    spell 표본 < _MIN_DWELL_SPELLS 면 기본값 3.0 반환. 반환 (W: float, source, n_spells).
    """
    dates = sorted(backups_by_date)
    if len(dates) < 3:
        return (_DEFAULT_DWELL, "default", 0)
    series: dict = {}
    for d in dates:
        for r in _cafe_rows(backups_by_date[d]):
            series.setdefault(row_identity(r), {})[d] = k_base_of(r) in EXPOSED_VALUES
    lengths: list = []
    for dmap in series.values():
        seq = [dmap.get(d) for d in dates]  # True/False/None(그날 행 없음)
        n = len(seq)
        i = 0
        while i < n:
            if seq[i] is True:
                j = i
                while j < n and seq[j] is True:
                    j += 1
                lengths.append(j - i)
                i = j
            else:
                i += 1
    if len(lengths) >= _MIN_DWELL_SPELLS:
        return (round(sum(lengths) / len(lengths), 1), "cohort", len(lengths))
    return (_DEFAULT_DWELL, "default", len(lengths))


def _cohort_lag(workdate: str, snap: date):
    """(발행일 date, lag): 작업일(M/D) → 스냅샷일 기준 lag(일). 관측 불가 시 None.

    작업일이 스냅샷보다 미래면 전년(12월 wrap)으로 재해석하되, lag 이 _MAX_DWELL_LAG 초과면
    '아직 발행 전(미래 작업일)' 아티팩트로 보고 제외. lag<1(당일/미래)도 제외.
    """
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})", str(workdate or ""))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        pub = date(snap.year, mo, d)
    except ValueError:
        return None
    if pub > snap:  # 스냅샷보다 미래 = 전년(12월→1월 wrap) 후보
        try:
            pub = date(snap.year - 1, mo, d)
        except ValueError:
            return None
    lag = (snap - pub).days
    if lag < 1 or lag > _MAX_DWELL_LAG:
        return None
    return (pub, lag)


def _dwell_cohort_curve(backups_by_date: dict) -> tuple:
    """코호트 생존곡선 원자료 (lag_tot, lag_exp, n_cohorts). _avg_dwell_cohort + audit 재사용.

    각 발행일 D 배치(작업일==D & 링크有)를 D+L 일 스냅샷에서 여전히 상위노출인지로 lag 별 집계.
    반환한 lag_tot/lag_exp 로 S(L)=exp/tot 를 만들면 metric_guards.guard_survival 이 반등을 감시.
    """
    dates = sorted(backups_by_date)
    lag_tot: Counter = Counter()
    lag_exp: Counter = Counter()
    cohorts: set = set()
    if len(dates) < 2:
        return (lag_tot, lag_exp, 0)
    for snap_iso in dates:
        snap = _iso_to_date(snap_iso)
        for r in _cafe_rows(backups_by_date[snap_iso]):
            if not str(r.get(_H_LINK, "") or "").strip():
                continue
            res = _cohort_lag(str(r.get(_H_WORKDATE, "") or "").strip(), snap)
            if res is None:
                continue
            pub, lag = res
            lag_tot[lag] += 1
            if k_base_of(r) in EXPOSED_VALUES:
                lag_exp[lag] += 1
            cohorts.add(pub)
    return (lag_tot, lag_exp, len(cohorts))


def _dwell_summary(lag_tot: Counter, lag_exp: Counter, n_cohorts: int) -> tuple:
    """생존곡선 → (W, source, n). 표본 부족 시 기본값 3.0(추측 아닌 명시 fallback)."""
    if n_cohorts < _MIN_DWELL_COHORTS or not lag_tot:
        return (_DEFAULT_DWELL, "default", n_cohorts)
    W = sum(lag_exp[L] / lag_tot[L] for L in lag_tot)
    return (round(W, 1), "cohort", n_cohorts)


def _avg_dwell_cohort(backups_by_date: dict) -> tuple:
    """평균체류일 W = 발행 배치 코호트 생존곡선의 합  W = Σ_{L≥1} S(L).

    각 발행일 D 배치(작업일==D & 링크有)를 기준으로, D+L 일 스냅샷에서 같은 배치가 여전히
    상위노출인 비율 S(L)을 lag 별로 풀링해 합산(관측 가능한 lag 만, L≤_MAX_DWELL_LAG).
    ⚠️ 2026-07-16 실측: 재발행(작업일 재스탬프)·좌측절단으로 S(L)가 비단조 반등해 이 방식이
    오히려 W 를 과대추정함(9.1). _MAX_DWELL_LAG 를 창 이내로 상한해 완화 + metric_guards 로
    생존곡선 반등을 직접 감시(리포트에 ⚠️). 구식 _avg_dwell(spell 평균 ~2.5)은 참고·괴리검출용.

    발행 코호트(작업일) 표본 < _MIN_DWELL_COHORTS 면 기본값 3.0. 반환 (W: float, source, n_cohorts).
    """
    lag_tot, lag_exp, n = _dwell_cohort_curve(backups_by_date)
    return _dwell_summary(lag_tot, lag_exp, n)


def _exposure_reconcile(prev: dict, curr: dict) -> dict:
    """노출 수 정합식(어제 + 들어옴 − 나감 + 기타 = 오늘)을 실제 노출 전이로 정확히 산출.

    kind 라벨('누락'/'삭제')만 세면 노출→미노출('변화') 이탈이 빠져 잔차가 커진다.
    여기선 행 매칭(row_identity)으로 실제 노출 여부 전이를 직접 세어 항등식이 정확히 성립.
    residual = 신규행(오늘만) 노출 − 사라진행(어제만) 노출.
    """
    def _idx(bk):
        m = {}
        for r in _cafe_rows(bk):
            m[row_identity(r)] = k_base_of(r) in EXPOSED_VALUES
        return m

    pmap, cmap = _idx(prev), _idx(curr)
    prev_exp = sum(1 for v in pmap.values() if v)
    curr_exp = sum(1 for v in cmap.values() if v)
    gained = lost = new_exp = gone_exp = 0
    for ident, cv in cmap.items():
        pv = pmap.get(ident)
        if pv is None:
            if cv:
                new_exp += 1
        elif cv and not pv:
            gained += 1
        elif pv and not cv:
            lost += 1
    for ident, pv in pmap.items():
        if pv and ident not in cmap:
            gone_exp += 1
    return {
        "prev": prev_exp, "gained": gained, "lost": lost, "curr": curr_exp,
        "new_exposed": new_exp, "gone_exposed": gone_exp,
        "residual": new_exp - gone_exp,
    }


def _keyword_stability(backups_by_date: dict) -> tuple:
    """(best, worst): Best=창 대부분 유지 / Worst=노출→이탈 반복. 각 [{keyword,frac|drops,...}]."""
    dates = sorted(backups_by_date)
    series: dict = {}
    meta: dict = {}
    for d in dates:
        for r in _cafe_rows(backups_by_date[d]):
            ident = row_identity(r)
            series.setdefault(ident, []).append(k_base_of(r) in EXPOSED_VALUES)
            kw = str(r.get(_H_KEYWORD, "") or "").strip()
            if kw:
                meta[ident] = kw
    best: list = []
    worst: list = []
    for ident, seq in series.items():
        n = len(seq)
        kw = meta.get(ident, "")
        if n < 3 or not kw:
            continue
        frac = sum(seq) / n
        drops = sum(1 for i in range(1, n) if seq[i - 1] and not seq[i])
        if frac >= 0.9 and sum(seq) >= 3:
            best.append({"keyword": kw, "days": sum(seq), "window": n, "pct": round(frac * 100)})
        if drops >= 2:
            worst.append({"keyword": kw, "drops": drops, "exposed_days": sum(seq), "window": n})
    best.sort(key=lambda x: (-x["pct"], -x["days"], x["keyword"]))
    worst.sort(key=lambda x: (-x["drops"], -x["exposed_days"], x["keyword"]))
    return (best[:10], worst[:10])


def _mass_drops(backups_by_date: dict) -> list:
    """전일 대비 상위노출 급감일(대량하락 이벤트). 절대 & 비율 임계 동시 충족."""
    dates = sorted(backups_by_date)
    events: list = []
    for i in range(1, len(dates)):
        a = _exposed(_cafe_rows(backups_by_date[dates[i - 1]]))
        b = _exposed(_cafe_rows(backups_by_date[dates[i]]))
        drop = a - b
        if drop >= _MASS_DROP_MIN and a > 0 and drop >= a * _MASS_DROP_RATIO:
            events.append({"date": _md(dates[i]), "from": a, "to": b, "drop": drop})
    return events


def _kinds_of(reports: list) -> Counter:
    c: Counter = Counter()
    for r in reports:
        c.update(d.kind for d in r.diffs)
    return c


def _trend(backups_by_date: dict, last_n: int) -> list:
    dates = sorted(backups_by_date)[-last_n:]
    return [{"date": _md(d), "exposed": _exposed(_cafe_rows(backups_by_date[d]))} for d in dates]


def _window_days(dates: list) -> int:
    """관측창 = 백업 첫날~마지막날 일수(+1). 체류일 과대추정·필요발행 밴드 판정 기준."""
    if not dates:
        return 0
    return (_iso_to_date(dates[-1]) - _iso_to_date(dates[0])).days + 1


# ── 일간 ─────────────────────────────────────────────────────────────────────
def daily_context(backups_by_date: dict) -> dict:
    """일간 대시보드 context. 최신일=오늘, 직전일=어제(비교). 최근 6~7일로 추세/퍼널."""
    dates = sorted(backups_by_date)
    if not dates:
        return {"scope": "daily", "empty": True}
    today = dates[-1]
    ref = _iso_to_date(today)
    curr = backups_by_date[today]
    prev = backups_by_date[dates[-2]] if len(dates) >= 2 else None
    today_md = _md(today)
    reports = [r for r in diff_backups(prev, curr, work_date=today_md) if _is_cafe(r.tab)]

    tabs = [{
        "name": _short(r.tab), "full": r.tab, "total": r.total,
        "exposed": r.exposed_now, "exposed_prev": r.exposed_prev,
        "baseline": r.baseline_available,
    } for r in reports]
    total = sum(t["total"] for t in tabs)
    exposed = sum(t["exposed"] for t in tabs)
    exposed_prev = sum(t["exposed_prev"] for t in tabs)
    has_base = prev is not None and any(t["baseline"] for t in tabs)

    kinds = _kinds_of(reports)
    changes = {k: kinds.get(k, 0) for k in ["신규노출", "오름", "내림", "누락", "삭제"]}
    # 정합식은 실제 노출 전이 기준(kind 라벨은 '변화' 이탈을 놓쳐 잔차가 큼)
    reconcile = (_exposure_reconcile(prev, curr) if has_base
                 else {"prev": 0, "gained": 0, "lost": 0, "curr": exposed, "residual": 0})

    curr_rows = _cafe_rows(curr)
    published_today, published_today_exposed = _funnel_for_date(curr_rows, today_md)

    lag_tot, lag_exp, w_n = _dwell_cohort_curve(backups_by_date)  # 생존곡선(audit 재사용)
    W, w_src, w_n = _dwell_summary(lag_tot, lag_exp, w_n)
    spell_W = _avg_dwell(backups_by_date)[0]  # 구식 spell 방식(괴리 검출용 비교값)
    need_publish = round(total * (GOAL_PCT / 100) / W) if (total and W) else 0

    funnel = []
    ft_pub = ft_exp = 0
    for i in range(6, -1, -1):
        md = _date_to_md(ref - timedelta(days=i))
        p, e = _funnel_for_date(curr_rows, md)
        funnel.append({"date": md, "published": p, "exposed": e,
                       "pct": round(e / p * 100) if p else 0})
        ft_pub += p
        ft_exp += e
    funnel_total = {"published": ft_pub, "exposed": ft_exp,
                    "pct": round(ft_exp / ft_pub * 100) if ft_pub else 0}

    type_dist = Counter()
    for r in reports:
        type_dist.update(r.type_dist)
    type_changes = sum(r.type_changes for r in reports)
    jisikin = sum(r.jisikin_now for r in reports)

    ctx = {
        "scope": "daily",
        "date_label": today_md,
        "date_full": today,
        "status_line": "정상",
        "tabs": tabs,
        "total": total,
        "exposed": exposed,
        "exposed_prev": exposed_prev,
        "exposed_delta": exposed - exposed_prev if has_base else None,
        "achieve_pct": round(exposed / total * 100) if total else 0,
        "goal_pct": GOAL_PCT,
        "avg_dwell": W,
        "avg_dwell_source": w_src,
        "avg_dwell_n": w_n,
        "avg_dwell_spell": spell_W,
        "window_days": _window_days(dates),
        "need_publish": need_publish,
        "published_today": published_today,
        "published_today_exposed": published_today_exposed,
        "has_base": has_base,
        "changes": changes,
        "reconcile": reconcile,
        "trend": _trend(backups_by_date, 6),
        "funnel_by_date": funnel,
        "funnel_total": funnel_total,
        "days_to_expose": _days_to_expose(curr_rows, ref),
        "type_dist": {k: type_dist.get(k, 0) for k in ["AB", "스마트블록", "인기글"]},
        "type_changes": type_changes,
        "jisikin": jisikin,
    }
    ctx["warnings"] = audit_daily(ctx, (lag_tot, lag_exp))
    return ctx


# ── 주간 ─────────────────────────────────────────────────────────────────────
def weekly_context(backups_by_date: dict) -> dict:
    """주간 집계. 창의 첫날=주 시작(prev), 마지막날=현재(curr)."""
    dates = sorted(backups_by_date)
    if not dates:
        return {"scope": "weekly", "empty": True}
    today = dates[-1]
    ref = _iso_to_date(today)
    start = dates[0]
    curr = backups_by_date[today]
    prev = backups_by_date[start] if start != today else None
    curr_rows = _cafe_rows(curr)
    reports = [r for r in diff_backups(prev, curr, work_date=None) if _is_cafe(r.tab)]

    total = sum(r.total for r in reports)
    exposed = sum(r.exposed_now for r in reports)
    exposed_start = sum(r.exposed_prev for r in reports)
    has_base = prev is not None
    week_gain = exposed - exposed_start if has_base else None

    span = (ref - _iso_to_date(start)).days + 1
    week_pub = week_exp = 0
    daily_funnel = []
    for i in range(span - 1, -1, -1):
        md = _date_to_md(ref - timedelta(days=i))
        p, e = _funnel_for_date(curr_rows, md)
        week_pub += p
        week_exp += e
        daily_funnel.append({"date": md, "published": p, "exposed": e,
                             "pct": round(e / p * 100) if p else 0})
    efficiency = (round(week_gain / week_pub * 100) if (has_base and week_pub) else None)

    churn = []
    for r in reports:
        for d in r.diffs:
            if d.prev_rank == 1 and d.kind in ("누락", "삭제", "내림"):
                churn.append({"tab": _short(r.tab), "keyword": d.keyword,
                              "kind": d.kind, "curr_rank": d.curr_rank})
    churn = churn[:10]

    lag_tot, lag_exp, w_n = _dwell_cohort_curve(backups_by_date)  # 생존곡선(audit 재사용)
    W, w_src, w_n = _dwell_summary(lag_tot, lag_exp, w_n)
    spell_W = _avg_dwell(backups_by_date)[0]

    ctx = {
        "scope": "weekly",
        "date_range": f"{_md(start)}~{_md(today)}",
        "date_full": today,
        "status_line": "정상",
        "total": total,
        "exposed": exposed,
        "exposed_start": exposed_start,
        "has_base": has_base,
        "week_gain": week_gain,
        "week_published": week_pub,
        "week_exposed_from_pub": week_exp,
        "efficiency_pct": efficiency,
        "achieve_pct": round(exposed / total * 100) if total else 0,
        "goal_pct": GOAL_PCT,
        "avg_dwell": W,
        "avg_dwell_source": w_src,
        "avg_dwell_n": w_n,
        "avg_dwell_spell": spell_W,
        "window_days": _window_days(dates),
        "trend": _trend(backups_by_date, span),
        "funnel_by_date": daily_funnel,
        "funnel_total": {"published": week_pub, "exposed": week_exp,
                         "pct": round(week_exp / week_pub * 100) if week_pub else 0},
        "churn_top": churn,
        "categories": _category_rates(curr_rows),
    }
    ctx["warnings"] = audit_weekly(ctx, (lag_tot, lag_exp))
    return ctx


# ── 월간 ─────────────────────────────────────────────────────────────────────
def monthly_context(backups_by_date: dict) -> dict:
    """월간 집계(더 깊게). 주별 추세 + Best/Worst + 대량하락 + 진단."""
    dates = sorted(backups_by_date)
    if not dates:
        return {"scope": "monthly", "empty": True}
    today = dates[-1]
    curr = backups_by_date[today]
    curr_rows = _cafe_rows(curr)
    total = len(curr_rows)
    exposed = _exposed(curr_rows)

    weeks = []
    for i in range(0, len(dates), 7):
        chunk = dates[i:i + 7]
        c_prev = backups_by_date[chunk[0]]
        c_curr = backups_by_date[chunk[-1]]
        c_rows = _cafe_rows(c_curr)
        c_tot = len(c_rows)
        c_exp = _exposed(c_rows)
        gain = c_exp - _exposed(_cafe_rows(c_prev))
        pub = sum(_funnel_for_date(c_rows, _md(d))[0] for d in chunk)
        weeks.append({
            "label": f"{_md(chunk[0])}~{_md(chunk[-1])}",
            "total": c_tot, "exposed": c_exp,
            "pct": round(c_exp / c_tot * 100) if c_tot else 0,
            "gain": gain, "published": pub,
            "efficiency_pct": round(gain / pub * 100) if pub else None,
        })

    best, worst = _keyword_stability(backups_by_date)
    events = _mass_drops(backups_by_date)
    lag_tot, lag_exp, w_n = _dwell_cohort_curve(backups_by_date)  # 생존곡선(audit 재사용)
    W, w_src, w_n = _dwell_summary(lag_tot, lag_exp, w_n)
    spell_W = _avg_dwell(backups_by_date)[0]
    need_daily = round(total * (GOAL_PCT / 100) / W) if (total and W) else 0
    need_month = need_daily * 30

    achieve_pct = round(exposed / total * 100) if total else 0
    diag = _monthly_diagnosis(achieve_pct, exposed, weeks, events, W, w_src)

    ctx = {
        "scope": "monthly",
        "date_range": f"{_md(dates[0])}~{_md(today)}",
        "date_full": today,
        "status_line": "정상",
        "total": total,
        "exposed": exposed,
        "achieve_pct": achieve_pct,
        "goal_pct": GOAL_PCT,
        "avg_dwell": W,
        "avg_dwell_source": w_src,
        "avg_dwell_n": w_n,
        "avg_dwell_spell": spell_W,
        "window_days": _window_days(dates),
        "weeks": weeks,
        "categories": _category_rates(curr_rows),
        "best_keywords": best,
        "worst_keywords": worst,
        "mass_drops": events,
        "need_publish_daily": need_daily,
        "need_publish_month": need_month,
        "ga4_placeholder": "신규 유입·매출 동행 = GA4/매출 연결 필요(다음 과제). 현재 데이터로는 노출까지만 측정.",
        "diagnosis": diag,
    }
    ctx["warnings"] = audit_monthly(ctx, (lag_tot, lag_exp))
    return ctx


def _monthly_diagnosis(achieve_pct, exposed, weeks, events, W, w_src) -> list:
    """서술형 진단 문단(데이터로 확인된 것만; 가설은 '가설:' 접두). 리스트[문장]."""
    L = []
    L.append(f"이번 기간 달성률 {achieve_pct}% · 현재 상위노출 {exposed}개.")
    if len(weeks) >= 2:
        first, last = weeks[0]["pct"], weeks[-1]["pct"]
        trend_word = "상승" if last > first else ("하락" if last < first else "보합")
        L.append(f"주별 달성률 {first}% → {last}% ({trend_word}).")
    if events:
        worst = max(events, key=lambda e: e["drop"])
        L.append(f"대량하락 {len(events)}회 관측 — 가장 큰 날 {worst['date']} ({worst['from']}→{worst['to']}, -{worst['drop']}개).")
    else:
        L.append("기간 중 대량하락 이벤트 없음.")
    src_note = "코호트 기준" if w_src == "cohort" else "표본 부족 → 기본값 3.0"
    L.append(f"평균체류일(W) {W}일 ({src_note}).")
    if events:
        L.append("가설: 대량하락일은 네이버 노출영역 개편/재색인 영향일 수 있음 — 라이브 확인 필요(측정 미완).")
    return L
