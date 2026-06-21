# -*- coding: utf-8 -*-
"""네이버 통합검색 + 브랜드스토어 직접 진입으로 두피/비듬 제품 URL 수집."""
import sys, time, re
from playwright.sync_api import sync_playwright
def log(*a): print(*a, flush=True)

# (브랜드스토어 슬러그) 두피/비듬 관련 후보. 슬러그 추정 + 통합검색 보강.
SEARCHES = sys.argv[1:] or ["두피 브러쉬 아로마티카", "닥터그루트 탈모", "헤드앤숄더 비듬"]

def harvest(pg):
    found = set()
    try:
        anchors = pg.eval_on_selector_all("a",
            "els => els.map(e => e.href).filter(Boolean)")
    except Exception:
        anchors = []
    html = ""
    try: html = pg.content()
    except Exception: pass
    blob = "\n".join(anchors) + "\n" + html
    for m in re.finditer(r"https?://(?:brand|smartstore)\.naver\.com/[A-Za-z0-9_\-]+/products/\d+", blob):
        found.add(m.group(0))
    return found

def run(searches):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"), locale="ko-KR",
              viewport={"width":1366,"height":2200})
        pg = ctx.new_page()
        all_found = set()
        for q in searches:
            url = "https://search.naver.com/search.naver?query=" + q.replace(" ", "+")
            log(f"[nav] {url}")
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                log(f"  [err] {e}")
                continue
            time.sleep(3)
            for _ in range(3):
                pg.mouse.wheel(0, 2200); time.sleep(0.9)
            f = harvest(pg)
            log(f"  found={len(f)} title={pg.title()[:40]!r}")
            for u in list(f)[:10]:
                log("   " + u)
            all_found |= f
        log("=" * 50)
        log(f"[TOTAL UNIQUE] {len(all_found)}")
        for u in sorted(all_found):
            log("  " + u)
        b.close()
    return all_found

if __name__ == "__main__":
    run(SEARCHES)
