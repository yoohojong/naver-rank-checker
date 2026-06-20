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


def test_weekly_schedule_and_dispatch():
    wf = _load()
    # yaml 의 'on' 키는 BaseLoader 에서 문자열 'on' 으로 유지.
    on = wf["on"]
    assert on["schedule"][0]["cron"] == "0 12 * * 1"   # 매주 월 UTC12 = KST21
    assert "workflow_dispatch" in on


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
    # 기존 키
    assert env["SPREADSHEET_ID"] == "${{ secrets.SPREADSHEET_ID }}"
    assert env["SERVICE_ACCOUNT_JSON"] == "${{ secrets.SERVICE_ACCOUNT_JSON }}"
    # 신규 키
    assert env["NAVER_OPENAPI_CLIENT_ID"] == "${{ secrets.NAVER_OPENAPI_CLIENT_ID }}"
    assert env["NAVER_OPENAPI_CLIENT_SECRET"] == "${{ secrets.NAVER_OPENAPI_CLIENT_SECRET }}"
    assert env["APIFY_TOKEN"] == "${{ secrets.APIFY_TOKEN }}"
    # 텔레그램(C9)
    assert env["TELEGRAM_BOT_TOKEN"] == "${{ secrets.TELEGRAM_BOT_TOKEN }}"
    assert env["TELEGRAM_CHAT_ID"] == "${{ secrets.TELEGRAM_CHAT_ID }}"


def test_c9_always_notification_step_present():
    wf = _load()
    steps = wf["jobs"]["collect"]["steps"]
    notify = next(s for s in steps if "Telegram" in s.get("name", ""))
    assert notify["if"] == "always()"
    assert notify["continue-on-error"] == "true"
