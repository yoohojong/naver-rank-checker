"""exposure_history 단위 테스트 (2026-07-07). 아카이브 행 → 일별 상위노출 개수 추세."""
from src.exposure_history import daily_trend


def test_daily_trend_counts_exposed_per_day_and_tab():
    rows = [
        ("2026-07-06", "샴푸 카외", "AB"),
        ("2026-07-06", "샴푸 카외", "미노출"),     # 노출 아님 → 제외
        ("2026-07-06", "바디워시 카외", "인기글"),
        ("2026-07-07", "샴푸 카외", "AB"),
        ("2026-07-07", "샴푸 카외", "중복노출(AB)"),
    ]
    tr = daily_trend(rows, days=6)
    assert list(tr.keys()) == ["2026-07-06", "2026-07-07"]   # 오름차순(왼쪽 과거→오른쪽 오늘)
    assert tr["2026-07-06"]["합계"] == 2                       # AB + 인기글 (미노출 제외)
    assert tr["2026-07-06"]["샴푸 카외"] == 1
    assert tr["2026-07-06"]["바디워시 카외"] == 1
    assert tr["2026-07-07"]["합계"] == 2                       # AB + 중복노출(AB) 둘 다 노출
    assert tr["2026-07-07"]["샴푸 카외"] == 2


def test_daily_trend_limits_to_recent_days():
    rows = [(f"2026-07-0{i}", "샴푸 카외", "AB") for i in range(1, 8)]  # 7/1~7/7
    tr = daily_trend(rows, days=3)
    assert list(tr.keys()) == ["2026-07-05", "2026-07-06", "2026-07-07"]  # 최근 3일만


def test_daily_trend_empty():
    assert daily_trend([], days=6) == {}
