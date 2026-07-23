# -*- coding: utf-8 -*-
"""제품이냐 아니냐 — 한 번 내린 판정을 파일에 남긴다.

왜 남기나 (2026-07-23)
- 같은 이름을 매일 다시 물어보면 Groq 무료 하루치를 또 태운다. 한 번 정하면 끝.
- 사장님이 직접 고칠 자리가 생긴다. 파일에서 판정을 "사장님" 으로 적어두면
  다시는 언어모델이 뒤집지 못한다(사람 판정이 위다).
- 어제 표가 왜 그랬는지 나중에 볼 수 있다.

파일 모양 (data/brand_verdicts.json)
  {"닥터이노브": {"제품": true,  "이름": "닥터이노브", "판정": "LLM",   "판정일": "2026-07-23"},
   "약국에서":   {"제품": false, "이름": "",           "판정": "LLM",   "판정일": "2026-07-23"},
   "다시꽃":     {"제품": true,  "이름": "다시꽃",     "판정": "사장님", "판정일": "2026-07-23"}}
"""
from __future__ import annotations

import json
import os

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "brand_verdicts.json")

# 사람이 내린 판정 — 언어모델이 못 덮는다.
HUMAN = "사장님"


def load(path: str = DEFAULT_PATH) -> dict:
    """저장된 판정 읽기. 없거나 깨졌으면 빈 것으로 시작한다(멈추지 않는다)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def merge(cached: dict, fresh: dict, *, today: str) -> dict:
    """새 판정을 얹는다. 사장님이 정한 것은 그대로 둔다."""
    out = dict(cached or {})
    for key, v in (fresh or {}).items():
        if out.get(key, {}).get("판정") == HUMAN:
            continue                        # 사람 판정이 위 — 덮지 않는다
        out[key] = {"제품": bool(v.get("제품")), "이름": str(v.get("이름") or ""),
                    "판정": "LLM", "판정일": today}
    return out


def save(verdicts: dict, path: str = DEFAULT_PATH) -> bool:
    """판정 저장. 실패해도 수집 전체를 죽이지 않는다(다음 run 이 다시 물어볼 뿐)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {k: verdicts[k] for k in sorted(verdicts)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        return True
    except OSError:
        return False


def is_product(verdicts: dict, key: str) -> bool:
    """판정된 제품인가. 판정이 없으면 False — 모르면 표에 넣지 않는다."""
    return bool((verdicts or {}).get(key, {}).get("제품"))


def display_name(verdicts: dict, key: str, fallback: str = "") -> str:
    """표에 쓸 이름 — 판정이 되살린 브랜드명이 있으면 그것."""
    return str((verdicts or {}).get(key, {}).get("이름") or fallback or key)
