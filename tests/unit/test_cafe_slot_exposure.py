"""카페 구좌 4위 이하 = '진짜 상위노출' 아님 (사장님 2026-07-28).

한 규칙(구좌 1~3위만 상위노출)이 4개 층에서 일관되게 적용되는지 잠근다:
  1) transitions: 구좌순위 판정 헬퍼 (색칠·집계 공용 진실원)
  2) sheets: K열 색 — 구좌 4위 이하는 노출 블록이라도 빨강
  3) snapshot_diff: 리포트 exposed_now 가 구좌 4위 이하를 제외
  4) exposure_history: 일별 트렌드도 같은 기준(옛 4-tuple 아카이브 호환)
"""
from src.transitions import (
    CAFE_SLOT_EXPOSED_MAX,
    cafe_slot_qualifies,
    cafe_slot_rank_value,
    is_real_exposure,
)
from src.sheets import _background_color_for_k, COLOR_EXPOSED, COLOR_NEGATIVE
from src.snapshot_diff import diff_backups, is_exposed_row
from src.exposure_history import daily_trend


# ── 1) transitions: 공용 판정 헬퍼 ───────────────────────────────────────────
def test_cafe_slot_rank_value_extracts_int():
    assert cafe_slot_rank_value("5") == 5
    assert cafe_slot_rank_value("5 (6/18 03:00~)") == 5
    assert cafe_slot_rank_value("") is None
    assert cafe_slot_rank_value(None) is None


def test_cafe_slot_qualifies_1to3_only():
    assert CAFE_SLOT_EXPOSED_MAX == 3
    assert cafe_slot_qualifies("1") and cafe_slot_qualifies("3")
    assert not cafe_slot_qualifies("4") and not cafe_slot_qualifies("10")
    # 미상(빈칸/None) = 자격 있음 (구좌 못 읽었다고 노출에서 빼지 않음 = 과소집계 방지)
    assert cafe_slot_qualifies("") and cafe_slot_qualifies(None)


def test_is_real_exposure_needs_block_and_slot():
    assert is_real_exposure("인기글", "3")
    assert is_real_exposure("AB", None)          # 슬롯 미상 = 노출 인정
    assert not is_real_exposure("인기글", "4")   # 구좌 4위 이하 = 제외
    assert not is_real_exposure("미노출", "1")   # 노출 블록 아님


# ── 2) sheets: K열 색 (구좌 4위 이하는 노출 블록이라도 빨강) ──────────────────
def test_color_slot_4plus_exposed_is_red():
    assert _background_color_for_k("인기글", "4") == COLOR_NEGATIVE
    assert _background_color_for_k("AB (5/10 03:00~)", "7") == COLOR_NEGATIVE
    assert _background_color_for_k("중복노출(AB)", "9") == COLOR_NEGATIVE


def test_color_slot_1to3_exposed_is_green():
    assert _background_color_for_k("인기글", "3") == COLOR_EXPOSED
    assert _background_color_for_k("AB", "1") == COLOR_EXPOSED


def test_color_slot_blank_exposed_is_green():
    # 구좌 미상 = 노출 인정(초록). 갓 검사된 노출행은 항상 M 이 채워지므로 실질 안전.
    assert _background_color_for_k("인기글", "") == COLOR_EXPOSED
    assert _background_color_for_k("인기글", None) == COLOR_EXPOSED


def test_color_slot_does_not_touch_negative_values():
    # 미노출/누락/삭제는 구좌와 무관하게 빨강 그대로.
    assert _background_color_for_k("미노출", "2") == COLOR_NEGATIVE
    assert _background_color_for_k("누락", "1") == COLOR_NEGATIVE


# ── 3) snapshot_diff: 리포트 exposed_now 가 구좌 4위 이하 제외 ────────────────
def _r(kw, area, slot, rownum):
    return {
        "_tab": "샴푸 카외", "_row": rownum,
        "키워드": kw, "링크": f"https://cafe.naver.com/x/{kw}",
        "노출영역": area, "노출여부(카페구좌순위)": slot,
    }


def test_is_exposed_row_respects_slot():
    assert is_exposed_row(_r("a", "인기글", "3", 2))
    assert not is_exposed_row(_r("b", "인기글", "4", 3))
    assert is_exposed_row(_r("c", "AB", "", 4))       # 슬롯 미상 = 인정


def test_exposed_now_excludes_slot_4plus():
    curr = {"tabs": {"샴푸 카외": [
        _r("a", "인기글", "1", 2),
        _r("b", "인기글", "4", 3),   # 구좌 4위 → 제외
        _r("c", "AB", "3", 4),
        _r("d", "AB", "5", 5),       # 구좌 5위 → 제외
        _r("e", "미노출", "", 6),
    ]}}
    tr = diff_backups(None, curr)[0]
    assert tr.total == 5
    assert tr.exposed_now == 2   # a(1)·c(3) 만. b(4)·d(5)·미노출 제외


# ── 4) exposure_history: 일별 트렌드도 같은 기준 ─────────────────────────────
def test_daily_trend_excludes_slot_4plus():
    rows = [
        ("2026-07-06", "샴푸 카외", "k1", "AB", "2"),      # 구좌 2위 → 포함
        ("2026-07-06", "샴푸 카외", "k2", "인기글", "4"),  # 구좌 4위 → 제외
        ("2026-07-06", "샴푸 카외", "k3", "인기글", ""),   # 미상 → 포함
    ]
    tr = daily_trend(rows, days=6)
    assert tr["2026-07-06"]["합계"] == 2


def test_daily_trend_legacy_4tuple_still_counts():
    # 옛 아카이브(구좌 열 없음) = 4-tuple → 슬롯 미상으로 취급, 노출은 그대로 카운트.
    rows = [("2026-07-06", "샴푸 카외", "k1", "AB")]
    tr = daily_trend(rows, days=6)
    assert tr["2026-07-06"]["합계"] == 1
