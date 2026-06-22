# -*- coding: utf-8 -*-
"""review_hwahae: 화해(hwahae.co.kr) 제품의 저점 후기를 실브라우저로 수집.

카페외부 원고 '재료' 3소스(네이버/화해/글로우픽) 중 하나. 화해는 무인 직접호출(WebFetch)은 제품상세
403(봇UA차단)이나, **실브라우저(Playwright)면 통과**(2026-06-23 실증). 검색→상품상세에 후기 본문이
렌더된다(향·사용감·불만 디테일 실측). '전체 리뷰보기'로 더 펼친다.

입력 = 키워드(시트 4·5단계 키워드 자동구동). 화해 검색으로 상품을 자동 확보 → 사장님 입력 0.
출력(3소스 공통): [{score, content, product_name, source_url, source}]
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import sync_playwright

SOURCE = "화해"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_PRODUCT_RE = re.compile(r"hwahae\.co\.kr/products/(\d+)")
_DATE_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}")


def _search_product_id(pg, keyword: str) -> str | None:
    kw = (keyword or "").strip()
    if kw.isdigit():
        return kw
    m = _PRODUCT_RE.search(kw)
    if m:
        return m.group(1)
    pg.goto("https://www.hwahae.co.kr/search?q=" + kw.replace(" ", "%20"),
            wait_until="domcontentloaded", timeout=45000)
    time.sleep(4)
    for _ in range(2):
        pg.mouse.wheel(0, 2000)
        time.sleep(0.9)
    blob = "\n".join(pg.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)"))
    m = _PRODUCT_RE.search(blob + "\n" + pg.content())
    return m.group(1) if m else None


# 화해 후기 카드 = 별점(채워진 별) + 날짜 + 본문. 별점은 SVG/별 아이콘이라 텍스트에 숫자 없음 →
# 카드 DOM 에서 '채워진 별' 요소 수를 센다. 본문/별점/날짜를 카드별로 함께 뽑는 JS.
_EXTRACT_JS = r"""
() => {
  const dateRe = /\d{4}\.\d{2}\.\d{2}/;
  const all = Array.from(document.querySelectorAll('li,article,div'));
  const cand = all.filter(e => {
    const t = e.innerText || '';
    return dateRe.test(t) && t.length >= 25 && t.length <= 700;
  });
  const out = [];
  const seen = new Set();
  for (const el of cand) {
    if (cand.some(o => o !== el && el.contains(o))) continue; // 가장 안쪽 카드
    // 별점: 채워진 별 추정 — fill 색이 있는 svg/path, 또는 class 에 fill/on/active/red.
    let score = null;
    const filled = el.querySelectorAll('[class*=fill i],[class*=on i],[class*=active i],[class*=red i],[fill]:not([fill="none"])').length;
    const stars = el.querySelectorAll('svg,[class*=star i]').length;
    if (stars > 0 && filled > 0 && filled <= 5) score = filled;
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


def fetch_hwahae_lowstar(
    keyword_or_id: str,
    max_reviews: int = 100,
    max_score: float = 2.0,
    *,
    headless: bool = True,
    max_scrolls: int = 30,
) -> list[dict]:
    """화해 제품의 저점(별점<=max_score) 후기 수집. 별점 못 읽은 후기는 보류(score=None 제외).

    원문 보존. 별점이 별 아이콘이라 추출 신뢰도가 낮으면 호출부에서 max_score 를 높이거나
    score=None 도 받도록 조정. (사장님 방침: 삭제 X — 여기선 저점 필터만, 태그는 호출부.)
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
            url = f"https://www.hwahae.co.kr/products/{pid}"
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5)
            try:
                product_name = (pg.title() or "").split("|")[0].split("리뷰")[0].strip()[:80]
            except Exception:
                product_name = ""
            # '전체 리뷰보기' 펼치기.
            try:
                el = pg.query_selector("text=전체 리뷰보기")
                if el:
                    el.click()
                    time.sleep(4)
            except Exception:
                pass

            seen_keys: set = set()
            stale = 0
            for _ in range(max_scrolls):
                try:
                    rows = pg.evaluate(_EXTRACT_JS)
                except Exception:
                    rows = []
                before = len(seen_keys)
                for rv in rows or []:
                    body = (rv.get("content") or "").strip()
                    key = body[:40]
                    if not body or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    sc = rv.get("score")
                    if isinstance(sc, (int, float)) and sc <= max_score:
                        results.append({
                            "score": sc, "content": body,
                            "product_name": product_name,
                            "source_url": url, "source": SOURCE,
                        })
                        if len(results) >= max_reviews:
                            return results
                pg.mouse.wheel(0, 5000)
                time.sleep(1.5)
                if len(seen_keys) == before:
                    stale += 1
                    if stale >= 4:
                        break
                else:
                    stale = 0
        finally:
            browser.close()
    return results[:max_reviews]


if __name__ == "__main__":
    import json
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "헤드앤숄더"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(fetch_hwahae_lowstar(arg, max_reviews=n), ensure_ascii=False, indent=2))
