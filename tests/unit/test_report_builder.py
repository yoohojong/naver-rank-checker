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
    # 한글 라벨 중심 (breakdown 미전달 시 날짜별 섹션 생략)
    assert "[어제 한 작업]" not in out   # 2026-07-02: 날짜별 발행→상위노출 breakdown 으로 교체
    assert "[지금 상위노출]" in out
    assert "전체 3개 중 2개" in out
    assert "새로 뜸(미노출→상위노출): 1개" in out
    assert "삭제(글 사라짐): 1개" in out  # ② 어제→오늘 변화 (라벨 명확화)
    assert "[제품별 노출]" in out
    assert "[대표 노출 유형]" in out and "유형 바뀐 키워드: 1개" in out
    assert "지식인에 뜬 키워드: 2개" in out
    assert "ℹ️ 용어" in out and "누락 =" in out  # 범례(용어 설명)
    # 빼야 할 것
    assert "비듬샴푸" not in out  # 키워드 나열 X
    assert "미작업" not in out  # 작업 안 된 키워드 보고 제외(사장님 요청)
    assert "🟦" not in out and "🔺" not in out  # 기호 클러스터 제거


def test_morning_same_as_evening_except_header():
    """사장님 요청(2026-06-21): 아침도 저녁과 동일 형식. 헤더(첫 줄)만 다름."""
    rep = [_shampoo()]
    morning = rb.build_morning_report(rep, "6/20", "정상")
    evening = rb.build_evening_report(rep, "6/20", "정상")
    assert morning.startswith("☀️ 상노체크 아침 · 6/20")
    # 헤더만 빼면 본문 완전 동일
    assert morning.split("\n", 1)[1] == evening.split("\n", 1)[1]
    # 저녁의 상세 섹션이 아침에도 전부 포함
    assert "[② 어제 → 오늘 변화]" in morning and "새로 뜸(미노출→상위노출): 1개" in morning
    assert "[대표 노출 유형]" in morning
    assert "지식인에 뜬 키워드: 2개" in morning
    assert "탈모샴푸 추천" not in morning  # 키워드 나열 X


def test_breakdown_section_renders_when_provided():
    """2026-07-02: build_*_report 에 breakdown 주면 '[날짜별 발행 → 상위노출]' 섹션이 맨 위에.
    ('어제 한 작업 N→M' 1일 라인의 7일·제품별 업그레이드.)"""
    bd = [
        ("7/1", {"샴푸 카외": (5, 2), "바디워시 카외": (3, 1)}, (8, 3)),
        ("6/30", {"샴푸 카외": (4, 1), "바디워시 카외": (0, 0)}, (4, 1)),
    ]
    out = rb.build_evening_report([_shampoo()], "7/2", "정상", breakdown=bd)
    assert "날짜별 발행 → 상위노출" in out
    assert "7/1  발행 8 → 상위노출 3" in out
    assert "샴푸 5→2" in out and "바디워시 3→1" in out
    assert "6/30" in out and "샴푸 4→1" in out  # 발행0 제품(바디워시)은 생략
    assert "최근 7일 합계: 발행 12 → 상위노출 4" in out
    assert "[어제 한 작업]" not in out


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
