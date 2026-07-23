"""metric_guards: 리포트 숫자 자가검증(guardrail) 층. 2026-07-16.

⚠️ 순수 함수 모듈(파일 I/O 0, 외부 의존 0 — 표준 라이브러리만). 테스트 대상.
목적: 공식이 맞아도 현실에서 틀린 숫자가 조용히 리포트로 나가는 걸 영구히 방지한다.
각 지표에 '상식 범위 + 구조 불변식'을 걸어, 벗어나면 사장님이 읽는 한국어 경고 문자열을 만든다.

- 각 guard_*(...) → 경고 문자열 리스트(위반 없으면 []).
- audit_daily/weekly/monthly(ctx, curve) → 해당 리포트의 전체 경고 리스트.
- report_metrics 가 context 계산 직후 audit_* 를 불러 ctx["warnings"] 에 담고,
  report_html 이 경고가 있으면 맨 위 ⚠️ 카드로 렌더한다.

배경(2026-07-16): 코호트 생존곡선 방식이 재발행(작업일 재스탬프)·좌측절단 오염으로 S(L)가
비단조 반등 → 평균체류일 W 과대추정(실측 9.1, 실제 ~2.5~4일) → 필요발행 과소추정.
그 결정적 시그니처가 '생존곡선 반등'이라 guard_survival 로 직접 잡는다. 과거 '821' 같은
'노출수가 전체 키워드수를 초과'하는 집계 오류는 guard_counts 로 잡는다.
"""
from __future__ import annotations

# ── 임계(상식 범위) 상수 ──────────────────────────────────────────────────────
_DWELL_METHOD_GAP = 2.5   # 코호트W / spellW 가 이 배수 초과면 두 계산법 괴리로 경고
_SURVIVAL_REBOUND_TOL = 0.05  # 생존곡선 유지율이 이 값(5%p) 초과로 반등하면 단조성 위반


def guard_dwell(W, source, spell_W, window_days) -> list:
    """평균체류일 W 의 상식 범위 + 두 계산법(코호트 vs spell) 괴리 검사.

    - W > 관측창(window_days): 관측 가능한 일수보다 긴 체류 = 과대추정 의심.
    - source=='cohort' & spell_W>0 & W/spell_W > 2.5: 코호트·spell 두 계산법이 크게 어긋남.
    - W < 1: 하루도 안 유지 = 비현실적으로 짧음(집계/공식 오류 의심).
    """
    out: list = []
    try:
        Wf = float(W)
    except (TypeError, ValueError):
        return [f"평균체류일(W) 값이 숫자가 아님({W!r}) — 계산 오류 의심."]
    if window_days and Wf > float(window_days):
        out.append(
            f"평균체류일 {Wf}일이 관측창 {window_days}일보다 큼 — 관측 못 한 구간까지 "
            f"유지로 가정한 과대추정 의심. 필요발행이 과소 산출됐을 수 있음."
        )
    if source == "cohort" and spell_W and float(spell_W) > 0:
        ratio = Wf / float(spell_W)
        if ratio > _DWELL_METHOD_GAP:
            out.append(
                f"평균체류일 두 계산법 괴리 — 코호트 {Wf}일 vs 관측spell {round(float(spell_W), 1)}일 "
                f"({ratio:.1f}배). 생존곡선 오염(재발행·좌측절단) 가능성, W 신뢰도 낮음."
            )
    if Wf < 1:
        out.append(f"평균체류일 {Wf}일 < 1 — 하루도 못 버티는 값이라 비현실적(집계/공식 재확인).")
    return out


def guard_survival(lag_tot, lag_exp) -> list:
    """생존곡선 S(L)=exp/tot 이 실질적으로 반등(단조 비증가 위반)하면 경고.

    정상 생존곡선은 lag 가 커질수록 유지율이 비증가여야 한다. 재발행으로 작업일이 재스탬프되거나
    좌측절단(창 밖 발행)이 섞이면 큰 lag 에서 유지율이 다시 올라가는 반등이 생기고, 이때 W 가
    과대추정된다 — 이번 W 버그(9.1)의 결정적 시그니처. 가장 큰 반등 1건을 대표로 보고한다.
    """
    lags = sorted(L for L in (lag_tot or {}) if lag_tot.get(L, 0) > 0)
    if len(lags) < 2:
        return []
    surv = [(L, lag_exp.get(L, 0) / lag_tot[L]) for L in lags]
    worst = None  # (delta, a, b, sa, sb)
    for (a, sa), (b, sb) in zip(surv, surv[1:]):
        delta = sb - sa
        if delta > _SURVIVAL_REBOUND_TOL and (worst is None or delta > worst[0]):
            worst = (delta, a, b, sa, sb)
    if worst is None:
        return []
    _, a, b, sa, sb = worst
    return [
        f"생존곡선 반등 — L{a}일→L{b}일 유지율 {sa*100:.0f}%→{sb*100:.0f}%. "
        f"오래된 글이 더 잘 버티는 건 비정상(재발행·좌측절단 오염). 평균체류일 과대추정 의심."
    ]


def guard_need_publish(need, total, window_days, W) -> list:
    """필요발행 need 가 상식 밴드 [total/window, total] 밖이면 경고.

    - 하한: 전체 total 을 관측창에 걸쳐 채우려면 최소 total/window/일(정수 내림)은 필요.
      그보다 작으면 체류일 과대추정 등으로 필요발행이 과소 산출됐을 가능성.
    - 상한: 하루 필요발행이 전체 키워드 수를 넘을 수 없다(전량 교체보다 많음 = 오류).
    """
    if not total or total <= 0 or not window_days or window_days <= 0:
        return []
    lo = max(1, int(total // window_days))
    hi = int(total)
    if need < lo or need > hi:
        return [
            f"필요발행 {need}개/일이 상식범위 [{lo}~{hi}]개 밖 — "
            f"체류일(W={W}일)·공식 입력 재확인(과대/과소 산출 의심)."
        ]
    return []


def guard_counts(exposed, total, label) -> list:
    """구조 불변식: 노출수는 전체 키워드수를 넘을 수 없고 음수일 수 없다('821'류 방지)."""
    out: list = []
    if exposed is None or total is None:
        return out
    if exposed < 0 or total < 0:
        out.append(f"'{label}' 값 음수(노출 {exposed}, 전체 {total}) — 집계 오류.")
        return out
    if exposed > total:
        out.append(
            f"'{label}' 노출 {exposed} > 전체 {total} — 노출수가 전체 키워드수를 초과할 수 없음"
            f"(집계 단위 혼동 의심, 예: 노출수 자리에 키워드수)."
        )
    return out


# ── 리포트 단위 종합 감사 ─────────────────────────────────────────────────────
def audit_daily(ctx: dict, curve=None) -> list:
    """일간 context 의 모든 guard 를 돌려 경고 리스트 반환(없으면 [])."""
    if not ctx or ctx.get("empty"):
        return []
    w = ctx.get("window_days") or 0
    out: list = []
    out += guard_dwell(ctx.get("avg_dwell"), ctx.get("avg_dwell_source"),
                       ctx.get("avg_dwell_spell", 0), w)
    if curve:
        out += guard_survival(curve[0], curve[1])
    out += guard_need_publish(ctx.get("need_publish"), ctx.get("total"), w, ctx.get("avg_dwell"))
    out += guard_counts(ctx.get("exposed"), ctx.get("total"), "지금 상위노출")
    # 퍼널 구조 불변식: 오늘 발행 중 노출수 ≤ 발행수
    out += guard_counts(ctx.get("published_today_exposed"), ctx.get("published_today"), "오늘 발행 노출")
    # 탭별 불변식
    for t in ctx.get("tabs") or []:
        out += guard_counts(t.get("exposed"), t.get("total"), f"{t.get('name', '탭')} 노출")
    return out


def audit_weekly(ctx: dict, curve=None) -> list:
    """주간 context 의 모든 guard 를 돌려 경고 리스트 반환(없으면 [])."""
    if not ctx or ctx.get("empty"):
        return []
    w = ctx.get("window_days") or 0
    out: list = []
    out += guard_dwell(ctx.get("avg_dwell"), ctx.get("avg_dwell_source"),
                       ctx.get("avg_dwell_spell", 0), w)
    if curve:
        out += guard_survival(curve[0], curve[1])
    out += guard_counts(ctx.get("exposed"), ctx.get("total"), "지금 상위노출")
    out += guard_counts(ctx.get("week_exposed_from_pub"), ctx.get("week_published"), "주간 발행 노출")
    return out


def audit_monthly(ctx: dict, curve=None) -> list:
    """월간 context 의 모든 guard 를 돌려 경고 리스트 반환(없으면 [])."""
    if not ctx or ctx.get("empty"):
        return []
    w = ctx.get("window_days") or 0
    out: list = []
    out += guard_dwell(ctx.get("avg_dwell"), ctx.get("avg_dwell_source"),
                       ctx.get("avg_dwell_spell", 0), w)
    if curve:
        out += guard_survival(curve[0], curve[1])
    out += guard_need_publish(ctx.get("need_publish_daily"), ctx.get("total"), w, ctx.get("avg_dwell"))
    out += guard_counts(ctx.get("exposed"), ctx.get("total"), "현재 상위노출")
    return out
