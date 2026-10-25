# -*- coding: utf-8 -*-
"""댓글을 한 번 읽었으면 다시 읽지 않는다 — 읽기 결과(이름들)를 파일에 남긴다.

왜 남기나 (2026-08-20)
- 키워드가 1,240개로 늘며 하루 댓글 2.6만 건(4.6만 건 중 중복 제거)이 됐는데,
  매일 처음부터 다시 읽으니 Groq 무료 한도(하루 20만 토큰·요청 1,000회)와
  시간(180분)을 다 태웠다. 7/29~8/16 매일 밤 시간 초과 취소, 8/17~19 모델 퇴역
  404 — 한 달간 시트 '경쟁사' 가 7/23 값에 멈춰 있었다.
- 카페 댓글은 한 번 달리면 그대로다. 같은 글자를 매일 다시 읽는 건 낭비가 아니라
  고장의 원인이었다. 읽은 결과를 남기면 다음 날은 **새 댓글만** 읽는다
  (brand_verdicts 가 '판정'에 하는 일을 '읽기'에도 한다 — 같은 무늬).

파일 모양 (data/comment_reads.json) — 원문 대신 지문(해시)만 남긴다(크기 억제):
  {"a1b2c3d4e5f6": {"이름": ["안티트로"], "깎음": ["니조랄"], "날": "2026-08-20"},
   "f6e5d4c3b2a1": {"이름": [], "깎음": [], "날": "2026-08-20"}}   ← 제품 없던 댓글도 '읽었다'로 기억
  · 이름 = 권하거나 좋게·중립으로 말한 제품(경쟁사 셈의 재료)
  · 깎음 = 나쁘게 말해 다른 제품으로 넘어가게 한 대상(2026-10-24 — 경쟁사로 세지 않는다)
  · 종류 = 상표가 아닌 깎인 종류(스테로이드 · 피부과 · 스케일링 · 약산성샴푸 — 2026-10-25).
           칸이 없으면 그 칸이 생기기 전에 읽은 항목이다('봤는데 없음' 은 []).

★2026-10-24 옛 항목 다시 읽기: '깎음' 칸이 생기기 전에 읽은 항목은 이름이 '미는 것'인지
  '깎는 것'인지 모른다. 그중 **이름이 비지 않은 것만**(약 7,707개) 다시 읽을 대상으로 친다
  (needs_reread). 이름이 빈 옛 항목은 깎을 것도 없었을 확률이 높아 다시 읽지 않는다(비용).
  다시 읽기 전까지는 옛 이름을 그대로 쓴다 — 예산이 모자라 못 다시 읽은 날 표가 비지 않게.

안전
- 실패한 읽기는 남기지 않는다 — '읽었는데 없음' 과 '못 읽음' 을 섞으면
  못 읽은 댓글이 영원히 다시 안 읽힌다.
- 오래 안 보인 댓글(기본 45일)은 지운다 — 파일이 한없이 크지 않게.
- 날짜 갱신(touch)은 7일에 한 번만 다시 적는다 — 매일 2만 줄이 통째로 바뀌면
  git 기록이 상태 창고가 되는 사고(2026-08-04 교훈)를 되풀이한다.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "comment_reads.json")

KEEP_DAYS = 45          # 이보다 오래 안 보인 댓글은 지운다
TOUCH_EVERY_DAYS = 7    # 날짜 갱신은 이 간격으로만 다시 적는다(git 잡음 억제)


def key_of(text) -> str:
    """댓글 원문 → 12자리 지문. 원문을 파일에 남기지 않는 이유이기도 하다(크기·사생활)."""
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:12]


def load(path: str = DEFAULT_PATH) -> dict:
    """저장된 읽기 기록. 없거나 깨졌으면 빈 것으로 시작한다(멈추지 않는다)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(v.get("이름"), list):
            e = {"이름": [str(n) for n in v["이름"]], "날": str(v.get("날") or "")}
            if isinstance(v.get("깎음"), list):      # 없으면 옛 항목 — 키를 만들어 넣지 않는다
                e["깎음"] = [str(n) for n in v["깎음"]]
            if isinstance(v.get("종류"), list):      # 2026-10-25 — 없으면 '종류' 칸 전에 읽은 항목
                e["종류"] = [str(n) for n in v["종류"]]
            out[str(k)] = e
    return out


def get(reads: dict, text) -> list | None:
    """이 댓글을 읽은 적 있나 — 있으면 그때 뽑힌 이름들(없었으면 []), 없으면 None."""
    e = (reads or {}).get(key_of(text))
    return list(e["이름"]) if e else None


def get_full(reads: dict, text) -> dict | None:
    """이 댓글을 읽은 적 있나 — 있으면 {"이름": [...], "깎음": [...] 또는 None}, 없으면 None.
    '깎음' 이 None 이면 그 칸이 생기기 전에 읽은 옛 항목이다."""
    e = (reads or {}).get(key_of(text))
    if not e:
        return None
    깎 = e.get("깎음")
    return {"이름": list(e["이름"]), "깎음": list(깎) if isinstance(깎, list) else None}


def needs_reread(entry: dict | None) -> bool:
    """옛 항목 중 다시 읽을 것인가 — 이름이 비지 않았고 '깎음' 칸이 없는 것만.

    get_full 이 돌려준 모양({"깎음": None})과 파일 모양(키 없음) 둘 다 받는다."""
    if not entry:
        return False
    return bool(entry.get("이름")) and not isinstance(entry.get("깎음"), list)


def get_종류(reads: dict, text) -> list | None:
    """이 댓글에서 깎은 종류(약 · 병원 · 시술 · 제품 종류) — 칸이 생기기 전에 읽었으면 None.

    get_full 의 모양은 그대로 두고 따로 꺼낸다(부르는 쪽 · 시험이 그 모양을 믿는다)."""
    e = (reads or {}).get(key_of(text))
    if not e:
        return None
    종 = e.get("종류")
    return list(종) if isinstance(종, list) else None


def put(reads: dict, text, names, today: str, 깎음=None, 종류=None) -> None:
    """종류가 None 이면 '종류' 칸을 안 봤다는 뜻이라 키를 만들지 않는다([] 은 '봤는데 없음')."""
    e = {"이름": [str(n) for n in (names or [])],
         "깎음": [str(n) for n in (깎음 or [])], "날": str(today)}
    if isinstance(종류, list):
        e["종류"] = [str(n) for n in 종류]
    reads[key_of(text)] = e


def touch(reads: dict, text, today: str) -> None:
    """오늘도 보였다 — 청소(prune)에서 살린다. 다시 적는 건 7일에 한 번만."""
    e = (reads or {}).get(key_of(text))
    if not e:
        return
    if _days_between(e.get("날", ""), today) >= TOUCH_EVERY_DAYS:
        e["날"] = str(today)


def prune(reads: dict, today: str, keep_days: int = KEEP_DAYS) -> dict:
    """오래 안 보인 댓글을 지운다. 날짜를 못 읽는 항목도 지운다(fail-closed 아님 — 재읽기일 뿐)."""
    out = {}
    for k, e in (reads or {}).items():
        d = _days_between(e.get("날", ""), today)
        if d is not None and d <= keep_days:
            out[k] = e
    return out


def save(reads: dict, path: str = DEFAULT_PATH) -> bool:
    """저장 실패해도 수집 전체를 죽이지 않는다(다음 run 이 다시 읽을 뿐)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: reads[k] for k in sorted(reads)}, f,
                      ensure_ascii=False, indent=0, sort_keys=True)
        return True
    except OSError:
        return False


def _days_between(then: str, today: str):
    """then → today 며칠 지났나. 못 읽으면 None(그 항목은 지워져 다시 읽힌다)."""
    try:
        return (date.fromisoformat(str(today)) - date.fromisoformat(str(then))).days
    except (ValueError, TypeError):
        return None
