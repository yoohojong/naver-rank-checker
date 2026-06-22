"""weekly_digest 단위 테스트 (M11, 2026-06-23).

검증: 최근 7일 작업일 집합(월 경계) / 작업→노출 퍼널 / 비정상 신호(급락·누락폭증·정상) /
주간 보고 텍스트(지난주 대비 有/無). 외부 의존(bs4/gspread/gh) 없음 — transitions(re만) 만 import.
"""
from datetime import date

from src.snapshot_diff import diff_backups
from src.weekly_digest import (
    build_weekly_text,
    detect_anomalies,
    funnel_last_n_days,
    work_dates_last_n,
)


def _row(rownum, kw, area, l="", link="", workdate=""):
    r = {
        "_tab": "샴푸 카외",
        "_row": rownum,
        "키워드": kw,
        "노출영역": area,
        "노출여부(통합탭 순위)": l,
        "링크": link or f"http://cafe.naver.com/a/{rownum}",
    }
    if workdate:
        r["작업일"] = workdate
    return r


def test_work_dates_last_n_spans_month_boundary():
    wd = work_dates_last_n(date(2026, 7, 2), 7)  # 7/2,7/1,6/30,6/29,6/28,6/27,6/26
    assert len(wd) == 7
    assert {"7/2", "7/1", "6/30", "6/26"} <= wd
    assert "6/25" not in wd  # 7일 밖


def test_funnel_counts_worked_and_exposed():
    curr = {"tabs": {"샴푸 카외": [
        _row(2, "a", "AB", workdate="6/20"),       # 7일 내 작업 + 노출
        _row(3, "b", "미노출", workdate="6/21"),    # 7일 내 작업 + 미노출
        _row(4, "c", "인기글", workdate="5/1"),     # 작업이지만 7일 밖
        _row(5, "d", "AB"),                          # 작업일 없음
    ]}}
    wd = work_dates_last_n(date(2026, 6, 23), 7)  # 6/17~6/23
    worked, exposed = funnel_last_n_days(curr, wd)
    assert worked == 2   # a, b (c=기간밖, d=작업일없음)
    assert exposed == 1  # a만 노출(인기글 c는 기간 밖이라 제외)


def test_detect_anomalies_drop_only():
    # 지난주 10개 노출 → 오늘 4개 (60% 줄음, base>=3) = 급락. 미노출 전환이라 누락/삭제 아님.
    prev = {"tabs": {"샴푸 카외": [_row(i, f"k{i}", "AB") for i in range(10)]}}
    curr = {"tabs": {"샴푸 카외": (
        [_row(i, f"k{i}", "AB") for i in range(4)]
        + [_row(i, f"k{i}", "미노출") for i in range(4, 10)]
    )}}
    sig = detect_anomalies(diff_backups(prev, curr))
    assert any("급락" in s for s in sig)
    assert not any("누락" in s for s in sig)  # lost 0 → 누락 플래그 없음


def test_detect_anomalies_lost_flag():
    # 지난주 12 노출 → 오늘 4 노출 + 8 누락 = 급락 + 누락 폭증(>=8) 둘 다.
    prev = {"tabs": {"샴푸 카외": [_row(i, f"k{i}", "AB") for i in range(12)]}}
    curr = {"tabs": {"샴푸 카외": (
        [_row(i, f"k{i}", "AB") for i in range(4)]
        + [_row(i, f"k{i}", "누락") for i in range(4, 12)]
    )}}
    sig = detect_anomalies(diff_backups(prev, curr))
    assert any("급락" in s for s in sig)
    assert any("누락 8건" in s and "점검" in s for s in sig)


def test_detect_anomalies_none_when_stable():
    prev = {"tabs": {"샴푸 카외": [_row(2, "a", "AB"), _row(3, "b", "인기글")]}}
    curr = {"tabs": {"샴푸 카외": [_row(2, "a", "AB"), _row(3, "b", "인기글")]}}
    assert detect_anomalies(diff_backups(prev, curr)) == []


def test_detect_anomalies_no_baseline_silent():
    # baseline 없으면 급락 판정 불가 → 신호 비움(오보 방지)
    curr = {"tabs": {"샴푸 카외": [_row(2, "a", "미노출"), _row(3, "b", "미노출")]}}
    assert detect_anomalies(diff_backups(None, curr)) == []


def test_build_weekly_text_with_baseline():
    prev = {"tabs": {"샴푸 카외": [
        _row(2, "비듬샴푸", "미노출"),
        _row(3, "단백질샴푸", "AB", l="8"),
    ]}}
    curr = {"tabs": {"샴푸 카외": [
        _row(2, "비듬샴푸", "인기글", workdate="6/22"),   # 신규노출 + 지난7일 작업
        _row(3, "단백질샴푸", "AB", l="5"),               # 오름
    ]}}
    reports = diff_backups(prev, curr)
    funnel = funnel_last_n_days(curr, work_dates_last_n(date(2026, 6, 23), 7))
    text = build_weekly_text(reports, funnel, "6/17~6/23")
    assert "카페외부 주간 총괄 · 6/17~6/23" in text
    assert "지금 노출: 2개" in text          # 인기글 + AB
    assert "지난주 1개" in text              # 어제 AB 1개만
    assert "작업 → 노출: 지난 7일 1개 작업 → 1개 떴어요 (100%)" in text
    assert "[지난주 대비 변화]" in text
    assert "신규 노출 +1" in text and "순위 상승 1" in text


def test_build_weekly_text_no_baseline():
    curr = {"tabs": {"샴푸 카외": [_row(2, "a", "AB"), _row(3, "b", "미노출")]}}
    reports = diff_backups(None, curr)
    text = build_weekly_text(reports, (0, 0), "6/17~6/23")
    assert "지금 노출: 1개" in text
    assert "지난주" not in text              # baseline 없음 → 비교 문구 생략
    assert "[지난주 대비 변화]" not in text
    assert "지난 7일 기록된 작업 없음" in text
