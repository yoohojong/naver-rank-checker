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

비ASCII = re.compile(r"[^\x00-\x7f]")

# ★줄 **어디서든** 대입을 찾는다. 처음엔 줄 시작만 봤는데, 그러면
#   `...; 인자=""`, `then 인자=""`, `&& 인자=""`, `export 인자=`, `for 항목 in ...`
#   이 전부 통과했다. 라이브 파일에 바로 그 모양(`then args="..."`)이 있어서,
#   한 글자만 한글로 되돌리면 exit 127 로 죽는데 검사는 초록이었다.
대입 = re.compile(
    r'''(?:^|[;&|(){}]|\b(?:then|do|else|elif|export|local|declare|readonly|typeset)\s+|\s)'''
    r'''([^\s=;|&()<>#"']+)=''')
# ★대입(=) 없이 **이름만** 받는 명령들. 3차 검증에서 여기로 13종이 뚫렸다 —
#   `export 인자`(= 없음), `read -r 값`(플래그 때문에 이름을 못 봄),
#   `printf -v 인자`, `mapfile 배열`, `getopts "x" 인자` 등 전부 실제 bash 에서 죽는다.
#   `read -r 값` 이 가장 흔한 모양인데 통과하고 있었다.
선언명령 = re.compile(
    r'''\b(?:export|local|declare|readonly|typeset|unset|mapfile|readarray|coproc)\s+'''
    r'''((?:-\S+\s+)*[^\s;|&()<>#"'=]+)''')
이름받는_명령 = re.compile(
    r'''\b(?:for|select|read)\s+((?:-\S+\s+)*(?:[^\s;|&()<>#"'=]+\s*)+)''')
printf_v = re.compile(r'''\bprintf\s+(?:-\S+\s+)*-v\s+([^\s;|&()<>#"'=]+)''')
getopts = re.compile(r'''\bgetopts\s+\S+\s+([^\s;|&()<>#"'=]+)''')


def _이름들(벗긴줄: str) -> list:
    """이 줄이 만들어 내는 **셸 이름**을 전부 뽑는다.

    대입(`x=1`)만 봐서는 부족하다 — `export 인자`, `read -r 값` 처럼
    = 없이 이름을 받는 명령이 여럿이고, 거기에 한글을 쓰면 똑같이 죽는다.
    """
    이름 = [m.group(1) for m in 대입.finditer(벗긴줄)]
    for 정규식 in (선언명령, 이름받는_명령):
        for m in 정규식.finditer(벗긴줄):
            이름 += [t for t in m.group(1).split() if not t.startswith("-")]
    이름 += [m.group(1) for m in printf_v.finditer(벗긴줄)]
    이름 += [m.group(1) for m in getopts.finditer(벗긴줄)]
    return 이름


def _따옴표_주석_제거(line: str) -> str:
    """따옴표 안 문자열과 주석을 지운다.

    안 지우면 `--data-urlencode "text=상노 점검..."` 같은 정상 줄이 걸린다.
    지우고 나면 남는 건 실제 셸 토큰뿐이다.
    """
    결과, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c == "#":
            break
        if c in "\"'":
            닫는 = line.find(c, i + 1)
            i = n if 닫는 == -1 else 닫는 + 1
            결과.append('""')
            continue
        결과.append(c)
        i += 1
    return "".join(결과)


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
        벗긴것 = _따옴표_주석_제거(line)
        if any(비ASCII.search(x) for x in _이름들(벗긴것)):
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


# ── 관문 자체를 검사한다 ─────────────────────────────────────────────────────

나쁜_줄 = [
    '인자=""',
    'echo hi; 인자=""',
    'true && 인자=""',
    'if true; then 인자=""; fi',
    'if [ "$x" = "y" ]; then 링크="u"; fi',
    'export 인자=""',
    'local 인자=1',
    'readonly 인자=1',
    'read 값',
    'export A=1 인자=2',
    'for 항목 in a b; do echo x; done',
    '인자=1 python x.py',
    # ★3차 검증에서 새로 뚫린 것들 — 전부 실제 bash 에서 죽는다
    'read -r 값',
    'read -r 가 나',
    'export 인자',
    'local 인자',
    'declare 인자',
    'readonly 인자',
    'unset 인자',
    'printf -v 인자 "%s" x',
    'mapfile 배열 < f',
    'readarray 배열 < f',
    'getopts "x" 인자',
    'for 항목 in $list; do :; done',
    'select 항목 in a b; do :; done',
]

좋은_줄 = [
    'args=""',
    'if [ "${x}" = "true" ]; then args="--발송안함"; fi',
    '--data-urlencode "text=상노 점검이 실패했습니다"',
    'echo "가동확인=1"',
    'link="https://x"',
    "body=$(printf '%s' \"문구\")",
    '# 인자= 는 주석이라 괜찮다',
    'for jid in $ids; do echo $jid; done',
    'python -u "scripts/가동확인.py" --모드 보고 $args',
    'echo "[가동확인] 사유=$cause"',
    'read -r line',
    'export GH_TOKEN',
    'for jid in $ids; do gh api "repos/$repo/x" --jq ".[].id"; done',
    'printf -v out "%s" "문구"',
    'echo "for 항목 in a b" # 따옴표 안이라 괜찮다',
]


def _걸리나(line: str) -> bool:
    return any(비ASCII.search(x) for x in _이름들(_따옴표_주석_제거(line)))


@pytest.mark.parametrize("line", 나쁜_줄)
def test_관문이_죽는_줄을_잡는다(line):
    """★1차 관문은 '줄 시작' 대입만 봐서 이 중 8종을 놓쳤다.

    `; 인자=` `then 인자=` `&& 인자=` 는 전부 실제 bash 에서 exit 127 로 죽는다.
    라이브 파일에 바로 그 모양(`then args="..."`)이 있어서, 한 글자만 한글로
    되돌리면 워크플로가 죽는데 관문은 초록이었다.
    """
    assert _걸리나(line), f"bash 에서 죽는 줄을 놓쳤다: {line}"


@pytest.mark.parametrize("line", 좋은_줄)
def test_관문이_멀쩡한_줄을_안_잡는다(line):
    """헛경보 금지 — 따옴표 안 한글과 주석은 정상이다."""
    assert not _걸리나(line), f"멀쩡한 줄을 잡았다: {line}"
