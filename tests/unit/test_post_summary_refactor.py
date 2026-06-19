"""post_summary_to_issue.build_comment_from_cycle 회귀 테스트 (M10 T-M10.3).

리팩토링(본문 생성부 헬퍼 추출) 후에도 success/failure/미존재 3분기가 기존과 동일하게 동작하는지.
scripts/ 모듈은 importlib 로 경로 로드(패키지 아님). 외부 의존 없음.
"""
import importlib.util
import json
import os
import tempfile

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "post_summary_to_issue.py")


def _load():
    spec = importlib.util.spec_from_file_location("post_summary_to_issue", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_comment_failure_when_missing():
    mod = _load()
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            os.environ["RUN_STATUS"] = "failure"
            out = mod.build_comment_from_cycle()
        finally:
            os.chdir(cwd)
            os.environ.pop("RUN_STATUS", None)
    assert "❌ cron 실패" in out
    assert "cycle_summary.json 미생성" in out
    assert "@yoohojong" not in out  # D-049: 이메일→텔레그램 전환 = 멘션 제거(이메일 미발생)


def test_build_comment_success_when_present():
    mod = _load()
    summary = {
        "success_rate": 1.0,
        "total_cells_written": 100,
        "total_rows_processed": 50,
        "cycle_seconds": 65,
    }
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with open("cycle_summary.json", "w", encoding="utf-8") as f:
                json.dump(summary, f)
            out = mod.build_comment_from_cycle()
        finally:
            os.chdir(cwd)
    assert "✅ cron 완료" in out
    assert "100" in out  # 시트 갱신 셀수
    assert "@yoohojong" not in out  # D-049: 멘션 제거(이메일 미발생)
