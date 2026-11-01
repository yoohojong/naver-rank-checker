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
  3) 사장님께 텔레그램으로 알리는 것은 **원인이 사장님 몫(열쇠(토큰) 만료 · 로그인 · 결제)일 때뿐**이다
     (★2026-11-01 알림 새 기준 · 판정표 B2 — 아래 `사장님몫_원인`). 처음 3회는 매번, 그 뒤로 하루 한 통.
       · 그 밖의 실패 · 시간 초과 잘림은 문자를 보내지 않는다 — 실패카드 장치
         (D:/ai-office/설치/실패카드/실패카드_내기.py, 30분마다)가 이 실행을 읽어 맥가이버 고침 카드를 낸다.
       · **복구됨**은 2026-10-21 부터 문자로 보내지 않는다(로그 한 줄).
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

# ★출력 UTF-8 고정 — 배치가 로그를 파일로 받아 적으면 윈도우 파이썬 기본 글자표가
#   cp949 라 `—` `★` `→` 한 글자에 죽는다. 일을 다 해놓고 마지막 줄에서 죽으므로
#   더 나쁘다(2026-08-13 주간 작업 · 2026-09-02 쿠팡 광고비 — 같은 사고 두 번).
#   관문 = .harness/tools/test_배치_글자표.py (워크플로가 부르는 파이썬 전부를 스스로 훑는다)
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    # ★2026-07-31 신설: 상태 파일이 깨진 채로 출발하면 예전엔 조용히 빈 값으로 지나가
    #   기록이 통째로 지워졌다. 이제 크게 죽는데, 그 죽음이 '원인 알 수 없음'으로 가면
    #   사장님이 손을 못 쓴다 → 이름과 복구법을 바로 보여준다.
    #   (고르는 규칙은 사전 순서가 아니라 '로그에서 제일 늦게 나온 패턴' — 아래 _고르기 참조.)
    (r"수집 상태 파일이 깨졌습니다|적재 자료 파일이 깨졌습니다"
     r"|병합 충돌 표시가 파일 안에 남아|상태 파일이 깨졌습니다\(JSON 파싱 불가\)"
     r"|JSONDecodeError",
     "상태 파일이 깨짐(대개 병합 충돌 표시)",
     "일부러 멈춘 것입니다 — 그대로 두면 수집 기록이 통째로 지워집니다. "
     "Claude 에게 '상태 파일 깨졌대' 라고 하시면 마지막 정상본으로 되돌립니다."),
    (r"ConnectionResetError|Connection aborted|Connection reset by peer",
     "상대 서버가 연결을 끊음",
     "구글 앱스스크립트(다리)가 응답을 못 준 경우가 많습니다. 대개 다음 회차에 저절로 풉니다."),
    (r"HTTP Error 429|Quota exceeded|RESOURCE_EXHAUSTED|rate limit exceeded",
     "하루 사용량 한도 초과",
     "구글·네이버가 오늘 몫을 다 썼습니다. 시간이 지나면 풀립니다."),
    # ★맨숫자 401 을 쓰면 pip 의 '(401 kB)' 나 '수집 401건' 에 걸려, 코드 버그를
    #   '토큰 만료'로 오진한다 → 사장님이 토큰을 새로 발급해도 아무것도 안 바뀐다
    #   (독립검토 H-1 이 실사례로 재현). 401 이 '상태코드'로 쓰인 자리만 잡는다.
    # ★2026-11-01 알림 새 기준(판정표 B2): 아래 세 이름(열쇠 · 로그인 · 결제)은 사장님만 푸는 원인이라
    #   이것으로 분류될 때만 사장님께 문자가 간다(`사장님몫_원인`). 실패카드 장치는 같은 모양이 원문 로그에
    #   있으면 카드를 안 낸다(설정.json "사장님몫_원문") — 두 쪽 모양이 어긋나면 그 실패는 아무에게도 안 간다.
    #   그래서 모양을 그 설정과 같은 글자로 맞췄다(열쇠는 'token expired' · '토큰이 만료' · 'Authentication failed'
    #   를 더함, 로그인 · 결제는 새 이름). 대소문자는 가리지 않는다(그 설정이 re.I).
    #   ★같은 날 고침: 옛 모양의 '401 Unauthorized' 양옆에 \b 대신 글자 지우기 문자(0x08)가 박혀 있어
    #     이 낱말은 한 번도 안 걸렸다(아래 403 도 같았다).
    (r"(?i:HTTP Error 401|\b401 Unauthorized\b|status(?: code)?[ =:]+401"
     r"|Bad credentials|invalid_grant|token (?:has )?expired|토큰이 만료|Authentication failed)",
     "열쇠(토큰)가 만료됨",
     "사장님 확인이 필요합니다 — GitHub Secrets 의 토큰을 새로 넣어야 합니다."),
    # ★같은 날 GPT 검토 3: 비밀번호를 넣으라는 화면 · 연결(OAuth) 승인을 다시 하라는 화면도 사장님 손이다 → '로그인'.
    (r"(?i:로그인이 필요|로그인 세션|세션이 만료|로그인 (?:실패|만료)|login (?:is )?required|login failed"
     r"|not logged in|please log ?in|session (?:has )?expired|sign in required"
     r"|비밀번호를 입력(?:해 ?주세요|하세요|하십시오)|password is required|please enter your password"
     r"|연결 승인이 필요|consent_required|interaction_required|re-?authori[sz]ation required)",
     "로그인",
     "사장님 확인이 필요합니다 — 로그인이 풀렸습니다. 다시 로그인해 주셔야 다음 회차가 돕니다."),
    # ★같은 날 GPT 검토 3: 사람 확인 퍼즐(캡차)은 사장님만 푼다. 이름은 신고.py 사장님몫_이름과 같은 글자.
    #   GPT 2차 검토 1: 'captcha required: False' · '자동입력 방지문자 없음 확인' 같은 점검 줄에 걸리면 헛문자가 가고
    #   실패카드도 막힌다 → 떴다는 사실 · 풀어 달라는 화면 글만 잡는다.
    #   같은 회사 검토(11-01): 우리 프로그램이 찍는 '캡차·추가 인증이 떴습니다'(smartstore · coupang 브라우저)도 잡는다.
    (r"(?i:(?:캡차|캡챠)[^\n]{0,12}?(?:떴|나타났)|captcha challenge (?:appeared|shown)"
     r"|(?:보안문자|방지문자)를 입력해 ?주세요|사람인지 확인해 ?주세요|verify(?:ing)? you are human|are you a robot\?"
     r"|detected unusual traffic)",
     "사람 확인 퍼즐",
     "사장님 확인이 필요합니다 — 사람 확인 퍼즐(캡차)이 떠서 멈췄습니다. 그 화면을 열어 풀어 주셔야 다음 회차가 돕니다."),
    (r"(?i:결제 (?:실패|필요|오류)|결제가 (?:필요|실패)|Payment Required|HTTP Error 402|\b402 Payment\b"
     r"|billing account|payment failed|insufficient[_ ]quota|exceeded your current quota"
     r"|credit balance is too low|recent account payments have failed"
     r"|spending limit needs to be increased)",
     "결제",
     "사장님 확인이 필요합니다 — 결제(또는 충전)가 막혀 멈췄습니다. 결제 상태를 확인해 주세요."),
    (r"HTTP Error 403|\b403 Forbidden\b|PERMISSION_DENIED",
     "권한이 막힘(또는 한도)",
     "토큰 권한이 빠졌거나 하루 몫을 다 썼을 수 있습니다."),
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

# ★GitHub run conclusion 은 failure 말고도 timed_out·startup_failure 가 있다.
#   옛 코드는 failure 만 세서, 5회 연속 타임아웃이 '연속 1회'로 보고됐다(독립검토 M-1).
실패군 = {"failure", "timed_out", "startup_failure"}
끊는군 = {"success"}          # 이것만 연속 구간을 끊는다

사람확인_임계 = 3        # 이만큼 연속 실패하면 '저절로 안 풀린다'로 보고 이슈를 연다

# ★2026-11-01 알림 새 기준(판정표 B2): 사장님께 실패 문자가 가는 원인은 이 셋뿐이다.
#   사장님 원문(10-31 21:2x): "고장난거를 나한테 왜보고해 … 니들이 CV 파악해서 제대로 고쳐야할거아니야 …
#   인간이 개입해야 하는 상황에 대한 기준만 만들어두고 좀 쓸데없는 보고좀 없애봐".
#   기준 원문 = D:/ai-office/vault/01_조직 규칙/사람_손_기준.md '★11-01 13:2x 개정' 절의 ③(넘을 수 없는 화면).
#   이름은 실패카드 장치 설정(D:/ai-office/설치/실패카드/설정.json "사장님몫_원인")과 같은 글자다 —
#   그 장치는 이 셋이면 카드를 안 내고 "자가치유 문자로 감"으로 넘기므로, 여기서 안 보내면 아무에게도 안 간다.
#   그 밖의 원인은 문자 대신 실패카드 장치가 이 실행을 읽어 맥가이버 고침 카드를 낸다.
사장님몫_원인 = ("열쇠(토큰)가 만료됨", "로그인", "결제", "사람 확인 퍼즐")


def 사장님몫인가(원인: str) -> bool:
    """분류 결과(원인사전의 이름 · 뒤에 붙는 \" · '단계' 에서\" 는 뗀다)가 사장님 몫인가. 글 낱말로 거르지 않는다."""
    return (원인 or "").split(" · ")[0].strip() in 사장님몫_원인
_API = "https://api.github.com"

# ★연속 실패를 몇 쪽까지 세나 (2026-10-21).
#   전에는 최근 실행 30개 **한 장**만 물었다. 30개가 다 실패면 '이번 것 1 + 30 = 31' 이
#   상한이라, margin-guard 는 정기 144회가 실패하는 동안 로그에 '31회 연속' 만 찍혔다.
#   100개씩 넘겨 가며 성공을 만날 때까지 센다. 그래도 끝을 못 보면 센 수는 '하한'이고,
#   문장에 '○회 이상' 이라고 적는다 — 정확한 수인 척하지 않는다.
쪽크기 = 100
세는_쪽수 = 3

# 두 저장소에 같은 파일을 복사해 쓴다. 한쪽만 고치면 조용히 갈라지므로
# 양쪽 테스트가 이 값을 대조한다(독립검토 L-4).
버전 = "2026-11-01.4"

# ★문자 대신 아침 건강 보고로 옮긴 작업 (2026-10-21 사장님 "이상한 보고가 너무 많아 진짜").
#   판정 원칙(2026-08-27 "경보 진짜 필요한것만"): **이 문자를 받고 사장님이 하실 수 있는
#   일이 있나?** — 아래는 **검사만 실패하고 수집·보고는 그대로 도는** 곳이라 고칠 사람이
#   Claude 다. 끄지 않는다: 실패 중이면 아침 건강 보고(system_health.py)에 ⚠️ 한 줄이 붙는다
#   (cafe-external/아침보고_작업상태.py). 확인용 이슈는 그대로 연다 — Claude 가 집는 자리.
#   수집·자료가 안 쌓이는 곳(cafe-auto-collect·clarity-daily·competitor-comments·
#   obsidian-autolink)은 사장님이 아셔야 하므로 여기 넣지 않는다 — 그대로 바로 보낸다.
#   근거 표: 작업복사본/텔레그램정리_20261020/2_판정표.md
#   파일 이름 → 워크플로가 `--이름` 으로 넘기는 이름(아침 보고가 이 이름으로 줄을 쓴다).
#   ★2026-11-01: 이 목록은 이제 문자를 가르지 않는다(모든 작업이 '사장님 몫일 때만 문자' 한 규칙 —
#     아래 `_본체`). 아침 보고(아침보고_작업상태.py)가 이 이름표를 읽어서 그대로 둔다.
아침보고로_옮김 = {
    "utm-guard.yml": "홈페이지 검사(정기)",
    "ext-guard.yml": "확장 검사(정기)",
    "margin-guard.yml": "마진 검사(정기)",
    "slot-rank-audit.yml": "구좌순위 화면대조",
    "cafe-folder-guard.yml": "카외 보관함 감시",
    "cafe-weekly-audit.yml": "카외 주간 감사",
    "sheet-slim-guard.yml": "카외 시트 주간 경량 유지",
}


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


def _같은줄기() -> str:
    """같은 브랜치의 정기 실행만 세도록 쿼리를 좁힌다 (독립검토 M-4).

    ★`exclude_pull_requests=true` 는 이름과 달리 PR 트리거 run 을 안 걸러낸다
      (응답의 pull_requests 배열만 비운다). 브랜치 필터가 없으면 개발 브랜치에서
      두 번 실패시켜 본 것이 다음날 크론 1회 실패를 '3회 연속'으로 만든다.
    """
    가지 = os.environ.get("GITHUB_REF_NAME", "").strip()
    return f"&branch={urllib.parse.quote(가지)}" if 가지 else ""


def _같은종류() -> str:
    """이번 실행과 **같은 종류**(정기·코드 올림·손 실행)만 세도록 쿼리를 좁힌다 (2026-10-21).

    ★실사고: 검사 워크플로들(margin-guard·utm-guard…)은 알림 단계를 **정기 실행에서만**
      돌리는데, 셈에는 코드 올림(push) 실행 실패까지 섞였다. 그래서 9/9 첫 정기 실패가
      '11회 연속'으로 보고됐고, 알릴 차례(12번째)가 push 실행에 걸려 그냥 지나갔다
      (로그 원문: 11 → 13, 12를 건너뜀).
    """
    종류 = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    return f"&event={urllib.parse.quote(종류)}" if 종류 else ""


def 연속실패_재기(저장소: str, 워크플로: str, 이번run: str, 이번결과: str,
              종류: str | None = None, 가지: str | None = None, api=None) -> dict:
    """이 워크플로가 **몇 번째로 연달아** 실패했는지 — 이번 것 포함.

    돌려주는 것: {"연속": 횟수, "이상": 끝을 못 봤나(센 수가 하한인가),
                 "못셈": 첫 쪽부터 못 읽었나(그러면 연속은 이번 것 1),
                 "직전실패시각": 바로 앞 실패 회차가 **시작한** 시각(ISO, 모르면 "")}

    상태 파일을 안 쓰는 이유: 파일을 커밋해 나르면 저장소마다 배선이 달라지고,
    그 배선이 고장나면 자가치유 자체가 조용히 멎는다. GitHub 이 이미 알고 있는 걸 묻는다.

    종류·가지를 안 주면 이번 실행의 것(GITHUB_EVENT_NAME·GITHUB_REF_NAME)을 쓴다.
    아침 건강 보고처럼 남의 워크플로를 셀 때는 직접 준다(빈 문자열 = 거르지 않음).
    """
    결과 = {"연속": 0, "이상": False, "못셈": False, "직전실패시각": ""}
    if 이번결과 != "failure":
        return 결과
    api = api or _api
    거름 = (_같은줄기() if 가지 is None
           else (f"&branch={urllib.parse.quote(가지)}" if 가지 else ""))
    거름 += (_같은종류() if 종류 is None
            else (f"&event={urllib.parse.quote(종류)}" if 종류 else ""))
    n = 1               # 이번 run 은 아직 completed 가 아닐 수 있으니 직접 센다
    for 쪽 in range(1, 세는_쪽수 + 1):
        데이터 = api(f"/repos/{저장소}/actions/workflows/{워크플로}/runs"
                  f"?per_page={쪽크기}&page={쪽}&status=completed{거름}")
        if not 데이터:
            # 첫 쪽부터 못 읽으면 최소 1회(이번 것)로 본다 — 과소보고가 과대보고보다 안전.
            # 다음 쪽을 못 읽었으면 여기까지 센 수는 '하한'이다.
            결과["이상"] = 쪽 > 1
            결과["못셈"] = 쪽 == 1
            break
        회차들 = 데이터.get("workflow_runs", []) or []
        끊김 = False
        for run in 회차들:
            if str(run.get("id")) == str(이번run):
                continue
            결론 = run.get("conclusion")
            if 결론 in 실패군:
                n += 1
                if not 결과["직전실패시각"]:
                    결과["직전실패id"] = str(run.get("id") or "")   # GPT 검토 2(11-01) — 그 회차가 문자를 보냈나 보려고
                    # ★**시작 시각**을 쓴다 (GPT 2차 검토 10-21 로 바꿈).
                    #   그 회차가 '보낼까'를 정한 때는 시작과 끝 사이 어딘가다. 끝난 시각을 쓰면
                    #   23:59:50 에 정하고 00:00:10 에 끝난 회차 뒤로 **그날 하루가 통째로 조용**하다
                    #   (모든 회차가 '오늘 이미 실패가 있었다'로 본다). 시작 시각을 쓰면 반대로
                    #   자정을 걸친 회차 뒤에 한 통이 더 갈 수 있다(하루 최대 두 통).
                    #   한 통 더 가는 것이 하루 침묵보다 낫다 — 이 파일의 원칙.
                    결과["직전실패시각"] = str(run.get("run_started_at") or run.get("created_at")
                                         or run.get("updated_at") or "")
            elif 결론 in 끊는군:
                끊김 = True
                break   # 성공을 만나야 연속 구간이 끝난다
            # cancelled·skipped 는 **끊지도 세지도 않고 건너뛴다** (독립검토 M-3).
            #   취소가 잦은 워크플로(telegram-qa)는 실패→취소→실패 가 섞여
            #   옛 코드에선 연속이 늘 1 이 되어 3층이 영원히 안 열렸다.
        if 끊김 or len(회차들) < 쪽크기:
            break       # 성공을 만났거나 기록이 끝났다 = 정확한 수
    else:
        결과["이상"] = True     # 쪽을 다 넘겼는데도 성공을 못 만났다 = 센 수는 하한
    결과["연속"] = n
    return 결과


def 연속실패_횟수(저장소: str, 워크플로: str, 이번run: str, 이번결과: str) -> int:
    """연속 실패 횟수만 — 자세한 것은 `연속실패_재기`."""
    return 연속실패_재기(저장소, 워크플로, 이번run, 이번결과)["연속"]


def 직전이_실패였나(저장소: str, 워크플로: str, 이번run: str) -> bool | None:
    """직전 완료 run 이 실패였나 — '복구됨' 을 보낼지 정하는 기준.

    반환: True(직전 실패) / False(직전 성공) / **None(못 읽었다)**

    ★2026-08-24 실사고: 조회에 실패하면 False 를 돌려줬다. 그래서 부르는 쪽이
      "평소 성공 — 알리지 않음" 으로 조용히 끝났다. 실제 로그가 이랬다:
          [자가치유] GitHub 조회 실패(...): HTTPError
          [자가치유] 평소 성공 — 알리지 않음
      **못 본 것을 '괜찮다'로 바꿔 말한 것이다.** 그 자리가 하필 '복구됐습니다'
      알림을 보낼지 정하는 곳이라, 직전이 진짜 실패였다면 사장님은 고쳐진 줄
      모르고 계속 걱정하신다.
      이 저장소가 계속 싸우는 그 모양이라 '모름' 을 따로 돌려준다.
    """
    데이터 = _api(f"/repos/{저장소}/actions/workflows/{워크플로}/runs"
                f"?per_page=10&status=completed{_같은줄기()}{_같은종류()}")
    if 데이터 is None:
        return None                      # 못 읽었다 — '실패 아님'과 다른 말이다
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
        # ★job.conclusion 으로 고르면 안 된다 (2026-07-24 독립검토 CRITICAL).
        #   자가치유는 **같은 job 의 마지막 step** 이라, 자기 job 은 그 시점에
        #   status=in_progress · conclusion=null 이다. conclusion=="failure" 로 거르면
        #   유일한 job 을 건너뛰고 **라이브에서 100% '알 수 없음'** 이 나온다
        #   (완료된 옛 run 에 붙여 본 실측만 통과했던 이유).
        #   step 단위 결과는 job 이 진행 중이어도 이미 확정돼 있으니 그걸 본다.
        if job.get("conclusion") == "success":
            continue
        죽은step = next((s.get("name", "") for s in job.get("steps", [])
                       if s.get("conclusion") in ("failure", "timed_out")), "")
        if job.get("conclusion") not in ("failure", "timed_out") and not 죽은step:
            continue
        로그 = _api(f"/repos/{저장소}/actions/jobs/{job.get('id')}/logs", raw=True)
        if not 로그:
            continue
        후보 = _검색구간(로그)
        # ★2026-11-01 알림 새 기준(판정표 B2): 사장님 몫(열쇠 · 로그인 · 결제) 모양은 '제일 늦게 걸린 것'이 아니어도
        #   먼저 고른다. 실패카드 장치가 같은 범위(이 구간 + 로그 마지막 30줄)에서 이 모양을 보면 카드를 안 내므로,
        #   여기서 다른 이름(예: 뒤따른 TypeError → '우리 코드 문제')으로 부르면 문자도 카드도 0이 된다.
        범위 = 사장님몫_볼글(후보 + "\n" + "\n".join(로그.splitlines()[-30:]))   # 같은 회사 검토(11-01)
        몫 = _가장_늦게_걸린_패턴(범위, 사장님몫_원인)
        # 다듬은 글에서 사장님 몫을 못 찾았으면 나머지 이름 가운데서만 고른다 — 원문 그대로 다시 대면
        #   스크립트 원문 · 부정 줄의 '로그인'이 여기서 다시 걸린다(같은 회사 검토 11-01).
        직원이름들 = [이름 for _, 이름, _ in 원인사전 if 이름 not in 사장님몫_원인]
        m, 후보 = (몫, 범위) if 몫 else (_가장_늦게_걸린_패턴(후보, 직원이름들), 후보)
        if m:
            이름, 안내, 위치 = m
            증거 = _증거줄(후보, 위치)
            if 죽은step:
                이름 = f"{이름} · '{죽은step}' 에서"
            return 이름, 안내, 증거
    return "알 수 없음", "로그에서 아는 패턴을 못 찾았습니다 — 링크로 확인해 주세요.", ""


# ★같은 회사 검토(11-01): 사장님 몫을 고를 때 볼 글에서 빼는 것.
#   ① GitHub 가 단계 시작 때 그대로 찍는 스크립트 원문(`##[group]Run …` ~ `##[endgroup]`) — 예: 여러 워크플로의
#      `throw "PC 파이썬을 못 찾음 — 로그인 세션이 아닐 수 있음"` 이 실패와 상관없이 모든 실행 로그에 찍혀,
#      검사가 실패하기만 하면 '로그인이 풀렸습니다' 문자가 갈 뻔했다.
#   ② 부정 · 완료 · 0건 줄 — 'login failed: False' · '세션이 만료되지 않았습니다' · '결제 오류 없음' · '로그인 완료'.
#   빼는 쪽으로 틀리면 사장님 몫이 직원 카드로 간다(침묵은 아니다 — 실패카드가 카드를 낸다).
_부정줄 = re.compile(r"(?i)(?:없음|없습니다|않았|않습니다|아닐 수|\b0\s*건|[:=]\s*(?:false|none|no|0)\b|성공|완료|\bok\b)")


def 사장님몫_볼글(글: str) -> str:
    """사장님 몫(열쇠 · 로그인 · 결제 · 사람 확인 퍼즐) 모양을 댈 글 — 스크립트 원문 칸과 부정 · 완료 줄을 뺀다.
    실패카드 장치(사장님몫_원문_찾기)도 이 함수를 빌려 같은 글을 본다."""
    남김, 원문칸 = [], False
    for 줄 in (글 or "").splitlines():
        if "##[group]Run" in 줄:
            원문칸 = True
            continue
        if 원문칸:
            if "##[endgroup]" in 줄:
                원문칸 = False
            continue
        if _부정줄.search(줄):
            continue
        남김.append(줄)
    return "\n".join(남김)


def _검색구간(로그: str) -> str:
    """원인을 찾을 구간을 좁힌다.

    ★마지막 traceback 이후만 본다 (독립검토 H-1). 로그 앞쪽에는 `pip install` 의
      '(401 kB)' 나 '재시도 1/3 ConnectionReset → 성공' 같은 **이미 복구된 잡음**이
      깔려 있다. 그걸 같이 보면 진짜 코드 버그가 '연결 끊김 · 저절로 풉니다' 로 덮인다.
    """
    꼬리 = 로그[-60000:]
    자리 = 꼬리.rfind("Traceback (most recent call last)")
    return 꼬리[자리:] if 자리 >= 0 else 꼬리


def _가장_늦게_걸린_패턴(글: str, 이름들=None):
    """사전 순서가 아니라 **로그에서 제일 늦게 나온** 패턴을 고른다.

    사전 순서로 첫 매치를 쓰면, 1순위인 '연결 끊김' 이 로그 앞쪽에서 걸려
    뒤에 있는 진짜 원인(코드 버그 등)을 이긴다. 실패는 대개 마지막에 있다.
    이름들 = 이 이름의 원인만 본다(없으면 전부 · 실패카드 장치는 한 인자로 부른다).
    """
    최고 = None
    for 패턴, 이름, 안내 in 원인사전:
        if 이름들 is not None and 이름 not in 이름들:
            continue
        늦은 = None
        for m in re.finditer(패턴, 글):
            늦은 = m.start()
        if 늦은 is not None and (최고 is None or 늦은 > 최고[2]):
            최고 = (이름, 안내, 늦은)
    return 최고


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
    # 차단 스위치 — 문구가 아니라 맥락으로만 막는다(2026-09-04).
    if os.environ.get("GOYU_NOTIFY_OFF") == "1":
        print("[자가치유] 경보 꺼짐(GOYU_NOTIFY_OFF) — 안 보냄")
        return False
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return False
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


def _워크플로_파일() -> str:
    """이 실행이 어느 워크플로 파일인가. 없으면 빈 문자열."""
    wf = os.environ.get("WORKFLOW_FILE", "") or os.environ.get("GITHUB_WORKFLOW_REF", "")
    if "/" in wf:                       # 'owner/repo/.github/workflows/x.yml@refs/…'
        wf = wf.split("@")[0].split("/")[-1]
    return wf.strip()


def _워크플로가_밝힌_한계분(파일이름: str = "") -> int:
    """워크플로 파일에서 `timeout-minutes:` 를 **직접 읽는다**. 못 읽으면 0.

    ★왜 파일을 직접 읽나 (2026-09-03)
      전에는 워크플로가 `TIMEOUT_MIN` 을 env 로 **한 번 더 적어 줘야만** 했다.
      그런데 그 값을 적어 둔 곳은 넷뿐이었고, 정작 5시간짜리 `cafe-auto-collect`
      에는 없었다. 5시간을 채우고 잘리면 아래 취소 갈래가 '한계 미지정'으로
      **조용히 넘어간다** — 2026-08-12 자동수집이 4연속 잘려 20시간 침묵한 그
      사고와 같은 자리인데, 그때 만든 방어가 정작 그 워크플로에 안 붙어 있었다.
      값을 두 벌 적게 하면 다음에 또 빠뜨린다. 선언한 자리에서 읽는다.

    ★여러 job 이 각각 한계를 적었으면 **가장 작은 값**을 쓴다. 크게 잡으면
      '경과가 한계에 못 미친다 → 사람 취소로 보고 침묵' 쪽으로 기운다 —
      이 저장소에서 침묵은 헛울림보다 나쁘다.
    """
    파일이름 = 파일이름 or _워크플로_파일()
    if not 파일이름:
        return 0
    후보 = []
    여기 = os.path.dirname(os.path.abspath(__file__))
    # ★**내 옆에 있는 것을 먼저 본다** (2026-09-04 실측으로 순서를 바꿈).
    #   전에는 `GITHUB_WORKSPACE` 를 맨 앞에 뒀다. 그러면 이 코드가 **딴 자리에서
    #   돌 때** 자기 옆의 워크플로가 아니라 원래 체크아웃의 것을 읽는다 —
    #   즉 **지금 도는 코드와 다른 나무를 재는 것**이다.
    #   되돌려보기(사본에서 timeout-minutes 를 지우고 검사)가 CI 에서만 통과하는
    #   것을 파고들다 찾았다: 사본에서 지웠는데 이 함수는 원래 체크아웃을 읽어
    #   15분이라고 답했다. 사본 실험이 아니어도, 같은 저장소를 두 자리에 두고
    #   돌리는 순간 같은 착각이 난다.
    #   보통 CI 에서는 둘이 같은 자리라 달라지는 것이 없다.
    for 뿌리 in (os.path.dirname(여기), 여기,
                os.environ.get("GITHUB_WORKSPACE", ""),
                os.getcwd(), os.path.dirname(os.getcwd())):
        if 뿌리:
            후보.append(os.path.join(뿌리, ".github", "workflows", 파일이름))
    # ★**찾은 첫 파일에서 끝낸다** (2026-09-04 실측으로 고침).
    #   전에는 값이 없으면 다음 후보로 넘어갔다. 그러면 '이 워크플로가 한계를
    #   안 밝혔다' 와 '여기엔 그 파일이 없다' 가 똑같아 보여서, **딴 나무의 숫자**를
    #   이 워크플로의 한계라고 답한다. 실측: 사본에서 timeout-minutes 를 지웠는데
    #   원래 체크아웃(GITHUB_WORKSPACE)의 값 15를 돌려줬다.
    #   그러면 한계를 안 밝힌 워크플로가 '밝힌 것'처럼 보여 잘림 판정이 어긋난다.
    #   '없다' 와 '못 찾았다' 를 뭉개지 않는다 — 파일을 찾았으면 그 파일이 답이다.
    for p in 후보:
        try:
            raw = open(p, encoding="utf-8").read()
        except Exception:
            continue                     # 여기엔 그 파일이 없다 → 다음 자리를 본다
        본문 = "\n".join(줄 for 줄 in raw.splitlines()
                       if not 줄.lstrip().startswith("#"))
        값들 = [int(x) for x in
               re.findall(r"^\s*timeout-minutes:\s*['\"]?(\d+)", 본문, re.M)]
        return min(값들) if 값들 else 0   # 찾았으면 이 파일이 답이다(안 밝혔으면 0)
    return 0


def _시간한계분() -> int:
    """이 워크플로의 시간 한계(분). 없으면 0 = 취소를 조용히 둔다.

    env `TIMEOUT_MIN` 을 먼저 본다(옛 워크플로가 적어 둔 것을 그대로 인정한다).
    없으면 워크플로 파일의 `timeout-minutes:` 를 직접 읽는다.
    """
    try:
        env값 = int(os.environ.get("TIMEOUT_MIN", "").strip() or 0)
    except ValueError:
        env값 = 0
    if env값 > 0:
        return env값
    return _워크플로가_밝힌_한계분()


def _경과분(저장소: str, run: str):
    """이 run 이 몇 분 돌았나. 못 재면 None — 한계가 밝혀진 워크플로에선 알리는 쪽으로 기운다."""
    데이터 = _api(f"/repos/{저장소}/actions/runs/{run}") if 저장소 and run else None
    if not isinstance(데이터, dict):
        return None
    from datetime import datetime, timezone
    try:
        시작 = datetime.strptime(str(데이터.get("run_started_at")),
                               "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - 시작).total_seconds() / 60.0


def _한국날(시각: str):
    """ISO 시각(…Z) → 한국 날짜. 못 읽으면 None."""
    from datetime import datetime, timedelta, timezone
    try:
        t = datetime.strptime(str(시각), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return t.astimezone(timezone(timedelta(hours=9))).date()


def 알릴차례인가(연속: int, 직전실패시각: str = "", 지금=None) -> bool:
    """지속 실패 때 알림이 폭주하지 않게 (독립검토 H-3) — 그러나 **영영 조용해지지도 않게**.

    telegram-qa 는 5분마다 돈다. 쿨다운이 없으면 고장난 하루에 **288통**이 가고,
    그러면 사장님이 알림을 꺼버려 원래 경보까지 안 보게 된다.

    ★2026-10-21 고침 — 전에는 '처음 3회 + 12의 배수'였다. 그런데 셈이 31 에서 멈추는
      바람에(30개 한 장만 물었다) 31은 영영 차례가 아니었고, margin-guard 는 정기
      144회가 실패하는 동안 알림이 한 통도 안 갔다. 횟수로 정하면 셈이 틀리는 순간
      같이 틀린다. 그래서 네 번째부터는 **날짜**로 정한다:
        처음 3회는 매번 / 그 뒤로는 **그날(한국 시각) 첫 실패에서만** = 하루 한 통.
      직전 실패 시각을 모르면 **보낸다** — 횟수 규칙으로 떨어지면 셈이 상한에 걸릴 때
      또 영영 조용해진다(GPT 검토 10-21). 한 통 더 가는 것이 침묵보다 낫다.
    """
    if 연속 <= 사람확인_임계:
        return True
    직전날 = _한국날(직전실패시각)
    if 직전날 is None:
        return True
    from datetime import datetime, timedelta, timezone
    지금 = 지금 or datetime.now(timezone.utc)
    오늘 = 지금.astimezone(timezone(timedelta(hours=9))).date()
    return 직전날 < 오늘


def 문장_만들기(이름, 결과, 연속, 원인, 안내, 증거, 링크, 재시도, 이상=False, 못셈=False, 이슈=True) -> str:
    if 결과 != "failure":
        return (f"✅ {이름} 복구됨\n"
                f"실패하던 자동 작업이 방금 정상으로 돌아왔습니다.\n"
                f"이제 따로 하실 일은 없습니다.")
    횟수 = f"{연속}회 이상" if 이상 else f"{연속}회"
    머리 = (f"🚨 {이름} 실패(연속 몇 번째인지 못 셌습니다 — GitHub 조회 실패)" if 못셈
            else f"🚨 {이름} 실패" if 연속 <= 1
            else f"🚨 {이름} {횟수} 연속 실패")
    줄 = [머리, f"원인: {원인}"]
    if 증거:
        줄.append(f"기록: {증거}")
    줄.append(안내)
    if 연속 >= 사람확인_임계:
        줄.append(f"\n⚠️ {횟수} 연속입니다 — 저절로 풀리는 문제가 아닙니다.\n"
                  + ("확인용 이슈를 열어뒀습니다(아래 링크)." if 이슈 else
                     "확인용 이슈는 열지 못했습니다(권한이 없거나 GitHub 조회 실패) — 아래 로그를 봐 주세요."))
        if 연속 > 사람확인_임계:
            줄.append("같은 실패가 이어지는 동안 이 문자는 하루 한 번만 보냅니다.")
    elif 재시도:
        # ★2026-11-01: '결과도 알려드릴게요'를 뺐다 — 복구 소식은 문자로 안 보낸다(10-21부터).
        줄.append(f"\n자동으로 {재시도} 다시 시도합니다.")
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

    저장소 = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    워크플로 = _워크플로_파일()
    링크 = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
          f"{저장소}/actions/runs/{run}") if 저장소 and run else ""

    if 결과 == "cancelled":
        # ★'취소'에는 두 얼굴이 있다(2026-08-20 실사고 교훈):
        #   사람이 누른 취소·새 run 이 옛 run 을 밀어낸 취소(telegram-qa)는 조용한 게 맞지만,
        #   **시간 한계를 다 채우고 잘린 취소는 고장**이다. GitHub 이 둘 다 'cancelled' 로
        #   적는 바람에 경쟁사-댓글 수집이 7/29~8/16 매일 밤 시간 초과로 죽는데 알림이
        #   0통이었다(카외 리포트도 8/19 저녁 같은 경로로 침묵). 침묵 조건을 넓히지 않는다 —
        #   워크플로가 TIMEOUT_MIN 을 밝힌 경우, 경과가 한계에 닿았으면(또는 못 쟀으면) 알린다.
        분한계 = _시간한계분()
        if 분한계 <= 0:
            print("[자가치유] 취소된 run — 시간 한계 미지정(TIMEOUT_MIN 없음), 알리지 않음")
            return 0
        경과 = _경과분(저장소, run)
        if 경과 is not None and 경과 < 분한계 - 2:
            print(f"[자가치유] 취소된 run(경과 {경과:.0f}분 < 한계 {분한계}분) "
                  f"— 사람 취소로 보고 알리지 않음")
            return 0
        # ★2026-11-01 알림 새 기준(판정표 B2): 시간 초과 잘림은 사장님 몫이 아니다(양이 늘었는지 · 어디서
        #   느려졌는지는 맥가이버가 볼 일) — 문자를 보내지 않는다. 실패카드 장치가 '한계를 채우고 잘린 취소'를
        #   실패로 세어 카드를 낸다. 옛 문자는 되살릴 수 있게 아래 주석으로 남긴다.
        print(f"::warning::[자가치유] {a.이름} 시간 한계({분한계}분)를 채우고 잘림 — 오늘치가 다 처리되지 못했습니다")
        print("[자가치유] 시간 초과 잘림 — 사장님 문자 안 보냄(알림 새 기준) · "
              "실패카드 장치가 이 실행을 읽어 고침 카드를 냅니다" + (f" · 로그: {링크}" if 링크 else ""))
        # 텔레그램(f"⏱ {a.이름} 시간 초과로 강제 종료"
        #       f"\n예정 한계({분한계}분)를 채우고 잘렸습니다 — 오늘치가 다 처리되지 못했습니다."
        #       f"\n양이 늘었는지 확인이 필요합니다. 다음 예정 회차에 자동으로 다시 시도합니다."
        #       + (f"\n로그: {링크}" if 링크 else ""))
        return 0

    if 결과 == "failure":
        셈 = 연속실패_재기(저장소, 워크플로, run, 결과)
        연속 = 셈["연속"]
        횟수 = ("몇 회인지 못 셈(GitHub 조회 실패)" if 셈.get("못셈")
                else f"{연속}회 이상" if 셈["이상"] else f"{연속}회")
        # ★이 줄은 다음 회차 로그에서 '셈이 맞게 도는지' 확인하는 자리다 — 지우지 않는다.
        print(f"[자가치유] 연속 실패 {횟수} "
              f"(같은 종류 실행만 셈: {os.environ.get('GITHUB_EVENT_NAME') or '전부'})")
        원인, 안내, 증거 = 실패로그_원인(저장소, run)
        차례 = 알릴차례인가(연속, 셈["직전실패시각"])
        이슈url = ""
        if 연속 >= 사람확인_임계 and 차례:
            이슈url = 이슈_열기(저장소, a.이름, 연속, 원인, 안내, 증거, 링크)
        # ★2026-11-01 알림 새 기준(판정표 B2): 사장님께는 사장님 몫(열쇠 · 로그인 · 결제)만 보낸다.
        #   그 밖의 실패는 문자 0 — 실패카드 장치가 이 실행을 읽어 연속 2번째부터 맥가이버 고침 카드를 낸다.
        #   (예전 '검사만 실패하는 작업 → 아침 건강 보고' 갈래도 여기 들어온다 — 11-01 아침 보고는 고장 줄을
        #   사장님께 안 싣는다. 대신 그 작업도 사장님 몫이면 문자가 간다: 장치가 카드를 안 내기 때문이다.)
        if not 사장님몫인가(원인):
            print(f"[자가치유] 직원 몫 실패(원인: {원인}) — 사장님 문자 안 보냄(알림 새 기준) · "
                  f"실패카드 장치가 이 실행을 읽어 고침 카드를 냅니다")
            return 0
        # ★GPT 검토 2(11-01): '하루 한 통'은 직전 실패가 문자를 보냈다고 보고 거른다. 그런데 직전 실패가 직원 몫이었으면
        #   문자는 0통이었다 — 오늘 첫 사장님 몫 실패를 '이미 알렸다'로 삼키게 된다. 직전 실패의 원인을 다시 읽어
        #   직원 몫이었으면(또는 못 읽었으면) 보낸다. 한 통 더 가는 것이 침묵보다 낫다 — 이 파일의 원칙.
        if not 차례 and 셈.get("직전실패id"):
            직전원인 = 실패로그_원인(저장소, 셈["직전실패id"])[0]
            if not 사장님몫인가(직전원인):
                차례 = True
                print(f"[자가치유] 직전 실패는 직원 몫이었음(원인: {직전원인}) — 문자를 안 보냈으므로 이번에 보냄")
        print(f"[자가치유] 사장님 몫 실패(원인: {원인}) — 사장님께 알릴 차례: {'예' if 차례 else '아니오(하루 한 통)'}")
        if 차례:
            문장 = 문장_만들기(a.이름, 결과, 연속, 원인, 안내, 증거,
                           이슈url or 링크, 다음_재시도(a.크론), 이상=셈["이상"],
                           못셈=셈.get("못셈"), 이슈=bool(이슈url))
            텔레그램(문장)
        else:
            print(f"[자가치유] {횟수} 연속 — 오늘은 이미 알렸습니다(하루 한 통)")
        return 0

    # 성공 — 직전이 실패였을 때만 '복구됨'. 평소 성공은 조용히(스팸 방지).
    # ★2026-10-21: '복구됐습니다'는 문자로 보내지 않는다(사장님 "이상한 보고가 너무 많아
    #   진짜"). 하실 일이 없는 소식이라 다음 아침 건강 보고가 한 줄로 싣는다
    #   (cafe-external/아침보고_작업상태.py 의 '다시 정상으로 돌아온 작업').
    직전 = 직전이_실패였나(저장소, 워크플로, run)
    if 직전 is None:
        # ★조용히 '평소 성공' 이라고 말하지 않는다(2026-08-24). 못 본 것은 못 본 것이다.
        #   이 단계는 보고용이라 run 을 빨갛게 만들지 않는다 — 대신 GitHub 요약에
        #   경고로 남겨 다음에 보는 사람이 알아채게 한다.
        print("::warning::[자가치유] 직전 회차를 확인하지 못했습니다(GitHub 조회 실패) "
              "— 직전이 실패였다면 확인용 이슈가 안 닫혔을 수 있습니다")
        print("[자가치유] 직전 회차 확인 실패 — 알림 판단을 못 했습니다")
    elif 직전:
        print(f"[자가치유] {a.이름} 복구됨 — 문자 대신 다음 아침 건강 보고에 한 줄로 갑니다")
        이슈_닫기(저장소, a.이름)
    else:
        print("[자가치유] 평소 성공 — 알리지 않음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
