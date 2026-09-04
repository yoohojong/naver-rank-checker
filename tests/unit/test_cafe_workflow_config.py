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


def test_모아둔_댓글을_다시_쓰는_길이_있다():
    """★2026-09-04 — 댓글을 3일 보관해 두고도 **다시 쓰는 길이 없었다.**

    훑기가 이 작업의 1시간 40분인데, 판정 쪽만 고쳐 다시 돌릴 때도 매번
    처음부터 긁었다(파일 주석에는 "판정만 실패했을 때 다시 훑지 않도록 남겨둔다"
    고 적혀 있었는데 배선이 0줄이었다 — 만들어 놓고 안 이은 자리).
    """
    import yaml
    from pathlib import Path
    p = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
         / "competitor-comments.yml")
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    inputs = d[True]["workflow_dispatch"]["inputs"]
    assert "reuse_mentions" in inputs and "reuse_run_id" in inputs
    steps = d["jobs"]["collect"]["steps"]
    받기 = [s for s in steps if "download-artifact" in str(s.get("uses", ""))]
    assert 받기, "지난 회차 댓글을 받아오는 단계가 있어야 한다"
    받 = 받기[0]
    assert 받.get("continue-on-error") is True, \
        "못 받으면 새로 긁으면 된다 — 여기서 멈추면 안 된다"
    assert 받["with"]["name"] == "mentions"
    # 받는 단계가 실제 실행 단계보다 **앞**에 있어야 파일이 쓰인다.
    자리 = [i for i, s in enumerate(steps)
            if "download-artifact" in str(s.get("uses", ""))][0]
    실행 = [i for i, s in enumerate(steps)
            if "collect_comment_brands" in str(s.get("run", ""))][0]
    assert 자리 < 실행, "받기가 실행보다 뒤에 있으면 아무 일도 안 한다"
