# -*- coding: utf-8 -*-
"""쓸 모델을 계정에 물어보고 고른다 — OpenAI 호환(chat/completions) 공용 관문.

★모델 이름을 코드에 박아두면 공급사가 그 모델을 내리는 날 조용히 404 가 난다.
  실제로 두 번 당했다:
    · 2026-07-23 발행본_검수 — 적어둔 llama-3.3-70b 가 계정에 없어 404
    · 2026-08-16 Groq 가 llama-3.3-70b-versatile 퇴역(공식 공지) → 경쟁사-댓글
      수집이 8/17~19 사흘 동안 1,304묶음 전부 404, 텔레그램 봇 자연어도 같이 죽음
  같은 실수 두 번이면 규칙이 아니라 관문을 만든다(2026-08-06 원칙) —
  "지금 무슨 모델이 있나"를 아는 곳은 여기 하나다. 각 파일에 이름을 적지 않는다.

쓰는 곳: comment_brand_llm(경쟁사 판정) · llm_intent(텔레그램 봇).
발행본_검수 는 제공사가 여럿(cerebras 포함)+복사 이식용 자립 파일이라 같은 원리를 자체 보유.

쓰는 법:
    model = llm_pick.pick(chat_url, api_key)      # 목록 조회 → 선호순 → 캐시
    ...호출이 HTTP 404 로 죽으면...
    llm_pick.forget(chat_url)                     # 캐시를 비우고
    model = llm_pick.pick(chat_url, api_key)      # 다시 골라 그 자리에서 이어간다
"""
from __future__ import annotations

import json
import urllib.request

# Groq 공식 후계(2026-08-16 llama-3.3-70b-versatile 퇴역 공지의 권고). 큰 모델부터.
DEFAULT = "openai/gpt-oss-120b"
PREFER = (
    "openai/gpt-oss-120b",          # 프로덕션 · 퇴역 공지의 1순위 권고
    "qwen/qwen3.6-27b",             # 퇴역 공지의 2순위 권고(프리뷰)
    "openai/gpt-oss-20b",           # 프로덕션 · 작은 쪽
    "llama-3.3-70b-versatile",      # 옛 기본 — 다른 계정·다른 제공사엔 남아 있을 수 있다
)

# 대화(chat)가 안 되는 모델 — '아무거나 첫 번째' 폴백이 이런 걸 집으면 400 만 난다.
# compound 는 대화는 되지만 웹검색·코드실행을 스스로 하는 별물이라 제외한다.
_NOT_CHAT = ("whisper", "tts", "guard", "orpheus", "embed", "moderation",
             "compound", "allam", "prompt")

# Groq 앞단 Cloudflare 가 기본 파이썬 시그니처를 403(error 1010)으로 막는다(2026-06-20 실측).
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_cache: dict = {}


def _tail(model_id) -> str:
    """제공사 경로를 뗀 꼬리 이름 — 'openai/gpt-oss-120b' 와 'groq/gpt-oss-120b' 는 같은 모델."""
    return str(model_id or "").rsplit("/", 1)[-1].strip().lower()


def _chat_like(model_id) -> bool:
    t = _tail(model_id)
    return bool(t) and not any(x in t for x in _NOT_CHAT)


def pick(chat_url: str, key: str, *, prefer=PREFER, default: str = DEFAULT,
         timeout: int = 15) -> str:
    """이 계정이 지금 실제로 쓸 수 있는 모델 하나를 고른다. 절대 죽지 않는다.

    목록을 못 물으면(네트워크·권한) 기본값 — 그 뒤는 호출부의 404 처리가 받는다.
    """
    if chat_url in _cache:
        return _cache[chat_url]
    if not str(key or "").strip():
        return default                      # 키가 없으면 묻지 않는다(캐시도 안 남긴다)

    chosen = default
    try:
        req = urllib.request.Request(
            str(chat_url).replace("/chat/completions", "/models"),
            headers={"Authorization": f"Bearer {key}", "User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        있는것 = [str(m.get("id") or "") for m in (data.get("data") or [])
               if isinstance(m, dict) and m.get("id")]
        꼬리표: dict = {}
        for mid in 있는것:
            if _chat_like(mid):
                꼬리표.setdefault(_tail(mid), mid)
        고른것 = None
        for want in prefer:
            if want in 있는것:               # 정확한 이름 먼저
                고른것 = want
                break
            hit = 꼬리표.get(_tail(want))     # 제공사 경로만 다른 같은 모델
            if hit:
                고른것 = hit
                break
        if 고른것 is None:                   # 선호가 다 떠났으면 대화되는 첫 번째
            고른것 = next((m for m in 있는것 if _chat_like(m)), None)
        if 고른것:
            chosen = 고른것
    except Exception:                       # noqa: BLE001 — 관문이 크론을 죽이면 본말전도
        pass
    _cache[chat_url] = chosen
    return chosen


def forget(chat_url: str) -> None:
    """404 를 맞으면 캐시를 비워 다음 pick 이 다시 묻게 한다(한낮 퇴역 대비)."""
    _cache.pop(chat_url, None)
