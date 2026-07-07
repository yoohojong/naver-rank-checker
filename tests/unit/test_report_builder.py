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
    assert "지금 상위노출 2개 / 전체 3" in out   # 2026-07-07 가독성: 제품별 한 줄로 합침
    assert "(샴푸 2)" in out                      # 제품별 = 지금 줄에 병합
    assert "새로 뜸(미노출→상위노출): 1개" in out
    assert "삭제(글 사라짐): 1개" in out  # ③ 어제→오늘 변화(정합)
    assert "── 정합: 어제 2 + 들어옴 1 − 나감 1 = 오늘 2" in out
    assert "유형: AB 67%" in out and "유형 바뀜 1개" in out  # 유형 목록 → 1줄 축소
    assert "지식인: 2개" in out
    assert "━━━ 어제 대비 변화" in out            # 그룹 구획(가독성)
    assert "ℹ️ 용어" not in out                   # 용어 범례 삭제(가독성)
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
    assert "━━━ 어제 대비 변화" in morning and "새로 뜸(미노출→상위노출): 1개" in morning
    assert "유형: AB 67%" in morning
    assert "지식인: 2개" in morning
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
    assert "지금 상위노출 1개 / 전체 1" in out
    assert "어제 대비 변화" not in out  # baseline 없으면 변화 섹션 생략


# ----- 2026-07-07: ② 노출 소요일 + ③ 정합(노출 개수 변화 완전 설명) -----

def _rrow(tab, rn, kw, k):
    return {"_tab": tab, "_row": rn, "키워드": kw, "노출영역": k}


def test_reconciliation_balances_and_line_correct():
    """diff_backups 가 만든 버킷으로 '어제 + 들어옴 − 나감 = 오늘'이 딱 맞아떨어지는지 +
    새 키워드/사라진 행/기타 이탈이 ③에 표시되는지."""
    from src.snapshot_diff import diff_backups
    T = "샴푸 카외"
    prev = {"tabs": {T: [
        _rrow(T, 2, "a", "AB"), _rrow(T, 3, "b", "AB"), _rrow(T, 4, "c", "인기글"),
        _rrow(T, 5, "d", "미노출"), _rrow(T, 6, "e", "AB"),   # e = 사라질 노출행
    ]}}
    curr = {"tabs": {T: [
        _rrow(T, 2, "a", "AB"),       # 유지
        _rrow(T, 3, "b", "누락"),      # 노출→누락
        _rrow(T, 4, "c", "미노출"),    # 노출→미노출 = 기타 이탈
        _rrow(T, 5, "d", "인기글"),    # 미노출→노출 = 신규노출
        _rrow(T, 7, "f", "AB"),        # 새 행 노출 = new_exposed
        # row6(e) 사라짐 = vanished_exposed
    ]}}
    reports = diff_backups(prev, curr)
    tr = reports[0]
    kc = Counter(d.kind for d in tr.diffs)
    gained = kc.get("신규노출", 0) + tr.new_exposed
    left = kc.get("누락", 0) + kc.get("삭제", 0) + tr.other_exit + tr.vanished_exposed
    # ★정합식이 실제로 성립
    assert tr.exposed_now == tr.exposed_prev + gained - left
    assert tr.exposed_prev == 4 and tr.exposed_now == 3
    assert tr.new_exposed == 1 and tr.vanished_exposed == 1 and tr.other_exit == 1
    out = rb.build_evening_report(reports, "7/7", "정상")
    assert "── 정합: 어제 4 + 들어옴 2 − 나감 3 = 오늘 3" in out
    assert "새 키워드 노출(어제 없던 글): 1개" in out
    assert "기타 이탈(미노출/재검사 등): 1개" in out
    assert "사라진 행(줄 자체 삭제): 1개" in out


def test_lag_section_renders():
    """② 발행하고 며칠 만에 떴나 — 쉬운말·묶음(당일/1~6일/일주일+/애매)·합계."""
    lag = Counter({"당일": 139, "+1일": 3, "+2일": 2, "+3~6일": 1, "+7일+": 15, "음수(재노출)": 4})
    out = rb.build_evening_report([_shampoo()], "7/7", "정상", lag_dist=lag)
    assert "② 발행 후 며칠에 뜨나 (지금 뜬 164개 중):" in out   # 139+3+2+1+15+4
    assert "당일 139" in out
    assert "1~6일 6" in out                          # 3+2+1
    assert "일주일+ 15" in out
    assert "애매" not in out                         # 헷갈리는 '애매' 삭제
    assert "노출 소요일" not in out                  # 옛 용어 제거


def test_trend_section_renders():
    """[추세] 최근 며칠 상위노출 개수 흐름 + 어제→오늘 델타 (사장님 2026-07-07)."""
    from collections import OrderedDict
    trend = OrderedDict([
        ("2026-07-06", {"합계": 188, "샴푸 카외": 80, "바디워시 카외": 96, "두드러기 카외": 12}),
        ("2026-07-07", {"합계": 148, "샴푸 카외": 60, "바디워시 카외": 78, "두드러기 카외": 10}),
    ])
    out = rb.build_evening_report([_shampoo()], "7/7", "정상", exposure_trend=trend)
    assert "추세" in out and "오른쪽이 오늘" in out
    assert "188 → 148" in out          # 합계 흐름
    assert "80 → 60" in out            # 샴푸 흐름
    assert "어제 188 → 오늘 148 (40개 줄음)" in out


def test_cohort_section_renders():
    """[발행분 변화] 발행일별 코호트가 며칠 뒤 몇 개 떠 있나 (사장님 2026-07-07)."""
    cohort = [
        ("7/6", 62, [("당일", 39), ("1일뒤", 22)]),
        ("7/5", 68, [("당일", 14), ("1일뒤", 30), ("2일뒤", 28)]),
    ]
    out = rb.build_evening_report([_shampoo()], "7/7", "정상", cohort=cohort)
    assert "발행분 변화" in out
    assert "7/6 발행 62개  →  당일 39개 → 1일뒤 22개" in out
    assert "7/5 발행 68개  →  당일 14개 → 1일뒤 30개 → 2일뒤 28개" in out
