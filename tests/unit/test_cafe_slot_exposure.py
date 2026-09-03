"""카페 구좌 **1위만** '진짜 상위노출' (사장님 2026-09-03. 그 전엔 1~3위였다).

한 규칙이 4개 층에서 일관되게 적용되는지 잠근다:
  1) transitions: 구좌순위 판정 헬퍼 (색칠·집계 공용 진실원)
  2) sheets: K열 색 — 1위 초록 / 2~3위 노랑 / 그 밖 빨강
  3) snapshot_diff: 리포트 exposed_now 가 구좌 2위 이하를 제외
  4) exposure_history: 일별 트렌드도 같은 기준(옛 4-tuple 아카이브 호환)
"""
from collections import Counter

from src.transitions import (
    CAFE_SLOT_COUNTED,
    CAFE_SLOT_NEAR_MAX,
    cafe_slot_qualifies,
    cafe_slot_rank_value,
    is_real_exposure,
)
from src.sheets import (
    _background_color_for_k,
    COLOR_EXPOSED,
    COLOR_SLOT_NEAR,
    COLOR_NEGATIVE,
)
from src.snapshot_diff import diff_backups, is_exposed_row
from src.exposure_history import daily_trend


# ── 1) transitions: 공용 판정 헬퍼 ───────────────────────────────────────────
def test_cafe_slot_rank_value_extracts_int():
    assert cafe_slot_rank_value("5") == 5
    assert cafe_slot_rank_value("5 (6/18 03:00~)") == 5
    assert cafe_slot_rank_value("") is None
    assert cafe_slot_rank_value(None) is None


def test_cafe_slot_qualifies_1위만():
    """사장님 2026-09-03: 1~3위 → 1위만 센다. 옛 기준으로 되돌아가면 여기서 걸린다."""
    assert CAFE_SLOT_COUNTED == 1 and CAFE_SLOT_NEAR_MAX == 3
    assert cafe_slot_qualifies("1")
    assert not cafe_slot_qualifies("2") and not cafe_slot_qualifies("3")
    assert not cafe_slot_qualifies("4") and not cafe_slot_qualifies("10")
    # 미상(빈칸/None) = 자격 있음 (구좌 못 읽었다고 노출에서 빼지 않음 = 과소집계 방지)
    assert cafe_slot_qualifies("") and cafe_slot_qualifies(None)


def test_is_real_exposure_needs_block_and_slot():
    assert is_real_exposure("인기글", "1")
    assert is_real_exposure("AB", None)          # 구좌 못 잼 = 노출 인정
    assert not is_real_exposure("인기글", "2")   # 2위부터 안 센다 (2026-09-03)
    assert not is_real_exposure("인기글", "4")
    assert not is_real_exposure("미노출", "1")   # 노출 블록 아님


# ── 2) sheets: K열 색 — 1위 초록 / 2~3위 노랑 / 그 밖 빨강 (사장님 2026-09-03) ──
def test_color_slot_4plus_exposed_is_red():
    assert _background_color_for_k("인기글", "4") == COLOR_NEGATIVE
    assert _background_color_for_k("AB (5/10 03:00~)", "7") == COLOR_NEGATIVE
    assert _background_color_for_k("중복노출(AB)", "9") == COLOR_NEGATIVE


def test_color_slot_1위만_초록():
    assert _background_color_for_k("AB", "1") == COLOR_EXPOSED


def test_color_slot_2와3은_노랑():
    """2~3위는 안 세지만 한 칸만 올리면 세어지는 자리라 눈에 보여야 한다."""
    assert _background_color_for_k("인기글", "2") == COLOR_SLOT_NEAR
    assert _background_color_for_k("AB", "3") == COLOR_SLOT_NEAR
    assert _background_color_for_k("중복노출(AB)", "3") == COLOR_SLOT_NEAR
    # 세 색이 서로 달라야 화면에서 구별된다.
    assert len({str(COLOR_EXPOSED), str(COLOR_SLOT_NEAR), str(COLOR_NEGATIVE)}) == 3


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
    assert is_exposed_row(_r("a", "인기글", "1", 2))
    assert not is_exposed_row(_r("b", "인기글", "3", 3))   # 2~3위는 안 센다(2026-09-03)
    assert not is_exposed_row(_r("b2", "인기글", "4", 5))
    assert is_exposed_row(_r("c", "AB", "", 4))            # 구좌 못 잼 = 인정


def test_exposed_now_은_구좌_1위만_센다():
    curr = {"tabs": {"샴푸 카외": [
        _r("a", "인기글", "1", 2),
        _r("b", "인기글", "4", 3),   # 구좌 4위 → 제외
        _r("c", "AB", "3", 4),       # 구좌 3위 → 2026-09-03 부터 제외
        _r("d", "AB", "5", 5),       # 구좌 5위 → 제외
        _r("e", "미노출", "", 6),
    ]}}
    tr = diff_backups(None, curr)[0]
    assert tr.total == 5
    assert tr.exposed_now == 1   # a(1위) 만


# ── 4) exposure_history: 일별 트렌드도 같은 기준 ─────────────────────────────
def test_daily_trend_도_구좌_1위만_센다():
    rows = [
        ("2026-07-06", "샴푸 카외", "k0", "AB", "1"),      # 구좌 1위 → 포함
        ("2026-07-06", "샴푸 카외", "k1", "AB", "2"),      # 구좌 2위 → 2026-09-03 부터 제외
        ("2026-07-06", "샴푸 카외", "k2", "인기글", "4"),  # 구좌 4위 → 제외
        ("2026-07-06", "샴푸 카외", "k3", "인기글", ""),   # 구좌 못 잼 → 포함
    ]
    tr = daily_trend(rows, days=6)
    assert tr["2026-07-06"]["합계"] == 2


def test_daily_trend_legacy_4tuple_still_counts():
    # 옛 아카이브(구좌 열 없음) = 4-tuple → 슬롯 미상으로 취급, 노출은 그대로 카운트.
    rows = [("2026-07-06", "샴푸 카외", "k1", "AB")]
    tr = daily_trend(rows, days=6)
    assert tr["2026-07-06"]["합계"] == 1


# ── 5) 정합식(HIGH) — '삭제'는 어제 진짜노출이던 것만 나감에 반영 ──────────────
def test_exposed_deleted_gating_keeps_identity_balanced():
    """구좌 4위/미노출 행이 삭제돼도 정합식(어제+들어옴−나감=오늘)이 음수로 안 깨진다.
    (2026-07-28 독립검토 HIGH: 전체 삭제를 나감에 넣으면 노출 아니던 삭제까지 차감)."""
    prev = {"tabs": {"샴푸 카외": [
        _r("a", "AB", "1", 2),      # 어제 진짜 노출(구좌 1위)
        _r("b", "인기글", "4", 3),  # 어제 구좌4 = 노출 아님
        _r("c", "미노출", "", 4),   # 어제 미노출
    ]}}
    curr = {"tabs": {"샴푸 카외": [
        _r("a", "삭제", "", 2),     # 셋 다 오늘 삭제
        _r("b", "삭제", "", 3),
        _r("c", "삭제", "", 4),
    ]}}
    tr = diff_backups(prev, curr)[0]
    assert tr.exposed_prev == 1      # a 만 어제 진짜 노출
    assert tr.exposed_now == 0
    assert tr.exposed_deleted == 1   # a 만 (b·c 는 노출 아니었음)

    kc = Counter(d.kind for d in tr.diffs)
    assert kc.get("삭제", 0) == 3    # 전체 삭제는 3(표시·점검용)
    gained = kc.get("신규노출", 0) + tr.new_exposed
    left = kc.get("누락", 0) + tr.exposed_deleted + tr.other_exit + tr.vanished_exposed
    # 정합: 0 == 1 + 0 − 1 (fix 전엔 전체삭제3으로 1+0−3=-2 로 깨짐)
    assert tr.exposed_now == tr.exposed_prev + gained - left


# ── 6) 아카이브 그리드(HIGH) — 6열 헤더 쓰기 전 그리드 먼저 확장 ──────────────
class _FakeWs5col:
    """옛 5열 그리드 '상위노출_이력' 탭 대역 (col_count·add_cols 모델링)."""
    def __init__(self):
        self.col_count = 5
        self.added_cols = []
        self.header = ["날짜", "탭", "키워드", "노출영역", "통합순위"]
        self.updated = []

    def row_values(self, n):
        return list(self.header) if n == 1 else []

    def add_cols(self, n):
        self.col_count += n
        self.added_cols.append(n)

    def update(self, cell, data, value_input_option="RAW"):
        self.updated.append((cell, data))
        if cell == "A1":
            self.header = list(data[0])


class _FakeSS:
    def __init__(self, ws):
        self._ws = ws

    def worksheet(self, title):
        return self._ws


class _FakeClient:
    def __init__(self, ws):
        self.spreadsheet = _FakeSS(ws)


def test_archive_migration_widens_grid_before_writing_6col_header():
    """5열 라이브 탭에 6열 헤더를 쓰기 전에 add_cols 로 먼저 넓힌다.
    (안 하면 A1:F1 write 가 'exceeds grid limits' 400 으로 조용히 실패 → 아카이빙 중단)."""
    from src.archive import _get_or_create_archive_ws, ARCHIVE_HEADER
    ws = _FakeWs5col()
    _get_or_create_archive_ws(_FakeClient(ws), "상위노출_이력")
    assert ws.added_cols == [1]           # 5→6, add_cols(1) 먼저 호출
    assert ws.col_count == 6
    assert ws.header == ARCHIVE_HEADER     # 그 다음 6열 헤더 기록
