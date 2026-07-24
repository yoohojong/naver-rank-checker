# -*- coding: utf-8 -*-
"""후보 이름 → "이 이름으로 물건을 살 수 있나" 를 **쇼핑 화면에 직접 물어본다**.

왜 (2026-07-24 사장님: "근본적으로 그게 유일한 해결 방법이야?")
------------------------------------------------------------------
판정 기준은 원래 "상점에서 그 이름으로 살 수 있으면 제품" 이다. 그걸 언어모델에게
물어보느라 하루치 한도를 태우고, 한도가 끝나면 표가 어제 값에 굳었다.
같은 질문을 쇼핑 화면에 하면 공짜이고 한도도 없다.

무엇을 확정하고 무엇을 안 하나 (실측 근거)
-------------------------------------------
판정해둔 이름 30개로 재보니 신호가 이렇게 갈렸다.
  제품:     닥터그루트 52 · 일리윤 47 · 로마 47 · 니조랄 46 · 다시꽃 43 (중앙 45)
  제품아님: 같아 2 · 결국 2 · 거예 2 · 괜찮나 3 · 같이 3 · 강한 4 (중앙 4)
높은 쪽은 겹친다 — '각질케어보습관리' 61, '고보습' 55 처럼 제품이 아닌데 높게 나오는
말이 있다. 낮은 쪽도 안전하지 않다 — 표본을 45개로 늘려 보니 신호 5 이하에
'뽀얀'(우리 제품) '아크시톨' 같은 진짜 이름이 섞여 있었다. 검색량이 적은 브랜드는
낮게 나온다. 그래서 **아주 낮은 구간(2 이하)만** 쓰고, 호출부는 여기에 더해
'여러 번 나온 이름은 아예 물어보지 않는' 안전장치를 건다.
적게 거르는 건 고칠 수 있지만, 잘못 거르면 진짜 경쟁사가 표에서 사라진다.
"""
from __future__ import annotations

import time
import urllib.parse

# 이 값 이하면 '파는 물건이 아니다' 로 본다.
# ★임계값은 실측으로 정했다(2026-07-24, 판정해둔 이름 45개):
#     임계 5 → 쓰레기 18/30 제거, 그런데 **진짜 브랜드 7/15 를 같이 버렸다**(뽀얀 포함!)
#     임계 3 → 쓰레기 18/30, 진짜 브랜드 5/15 손실
#     임계 2 → 쓰레기 15/30, 진짜 브랜드 2/15 손실 ('아크시톨' '터그루트')
# 처음엔 5로 잡았다가 실측에 반증당했다. 작은 브랜드·잘린 이름·우리 제품은
# 검색량이 적어 신호가 낮게 나온다. 그래서 가장 보수적인 2로 내렸다.
NOT_PRODUCT_AT_OR_BELOW = 2
# 쇼핑 자리가 화면에 있는지 세는 표식.
_MARKS = ("네이버쇼핑", "브랜드스토어", "shopping.naver")


def signal(name: str, *, timeout: int = 20, session=None) -> int:
    """이름 하나 → 쇼핑 신호 개수. 못 물어보면 -1(모름)."""
    name = str(name or "").strip()
    if not name:
        return -1
    url = ("https://search.naver.com/search.naver?where=nexearch&query="
           + urllib.parse.quote(name))
    try:
        from curl_cffi import requests as cr
        get = session.get if session is not None else cr.get
        html = get(url, impersonate="chrome", timeout=timeout).text
    except Exception:
        return -1                      # 못 물어봤으면 모르는 것 — 판정하지 않는다
    return sum(html.count(m) for m in _MARKS)


def not_products(names: list, *, sleep=time.sleep, pause: float = 0.7,
                 stat: dict | None = None) -> set:
    """이름 목록 → **'파는 물건이 아니다' 가 확실한 이름들**.

    모르겠으면(신호 -1, 또는 6 이상) 넣지 않는다 → 호출부가 언어모델에게 묻는다.
    """
    out: set = set()
    물어본, 못물어본 = 0, 0
    for i, n in enumerate(names or []):
        s = signal(n)
        if s < 0:
            못물어본 += 1
        else:
            물어본 += 1
            if s <= NOT_PRODUCT_AT_OR_BELOW:
                out.add(n)
        if pause and i < len(names) - 1:
            sleep(pause)               # 네이버 부담 줄이기
    if stat is not None:
        stat.update({"쇼핑물어봄": 물어본, "쇼핑못물어봄": 못물어본, "쇼핑에서걸러냄": len(out)})
    return out
