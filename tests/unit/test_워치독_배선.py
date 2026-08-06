# -*- coding: utf-8 -*-
"""워치독 워크플로의 **배선**을 지킨다 (2026-08-07).

## 왜 이 파일이 있나
검사가 파이썬 함수와 셸 판별식은 지키는데, **YAML 배선은 한 줄도 안 지키고 있었다.**
독립 검증에서 돌연변이 9종을 심어 확인했더니 전부 초록이었다:
  · 알림 스텝에 `|| true` 복원(= 첫 REJECT 를 만든 그 결함)
  · curl 최후수단 통째 삭제 / 조건 무력화
  · job 게이트를 엉뚱한 값으로 (워치독 전체 사망)
  · `if: always()` 삭제 / 알림 스텝 `if: false`
  · `permissions` 에서 `checks: read` 삭제
  · `types: [completed]` → `[requested]`
  · CAUSE env 매핑 삭제

전부 "사장님이 아무것도 못 받는다"로 끝나는 변경인데, 검사는 통과시켰다.
같은 실수가 두 번이면 규칙이 아니라 관문 — 그래서 배선을 코드로 못 박는다.
"""
import pathlib

import pytest
import yaml

WF = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/rank-check-watchdog.yml"


@pytest.fixture(scope="module")
def 워크플로() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def 잡(워크플로) -> dict:
    return 워크플로["jobs"]["watchdog"]


def _스텝(잡, 아이디: str) -> dict:
    for s in 잡["steps"]:
        if s.get("id") == 아이디:
            return s
    raise AssertionError(f"스텝 id={아이디} 가 사라졌다")


def _명령만(run: str) -> str:
    """주석을 걷어낸 실행 명령만 남긴다.

    ★이게 없으면 검사가 헛돈다. `--fail` 을 지웠는데도 검사가 통과했는데,
      바로 윗줄 주석에 '--fail 없이 쓰면…' 이라고 적혀 있었기 때문이다.
      설명글이 검사를 대신 통과시켜 주는 일은 없어야 한다.
    """
    return "\n".join(L for L in run.splitlines() if not L.strip().startswith("#"))


class Test워치독이_실제로_깨어나는가:
    def test_점검이_실패하면_깨어난다(self, 잡):
        assert "failure" in 잡["if"]

    def test_취소_시간초과_시작실패에도_깨어난다(self, 잡):
        """★실측으로 알림 0건이 두 번 있었다(07-23 · 07-28 점검이 cancelled).

        러너를 못 받아 큐에 갇힌 run 은 cancelled 로 끝난다 — 지금 겨냥한 그 상황이다.
        """
        for c in ("cancelled", "timed_out", "startup_failure"):
            assert c in 잡["if"], f"'{c}' 로 끝나면 워치독이 통째로 건너뛴다 = 알림 0건"

    def test_점검_완료_시점에_걸려_있다(self, 워크플로):
        # PyYAML 은 YAML 1.1 이라 'on:' 을 True 로 읽는다.
        트리거 = 워크플로.get("on") or 워크플로.get(True)
        assert 트리거["workflow_run"]["types"] == ["completed"]
        assert "naver-rank-check" in 트리거["workflow_run"]["workflows"]

    def test_실패_주석을_읽을_권한이_있다(self, 워크플로):
        """checks 가 없으면 결제 차단과 러너 미배정을 구분할 단서가 사라진다."""
        assert 워크플로["permissions"].get("checks") == "read"


class Test알림_통로가_둘인가:
    def test_알림은_앞_스텝이_어떻게_되든_돈다(self, 잡):
        assert _스텝(잡, "notify")["if"] == "always()"

    def test_알림_실패를_삼키지_않는다(self, 잡):
        """★`|| true` 가 실제로 한 번 되돌아왔던 자리다. 삼키면 최후수단이 안 돈다."""
        run = _명령만(_스텝(잡, "notify")["run"])
        assert "|| true" not in run
        assert "|| :" not in run

    def test_알림이_실패하면_최후수단이_받는다(self, 잡):
        assert self._최후수단(잡) is not None, \
            "curl 최후수단이 없거나 조건이 끊겼다 — 통로가 하나뿐이다"

    def test_최후수단은_준비가_필요없는_도구를_쓴다(self, 잡):
        """파이썬·pip 를 거치면 그게 깨질 때 같이 죽는다 = 통로가 둘이 아니다."""
        run = _명령만(self._최후수단(잡)["run"])
        assert "curl" in run
        assert ".venv" not in run

    def test_최후수단이_HTTP_오류를_성공으로_읽지_않는다(self, 잡):
        run = _명령만(self._최후수단(잡)["run"])
        assert "--fail" in run, "텔레그램이 400 을 줘도 성공으로 끝난다"

    @staticmethod
    def _최후수단(잡):
        for s in 잡["steps"]:
            조건 = str(s.get("if", ""))
            if "steps.notify.outcome" in 조건 and "success" in 조건 and s.get("run"):
                return s
        raise AssertionError("최후수단 스텝이 사라졌다 — 알림 통로가 하나뿐이다")

    def test_알림_스텝이_잡을_죽이지_않는다(self, 잡):
        """1 로 끝나도 job 은 살아야 최후수단이 돈다."""
        assert _스텝(잡, "notify")["continue-on-error"] is True


class Test판단_결과가_알림까지_전달되는가:
    """중간 스텝이 값을 만들어도 env 매핑이 끊기면 아무 소용이 없다."""

    @pytest.mark.parametrize("키,출처", [
        ("CAUSE", "steps.cause.outputs.cause"),
        ("STREAK", "steps.streak.outputs.streak"),
        ("RETRYING", "steps.rerun_step.outcome"),
        ("CONCLUSION", "github.event.workflow_run.conclusion"),
    ])
    def test_배선이_이어져_있다(self, 잡, 키, 출처):
        env = _스텝(잡, "notify")["env"]
        assert 키 in env, f"{키} env 매핑이 사라졌다"
        assert 출처 in str(env[키]), f"{키} 가 {출처} 에서 안 온다"

    def test_판별_실패는_unknown_으로_떨어진다(self, 잡):
        """빈 값이 되면 파이썬 쪽에서 code 로 읽혀 문구가 어긋난다."""
        assert "'unknown'" in str(_스텝(잡, "notify")["env"]["CAUSE"])


class Test재시도가_판별보다_먼저_돌아도_되는가:
    def test_사유_판별은_실패한_attempt_를_못박는다(self, 잡):
        """rerun 이 새 attempt 를 만든다 — 안 박으면 엉뚱한 시도를 원인으로 읽는다."""
        assert "attempts/${RUN_ATTEMPT}/jobs" in _스텝(잡, "cause")["run"]

    def test_연속_실패_계산이_이번_회차를_뺀다(self, 잡):
        """재시도가 이 run 을 queued 로 되돌려 'completed' 필터에서 빠지기 때문."""
        run = _스텝(잡, "streak")["run"]
        assert "databaseId != ${RUN_ID}" in run
        assert "streak=1" in run, "이번 실패를 안 세면 1회 적게 나온다"
