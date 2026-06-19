"""fetch_yesterday_backup.pick_previous_success 단위 테스트 (M10 T-M10.6).

"어제" = 직전 성공 백업 선택 로직(순수 함수). subprocess 호출 없음.
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "fetch_yesterday_backup.py")


def _load():
    spec = importlib.util.spec_from_file_location("fetch_yesterday_backup", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pick_previous_success_latest_excluding_current():
    fb = _load()
    runs = [
        {"databaseId": 1, "createdAt": "2026-06-18T01:00:00Z"},
        {"databaseId": 2, "createdAt": "2026-06-19T01:00:00Z"},  # 현재 run
        {"databaseId": 3, "createdAt": "2026-06-18T19:00:00Z"},
    ]
    assert fb.pick_previous_success(runs, exclude_run_id="2") == "3"


def test_pick_previous_success_empty():
    fb = _load()
    assert fb.pick_previous_success([], exclude_run_id="2") is None


def test_pick_previous_success_only_current():
    fb = _load()
    runs = [{"databaseId": 2, "createdAt": "2026-06-19T01:00:00Z"}]
    assert fb.pick_previous_success(runs, exclude_run_id="2") is None


def test_pick_run_near_hours_finds_24h_ago():
    fb = _load()
    runs = [
        {"databaseId": 10, "createdAt": "2026-06-20T01:00:00+00:00"},  # 현재
        {"databaseId": 11, "createdAt": "2026-06-19T19:00:00+00:00"},  # 6h 전
        {"databaseId": 12, "createdAt": "2026-06-19T01:00:00+00:00"},  # 24h 전
    ]
    got = fb.pick_run_near_hours(runs, "2026-06-20T01:00:00+00:00", hours=24, tolerance_h=5, exclude_run_id="10")
    assert got == "12"


def test_pick_run_near_hours_none_out_of_tolerance():
    fb = _load()
    runs = [{"databaseId": 11, "createdAt": "2026-06-19T19:00:00+00:00"}]  # 6h 전만 존재
    got = fb.pick_run_near_hours(runs, "2026-06-20T01:00:00+00:00", hours=24, tolerance_h=3, exclude_run_id="10")
    assert got is None
