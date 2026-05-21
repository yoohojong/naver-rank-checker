from pathlib import Path

import yaml


def test_rank_check_workflow_type_write_defaults_and_bulk_override():
    workflow = yaml.load(
        Path(".github/workflows/rank-check.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    dispatch_inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch_inputs["apply_type_preview"]["default"] == "true"
    assert dispatch_inputs["apply_type_preview"]["options"] == ["true", "false"]
    assert dispatch_inputs["allow_bulk_type_preview"]["default"] == "false"
    assert dispatch_inputs["allow_bulk_type_preview"]["options"] == ["false", "true"]
    assert dispatch_inputs["apply_stale_formula_mode"]["default"] == "true"
    assert dispatch_inputs["apply_stale_formula_mode"]["options"] == ["true", "false"]

    run_cron_steps = workflow["jobs"]["run-cron"]["steps"]
    run_cycle_step = next(step for step in run_cron_steps if step.get("name") == "Run cron cycle")
    run_cycle_env = run_cycle_step["env"]
    assert run_cycle_env["TYPE_PREVIEW_WRITE_CONFIRMED"] == (
        "${{ github.event_name == 'schedule' || "
        "(github.event_name == 'workflow_dispatch' && inputs.apply_type_preview != 'false') }}"
    )
    assert run_cycle_env["TYPE_PREVIEW_WRITE_ALLOW_BULK"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.allow_bulk_type_preview == 'true' }}"
    )
    assert run_cycle_env["STALE_OUTPUT_FORMULA_MODE"] == (
        "${{ github.event_name == 'schedule' || "
        "(github.event_name == 'workflow_dispatch' && inputs.apply_stale_formula_mode != 'false') }}"
    )

    diagnostics_step = next(step for step in run_cron_steps if step.get("name") == "Upload diagnostics artifact")
    diagnostics_path = diagnostics_step["with"]["path"]
    assert ".harness/stale-previews/*.jsonl" in diagnostics_path
    assert ".harness/stale-previews/*.md" in diagnostics_path
