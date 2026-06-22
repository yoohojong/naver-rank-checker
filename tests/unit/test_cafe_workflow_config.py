"""cafe-material-collect.yml 워크플로 구조 검증 (C4/C9).

순위체커(rank-check)와 schedule·concurrency 분리, 신규 secrets 주입, C9 알림 step 확인.
"""
from pathlib import Path

import yaml


def _load():
    return yaml.load(
        Path(".github/workflows/cafe-material-collect.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_manual_only_no_cron_d062():
    # D-062: 카페외부 시스템 '가동 게이트' 열기 전까지 자동(cron) 실행 중지 → 수동 전용.
    wf = _load()
    on = wf["on"]
    assert not on.get("schedule")          # cron 제거됨(주석 처리) — 자동 실행 X
    assert "workflow_dispatch" in on       # 사장님 수동 트리거는 유지


def test_concurrency_group_separate_from_rank_check():
    wf = _load()
    group = wf["concurrency"]["group"]
    assert group == "cafe-material-collect"
    assert group != "naver-rank-check"  # 순위체커와 분리


def test_runs_integration_runner_module():
    wf = _load()
    steps = wf["jobs"]["collect"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run cafe material collection")
    assert "python -u -m src.integration_runner" in run_step["run"]


def test_new_and_existing_secrets_wired():
    wf = _load()
    steps = wf["jobs"]["collect"]["steps"]
    env = next(s for s in steps if s.get("name") == "Run cafe material collection")["env"]
    # 시트/APIFY 키는 항상 주입(모드 무관).
    assert env["SPREADSHEET_ID"] == "${{ secrets.SPREADSHEET_ID }}"
    assert env["SERVICE_ACCOUNT_JSON"] == "${{ secrets.SERVICE_ACCOUNT_JSON }}"
    assert env["APIFY_TOKEN"] == "${{ secrets.APIFY_TOKEN }}"
    # 지식인(NAVER) 키는 단일 모드(shards=1)에서만 주입 → 분할 모드선 빈값(12× 중복수집 방지).
    assert env["NAVER_OPENAPI_CLIENT_ID"] == (
        "${{ github.event.inputs.shards == '1' && secrets.NAVER_OPENAPI_CLIENT_ID || '' }}"
    )
    assert env["NAVER_OPENAPI_CLIENT_SECRET"] == (
        "${{ github.event.inputs.shards == '1' && secrets.NAVER_OPENAPI_CLIENT_SECRET || '' }}"
    )
    # 텔레그램(C9)도 단일 모드에서만(분할 모드선 12× 알림 폭주 방지).
    assert env["TELEGRAM_BOT_TOKEN"] == (
        "${{ github.event.inputs.shards == '1' && secrets.TELEGRAM_BOT_TOKEN || '' }}"
    )
    assert env["TELEGRAM_CHAT_ID"] == (
        "${{ github.event.inputs.shards == '1' && secrets.TELEGRAM_CHAT_ID || '' }}"
    )


def test_c9_always_notification_step_present():
    wf = _load()
    steps = wf["jobs"]["collect"]["steps"]
    notify = next(s for s in steps if "Telegram" in s.get("name", ""))
    # 백업 알림은 단일 모드에서만(분할 모드선 shard 마다 폭주 방지).
    assert notify["if"] == "${{ always() && github.event.inputs.shards == '1' }}"
    assert notify["continue-on-error"] == "true"


def test_matrix_parallel_structure():
    """병렬(matrix) 구조: prep job 이 shard 배열 출력 → collect 가 matrix 로 동시 실행."""
    wf = _load()
    # shards 입력 존재(기본 1 = 단일).
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert "shards" in inputs
    assert inputs["shards"]["default"] == "1"
    # prep 이 shards 배열을 output.
    assert "prep" in wf["jobs"]
    assert "shards" in wf["jobs"]["prep"]["outputs"]
    # collect 가 prep 의 배열을 matrix 로 소비 + 자기 shard 를 REVIEW_SHARD 로 받음.
    collect = wf["jobs"]["collect"]
    assert collect["needs"] == "prep"
    assert "fromJSON(needs.prep.outputs.shards)" in collect["strategy"]["matrix"]["shard"]
    env = next(s for s in collect["steps"] if s.get("name") == "Run cafe material collection")["env"]
    assert env["REVIEW_SHARD"] == "${{ matrix.shard }}/${{ github.event.inputs.shards }}"
