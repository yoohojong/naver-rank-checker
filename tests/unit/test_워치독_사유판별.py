# -*- coding: utf-8 -*-
"""워치독 '실패 사유 판별' 셸 스텝을 실제로 돌려서 검사한다 (2026-08-07).

## 왜 이 파일이 있나
사유 판별은 파이썬이 아니라 워크플로 안의 셸에 있다. 그래서 파이썬 검사만으로는
한 줄도 지켜지지 않았고, 독립 리뷰에서 확인된 결함 네 개가 전부 이 셸 안에 살아 있었다.

특히 뒤집혀 있던 것: `gh run rerun` 이 **새 attempt** 를 만드는데 조회는 최신 attempt 를
본다. 그래서 '방금 큐에 들어간 새 시도'(스텝 0개)를 실패 원인으로 오독했다.
겨냥한 상황(1회차)에서는 판별이 눈이 멀고, 엉뚱한 상황(2회차)에서만 맞는 구조였다.

## 어떻게 검사하나
`gh` 를 가짜로 만들어 PATH 앞에 두고 워크플로에서 뽑아낸 셸을 그대로 실행한다.
네트워크도 GitHub 도 필요 없다. 조회 URL 에 attempt 가 박혀 있는지도 가짜 gh 가 기록한다.
"""
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

WF = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/rank-check-watchdog.yml"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음 (윈도우 기본 환경)")


def _사유판별_셸() -> str:
    """워크플로에서 '실패 사유 판별' 스텝의 run 본문을 그대로 꺼낸다.

    복사본을 두지 않는다 — 워크플로가 바뀌면 이 검사도 같이 바뀌어야 한다.
    """
    d = yaml.safe_load(WF.read_text(encoding="utf-8"))
    for s in d["jobs"]["watchdog"]["steps"]:
        if s.get("id") == "cause":
            return s["run"]
    raise AssertionError("워크플로에서 id=cause 스텝이 사라졌다")


def _가짜gh(*, steps: str, annotation: str, jobs_api_실패: bool = False) -> str:
    """gh 를 흉내내는 **셸 함수**. 호출된 URL 을 calls.log 에 남긴다.

    PATH 에 파일을 두는 방식은 윈도우 Git Bash 가 실제 gh.exe 를 먼저 집어 안 통했다.
    함수는 PATH 조회보다 우선하므로 어디서든 확실히 가로챈다.
    """
    실패 = "return 1" if jobs_api_실패 else ":"
    return (
        "gh() {\n"
        '  echo "$@" >> "$FAKE_GH_LOG"\n'
        '  case "$*" in\n'
        f'    *"/jobs"*steps*) {실패}; printf "%s\\n" "{steps}" ;;\n'
        f'    *"/jobs"*.id*) {실패}; printf "%s\\n" "$FAKE_JOB_IDS" ;;\n'
        f'    *annotations*) printf "%s\\n" "{annotation}" ;;\n'
        "    *) return 1 ;;\n"
        "  esac\n"
        "}\n"
    )


def _돌린다(tmp_path, *, steps="0", annotation="", attempt="1",
            job_ids="111", jobs_api_실패=False) -> tuple:
    """(cause, gh 가 호출된 URL 목록) 반환."""
    out = tmp_path / "gh_out"
    log = tmp_path / "calls.log"
    out.write_text("", encoding="utf-8")
    log.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "GITHUB_OUTPUT": str(out),
        "FAKE_GH_LOG": str(log),
        "FAKE_JOB_IDS": job_ids,
        "GH_REPO": "o/r",
        "RUN_ID": "999",
        "RUN_ATTEMPT": attempt,
    })
    script = tmp_path / "step.sh"
    # GitHub Actions 의 shell: bash 기본값과 같은 옵션으로 돌린다(-e 포함).
    script.write_text(
        "set -eo pipefail\n"
        + _가짜gh(steps=steps, annotation=annotation, jobs_api_실패=jobs_api_실패)
        + _사유판별_셸(),
        encoding="utf-8",
    )
    r = subprocess.run([BASH, str(script)], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"스텝이 죽었다(rc={r.returncode}):\n{r.stderr}"

    cause = ""
    for line in out.read_text(encoding="utf-8").splitlines():
        if line.startswith("cause="):
            cause = line.split("=", 1)[1]
    return cause, log.read_text(encoding="utf-8")


class Test사유를_제대로_가른다:
    def test_기계_미배정_주석이면_runner(self, tmp_path):
        cause, _ = _돌린다(
            tmp_path, steps="0",
            annotation="The job was not acquired by Runner of type hosted even after multiple attempts")
        assert cause == "runner"

    def test_결제_한도면_billing(self, tmp_path):
        cause, _ = _돌린다(tmp_path, steps="0",
                          annotation="The job was not started because recent account payments have failed")
        assert cause == "billing"

    def test_결제가_기계미배정보다_우선한다(self, tmp_path):
        """둘 다 섞여 오면 사람이 조치해야 하는 쪽으로 읽어야 한다."""
        cause, _ = _돌린다(tmp_path, steps="0",
                          annotation="spending limit reached; job was not acquired by Runner")
        assert cause == "billing"

    def test_스텝이_돌았고_주석이_없으면_code(self, tmp_path):
        """진짜 코드 실패 — 완화하면 안 된다."""
        cause, _ = _돌린다(tmp_path, steps="12", annotation="")
        assert cause == "code"

    def test_주석을_못_읽어도_스텝0이면_runner(self, tmp_path):
        """checks 권한이 없어 주석이 안 보이는 경우의 보루."""
        cause, _ = _돌린다(tmp_path, steps="0", annotation="")
        assert cause == "runner"


class Test못_읽으면_평소대로_알린다:
    """★못 잰 것이 침묵이 되면 안 된다 — 이 저장소가 이미 겪은 사고다."""

    def test_조회_실패면_unknown(self, tmp_path):
        cause, _ = _돌린다(tmp_path, jobs_api_실패=True)
        assert cause == "unknown", "조회가 깨졌는데 사유를 단정했다"

    def test_잡이_비면_code(self, tmp_path):
        """jobs 가 빈 배열이면 max→null→-1. '스텝 0개'와 헷갈리면 안 된다."""
        cause, _ = _돌린다(tmp_path, steps="-1", annotation="", job_ids="")
        assert cause == "code"

    def test_unknown_과_code_는_둘_다_평소_경보로_간다(self):
        from scripts.notify_run_failure import build_failure_alert
        for c in ("unknown", "code"):
            assert "사람 확인" in build_failure_alert(run_url="u", attempt=2,
                                                   retrying=False, cause=c)


class Test재시도가_판별을_망치지_않는다:
    """★뒤집혀 있던 결함. rerun 이 새 attempt 를 만들면 기본 조회는 그걸 본다."""

    def test_실패한_attempt_를_못박아_조회한다(self, tmp_path):
        _, calls = _돌린다(tmp_path, attempt="1")
        assert "attempts/1/jobs" in calls, (
            "attempt 를 안 박고 조회한다 — 재시도가 만든 새 시도를 실패 원인으로 오독한다.\n"
            f"실제 호출:\n{calls}")

    def test_2차_시도면_2차를_조회한다(self, tmp_path):
        _, calls = _돌린다(tmp_path, attempt="2")
        assert "attempts/2/jobs" in calls
