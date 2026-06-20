"""D-056 디버그 회귀: 공식 모드(D-040)에서 집계가 raw_* 우선 읽는지.

버그: 봇 '지식인 0개' — 보이는 지식인탭 칸이 부재/빈칸(공식)인데 raw_지식인탭 에 실제 값('O').
fix: snapshot_diff.field_value 가 raw_* 우선 → K/L/M/지식인 전부 진짜 값 집계.
"""
from src import qa_formatter as qa
from src import snapshot_diff as sd


def _backup(rows):
    return {"tabs": {"샴푸 카외": rows}}


def test_field_value_prefers_raw_then_visible():
    # raw 있으면 raw (보이는 게 '재검사필요' 여도 진짜 값)
    assert sd.field_value({"노출영역": "재검사필요", "raw_노출영역": "AB (6/1 00:00~)"}, "노출영역").startswith("AB")
    # raw 키 없으면 보이는 값(구 백업/비공식 모드)
    assert sd.field_value({"노출영역": "인기글"}, "노출영역") == "인기글"
    # raw 키 있고 빈값이면 빈값이 진실
    assert sd.field_value({"노출영역": "재검사필요", "raw_노출영역": ""}, "노출영역") == ""


def test_count_jisikin_uses_raw_when_visible_absent():
    # 실제 최신 백업 형태: 보이는 지식인탭 키 없음, raw_지식인탭 만 존재
    rows = [
        {"키워드": "a", "raw_지식인탭": "O"},
        {"키워드": "b", "raw_지식인탭": ""},
        {"키워드": "c", "raw_지식인탭": "O"},
    ]
    assert sd._count_jisikin(_backup(rows), "샴푸 카외") == 2


def test_k_base_and_rank_use_raw():
    row = {"노출영역": "재검사필요", "raw_노출영역": "AB (6/1 00:00~)",
           "노출여부(통합탭 순위)": "", "raw_통합순위": "3"}
    assert sd.k_base_of(row) == "AB"
    assert sd.rank_of(row) == 3


def test_diff_backups_jisikin_now_from_raw():
    rows = [
        {"키워드": "a", "raw_지식인탭": "O", "raw_노출영역": "AB (6/1 00:00~)", "_tab": "샴푸 카외", "_row": 2},
        {"키워드": "b", "raw_지식인탭": "O", "raw_노출영역": "인기글 (6/1 00:00~)", "_tab": "샴푸 카외", "_row": 3},
    ]
    reps = sd.diff_backups(None, _backup(rows))
    assert reps[0].jisikin_now == 2
    assert "2개" in qa.fmt_jisikin(reps)


def test_fmt_keyword_jisikin_from_raw():
    backup = {"tabs": {"샴푸 카외": [
        {"키워드": "비듬샴푸", "raw_노출영역": "인기글 (6/1 00:00~)", "raw_지식인탭": "O",
         "유형": "인기글", "작업일": "6/1", "_tab": "샴푸 카외", "_row": 2},
    ]}}
    out = qa.fmt_keyword(backup, "비듬샴푸")
    assert "지식인: O" in out and "인기글" in out


def test_old_backup_visible_only_still_works():
    # 구 백업(raw_ 키 없음)은 보이는 값으로 그대로 동작(회귀 방지)
    rows = [{"키워드": "a", "지식인탭": "O", "노출영역": "AB (6/1 00:00~)"}]
    assert sd._count_jisikin(_backup(rows), "샴푸 카외") == 1
    assert sd.k_base_of(rows[0]) == "AB"
