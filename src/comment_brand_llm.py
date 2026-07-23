# -*- coding: utf-8 -*-
"""제품 후보 → "이게 진짜 팔리는 제품인가" 판정 (Groq 무료 LLM).

왜 규칙만으로 안 되나 (2026-07-23 실측)
---------------------------------------
"공홈 들어가서 구매하면" → '들어가서' 를, "동네 약국에서 추천해줘서" → '약국에서' 를
제품으로 집었다. 한국어 활용형과 제품 이름을 글자 규칙으로 가르는 데는 한계가 있다.
반대로 사람은 한 줄만 봐도 안다 → 판정만 언어모델에 맡긴다.

역할 분담
- comment_brand.py : 어느 댓글을 볼지 고르고, 후보를 뽑고, 흐트러뜨린 글자를 정리한다.
- 이 모듈         : 후보 하나하나에 "제품이다/아니다" 를 매긴다. 판정 못 하면 **비운다**.

★댓글 통째로가 아니라 '후보 이름' 을 보낸다 (2026-07-23 재설계)
---------------------------------------------------------------
전에는 글마다 댓글 20줄을 통째로 보냈다. 키워드 400개 × 글 4개 = 1,600번 호출이라
Groq 무료 하루치(요청 1,000회 · 토큰 100,000)를 몇 분 만에 다 썼고, 그 뒤로는 전부
실패 → 옛 글자규칙으로 되돌아가 '약국에서' 같은 게 표를 채웠다.
지금은 **온 run 의 후보를 중복 없이 모아 이름만** 보낸다(한 번에 25개).
후보는 run 전체로도 수백 개라 호출이 몇 번으로 줄고, 판정 결과는 파일에 남아
다음 날엔 새로 나온 이름만 물어본다.

안전
- 실패·키 없음 = 그 후보는 '미판정'. 지어내지 않고, 호출부가 표에서 뺀다.
- 보내는 것은 후보 이름과 댓글 한 토막뿐. 시트·순위 데이터는 보내지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

_BASE_URL = os.environ.get(
    "GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 한 번에 물어볼 후보 수. 답이 길어지면 잘려서 묶음 통째로 미판정이 되므로 크게 잡지 않는다
# (25개로 돌렸더니 113종 중 67종이 답을 못 받았다 — 2026-07-23 실측).
BATCH = 12

_SYSTEM = (
    "너는 네이버 카페 댓글에서 나온 말이 **실제로 팔리는 제품의 브랜드명인지** 판정한다.\n"
    "각 항목은 '후보 | 그 말이 나온 댓글 토막' 형식이다.\n"
    "규칙:\n"
    "1. 상점·쇼핑몰에서 그 이름으로 살 수 있는 제품이면 제품이다.\n"
    "2. 다음은 제품이 아니다 (제품=false):\n"
    "   · 일반 명사·종류: 샴푸, 탈모샴푸, 비듬샴푸, 바디워시, 두피, 각질, 트리트먼트\n"
    "   · 증상·성분: 지루성, 비듬, 어성초, 카페인, 맥주효모, 살리실산\n"
    "   · 장소·기관·사람: 약국, 병원, 피부과, 대학병원, 공홈, 올리브영, 약사, 교수\n"
    "   · 동사·부사·문장 조각: 들어가서, 추천해줘서, 꾸준히, 정착해서, 있는데, 지금, 공감\n"
    "3. 글자 사이에 영문·자음을 끼워 검열을 피한 이름이 많다. 그것도 제품이다.\n"
    "   ★ **사람이 읽는 원래 브랜드명으로 되살려서** 이름 칸에 적어라:\n"
    "     '맥단ㅂI' → '맥단비'   ('ㅂ'+'I' 는 '비')\n"
    "     '모zi젠 펩ㅋㅏ놀' → '모지젠 펩카놀'   ('zi'는 '지', 'ㅋ'+'ㅏ'는 '카')\n"
    "     'ㅃ얀샴푸' → '뽀얀'   ·   '뽀.ㅇ얀' → '뽀얀'\n"
    "   되살릴 수 없으면 적힌 그대로 둔다.\n"
    "4. **브랜드까지만** 적는다. 제품 종류는 빼라:\n"
    "     '맥단비 탈모샴푸' → '맥단비'   ·   '아윤채샴푸' → '아윤채'\n"
    "     '닥터그루트샴푸' → '닥터그루트'   ·   '일리윤 바디워시' → '일리윤'\n"
    "5. 확실하지 않으면 제품=false. 지어내지 마라.\n"
    "6. 받은 번호 전부에 대해 답한다. 빠뜨리지 않는다.\n"
    "7. '후보' 칸에는 받은 후보를 **그대로 옮겨 적는다**(번호가 밀리지 않았는지 대조한다).\n"
    '출력은 JSON 만: {"판정": [{"n":1,"후보":"맥단ㅂI","제품":true,"이름":"맥단비"},'
    ' {"n":2,"후보":"약국에서","제품":false}]}\n'
    "다른 말은 절대 하지 않는다."
)


def _key(text) -> str:
    """대조용 글자만 남긴다 — 띄어쓰기·기호 차이로 어긋나지 않게."""
    return "".join(ch for ch in str(text or "") if ch.isalnum()).lower()


def _api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()


def available() -> bool:
    return bool(_api_key())


def _extract_json(content: str):
    s = str(content or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        s = s.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
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


_ONE_VERDICT_RE = re.compile(r"\{[^{}]*\"n\"\s*:\s*\d+[^{}]*\}")


def _salvage(content: str) -> list:
    """답이 중간에 잘려도 온전한 줄만 골라 읽는다 — 묶음 전체를 버리지 않으려고."""
    out = []
    for m in _ONE_VERDICT_RE.finditer(str(content or "")):
        try:
            v = json.loads(m.group(0))
        except (ValueError, TypeError):
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def _post(payload: dict, *, timeout: int, tries: int = 3, sleep=time.sleep,
          errors: list | None = None):
    """Groq 호출. 한도 초과(429)면 알려준 만큼 쉬었다 다시 — 조용히 포기하지 않는다.

    실패하면 왜 실패했는지 errors 에 남긴다. 안 남기면 다음에 또 깜깜이가 된다.
    """
    def note(reason: str):
        if errors is not None:
            errors.append(reason)

    key = _api_key()
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(tries):
        req = urllib.request.Request(
            _BASE_URL, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            note(f"HTTP {e.code}")
            if e.code == 429 and attempt < tries - 1:
                wait = 5.0
                try:                       # 얼마나 기다리라고 알려준다
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


def judge_batch(items: list, *, timeout: int = 30, sleep=time.sleep,
                errors: list | None = None) -> dict | None:
    """후보 묶음 하나 판정. {키: {"제품": bool, "이름": str}}. 실패하면 None.

    items = [{"키": ..., "표시": ..., "예시": 댓글토막}, ...]
    """
    def note(reason: str):
        if errors is not None:
            errors.append(reason)

    if not _api_key():
        note("키 없음")
        return None
    items = [i for i in (items or []) if i.get("키")]
    if not items:
        return {}

    lines = []
    for n, it in enumerate(items, 1):
        example = str(it.get("예시") or "").replace("\n", " ")[:80]
        lines.append(f"{n}. {it.get('표시') or it['키']} | {example}")

    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "각 후보가 제품인지 판정해줘.\n" + "\n".join(lines)},
        ],
        "temperature": 0,
        # 답이 잘리면 JSON 이 깨져 묶음 전체가 미판정이 된다 — 넉넉히 준다.
        "max_tokens": 4000,
    }
    data = _post(payload, timeout=timeout, sleep=sleep, errors=errors)
    if not data:
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        note("답 모양이 다름")
        return None
    if str((data.get("choices") or [{}])[0].get("finish_reason") or "") == "length":
        note("답 잘림")           # 그래도 아래에서 읽히는 만큼은 건진다

    obj = _extract_json(content)
    verdicts = obj.get("판정") if isinstance(obj, dict) else None
    if not isinstance(verdicts, list):
        verdicts = _salvage(content)       # 잘린 답에서도 읽히는 줄은 건진다
        if not verdicts:
            note("JSON 아님")
            return None
        note("부분만 읽음")

    # 번호가 한 칸 밀리면 '스테로이드' 가 옆 후보의 이름을 달고 제품이 된다(2026-07-23 실측).
    # 그래서 되돌려받은 '후보' 글자로 대조하고, 어긋나면 그 이름으로 다시 찾는다.
    by_echo = {_key(it.get("표시") or it["키"]): it for it in items}

    out: dict = {}
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        try:
            n = int(v.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(items):
            continue
        it = items[n - 1]
        echo = _key(v.get("후보"))
        if echo and echo != _key(it.get("표시") or it["키"]):
            it = by_echo.get(echo)
            if it is None:                 # 누구 얘긴지 모르겠으면 판정하지 않는다
                continue
        is_product = bool(v.get("제품"))
        name = str(v.get("이름") or "").strip() or it.get("표시") or it["키"]
        out[it["키"]] = {"제품": is_product, "이름": name if is_product else ""}
    return out


def judge(items: list, *, batch: int = BATCH, max_calls: int = 60,
          timeout: int = 30, sleep=time.sleep) -> tuple:
    """후보 전체 판정 → (판정 dict, 통계 dict).

    판정 못 받은 후보는 dict 에 **없다** — 호출부가 표에서 뺀다(지어내지 않는다).
    """
    stat = {"후보": len(items or []), "호출": 0, "판정": 0, "미판정": 0,
            "한도소진": False, "탈": []}
    if not _api_key():
        stat["미판정"] = stat["후보"]
        return {}, stat

    out: dict = {}
    errors: list = []
    pending = list(items or [])

    # 한 바퀴 돌고, 답을 못 받은 후보만 **작은 묶음**으로 한 번 더 묻는다.
    # 묶음이 크면 답이 잘려 통째로 미판정이 되기 때문(2026-07-23 실측 67/113).
    for size in (batch, max(5, batch // 3)):
        if not pending:
            break
        for start in range(0, len(pending), size):
            if stat["호출"] >= max_calls:
                stat["한도소진"] = True
                break
            chunk = pending[start:start + size]
            stat["호출"] += 1
            got = judge_batch(chunk, timeout=timeout, sleep=sleep, errors=errors)
            if got:
                out.update(got)
        pending = [it for it in pending if it["키"] not in out]

    stat["판정"] = len(out)
    stat["미판정"] = stat["후보"] - stat["판정"]
    stat["탈"] = sorted(set(errors))        # 왜 못 받았는지 — 다음엔 깜깜이로 두지 않는다
    return out, stat
