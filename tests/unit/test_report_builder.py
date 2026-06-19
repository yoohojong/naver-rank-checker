"""report_builder 요약형 단위 테스트 (M10 D-052). 키워드 나열 X 검증 포함."""
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
        jisikin_now=2,
        jisikin_prev=1,
        worked=3,
        worked_exposed=1,
        unworked=4,
        type_dist=Counter({"AB": 2, "인기글": 1}),
        type_changes=1,
        type_change_dirs=Counter({"AB→인기글": 1}),
    )


def test_evening_summary_format():
    out = rb.build_evening_report([_shampoo()], "6/20", "✅정상")
    assert "샴푸 카외" in out
    assert "상위노출" in out
    assert "어제 작업  3개 → 1개 떴음 (적중 33%)" in out
    assert "변화" in out and "🟦" in out and "❌" in out
    assert "지식인 노출" in out
    assert "🚨 빠진 키워드 1개" in out  # 삭제 1 → 손실 경보
    assert "비듬샴푸" not in out  # ⬅ 요약형 = 키워드 나열 안 함
    assert "키워드 3개" in out  # 전체 키워드 수
    assert "유형(대표구좌)" in out and "변경 1건" in out  # 유형 분포·변경


def test_morning_summary_format():
    out = rb.build_morning_report([_shampoo()], "6/20", "✅정상")
    assert "챙길 것" in out
    assert "상위노출" in out
    assert "탈모샴푸 추천" not in out  # 키워드 나열 안 함


def test_no_baseline_graceful():
    tr = TabReport(
        tab="샴푸 카외",
        distribution=Counter({"AB": 1}),
        prev_distribution=Counter(),
        baseline_available=False,
    )
    out = rb.build_evening_report([tr], "6/20", "✅정상")
    assert "비교 기준 없음" in out
