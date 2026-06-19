"""report_builder 말 중심 단위 테스트 (M10 D-052c). 기호 대신 한글 라벨 검증."""
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


def test_evening_words_format():
    out = rb.build_evening_report([_shampoo()], "6/20", "정상")
    # 한글 라벨 중심
    assert "[어제 한 작업]" in out
    assert "샴푸 카외: 3개 작업 → 1개 떴어요" in out
    assert "[지금 상위노출]" in out
    assert "전체 3개 중 2개" in out
    assert "신규 노출: 1개" in out
    assert "삭제: 1개" in out  # 상노 프로그램 용어 그대로
    assert "[제품별 노출]" in out
    assert "[대표 노출 유형]" in out and "유형 바뀐 키워드: 1개" in out
    assert "지식인에 뜬 키워드: 2개" in out
    assert "ℹ️ 용어" in out and "누락 =" in out  # 범례(용어 설명)
    # 빼야 할 것
    assert "비듬샴푸" not in out  # 키워드 나열 X
    assert "미작업" not in out  # 작업 안 된 키워드 보고 제외(사장님 요청)
    assert "🟦" not in out and "🔺" not in out  # 기호 클러스터 제거


def test_morning_words_format():
    out = rb.build_morning_report([_shampoo()], "6/20", "정상")
    assert "누락·삭제(사라짐): 1개" in out
    assert "어제 작업: 3개 → 1개" in out
    assert "[제품별 노출]" in out
    assert "탈모샴푸 추천" not in out


def test_no_baseline_graceful():
    tr = TabReport(
        tab="샴푸 카외",
        distribution=Counter({"AB": 1}),
        prev_distribution=Counter(),
        baseline_available=False,
    )
    out = rb.build_evening_report([tr], "6/20", "정상")
    assert "전체 1개 중 1개" in out
    assert "어제→오늘 변화" not in out  # baseline 없으면 변화 섹션 생략
