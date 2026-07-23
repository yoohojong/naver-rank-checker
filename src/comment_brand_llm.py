# -*- coding: utf-8 -*-
"""댓글 → 경쟁 제품명 판정 (Groq 무료 LLM).

왜 규칙만으로 안 되나 (2026-07-23 실측)
---------------------------------------
"공홈 들어가서 구매하면" → '들어가서' 를 제품으로,
"동네 약국에서 추천해줘서" → '약국에서' 를 제품으로 집었다.
한국어 활용형과 제품 이름을 글자 규칙으로 가르는 데는 한계가 있다.
반대로 사람은 한 줄만 봐도 안다 → 판정만 언어모델에 맡긴다.

역할 분담
- 규칙(comment_brand.py): 어느 댓글을 볼지 고르고(티키타카), 흐트러뜨린 글자를 정리한다.
- 이 모듈: "이 댓글에 제품 브랜드가 있나, 있다면 무엇인가" 만 판정한다.

안전
- 키 없거나 실패하면 None → 호출부가 규칙 결과로 폴백(멈추지 않는다).
- 보내는 것은 댓글 글자뿐. 시트·순위 데이터는 보내지 않는다.
- **없으면 없다고 하게** 지시한다(지어내기 금지 — 이 프로젝트 원칙).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE_URL = os.environ.get(
    "GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_SYSTEM = (
    "너는 네이버 카페 댓글에서 **판매되는 제품의 브랜드·제품명만** 골라내는 추출기다.\n"
    "규칙:\n"
    "1. 상품으로 팔리는 이름만 뽑는다. 브랜드명·제품명 그대로.\n"
    "2. 다음은 제품이 아니다 — 절대 뽑지 마라:\n"
    "   · 일반 명사: 샴푸, 탈모샴푸, 비듬샴푸, 두피, 각질, 트리트먼트\n"
    "   · 증상·성분: 지루성, 비듬, 어성초, 카페인, 맥주효모, 살리실산\n"
    "   · 장소·기관: 약국, 병원, 피부과, 대학병원, 공홈, 올리브영\n"
    "   · 동사·부사 활용형: 들어가서, 추천해줘서, 꾸준히, 정착해서, 바꿔가며\n"
    "3. 글자 사이에 영문·자음을 끼워 검열을 피한 이름이 많다. 그것도 제품이다.\n"
    "   ★ **사람이 읽는 원래 브랜드명으로 되살려서** 적어라:\n"
    "     '맥단ㅂI' → '맥단비'   ('ㅂ'+'I' 는 '비')\n"
    "     '모zi젠 펩ㅋㅏ놀' → '모지젠 펩카놀'   ('zi'는 '지', 'ㅋ'+'ㅏ'는 '카')\n"
    "     'ㅃ얀샴푸' → '뽀얀'   ·   '뽀.ㅇ얀' → '뽀얀'\n"
    "   되살릴 수 없으면 적힌 그대로 둔다.\n"
    "4. **브랜드까지만** 적는다. 제품 종류는 빼라:\n"
    "     '맥단비 탈모샴푸' → '맥단비'   ·   '아윤채샴푸' → '아윤채'\n"
    "     '닥터그루트샴푸' → '닥터그루트'   ·   '일리윤 바디워시' → '일리윤'\n"
    "5. 확실하지 않으면 뽑지 않는다. 없으면 빈 배열.\n"
    '출력은 JSON 만: {"products": ["맥단비", "모지젠 펩카놀"]}\n'
    "다른 말은 절대 하지 않는다."
)


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


def extract(comment_texts: list, *, timeout: int = 20) -> list | None:
    """댓글 여러 줄 → 제품명 목록. 키 없거나 실패하면 None(폴백 신호).

    한 번에 여러 줄을 보내 호출 수를 줄인다(무료 한도 절약).
    """
    key = _api_key()
    if not key:
        return None
    lines = [str(t or "").replace("\n", " ").strip()[:300] for t in (comment_texts or []) if t]
    if not lines:
        return []
    joined = "\n".join(f"{i+1}. {t}" for i, t in enumerate(lines[:20]))

    body = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": "다음 댓글들에서 제품명을 뽑아줘.\n" + joined},
        ],
        "temperature": 0,
        "max_tokens": 400,
    }).encode("utf-8")

    req = urllib.request.Request(
        _BASE_URL, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    obj = _extract_json(content)
    if not isinstance(obj, dict):
        return None
    products = obj.get("products")
    if not isinstance(products, list):
        return None
    return [str(p).strip() for p in products if str(p).strip()]
