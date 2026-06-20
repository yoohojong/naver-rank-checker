"""llm_intent: 자유로운 자연어 질문 → 의도(intent) 분류 (Groq 무료 LLM). M12.

키워드 매칭(qa_formatter.classify_with_confidence)이 '확신 못한' 질문만 이 모듈로 넘어온다.
즉 정확한 명령(누락/삭제/순위 등)은 LLM 호출 없이 즉시 처리 → 무료 한도 절약.

프라이버시(핵심): LLM 에 보내는 것은 사장님 '질문 글' + 의도 목록 + 제품 탭 이름뿐.
실제 순위/시트 데이터는 절대 외부로 보내지 않는다(답 생성은 로컬 qa_formatter 가 담당).

안전(비차단): GROQ_API_KEY 미설정·네트워크 실패·파싱 실패 시 None 반환 →
호출부가 기존 키워드 결과로 폴백. 봇은 절대 죽지 않는다.

설정(secret 으로 override 가능 — 모델 deprecate/엔드포인트 변경 대비):
- GROQ_API_KEY  : Groq 무료 API 키 (필수, 없으면 LLM 분류 skip)
- GROQ_MODEL    : 기본 'llama-3.3-70b-versatile' (Groq 프로덕션·한국어 양호, 2026-06 확인)
- GROQ_BASE_URL : 기본 OpenAI 호환 chat completions 엔드포인트
"""
from __future__ import annotations

import json
import os
import urllib.request

# Groq OpenAI 호환 엔드포인트 (console.groq.com, 2026-06 확인)
_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"

# Groq API 앞단 Cloudflare 가 기본 urllib 시그니처를 403/error 1010 으로 차단 →
# 브라우저 User-Agent 필수(실측 2026-06-20). 빠지면 모든 호출 403 → None 폴백(자연어 OFF).
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# qa_formatter 와 동일한 의도 집합 (product/keyword 만 arg 동반)
_VALID_INTENTS = frozenset(
    {"help", "missing", "deleted", "jisikin", "type", "rank", "summary", "product", "keyword"}
)

_SYSTEM = (
    "너는 네이버 검색 순위 점검 봇의 '질문 의도 분류기'다. "
    "사용자(한국어)의 질문을 아래 의도 중 정확히 하나로 분류해 JSON 으로만 답한다.\n"
    "의도 목록:\n"
    "- missing: 검색에서 빠진/누락된 키워드를 물음\n"
    "- deleted: 글이 삭제/사라진 키워드를 물음\n"
    "- rank: 순위가 오르거나 내린 것을 물음\n"
    "- jisikin: 지식iN(지식인) 노출을 물음\n"
    "- type: 노출 유형(AB/인기글/스마트블록)·구좌 분포를 물음\n"
    "- summary: 전체 현황 요약을 물음\n"
    "- product: 특정 제품/카테고리 현황을 물음. arg = 사용자가 말한 제품 단어(예: 샴푸, 바디워시). 없으면 null\n"
    "- keyword: 특정 키워드 1개의 상태를 물음. arg = 그 키워드 단어만(문장 전체 금지)\n"
    "- help: 사용법/도움/무엇을 할 수 있는지 물음\n"
    'JSON 형식만 출력: {"intent": "<의도>", "arg": "<arg 또는 null>"}\n'
    "그 외 다른 말은 절대 출력하지 않는다."
)


def _api_key():
    return os.environ.get("GROQ_API_KEY", "").strip()


def build_messages(text):
    """질문 글만으로 messages 구성. 시트 파생 데이터(탭 이름 포함) 일절 미전송 —
    product arg 는 LLM 이 질문에서 뽑은 단어이고, 실제 탭 매핑은 로컬 parse_response 에서 한다."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": str(text or "").strip()},
    ]


def _extract_json(content):
    """LLM 응답 문자열에서 첫 JSON 객체 추출(코드펜스/잡텍스트 허용)."""
    if not content:
        return None
    s = str(content).strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1 and s[:nl].strip().lower() in ("json", ""):
            s = s[nl + 1:]
        s = s.strip()
    # 1) 통짜 JSON 우선 시도(가장 흔한 경우, 문자열 내 중괄호도 안전)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    # 2) 잡텍스트 섞인 경우만 첫 {..} 균형 추출 폴백
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


def _match_tab(arg, tab_names):
    """LLM 이 준 제품명 → 실제 탭 이름 매핑(부분일치 허용). 없으면 None."""
    if not arg:
        return None
    tabs = [str(t) for t in (tab_names or [])]
    for tab in tabs:                       # 정확 일치 우선
        if tab == arg:
            return tab
    a = arg.replace("카외", "").strip().lower()
    for tab in tabs:
        base = tab.replace("카외", "").strip().lower()
        if a and base and (a == base or a in base or base in a):
            return tab
    return None


def parse_response(content, tab_names=None):
    """LLM content → (intent, arg) | None. intent 검증 + product arg 탭 매핑."""
    obj = _extract_json(content)
    if not isinstance(obj, dict):
        return None
    intent = str(obj.get("intent", "")).strip()
    if intent not in _VALID_INTENTS:
        return None
    arg = obj.get("arg", None)
    if arg is not None:
        arg = str(arg).strip() or None
    if intent == "product":
        return ("product", _match_tab(arg, tab_names))
    if intent == "keyword":
        return ("keyword", arg)
    return (intent, None)               # 그 외 의도는 arg 무시


def classify(text, tab_names=None, *, timeout=8):
    """자유 질문 → (intent, arg) | None. 키 없음/호출 실패 시 None(키워드 결과로 폴백)."""
    key = _api_key()
    if not key:
        return None
    body = {
        "model": os.environ.get("GROQ_MODEL", _DEFAULT_MODEL),
        "messages": build_messages(text),
        "temperature": 0,
        "max_tokens": 60,
    }
    url = os.environ.get("GROQ_BASE_URL", _DEFAULT_BASE_URL)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": _USER_AGENT,   # Cloudflare 1010 차단 회피(필수)
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("[QA][LLM] 응답 형식 불일치 (Groq API 변경 가능)")
        return None
    except Exception as e:  # noqa: BLE001 — 키/URL 노출 금지, 봇 비차단
        print(f"[QA][LLM] 분류 실패: {type(e).__name__}")
        return None
    return parse_response(content, tab_names)
