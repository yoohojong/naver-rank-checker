"""cafe-material-collect.yml 워크플로 구조 검증 (C4/C9).

순위체커(rank-check)와 schedule·concurrency 분리, 신규 secrets 주입, C9 알림 step 확인.
"""
from pathlib import Path

import yaml


_WF_PATH = Path(".github/workflows/cafe-material-collect.yml")


def _load():
    return yaml.load(_WF_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_schedule_disabled_dispatch_active():
    """야간/주기 자동은 사장님 go 전까지 비활성(no-auto-activation). 트리거는 수동만."""
    wf = _load()
    # yaml 의 'on' 키는 BaseLoader 에서 문자열 'on' 으로 유지.
    on = wf["on"]
    # schedule 블록은 주석 처리 → 파싱된 트리거에 없어야 한다(절대 켜지지 않음).
    assert "schedule" not in on, "cron schedule 은 비활성(주석) 상태여야 함 — 자동 활성화 금지"
    assert "workflow_dispatch" in on


def test_schedule_cron_kept_as_comment_for_future_activation():
    """미래 활성화용 cron 정의가 '주석으로' 남아 있어야 한다(값 보존, 비활성 상태)."""
    raw = _WF_PATH.read_text(encoding="utf-8")
    assert "# schedule:" in raw
    assert "#   - cron: '0 12 * * 1'" in raw  # 매주 월 UTC12=KST21, 주석 보존


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


def test_batch_cap_env_wired():
    """⑧ 배치 상한/시간가드 env 가 run step 에 배선돼 있어야 한다(GHA 60분 timeout 회피)."""
    wf = _load()
    steps = wf["jobs"]["collect"]["steps"]
    env = next(s for s in steps if s.get("name") == "Run cafe material collection")["env"]
    assert env["MAX_KEYWORDS_PER_RUN"] == "${{ github.event.inputs.max_keywords }}"
    assert env["MAX_RUN_SECONDS"] == "${{ github.event.inputs.max_run_seconds }}"


def test_dispatch_inputs_for_batch_cap():
    """수동 트리거 시 max_keywords / max_run_seconds 를 inputs 로 받을 수 있어야 한다(선택)."""
    wf = _load()
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert "max_keywords" in inputs
    assert "max_run_seconds" in inputs
    # 미입력 허용(required=false) — 비우면 integration_runner 기본값 사용.
    assert inputs["max_keywords"]["required"] == "false"
    assert inputs["max_run_seconds"]["required"] == "false"


def test_timeout_still_60_min_with_batch_guard():
    """배치 가드가 있어도 job timeout 은 60분 유지(이중 안전 — 가드 + GHA timeout)."""
    wf = _load()
    assert wf["jobs"]["collect"]["timeout-minutes"] == "60"
