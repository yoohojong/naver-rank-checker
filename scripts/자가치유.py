#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자가치유.py — 자동화가 넘어지면 스스로 진단하고, 사장님께 상태를 끝까지 보고한다.

왜 있나 (2026-07-24 사장님 지시)
--------------------------------
  "오류가 나도 무조건 스스로 계속 디벨롭해서 갈 수 있게 하는게 어때?
   당연히 재시도여부도 텔레그램으로 보내줘야하고 성공 여부까지 보내줘야지"

지금까지는 실패하면 `🚨 크론 실패 + 로그 링크` 한 줄만 갔다. 그래서 사장님이 매번
로그를 열거나 Claude 를 불러야 했고, **언제 정상으로 돌아왔는지도 알 수 없었다**
(조용히 복구되면 아무 소식이 없으니 계속 고장난 줄 안다).

이 모듈이 하는 일 — 3층 구조의 **2층**:
  1) 이 워크플로의 최근 run 들을 GitHub 에 물어 **연속 실패 몇 번째**인지 센다.
  2) 실패한 job 로그를 긁어 **원인을 이름으로 분류**한다(연결 끊김·쿼터·토큰만료 …).
  3) 사장님께 텔레그램으로 **세 가지 시점 모두** 알린다:
       · 실패(자동 재시도 예정 시각까지)   · 반복 실패(사람 확인 필요)   · **복구됨**
  4) 연속 실패가 임계를 넘으면 **GitHub 이슈**를 열어 3층(Claude 개입)이 집을 자리를 만든다.

설계 원칙
---------
· **상태 파일이 없다.** 연속 실패 횟수를 GitHub API 로 그때그때 센다 —
  파일을 커밋해 나르면 저장소마다 배선이 달라지고 그 배선이 또 고장난다.
· **표준 라이브러리만.** 어느 저장소에 복사해도 그냥 돈다(pip 설치 불필요).
· **경보의 경보는 없다.** 여기서 무슨 일이 나도 비0으로 죽지 않는다.
  자가치유가 크론을 죽이면 본말전도다.
· **조용한 성공은 조용히.** 평소 성공엔 알림을 보내지 않는다. 직전이 실패였을 때만
  '복구됨'을 보낸다 — 안 그러면 하루 수십 통이 되어 아무도 안 본다.

사용(워크플로 마지막 step):
    - name: 자가치유 보고
      if: always()
      continue-on-error: true
      env:
        TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
        TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: python 자가치유.py --이름 "카외 자동수집" --결과 ${{ job.status }}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# ── 원인 사전 ────────────────────────────────────────────────────────────
# 로그에서 이 패턴이 보이면 그 이름으로 부른다. **위에서부터 먼저 맞는 것**을 쓴다.
# 사장님이 읽을 문장이므로 개발자 용어 대신 무슨 일이 났는지로 적는다.
원인사전: list[tuple[str, str, str]] = [
    # (정규식, 사장님께 보일 이름, 대처 안내)
    (r"ConnectionResetError|Connection aborted|Connection reset by peer",
     "상대 서버가 연결을 끊음",
     "구글 앱스스크립트(다리)가 응답을 못 준 경우가 많습니다. 대개 다음 회차에 저절로 풉니다."),
    (r"HTTP Error 429|Quota exceeded|RESOURCE_EXHAUSTED|rate limit",
     "하루 사용량 한도 초과",
     "구글·네이버가 오늘 몫을 다 썼습니다. 시간이 지나면 풀립니다."),
    (r"HTTP Error 40[13]|Bad credentials|invalid_grant|401|PERMISSION_DENIED",
     "열쇠(토큰)가 만료됨",
     "사장님 확인이 필요합니다 — GitHub Secrets 의 토큰을 새로 넣어야 합니다."),
    (r"HTTP Error 5\d\d|Internal Server Error|Service Unavailable",
     "상대 서버가 아픔",
     "우리 문제가 아닙니다. 다음 회차에 대개 풉니다."),
    (r"TimeoutError|timed out|timeout-minutes|The job running on runner .* has exceeded",
     "시간 초과",
     "작업이 예정 시간을 넘겼습니다. 양이 늘었는지 확인이 필요합니다."),
    (r"ModuleNotFoundError|ImportError|SyntaxError|NameError|AttributeError|TypeError",
     "우리 코드 문제",
     "코드를 고쳐야 합니다 — 저절로 안 풉니다."),
    (r"WorksheetNotFound|SpreadsheetNotFound|gspread\.exceptions",
     "시트를 못 찾음",
     "탭 이름이 바뀌었거나 권한이 빠졌을 수 있습니다."),
    (r"MergeConflict|non-fast-forward|failed to push",
     "저장소 밀어넣기 실패",
     "다음 회차가 옛 상태로 시작할 수 있습니다."),
]

사람확인_임계 = 3        # 이만큼 연속 실패하면 '저절로 안 풀린다'로 보고 이슈를 연다
_API = "https://api.github.com"


# ── GitHub 조회 (읽기 전용) ──────────────────────────────────────────────
class _리다이렉트막기(urllib.request.HTTPRedirectHandler):
    """302 를 따라가지 않고 HTTPError 로 올린다 — 호출부가 Location 을 직접 쓰게."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _토큰() -> str:
    return (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def _api(경로: str, 방법: str = "GET", 본문: dict | None = None, raw: bool = False):
    """GitHub API 호출. 실패하면 None — 여기서 죽으면 안 된다."""
    tok = _토큰()
    if not tok:
        return None
    url = 경로 if 경로.startswith("http") else _API + 경로
    데이터 = json.dumps(본문).encode() if 본문 is not None else None
    req = urllib.request.Request(url, data=데이터, method=방법)
    req.add_header("Authorization", f"Bearer {tok}")
    req.add_header("Accept", "application/vnd.github+json")
    if 데이터:
        req.add_header("Content-Type", "application/json")
    try:
        if raw:
            # ★로그 엔드포인트는 저장소가 아니라 **블롭 스토리지로 302** 를 준다.
            #   urllib 는 리다이렉트를 따라가면서 Authorization 헤더까지 들고 가는데,
            #   스토리지는 그 헤더를 보고 거부한다(실제 API 로 확인함).
            #   → 리다이렉트를 안 따라가고 주소만 받아, 최종 요청은 **인증 없이** 보낸다.
            오프너 = urllib.request.build_opener(_리다이렉트막기)
            try:
                with 오프너.open(req, timeout=30) as r:
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as he:
                간곳 = he.headers.get("Location") if he.code in (301, 302, 303, 307, 308) else None
                if not 간곳:
                    raise
                with urllib.request.urlopen(
                        urllib.request.Request(간곳), timeout=60) as r2:
                    return r2.read().decode("utf-8", "replace")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:      # noqa: BLE001 — 조회 실패가 크론을 죽이면 안 됨
        print(f"[자가치유] GitHub 조회 실패({방법} {경로}): {type(e).__name__}")
        return None


def 연속실패_횟수(저장소: str, 워크플로: str, 이번run: str, 이번결과: str) -> int:
    """이 워크플로가 **몇 번째로 연달아** 실패했는지. 이번 것 포함.

    상태 파일을 안 쓰는 이유: 파일을 커밋해 나르면 저장소마다 배선이 달라지고,
    그 배선이 고장나면 자가치유 자체가 조용히 멎는다. GitHub 이 이미 알고 있는 걸 묻는다.
    """
    if 이번결과 != "failure":
        return 0
    데이터 = _api(f"/repos/{저장소}/actions/workflows/{워크플로}/runs"
                f"?per_page=15&status=completed&exclude_pull_requests=true")
    if not 데이터:
        return 1        # 못 세면 최소 1회(이번 것)로 본다 — 과소보고가 과대보고보다 안전
    n = 1               # 이번 run 은 아직 completed 가 아닐 수 있으니 직접 센다
    for run in 데이터.get("workflow_runs", []):
        if str(run.get("id")) == str(이번run):
            continue
        if run.get("conclusion") == "failure":
            n += 1
        elif run.get("conclusion") in ("success", "cancelled", "skipped"):
            break       # 성공(또는 취소)을 만나면 연속 구간 끝
    return n


def 직전이_실패였나(저장소: str, 워크플로: str, 이번run: str) -> bool:
    """직전 완료 run 이 실패였나 — '복구됨' 을 보낼지 정하는 기준."""
    데이터 = _api(f"/repos/{저장소}/actions/workflows/{워크플로}/runs"
                f"?per_page=10&status=completed&exclude_pull_requests=true")
    if not 데이터:
        return False
    for run in 데이터.get("workflow_runs", []):
        if str(run.get("id")) == str(이번run):
            continue
        결론 = run.get("conclusion")
        if 결론 in ("success", "failure"):
            return 결론 == "failure"
    return False


def 실패로그_원인(저장소: str, 이번run: str) -> tuple[str, str, str]:
    """실패한 job 의 로그를 긁어 원인을 분류한다.

    반환 (원인이름, 대처안내, 로그에서 뽑은 증거 한 줄). 못 읽으면 ('알 수 없음', …, '').
    """
    잡목록 = _api(f"/repos/{저장소}/actions/runs/{이번run}/jobs?per_page=30")
    if not 잡목록:
        return "알 수 없음", "로그를 못 읽었습니다 — 링크로 직접 확인해 주세요.", ""
    for job in 잡목록.get("jobs", []):
        if job.get("conclusion") != "failure":
            continue
        로그 = _api(f"/repos/{저장소}/actions/jobs/{job.get('id')}/logs", raw=True)
        if not 로그:
            continue
        꼬리 = 로그[-40000:]          # 마지막 부분에 traceback 이 있다
        for 패턴, 이름, 안내 in 원인사전:
            m = re.search(패턴, 꼬리)
            if m:
                증거 = _증거줄(꼬리, m.start())
                # 어느 step 에서 죽었는지도 같이 준다(사장님이 바로 위치를 안다)
                죽은step = ""
                for s in job.get("steps", []):
                    if s.get("conclusion") == "failure":
                        죽은step = s.get("name", "")
                        break
                if 죽은step:
                    이름 = f"{이름} · '{죽은step}' 에서"
                return 이름, 안내, 증거
    return "알 수 없음", "로그에서 아는 패턴을 못 찾았습니다 — 링크로 확인해 주세요.", ""


def _증거줄(글: str, 위치: int) -> str:
    """패턴이 걸린 줄 하나를 사장님이 볼 만하게 다듬어 돌려준다."""
    시작 = 글.rfind("\n", 0, 위치) + 1
    끝 = 글.find("\n", 위치)
    줄 = 글[시작:끝 if 끝 > 0 else len(글)]
    # 앞에 붙는 잡음 제거 — 형식이 두 가지다:
    #   'job\tstep\t2026-07-23T14:54:10Z 본문'  (gh run view --log)
    #   '2026-07-23T14:54:10.1306926Z 본문'      (API 로그 원본)
    줄 = re.sub(r"^(?:[^\t]*\t){0,2}\s*", "", 줄)
    줄 = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z?\s*", "", 줄).strip()
    return 줄[:200]


# ── 알림 ─────────────────────────────────────────────────────────────────
def 텔레그램(문장: str) -> bool:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (tok and chat):
        print("[자가치유] 텔레그램 secret 미설정 — 발송 생략")
        print(문장)
        return False
    try:
        데이터 = urllib.parse.urlencode({"chat_id": chat, "text": 문장}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=데이터)
        urllib.request.urlopen(req, timeout=20)
        print("[자가치유] 텔레그램 발송 완료")
        return True
    except Exception as e:      # noqa: BLE001
        print(f"[자가치유] 발송 실패(비차단): {type(e).__name__}")
        return False


def 다음_재시도(크론: str) -> str:
    """다음 자동 재시도가 대략 언제인지 사람 말로. 크론을 못 읽으면 빈 문자열."""
    if not 크론:
        return ""
    분, 시 = (크론.split() + ["", ""])[:2]
    if 시.startswith("*/"):
        try:
            return f"{int(시[2:])}시간 뒤쯤"
        except ValueError:
            return ""
    if 시.isdigit() or "," in 시:
        return "다음 예정 시각에"
    return ""


def 문장_만들기(이름, 결과, 연속, 원인, 안내, 증거, 링크, 재시도) -> str:
    if 결과 != "failure":
        return (f"✅ {이름} 복구됨\n"
                f"실패하던 자동 작업이 방금 정상으로 돌아왔습니다.\n"
                f"이제 따로 하실 일은 없습니다.")
    머리 = (f"🚨 {이름} 실패" if 연속 <= 1
            else f"🚨 {이름} {연속}회 연속 실패")
    줄 = [머리, f"원인: {원인}"]
    if 증거:
        줄.append(f"기록: {증거}")
    줄.append(안내)
    if 연속 >= 사람확인_임계:
        줄.append(f"\n⚠️ {연속}회 연속입니다 — 저절로 풀리는 문제가 아닙니다.\n"
                  f"확인용 이슈를 열어뒀습니다(아래 링크).")
    elif 재시도:
        줄.append(f"\n자동으로 {재시도} 다시 시도합니다. 결과도 알려드릴게요.")
    else:
        줄.append("\n다음 예정 회차에 자동으로 다시 시도합니다.")
    if 링크:
        줄.append(f"로그: {링크}")
    return "\n".join(줄)


# ── 3층 진입점: 반복 실패면 이슈를 열어 Claude 가 집게 한다 ────────────────
이슈라벨 = "자가치유"


def 이슈_열기(저장소, 이름, 연속, 원인, 안내, 증거, 링크) -> str:
    """같은 제목의 열린 이슈가 있으면 댓글만 달고, 없으면 새로 연다. 반환=이슈 URL."""
    제목 = f"[자가치유] {이름} 연속 실패"
    찾기 = _api(f"/repos/{저장소}/issues?state=open&per_page=50")
    기존 = None
    for it in (찾기 or []):
        if it.get("title") == 제목 and "pull_request" not in it:
            기존 = it
            break
    본문 = (f"**{연속}회 연속 실패**\n\n"
            f"- 원인 분류: {원인}\n"
            f"- 기록: `{증거}`\n"
            f"- 안내: {안내}\n"
            f"- 로그: {링크}\n\n"
            f"---\n"
            f"### Claude 가 할 일\n"
            f"1. 위 로그로 **근본 원인**을 분석한다(증상 아닌 뿌리).\n"
            f"2. 해결책을 기획하고 **고친다**.\n"
            f"3. 회귀 테스트를 붙여 같은 실패가 다시 안 나게 한다.\n"
            f"4. **PR 로 올린다 — 라이브 자동 반영은 하지 않는다**(사장님 승인 1회).\n"
            f"5. 다음 회차가 정상일 때까지 이 이슈를 닫지 않는다.\n")
    if 기존:
        _api(f"/repos/{저장소}/issues/{기존['number']}/comments",
             "POST", {"body": 본문})
        return 기존.get("html_url", "")
    새것 = _api(f"/repos/{저장소}/issues", "POST",
              {"title": 제목, "body": 본문, "labels": [이슈라벨]})
    return (새것 or {}).get("html_url", "")


def 이슈_닫기(저장소, 이름) -> None:
    """복구되면 열려 있던 이슈를 닫는다 — 낫은 걸 계속 띄워두면 아무도 안 본다."""
    제목 = f"[자가치유] {이름} 연속 실패"
    찾기 = _api(f"/repos/{저장소}/issues?state=open&per_page=50")
    for it in (찾기 or []):
        if it.get("title") == 제목 and "pull_request" not in it:
            _api(f"/repos/{저장소}/issues/{it['number']}/comments", "POST",
                 {"body": "✅ 다음 회차가 정상으로 끝나 자동으로 닫습니다."})
            _api(f"/repos/{저장소}/issues/{it['number']}", "PATCH",
                 {"state": "closed"})
            print(f"[자가치유] 이슈 #{it['number']} 닫음(복구)")


# ── 진입점 ───────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    """★어떤 일이 나도 0 으로 끝난다 — 자가치유가 크론을 죽이면 본말전도다.

    개별 함수마다 try 를 달아뒀지만 그건 '내가 예상한 실패'만 막는다. GitHub 이 형식을
    바꾸거나 로그가 이상하게 오면 예상 밖에서 터진다. 그때 이 step 이 빨개지면
    **멀쩡히 끝난 크론이 실패로 뒤집힌다** — 회귀 테스트가 실제로 이걸 잡았다.
    """
    try:
        return _본체(argv)
    except SystemExit:
        raise                       # argparse 의 --help·인자오류는 그대로
    except BaseException as e:      # noqa: BLE001 — 여기서 죽으면 안 된다
        print(f"[자가치유] 예상 밖 오류(무시하고 정상 종료): {type(e).__name__}: {e}")
        return 0


def _본체(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--이름", required=True, help="사장님이 읽을 자동화 이름")
    p.add_argument("--결과", required=True, help="job.status (success/failure/cancelled)")
    p.add_argument("--크론", default="", help="이 워크플로 cron 식(다음 재시도 안내용)")
    a = p.parse_args(argv)

    결과 = (a.결과 or "").strip().lower()
    if 결과 == "cancelled":
        print("[자가치유] 취소된 run — 알리지 않음")
        return 0

    저장소 = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    워크플로 = os.environ.get("WORKFLOW_FILE", "") or os.environ.get("GITHUB_WORKFLOW_REF", "")
    if "/" in 워크플로:                     # 'owner/repo/.github/workflows/x.yml@refs/…'
        워크플로 = 워크플로.split("@")[0].split("/")[-1]
    링크 = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
          f"{저장소}/actions/runs/{run}") if 저장소 and run else ""

    if 결과 == "failure":
        연속 = 연속실패_횟수(저장소, 워크플로, run, 결과)
        원인, 안내, 증거 = 실패로그_원인(저장소, run)
        이슈url = ""
        if 연속 >= 사람확인_임계:
            이슈url = 이슈_열기(저장소, a.이름, 연속, 원인, 안내, 증거, 링크)
        문장 = 문장_만들기(a.이름, 결과, 연속, 원인, 안내, 증거,
                       이슈url or 링크, 다음_재시도(a.크론))
        텔레그램(문장)
        return 0

    # 성공 — 직전이 실패였을 때만 '복구됨'. 평소 성공은 조용히(스팸 방지).
    if 직전이_실패였나(저장소, 워크플로, run):
        텔레그램(문장_만들기(a.이름, "success", 0, "", "", "", "", ""))
        이슈_닫기(저장소, a.이름)
    else:
        print("[자가치유] 평소 성공 — 알리지 않음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
