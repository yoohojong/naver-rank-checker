# -*- coding: utf-8 -*-
"""워크플로 셸 블록의 '조용히 죽는 문법'을 저장소 전체에서 막는다 (2026-08-07).

## 왜 생겼나
`가동확인.yml` 의 첫 실제 실행이 이렇게 죽었다:

    /home/runner/work/_temp/....sh: line 1: 인자=: command not found
    ##[error]Process completed with exit code 127.

**bash 는 변수 이름에 ASCII 만 받는다.** `인자=""` 는 대입이 아니라 명령으로 읽힌다.
그런데 그 스텝은 `continue-on-error: true` 라 **run 의 conclusion 은 success** 로 찍혔고,
jobs API 로도 정상처럼 보였다. 최후수단 스텝도 같은 이유(`링크=`)로 curl 앞에서 죽어,
결국 **아무 문자도 안 나가고 전부 초록**이었다.

검사 67건도, 독립 검증 두 번도 이걸 못 잡았다 — 파이썬 로직과 YAML 구조만 봤지
**셸이 실제로 도는지**는 아무도 안 봤기 때문이다. 그래서 관문을 만든다.

## 여기서 막는 것
저장소 안 모든 워크플로의 모든 `run:` 블록에 대해:
① 비ASCII 변수 이름 (bash 가 명령으로 읽어 exit 127)
② `bash -n` 문법 검사 (열린 따옴표·짝 안 맞는 fi/done 등)
"""
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

워크플로_폴더 = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows"
BASH = shutil.which("bash")

대입 = re.compile(r"^\s*([^\s=;|&()<>#]+)=")
비ASCII = re.compile(r"[^\x00-\x7f]")


def _셸블록():
    """(파일명, 스텝이름, run본문) 전부. bash 가 아닌 셸은 건너뛴다."""
    for f in sorted(워크플로_폴더.glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        for job in (d.get("jobs") or {}).values():
            for s in job.get("steps") or []:
                run = s.get("run")
                if not run:
                    continue
                셸 = (s.get("shell") or job.get("defaults", {})
                      .get("run", {}).get("shell") or "bash")
                if "bash" not in str(셸) and "sh" != str(셸):
                    continue
                yield f.name, s.get("name", "(이름없음)"), run


def _매개변수():
    목록 = list(_셸블록())
    assert 목록, "워크플로에서 셸 블록을 하나도 못 찾았다 — 검사가 헛돈다"
    return [pytest.param(f, n, r, id=f"{f}::{n[:28]}") for f, n, r in 목록]


@pytest.mark.parametrize("파일,스텝,run", _매개변수())
def test_셸_변수_이름은_ASCII다(파일, 스텝, run):
    """★한글 변수 이름은 bash 가 명령으로 읽는다 → exit 127.

    continue-on-error 가 붙어 있으면 초록으로 보이고, 아무 문자도 안 나간다.
    """
    나쁜것 = []
    for i, line in enumerate(run.splitlines(), 1):
        m = 대입.match(line)
        if m and 비ASCII.search(m.group(1)):
            나쁜것.append(f"{i}행: {line.strip()[:70]}")
    assert not 나쁜것, (
        f"{파일} / {스텝} 에 비ASCII 셸 변수 이름이 있다 — bash 가 명령으로 읽어 죽는다:\n"
        + "\n".join(나쁜것))


@pytest.mark.skipif(BASH is None, reason="bash 없음")
@pytest.mark.parametrize("파일,스텝,run", _매개변수())
def test_셸_문법이_성립한다(파일, 스텝, run):
    """`bash -n` 으로 문법만 본다(실행 안 함).

    GitHub 표현식 ${{ ... }} 는 bash 문법이 아니므로 자리표시자로 바꿔서 본다.
    """
    본문 = re.sub(r"\$\{\{[^}]*\}\}", "PLACEHOLDER", run)
    r = subprocess.run([BASH, "-n"], input=본문, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"{파일} / {스텝} 셸 문법 오류:\n{r.stderr}"
