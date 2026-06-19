"""report_builder 단위 테스트 (M10 T-M10.4). 외부 의존 없음."""
from collections import Counter

from src import report_builder as rb
from src.snapshot_diff import RowDiff, TabReport


def _shampoo() -> TabReport:
    return TabReport(
        tab="샴푸 카외",
        distribution=Counter({"인기글": 1, "AB": 1, "삭제": 1}),
        prev_distribution=Counter({"미노출": 1, "AB": 2}),
        diffs=[
            RowDiff("샴푸 카외", "비듬샴푸", "미노출", "인기글", None, None, "신규노출", "6/19"),
            RowDiff("샴푸 카외", "단백질샴푸", "AB", "AB", 8, 5, "오름", ""),
            RowDiff("샴푸 카외", "탈모샴푸 추천", "AB", "삭제", 2, None, "삭제", ""),
        ],
    )


def test_evening_report_contains_products_and_changes():
    out = rb.build_evening_report([_shampoo()], "6/19", "✅정상")
    assert "샴푸 카외" in out
    assert "상위노출" in out
    assert "비듬샴푸" in out
    assert "변화:" in out
    assert "🟦" in out and "❌" in out


def test_morning_report_urgent_first():
    out = rb.build_morning_report([_shampoo()], "6/19", "✅정상")
    assert "🚨 챙길 것" in out
    assert "탈모샴푸 추천" in out  # 삭제 = 챙길 것에 표기


def test_no_baseline_graceful():
    tr = TabReport(
        tab="샴푸 카외",
        distribution=Counter({"AB": 1}),
        prev_distribution=Counter(),
        baseline_available=False,
    )
    out = rb.build_evening_report([tr], "6/19", "✅정상")
    assert "비교 기준 없음" in out
