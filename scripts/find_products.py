# -*- coding: utf-8 -*-
"""네이버 쇼핑 검색으로 두피/비듬 제품의 brand|smartstore 상품 URL 수집."""
import sys, time, re, json
from playwright.sync_api import sync_playwright
def log(*a): print(*a, flush=True)

QUERY = sys.argv[1] if len(sys.argv) > 1 else "비듬 샴푸"

def run(query):
    urls = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"), locale="ko-KR",
              viewport={"width":1366,"height":2200})
        pg = ctx.new_page()
        found = set()
        def on_resp(resp):
            pass
        url = "https://search.shopping.naver.com/search/all?query=" + query
        log(f"[nav] {url}")
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            log(f"[nav-err] {e}")
        time.sleep(5)
        # scroll to load lazy products
        for _ in range(4):
            pg.mouse.wheel(0, 2500); time.sleep(1.2)
        html = pg.content()
        # extract any brand.naver.com/smartstore.naver.com product links from anchors + html
        anchors = pg.eval_on_selector_all("a",
            "els => els.map(e => e.href).filter(h => h && (h.includes('brand.naver.com') || h.includes('smartstore.naver.com')))")
        for h in anchors:
            m = re.search(r"https?://(?:brand|smartstore)\.naver\.com/[^/]+/products/\d+", h)
            if m: found.add(m.group(0))
        for m in re.finditer(r"https?://(?:brand|smartstore)\.naver\.com/[^/\"']+/products/\d+", html):
            found.add(m.group(0))
        log(f"[result] query={query!r} title={pg.title()[:50]!r} found={len(found)}")
        for u in list(found)[:15]:
            log("  " + u)
        b.close()
    return list(found)

if __name__ == "__main__":
    run(QUERY)
