# -*- coding: utf-8 -*-
"""review_glowpick: 글로우픽(glowpick.com) 제품의 저점 후기를 실브라우저로 수집.

카페외부 원고 '재료'(경쟁사 제품의 불만·사용감 디테일)를 모으는 3소스(네이버/화해/글로우픽) 중 하나.
글로우픽은 로그인월·봇차단이 없어 가장 쉽다(2026-06-23 실증). 후기는 `/products/{id}/reviews`
페이지를 스크롤하면 DOM 에 렌더된다 — 후기 API(`/api/proxy/reviewApiK/api/reviews`)는 protobuf
인코딩이라 직접 복제가 어렵고, **렌더된 화면(DOM)을 긁는 것이 정답**(정찰 결과).

수집 기준(사장님 확정): 별점 낮은(<=max_score, 기본 2) 후기 + **원문 그대로**(요약/자르기 X).
  → 제품 불만·사용감 디테일이 원고 '리얼함' 재료. 선별/필터는 사람이(자동삭제 안 함).

출력(3소스 공통): [{score, content, product_name, source_url, source}]
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import sync_playwright

SOURCE = "글로우픽"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_PRODUCT_RE = re.compile(r"glowpick\.com/products/(\d+)")


def _search_product_id(pg, keyword: str) -> str | None:
    """글로우픽 검색에서 첫 제품 id 확보. 이미 숫자 id 면 그대로 사용."""
    kw = (keyword or "").strip()
    if kw.isdigit():
        return kw
    m = _PRODUCT_RE.search(kw)
    if m:
        return m.group(1)
    pg.goto("https://www.glowpick.com/search?query=" + kw.replace(" ", "%20"),
            wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    for _ in range(3):
        pg.mouse.wheel(0, 2000)
        time.sleep(0.8)
    blob = "\n".join(pg.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)"))
    m = _PRODUCT_RE.search(blob + "\n" + pg.content())
    return m.group(1) if m else None


# DOM 에서 후기(별점+본문)를 뽑는 JS (정찰 확정: 별점 = 채워진 빨간 별 <li class*=starRed> 개수,
# 본문 = 날짜(YYYY.MM.DD) 뒤 텍스트). 후기 리스트 컨테이너(productReviewL) 안에서, 날짜+빨간별을 가진
# '가장 안쪽' 요소를 후기 카드로 본다(부모 중복 제외).
_EXTRACT_JS = r"""
() => {
  const L = document.querySelector('[class*=productReviewL]') || document.body;
  const dateRe = /\d{4}\.\d{2}\.\d{2}/;
  const cand = Array.from(L.querySelectorAll('*')).filter(e => {
    const t = e.innerText || '';
    return dateRe.test(t) && t.length >= 20 && t.length <= 700 && e.querySelector('[class*=starRed]');
  });
  const out = [];
  const seen = new Set();
  for (const el of cand) {
    // 더 안쪽 카드가 있으면(부모) 건너뜀 → 가장 타이트한 카드만.
    if (cand.some(o => o !== el && el.contains(o))) continue;
    const red = el.querySelectorAll('[class*=starRed]').length;
    const half = el.querySelectorAll('[class*=starHalf], [class*=Half]').length;
    const score = red + (half ? 0.5 : 0);
    const t = el.innerText || '';
    const m = t.match(/(\d{4}\.\d{2}\.\d{2})\s*([\s\S]+)/);
    const body = (m ? m[2] : t).replace(/\s+/g, ' ').trim();
    if (body.length < 10) continue;
    const key = body.slice(0, 40);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ score: score, content: body });
  }
  return out;
}
"""


def _extract_reviews(pg) -> list[dict]:
    try:
        rows = pg.evaluate(_EXTRACT_JS)
    except Exception:
        rows = []
    return rows or []


def fetch_glowpick_lowstar(
    keyword_or_id: str,
    max_reviews: int = 100,
    max_score: float = 2.0,
    *,
    headless: bool = True,
    max_scrolls: int = 30,
) -> list[dict]:
    """글로우픽 제품의 저점(별점<=max_score) 후기를 수집.

    keyword_or_id: 검색 키워드(예 "헤드앤숄더 가려운 두피") 또는 제품 id(숫자) 또는 제품 URL.
    스크롤로 후기를 추가 로드하며 DOM 에서 별점+본문을 긁는다. 목표 수 도달/스크롤 한도서 종료.
    반환: [{score, content, product_name, source_url, source}] (저점만, 원문 보존).
    """
    target = (keyword_or_id or "").strip()
    if not target:
        return []
    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=_UA, locale="ko-KR", viewport={"width": 1366, "height": 3000}
        )
        pg = ctx.new_page()
        try:
            pid = _search_product_id(pg, target)
            if not pid:
                return []
            url = f"https://www.glowpick.com/products/{pid}/reviews"
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(4)
            try:
                product_name = (pg.title() or "").split("|")[0].strip()[:80]
            except Exception:
                product_name = ""
            seen_keys: set = set()
            stale = 0
            for _ in range(max_scrolls):
                for rv in _extract_reviews(pg):
                    sc = rv.get("score")
                    content = (rv.get("content") or "").strip()
                    if not content:
                        continue
                    key = content[:40]
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # 저점만(별점 모르면 보류 — 글로우픽은 별점 항상 노출).
                    if isinstance(sc, (int, float)) and sc <= max_score:
                        results.append({
                            "score": sc, "content": content,
                            "product_name": product_name,
                            "source_url": url, "source": SOURCE,
                        })
                        if len(results) >= max_reviews:
                            return results
                before = len(seen_keys)
                pg.mouse.wheel(0, 4000)
                time.sleep(1.3)
                # 더 안 늘면 종료(끝까지 봄).
                if len(seen_keys) == before:
                    stale += 1
                    if stale >= 3:
                        break
                else:
                    stale = 0
        finally:
            browser.close()
    return results[:max_reviews]


if __name__ == "__main__":
    import json
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "161538"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(fetch_glowpick_lowstar(arg, max_reviews=n), ensure_ascii=False, indent=2))
