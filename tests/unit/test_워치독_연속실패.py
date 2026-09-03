# -*- coding: utf-8 -*-
"""워치독 '연속 실패 수 계산' 셸 스텝을 실제로 돌려서 검사한다 (2026-09-03).

## 왜 이 파일이 있나
세기가 `[ "$c" = "failure" ] || break` 였다. 그런데 워치독을 깨우는 조건은
`failure · cancelled · timed_out · startup_failure` **넷**이다.
러너를 못 받아 큐에 갇힌 실행은 `cancelled` 로 끝나므로, 하루 여덟 회차가 전부
그렇게 죽으면 세기가 매번 첫 줄에서 끊겨 **streak 이 늘 1** 이었다.

그 결과 `notify_run_failure.py` 의 사다리 맨 위 —
"5회 연속 시작조차 못 했습니다 · 이 정도면 하루치 순위가 통째로 빕니다 · 수동 실행이
필요해요" — 이 **영원히 안 떴다.** 정확히 그 문구가 필요한 상황에서만 안 떴다.

## 어떻게 검사하나
`gh` 를 가짜 셸 함수로 만들어 PATH 조회보다 앞세우고, 워크플로에서 뽑아낸 셸을
그대로 돌린다. 셸을 복사해 두지 않는다 — 워크플로가 바뀌면 이 검사도 같이 바뀐다.
"""
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml

저장소루트 = pathlib.Path(__file__).resolve().parents[2]
WF = 저장소루트 / ".github/workflows/rank-check-watchdog.yml"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음 (윈도우 기본 환경)")

# 워치독이 깨어나는 결론들 — job 게이트(`if:`)와 한 몸이다.
깨우는_결론 = ("failure", "cancelled", "timed_out", "startup_failure")


def _잡() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["watchdog"]


def _연속실패_셸() -> str:
    for s in _잡()["steps"]:
        if s.get("id") == "streak":
            return s["run"]
    raise AssertionError("워크플로에서 id=streak 스텝이 사라졌다")


def _streak(tmp_path, 결론들) -> int:
    """gh 가 이 결론 목록을 돌려줄 때 스텝이 내놓는 streak 값."""
    out = tmp_path / "gh_out"
    out.write_text("", encoding="utf-8")
    목록 = "\\n".join(결론들)
    가짜gh = (
        "gh() {\n"
        f'  printf "%b" "{목록}\\n"\n'
        "}\n"
    )
    script = tmp_path / "step.sh"
    script.write_text("set -eo pipefail\n" + 가짜gh + _연속실패_셸(), encoding="utf-8")
    env = dict(os.environ)
    env.update({"GITHUB_OUTPUT": str(out), "GH_REPO": "o/r", "RUN_ID": "999"})
    r = subprocess.run([BASH, str(script)], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"스텝이 죽었다(rc={r.returncode}):\n{r.stderr}"
    값 = [L.split("=", 1)[1] for L in out.read_text(encoding="utf-8").splitlines()
          if L.startswith("streak=")]
    assert 값, f"streak 을 안 내놨다:\n{r.stdout}"
    return int(값[-1])


class Test끊는_조건은_성공_하나뿐이다:
    def test_취소_다섯_번이면_다섯으로_센다(self, tmp_path):
        """★이 저장소가 실제로 겪은 모양 — 러너를 못 받아 전부 cancelled.

        예전 셸은 첫 줄에서 끊겨 늘 1이었고, 그래서 5회 사다리가 영원히 안 떴다.
        (이번 회차는 세기 전에 이미 1로 잡아 두므로, 앞선 넷 + 이번 = 5.)
        """
        assert _streak(tmp_path, ["cancelled"] * 4) == 5

    @pytest.mark.parametrize("결론", 깨우는_결론)
    def test_워치독이_깨어나는_결론은_전부_센다(self, tmp_path, 결론):
        assert _streak(tmp_path, [결론] * 4) == 5, \
            f"'{결론}' 을 안 세면 그 모양으로 죽는 날 사다리가 안 올라간다"

    def test_섞여_있어도_다_센다(self, tmp_path):
        assert _streak(tmp_path, ["cancelled", "failure", "timed_out",
                                  "startup_failure"]) == 5

    def test_성공을_만나면_거기서_끊는다(self, tmp_path):
        assert _streak(tmp_path, ["cancelled", "success", "cancelled"]) == 2

    def test_첫_줄이_성공이면_이번_한_번뿐이다(self, tmp_path):
        assert _streak(tmp_path, ["success", "failure", "failure"]) == 1

    def test_기록이_없으면_이번_한_번으로_본다(self, tmp_path):
        """과소보고가 과대보고보다 안전 — 없는 '5연속'으로 사장님을 놀래지 않는다."""
        assert _streak(tmp_path, []) == 1


class Test게이트와_세기가_같은_것을_본다:
    """★깨우는 조건과 세는 조건이 갈라지면, 깨어나 놓고 못 세는 결론이 생긴다.

    바로 그 갈라짐이 이번 버그였다 — 게이트는 넷을 깨우는데 세기는 하나만 셌다.
    """

    def test_게이트가_네_결론을_다_깨운다(self):
        조건 = str(_잡()["if"])
        for c in 깨우는_결론:
            assert c in 조건, f"게이트에서 '{c}' 가 빠졌다"

    def test_세기가_게이트의_네_결론을_다_센다(self, tmp_path):
        for c in 깨우는_결론:
            assert _streak(tmp_path, [c]) == 2, \
                f"게이트는 '{c}' 로 깨우는데 세기는 그걸 안 센다 — 사다리가 안 올라간다"

    def test_성공만_끊는다고_적혀_있다(self):
        """셸을 눈으로도 확인할 수 있게 — 'failure' 하나만 보고 끊던 자리다."""
        본문 = "\n".join(L for L in _연속실패_셸().splitlines()
                        if not L.strip().startswith("#"))
        assert '"$c" = "success"' in 본문, "끊는 조건이 success 가 아니다"
        assert '"$c" = "failure" ] && streak' not in 본문, \
            "failure 만 세던 옛 셸이 되돌아왔다"


class Test사다리가_실제로_끝까지_올라간다:
    """★셸이 5를 내놔도 문구가 안 바뀌면 사장님은 여전히 아무것도 못 본다."""

    def test_취소_5연속이면_빨간불_문구가_나온다(self):
        from scripts.notify_run_failure import build_failure_alert
        문구 = build_failure_alert("http://x", attempt=1, retrying=False,
                                  streak=5, cause="runner", conclusion="cancelled")
        assert "🔴" in 문구
        assert "하루치" in 문구 and "수동 실행" in 문구
        assert "중단됨" in 문구, "무슨 모양으로 끝났는지를 안 밝혔다"
