# -*- coding: utf-8 -*-
"""댓글 원문 → 경쟁 제품 브랜드명. **AI 가 원문을 직접 읽는다.**

왜 갈아엎었나 (2026-07-24 사장님: "다 갈아엎고 다시 만들어. 문제가 있다 지금")
--------------------------------------------------------------------------------
전 구조는 **글자 규칙이 후보를 뽑고, AI 는 O/X 만** 했다. 그래서 두 방향으로 틀렸다.
  · 진짜가 빠졌다 — '안티트로' 는 댓글에 4번 나왔는데 AI 가 '제품 아님' 으로 지웠다.
  · 가짜가 들어왔다 — '닥터그루트' 가 '터그루트' 로 잘려 나가도 O/X 로는 못 고친다.
    '로마' '태열베개' '크리케' 같은 조각도 그렇게 표에 올랐다.

지금은 AI 가 댓글 원문을 읽고 **이름을 직접 뽑는다**. 잘림이 없고, 흐트러뜨린 표기도
문맥으로 되살린다. 뽑은 이름은 shop_probe 가 실제로 검색되는지 확인한다 —
잘린 이름은 검색이 안 되기 때문이다(실측: '터그루트' 신호 2 · '안티트로' 42).

두 관문이 서로의 약점을 메운다:
  AI 혼자 → 안티트로를 지운다 / 잘린 이름을 통과시킨다
  검색 혼자 → 문맥을 모른다 / 일반어도 신호가 높다
  둘 다   → 실측에서 30종 중 '터그루트'·'오프온' 만 걸러지고 나머지 26종은 정상 통과
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

_HANGUL = re.compile(r"[^가-힣]")


def _hangul(s) -> str:
    return _HANGUL.sub("", str(s or ""))


def grounded(name: str, text: str, *, min_ratio: float = 0.6) -> bool:
    """AI 가 뽑은 이름이 **실제로 그 댓글 글자에 있나** — 환각 거르기.

    ★2026-07-24 실측에서 드러난 구멍: 검색 확인만으론 못 잡는다.
    AI 가 '안ㅌ티트로' 를 읽다가 아는 브랜드 '아로마티카' 를 연상해 뽑으면,
    아로마티카는 실제 팔리는 제품이라 검색을 통과한다. 그런데 그 댓글엔 없었다
    ('려'←맥단비 · '고루트'←브랜드없음 · '진생화'←브랜드없음 도 같은 환각).
    → 이름의 한글 글자가 원문에 순서대로(흐트러뜨림 허용) min_ratio 이상 나올 때만 인정.
    '맥단비' 는 '맥단ㅂI' 에서 '맥''단' 이 잡혀 통과, '아로마티카' 는 원문에 없어 탈락.
    """
    n = _hangul(name)
    if len(n) < 2:
        return False                    # 한 글자 이름은 우연히 맞을 위험이 커 버린다
    t = _hangul(text)
    # 짧은 이름(2~3글자)은 흔한 음절이 흩어져 우연히 걸린다('바이오'가 '바쁜데…오래' 에
    # subsequence 로 매칭). 그래서 **연속된 2글자 조각**이 원문에 그대로 있을 때만 인정한다
    # ('맥단비'→'맥단' 있음 통과, '바이오'→무관 댓글엔 '바이'·'이오' 없음 탈락. 독립검토 MINOR).
    if len(n) <= 3:
        return any(n[i:i + 2] in t for i in range(len(n) - 1))
    맞음, i = 0, 0
    for ch in n:
        j = t.find(ch, i)
        if j >= 0:
            맞음 += 1
            i = j + 1
    return 맞음 / len(n) >= min_ratio

# 판정기는 OpenAI 규격이면 무엇이든 꽂힌다(Groq·OpenAI 둘 다 이 규격).
# ★라이브 경로는 comment_brand_llm._call 을 쓴다(2026-07-30 통일) — 모델 선택도
#   src/llm_pick 하나로 간다. 아래 _MODEL·_post 는 옛 직접 호출 잔재로, 새로 쓰지 말 것.
_BASE_URL = os.environ.get(
    "GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 한 번에 읽힐 댓글 수. 댓글이 길어 너무 크게 잡으면 답이 잘린다.
BATCH = 20

SYSTEM = (
    "너는 네이버 카페 댓글을 읽고 **그 댓글이 언급한 실제 판매 제품의 브랜드명**을 뽑는다.\n"
    "우리가 찾는 것은 두피·모발·바디 관련 제품이다(샴푸·트리트먼트·토닉·바디워시·바디로션·"
    "두피 앰플 등). 그 밖의 제품(식품·가전·화장품 일반 등)은 뽑지 않는다.\n"
    "규칙:\n"
    "1. 상점에서 그 이름으로 살 수 있는 제품만. 증상·성분·장소·일반명사는 뽑지 않는다.\n"
    "   (지루성·비듬·각질·어성초·약국·병원·피부과·올리브영·공홈 → 뽑지 않음)\n"
    "2. 검열을 피하려 글자를 흐트러뜨린 이름이 많다(안ㅌ티트로, 맥단ㅂI, 뽀.ㅇ얀).\n"
    "   **원래 브랜드명으로 되살려서** 적는다. 되살릴 수 없으면 뽑지 않는다.\n"
    "3. 브랜드까지만 적는다. 제품 종류는 뺀다('맥단비 탈모샴푸' → '맥단비').\n"
    "4. **이름을 자르지 마라.** '닥터그루트' 를 '터그루트' 로 적으면 안 된다.\n"
    "   앞글자가 잘린 것 같으면 아예 뽑지 않는다.\n"
    "5. 확실하지 않으면 뽑지 않는다. 지어내지 마라.\n"
    "6. 제품 언급이 없는 댓글은 빈 배열.\n"
    '출력은 JSON 만: {"결과":[{"n":1,"제품":["안티트로"]},{"n":2,"제품":[]}]}\n'
    "다른 말은 절대 하지 않는다."
)


def _api_key() -> str:
    """★2026-09-04 검수 지적 #11 — 씻는 코드를 만들어 놓고 정작 여기가 안 썼다.

    여기가 댓글을 실제로 읽는 본 경로다. 열쇠 씻는 규칙은 comment_brand_llm
    한 곳에만 두고 쓰는 쪽이 그것을 부른다([[feedback_one-rule-one-place]]).
    """
    from src.comment_brand_llm import _열쇠씻기
    return _열쇠씻기(os.environ.get("GROQ_API_KEY", ""))


def _post(payload: dict, *, timeout: int, tries: int = 3, sleep=time.sleep,
          errors: list | None = None):
    def note(reason: str):
        if errors is not None:
            errors.append(reason)

    body = json.dumps(payload).encode("utf-8")
    for attempt in range(tries):
        req = urllib.request.Request(
            _BASE_URL, data=body,
            headers={"Authorization": f"Bearer {_api_key()}",
                     "Content-Type": "application/json", "User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            note(f"HTTP {e.code}")
            if e.code == 429 and attempt < tries - 1:
                wait = 5.0
                try:
                    wait = float(e.headers.get("retry-after") or 5.0)
                except (TypeError, ValueError):
                    pass
                sleep(min(wait, 60.0))
                continue
            return None
        except (urllib.error.URLError, ValueError, TimeoutError, OSError):
            if attempt < tries - 1:
                sleep(2.0 * (attempt + 1))
                continue
            return None
    return None


def _read_json(content: str):
    s = str(content or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        s = s.strip()
    if s.startswith("json"):
        s = s[4:].strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        pass
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


def read_batch(texts: list, *, timeout: int = 60, sleep=time.sleep,
               errors: list | None = None) -> dict | None:
    """댓글 묶음 → {댓글 번호(0부터): [브랜드명]}. 실패하면 None(판정 안 함)."""
    texts = [str(t or "").strip() for t in (texts or [])]
    texts = [t for t in texts if t]
    if not texts:
        return {}
    # ★2026-07-30: 이름 뽑기만 Groq 전용이었다 — 판정·이름묶기(comment_brand_llm)는
    #   '무료 먼저, 막히면 유료 보험' 인데 첫 단계인 여기가 Groq 하나에 매달려 있으면
    #   Groq 가 막힌 날(7/23 실측: 4번 중 2번) 파이프라인 전체가 빈손이 된다.
    #   같은 _call 로 통일한다(일이관지).
    from . import comment_brand_llm as _llm
    if not (_api_key() or _llm._api_key()):
        if errors is not None:
            errors.append("키 없음")
        return None

    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    content, truncated = _llm._call(SYSTEM, lines, max_tokens=2000,
                                    timeout=timeout, sleep=sleep, errors=errors)
    if not content:
        return None
    if truncated and errors is not None:
        errors.append("답 잘림")          # 그래도 읽히는 만큼은 아래에서 건진다
    obj = _read_json(content)
    rows = obj.get("결과") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        if errors is not None:
            errors.append("JSON 아님")
        return None

    out: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(texts):
            continue
        # ★뽑은 이름이 실제로 그 댓글 글자에 있는 것만 남긴다 — AI 환각 거르기.
        names = [str(x).strip() for x in (r.get("제품") or []) if str(x).strip()
                 and grounded(str(x).strip(), texts[n - 1])]
        if names:
            out[n - 1] = names
    return out


def 한도인가(사유들) -> bool:
    """이 실패가 '잠깐 기다려'(한도)인가, '영영 안 됨'(고장)인가.

    ★2026-09-04 실사고: 차단기가 둘을 똑같이 셌다. 429 는 분 단위로 풀리는데
    5번 만에 그날을 접어, 댓글 16,379건 중 하루에 10묶음밖에 못 읽었다.
    """
    return any("429" in str(x) or "한도" in str(x) for x in (사유들 or []))


def read_all(texts: list, *, batch: int = BATCH, timeout: int = 60,
             sleep=time.sleep, max_batches: int | None = None,
             max_consecutive_fail: int = 5,
             max_한도대기: int = 20) -> tuple:
    """댓글 전체 → ({댓글 index: [브랜드명]}, 통계). 못 읽은 묶음은 통계에 남긴다.

    ★멈출 줄 안다 (2026-08-20):
      · max_batches — 한 회차가 부를 수 있는 묶음 수. 넘치면 멈춘다.
        (남은 몫은 comment_reads 캐시 덕에 다음 회차가 이어 읽는다)
      · 연속 실패 차단 — 8/19 실사고: 퇴역 모델 404 로 1,304묶음을 전부
        헛호출하며 2시간을 태웠다. 연속 5묶음 실패면 그날은 접는다.
    안 부른 몫도 '못 읽은 묶음'에 넣는다 — should_skip_write 가
    반쪽 표를 막는 잣대가 이 수라서, 정직하게 세야 시트가 안전하다.
    통계에 '읽은자리'(성공한 댓글 index 집합)를 얹는다 — 빈 결과와 실패를
    가르는 유일한 근거라, 캐시가 이걸 보고 '읽음'만 남긴다.
    """
    texts = list(texts or [])
    stat = {"댓글": len(texts), "묶음": 0, "못읽은묶음": 0, "탈": [], "예산사용": 0}
    전체묶음 = (len(texts) + batch - 1) // batch if batch else 0
    out: dict = {}
    읽은자리: set = set()
    errors: list = []
    연속실패 = 0          # 진짜 고장(다시 해도 안 됨)
    한도대기 = 0          # 기다리면 풀리는 것
    중단 = ""
    for start in range(0, len(texts), batch):
        if max_batches is not None and stat["예산사용"] >= max_batches:
            중단 = "회차 예산 소진"
            break
        if 연속실패 >= max_consecutive_fail:
            중단 = f"연속 {max_consecutive_fail}묶음 실패"
            break
        if 한도대기 >= max_한도대기:
            중단 = f"한도에 {max_한도대기}번 걸림"
            break
        chunk = texts[start:start + batch]
        stat["묶음"] += 1
        stat["예산사용"] += 1
        앞사유 = len(errors)
        got = read_batch(chunk, timeout=timeout, sleep=sleep, errors=errors)
        if got is None:
            stat["못읽은묶음"] += 1
            새사유 = errors[앞사유:]
            if 한도인가(새사유):
                # 기다리면 풀린다 — 고장으로 세지 않고, 점점 더 오래 쉰다.
                한도대기 += 1
                sleep(min(10.0 * 한도대기, 60.0))
            else:
                연속실패 += 1
            continue
        연속실패 = 한도대기 = 0
        읽은자리.update(range(start, start + len(chunk)))   # 빈 결과도 '읽은 자리'다
        for i, names in got.items():
            out[start + i] = names
    if 중단:
        남은 = 전체묶음 - stat["묶음"]
        stat["묶음"] += 남은
        stat["못읽은묶음"] += 남은
        errors.append(f"{중단} — 남은 {남은}묶음은 다음 회차에")
    stat["탈"] = sorted(set(errors))
    stat["뽑은이름"] = len({n for names in out.values() for n in names})
    stat["읽은자리"] = 읽은자리
    return out, stat
