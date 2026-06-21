"""cafe-apply-classify.yml 워크플로 설정 검증 — workflow_dispatch 전용, cron 없음."""
from pathlib import Path

import yaml


def _load():
    return yaml.load(
        Path(".github/workflows/cafe-apply-classify.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_dispatch_only_no_cron():
    wf = _load()
    on = wf["on"]
    assert "workflow_dispatch" in on
    assert "schedule" not in on  # cron 없음 (수동 전용)


def test_dispatch_inputs_defaults():
    wf = _load()
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert inputs["target_tab"]["default"] == "샴푸 카외"
    assert inputs["dry_run"]["default"] == "false"
    assert inputs["dry_run"]["options"] == ["false", "true"]


def test_run_step_env_and_secrets():
    wf = _load()
    steps = wf["jobs"]["apply"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Apply keyword classify to sheet")
    env = run_step["env"]
    assert env["SPREADSHEET_ID"] == "${{ secrets.SPREADSHEET_ID }}"
    assert env["SERVICE_ACCOUNT_JSON"] == "${{ secrets.SERVICE_ACCOUNT_JSON }}"
    assert env["TARGET_TAB"] == "${{ inputs.target_tab }}"
    assert env["CSV_PATH"] == "data/keyword_classify_shampoo.csv"
    # dry_run='true' → DRY_RUN='1', 아니면 빈값(실반영).
    assert env["DRY_RUN"] == "${{ inputs.dry_run == 'true' && '1' || '' }}"


def test_runs_the_module():
    wf = _load()
    steps = wf["jobs"]["apply"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Apply keyword classify to sheet")
    assert "src.apply_keyword_classify" in run_step["run"]
