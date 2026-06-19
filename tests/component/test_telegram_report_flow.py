"""저녁/아침 보고 wiring 컴포넌트 테스트 (M10 T-M10.7).

합성 백업 2개(.json.gz) → build_report_text → 텍스트 검증. gh/네트워크 없음.
"""
import gzip
import importlib.util
import json
import os
import tempfile

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "send_telegram_report.py")


def _load():
    spec = importlib.util.spec_from_file_location("send_telegram_report", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(rownum, kw, area, l="", link=""):
    return {
        "_tab": "샴푸 카외",
        "_row": rownum,
        "키워드": kw,
        "노출영역": area,
        "노출여부(통합탭 순위)": l,
        "링크": link,
    }


_PREV = {
    "tabs": {
        "샴푸 카외": [
            _row(2, "비듬샴푸", "미노출 (6/18 01:00~)", "", "http://cafe.naver.com/a/1"),
            _row(3, "단백질샴푸", "AB (6/15 01:00~)", "8", "http://cafe.naver.com/a/2"),
        ]
    }
}
_CURR = {
    "tabs": {
        "샴푸 카외": [
            _row(2, "비듬샴푸", "인기글 (6/20 01:00~)", "", "http://cafe.naver.com/a/1"),
            _row(3, "단백질샴푸", "AB (6/15 01:00~)", "5", "http://cafe.naver.com/a/2"),
        ]
    }
}


def _gz(path, obj):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(obj, f)


def test_build_report_text_evening_with_baseline():
    m = _load()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "prev.json.gz")
        c = os.path.join(d, "curr.json.gz")
        _gz(p, _PREV)
        _gz(c, _CURR)
        out = m.build_report_text(p, c, mode="evening", kst="6/20", status_line="✅정상")
    assert "샴푸 카외" in out
    assert "상위노출" in out
    assert "비듬샴푸" not in out  # 요약형 = 키워드 나열 안 함


def test_build_report_text_no_baseline():
    m = _load()
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "curr.json.gz")
        _gz(c, _CURR)
        out = m.build_report_text(None, c, mode="evening", kst="6/20", status_line="✅정상")
    assert "비교 기준 없음" in out
