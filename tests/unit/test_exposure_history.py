"""exposure_history 단위 테스트 (2026-07-07). 아카이브 행 → 일별 개수 추세 + 발행분 코호트."""
from src.exposure_history import cohort_evolution, daily_trend


def test_daily_trend_counts_exposed_per_day_and_tab():
    rows = [
        ("2026-07-06", "샴푸 카외", "kw1", "AB"),
        ("2026-07-06", "샴푸 카외", "kw2", "미노출"),     # 노출 아님 → 제외
        ("2026-07-06", "바디워시 카외", "kw3", "인기글"),
        ("2026-07-07", "샴푸 카외", "kw1", "AB"),
        ("2026-07-07", "샴푸 카외", "kw4", "중복노출(AB)"),
    ]
    tr = daily_trend(rows, days=6)
    assert list(tr.keys()) == ["2026-07-06", "2026-07-07"]   # 오름차순(왼쪽 과거→오른쪽 오늘)
    assert tr["2026-07-06"]["합계"] == 2                       # AB + 인기글 (미노출 제외)
    assert tr["2026-07-06"]["샴푸 카외"] == 1
    assert tr["2026-07-06"]["바디워시 카외"] == 1
    assert tr["2026-07-07"]["합계"] == 2                       # AB + 중복노출(AB) 둘 다 노출
    assert tr["2026-07-07"]["샴푸 카외"] == 2


def test_daily_trend_limits_to_recent_days():
    rows = [(f"2026-07-0{i}", "샴푸 카외", f"kw{i}", "AB") for i in range(1, 8)]  # 7/1~7/7
    tr = daily_trend(rows, days=3)
    assert list(tr.keys()) == ["2026-07-05", "2026-07-06", "2026-07-07"]  # 최근 3일만


def test_daily_trend_empty():
    assert daily_trend([], days=6) == {}


def test_cohort_evolution_tracks_publish_cohort():
    """7/6 발행분(kwA,kwB)이 당일 몇 개, 1일뒤 몇 개 노출인지 추적."""
    rows = [
        ("2026-07-06", "샴푸 카외", "kwA", "AB"),        # 당일 kwA 노출
        ("2026-07-06", "샴푸 카외", "kwB", "미노출"),
        ("2026-07-07", "샴푸 카외", "kwA", "AB"),        # 1일뒤 kwA 유지
        ("2026-07-07", "샴푸 카외", "kwB", "인기글"),     # 1일뒤 kwB 새로 뜸
    ]
    curr = {"tabs": {"샴푸 카외": [
        {"키워드": "kwA", "작업일": "7/6"},
        {"키워드": "kwB", "작업일": "7/6"},
    ]}}
    coh = cohort_evolution(rows, curr, n_cohorts=3)
    assert len(coh) == 1
    md, total, steps = coh[0]
    assert md == "7/6" and total == 2
    assert steps == [("당일", 1), ("1일뒤", 2)]


def test_cohort_evolution_empty_when_no_archive():
    assert cohort_evolution([], {"tabs": {}}, n_cohorts=3) == []
