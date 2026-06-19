"""snapshot_diff 단위 테스트 (M10 T-M10.1).

검증: 제품(탭)별 분포 집계 / 행 매칭 / 시점 제거 base / 순위 파싱 / 변화 분류 /
작업일(상태 시작일) 추출 / prev 부재 시 graceful(diffs 비움, 분포는 산출).
외부 의존(bs4/gspread) 없음 — transitions(re만) 만 import.
"""
from collections import Counter

from src.snapshot_diff import (
    classify,
    compute_distribution,
    diff_backups,
    k_base_of,
    rank_of,
    work_date_of,
)


def _row(rownum, kw, area, l="", link=""):
    return {
        "_tab": "샴푸 카외",
        "_row": rownum,
        "키워드": kw,
        "노출영역": area,
        "노출여부(통합탭 순위)": l,
        "링크": link,
    }


# 어제 백업: 비듬=미노출, 단백질=AB 8위, 탈모=AB 2위
PREV = {
    "run_id": "y1",
    "tabs": {
        "샴푸 카외": [
            _row(2, "비듬샴푸", "미노출 (6/18 01:00~)", "", "http://cafe.naver.com/a/1"),
            _row(3, "단백질샴푸", "AB (6/15 01:00~)", "8", "http://cafe.naver.com/a/2"),
            _row(4, "탈모샴푸 추천", "AB (6/10 01:00~)", "2", "http://cafe.naver.com/a/3"),
        ]
    },
}
# 오늘 백업: 비듬=인기글 신규, 단백질=AB 5위(오름), 탈모=삭제
CURR = {
    "run_id": "t1",
    "tabs": {
        "샴푸 카외": [
            _row(2, "비듬샴푸", "인기글 (6/19 13:00~)", "", "http://cafe.naver.com/a/1"),
            _row(3, "단백질샴푸", "AB (6/15 01:00~)", "5", "http://cafe.naver.com/a/2"),
            _row(4, "탈모샴푸 추천", "삭제 (6/19 13:00)", "", "http://cafe.naver.com/a/3"),
        ]
    },
}


def test_k_base_strips_stamp():
    assert k_base_of({"노출영역": "AB (6/15 01:00~)"}) == "AB"
    assert k_base_of({"노출영역": "삭제 (6/19 13:00)"}) == "삭제"
    assert k_base_of({"노출영역": ""}) == "미노출"


def test_rank_of_parses_int():
    assert rank_of({"노출여부(통합탭 순위)": "5"}) == 5
    assert rank_of({"노출여부(통합탭 순위)": "5위"}) == 5
    assert rank_of({"노출여부(통합탭 순위)": ""}) is None


def test_work_date_is_state_start_day():
    # 메모리: 시점 = 상태 시작일, 마지막 측정일 아님
    assert work_date_of({"노출영역": "인기글 (6/19 13:00~)"}) == "6/19"
    assert work_date_of({"노출영역": "AB"}) == ""


def test_compute_distribution():
    dist = compute_distribution(CURR)["샴푸 카외"]
    assert dist == Counter({"인기글": 1, "AB": 1, "삭제": 1})


def test_classify_kinds():
    assert classify("미노출", "AB", None, None) == "신규노출"
    assert classify("AB", "누락", 2, None) == "누락"
    assert classify("AB", "삭제", 2, None) == "삭제"
    assert classify("AB", "AB", 8, 5) == "오름"
    assert classify("AB", "AB", 5, 8) == "내림"


def test_diff_backups_detects_changes():
    [tr] = diff_backups(PREV, CURR)
    assert tr.tab == "샴푸 카외"
    assert tr.baseline_available is True
    assert tr.total == 3
    # 어제 노출 2(AB,AB), 오늘 노출 2(인기글,AB)
    assert tr.exposed_prev == 2
    assert tr.exposed_now == 2
    kinds = {d.keyword: d.kind for d in tr.diffs}
    assert kinds == {"비듬샴푸": "신규노출", "단백질샴푸": "오름", "탈모샴푸 추천": "삭제"}
    # 작업일(상태 시작일) 부착
    bidum = next(d for d in tr.diffs if d.keyword == "비듬샴푸")
    assert bidum.work_date == "6/19"


def test_diff_backups_no_baseline_graceful():
    # 첫 운영/retention 경계 = prev 없음 → 분포는 내되 diffs 비움 (오보 방지)
    [tr] = diff_backups(None, CURR)
    assert tr.baseline_available is False
    assert tr.diffs == []
    assert tr.distribution == Counter({"인기글": 1, "AB": 1, "삭제": 1})
    assert tr.prev_distribution == Counter()
