"""metric_guards 단위 테스트 (2026-07-16).

검증: 리포트 숫자 자가검증(guardrail) 층.
- 개별 guard(생존곡선 반등 / 체류일 상식범위 / 노출수 불변식 / 필요발행 밴드)가 정확히 트립.
- 정상 지표는 전부 무경고(false-positive 없음).
- 통합: guard 를 트립하는 합성 백업으로 daily_context 를 돌리면 ctx["warnings"] 채워짐.
외부 의존 0 — 합성 데이터만. (이번 W 버그 = 생존곡선 반등이 결정적 시그니처.)
"""
from collections import Counter

from src.metric_guards import (
    audit_daily,
    guard_counts,
    guard_dwell,
    guard_need_publish,
    guard_survival,
)
from src.report_metrics import daily_context
from tests.unit.test_report_metrics import _bk, _dataset, _row


# ── (a) 단조 생존곡선 → 무경고 ────────────────────────────────────────────────
def test_survival_monotone_no_warning():
    lag_tot = Counter({1: 10, 2: 10, 3: 10})
    lag_exp = Counter({1: 10, 2: 6, 3: 3})  # S = 1.0 → 0.6 → 0.3 (비증가)
    assert guard_survival(lag_tot, lag_exp) == []


# ── (b) 반등 생존곡선(이번 W버그 모양) → 경고 ─────────────────────────────────
def test_survival_rebound_warns():
    lag_tot = Counter({1: 10, 2: 10, 7: 10, 8: 10})
    lag_exp = Counter({1: 9, 2: 5, 7: 8, 8: 9})  # S = 0.9 → 0.5 → 0.8 → 0.9 (반등)
    warns = guard_survival(lag_tot, lag_exp)
    assert warns, "반등 곡선인데 경고가 없음"
    assert any("생존곡선" in w for w in warns)


def test_survival_single_lag_no_warning():
    # lag 1개면 비교 대상 없음 → 무경고
    assert guard_survival(Counter({3: 5}), Counter({3: 2})) == []


# ── (c) W > 관측창 → 경고 ─────────────────────────────────────────────────────
def test_dwell_exceeds_window_warns():
    warns = guard_dwell(9.1, "cohort", 0, 7)  # spell_W=0 → 괴리검사 skip, 창 초과만
    assert len(warns) == 1
    assert "관측창" in warns[0]


def test_dwell_method_gap_warns():
    # 코호트 9.1 vs spell 2.5 → 3.6배 괴리 (창 초과와 별개로 트립)
    warns = guard_dwell(9.1, "cohort", 2.5, 30)  # window 크게 줘서 창 초과는 배제
    assert warns
    assert any("괴리" in w for w in warns)


def test_dwell_below_one_warns():
    warns = guard_dwell(0.4, "default", 0, 14)
    assert any("< 1" in w for w in warns)


# ── (d) 노출수 > 전체 키워드수 → 경고 ('821' 류) ──────────────────────────────
def test_counts_exposed_over_total_warns():
    warns = guard_counts(821, 176, "상위노출")
    assert warns
    assert "초과" in warns[0]


def test_counts_negative_warns():
    assert guard_counts(-1, 10, "x")


# ── 필요발행 상식 밴드 ────────────────────────────────────────────────────────
def test_need_publish_band():
    # total=176, window=14 → 밴드 [12, 176]
    assert guard_need_publish(50, 176, 14, 3.0) == []      # 밴드 안
    assert guard_need_publish(0, 176, 14, 9.1)             # 하한 밖(과소)
    assert guard_need_publish(500, 176, 14, 0.3)           # 상한 밖(과대)


# ── (e) 정상 지표 전부 → 무경고 ───────────────────────────────────────────────
def test_all_normal_no_warnings():
    assert guard_dwell(3.0, "cohort", 2.8, 14) == []       # 창 이내 + 두 법 근접
    assert guard_survival(Counter({1: 10, 2: 10, 3: 10}),
                          Counter({1: 9, 2: 5, 3: 2})) == []
    assert guard_need_publish(50, 176, 14, 3.0) == []
    assert guard_counts(120, 176, "상위노출") == []
    # 종합 audit 도 정상 ctx 면 빈 리스트
    ctx = {
        "avg_dwell": 3.0, "avg_dwell_source": "cohort", "avg_dwell_spell": 2.8,
        "window_days": 14, "need_publish": 50, "total": 176, "exposed": 120,
        "published_today": 8, "published_today_exposed": 5, "tabs": [
            {"name": "샴푸", "exposed": 60, "total": 90},
            {"name": "바디워시", "exposed": 60, "total": 86},
        ],
    }
    assert audit_daily(ctx, (Counter({1: 10, 2: 10}), Counter({1: 9, 2: 5}))) == []


# ── (f) 통합: guard 트립 fixture → daily_context ctx["warnings"] 채워짐 ────────
def _rebound_backups():
    """2일 백업. 코호트 생존곡선이 큰 lag 에서 반등하도록 구성(재발행/좌측절단 오염 모양).

    짧은 lag(1,2) 미노출 / 긴 lag(6,7) 노출 → S 가 반등 → 이번 W버그 시그니처.
    """
    d15 = _bk([
        _row(2, "가", "미노출", workdate="7/14"),   # lag1 미노출
        _row(3, "나", "인기글", workdate="7/9"),    # lag6 노출
    ])
    d16 = _bk([
        _row(2, "가", "미노출", workdate="7/14"),   # lag2 미노출
        _row(3, "나", "인기글", workdate="7/9"),    # lag7 노출
    ])
    return {"2026-07-15": d15, "2026-07-16": d16}


def test_daily_context_populates_warnings_on_rebound():
    ctx = daily_context(_rebound_backups())
    assert ctx["warnings"], "guard 트립 fixture인데 warnings 비어있음"
    assert any("생존곡선" in w for w in ctx["warnings"])


def test_daily_context_normal_dataset_no_warnings():
    # 정상 합성 데이터(_dataset)는 guardrail false-positive 없어야 함(리포트 조용).
    ctx = daily_context(_dataset())
    assert ctx["warnings"] == []
