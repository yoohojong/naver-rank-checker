# -*- coding: utf-8 -*-
"""진단: 서버에서 네이버 쇼핑 계열 주소가 어떻게 응답하는지 상태만 기록(읽기 전용)."""
import json, sys, pathlib, urllib.parse
from playwright.sync_api import sync_playwright
sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("out"); OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
q = urllib.parse.quote("족저근막염 깔창")
URLS = [
 "https://search.naver.com/search.naver?query=" + q,
 "https://search.naver.com/search.naver?where=shopping&query=" + q,
 "https://m.search.naver.com/search.naver?query=" + q,
 "https://search.shopping.naver.com/search/all?query=" + q,
 "https://msearch.shopping.naver.com/search/all?query=" + q,
 "https://brand.naver.com/naboso",
 "https://smartstore.naver.com/main/products/12144849743",
 "https://shopping.naver.com/",
]
rows = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--mute-audio"])
    ctx = b.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1366, "height": 2200})
    pg = ctx.new_page()
    for u in URLS:
        r = {"url": u}
        try:
            resp = pg.goto(u, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(4000)
            r["status"] = resp.status if resp else None
            r["final"] = pg.url
            r["title"] = pg.title()
            r["text"] = pg.evaluate("document.body ? document.body.innerText.slice(0,600) : ''")
            html = pg.content()
            import re
            r["product_links"] = sorted(set(re.findall(r"https?://(?:brand|smartstore)\.naver\.com/[A-Za-z0-9_\-]+/products/\d+", html)))[:20]
            r["shop_links"] = sorted(set(re.findall(r"https?://(?:search\.)?shopping\.naver\.com/[^\"' <>]{5,80}", html)))[:10]
        except Exception as e:
            r["error"] = repr(e)[:200]
        print(json.dumps(r, ensure_ascii=False)[:700], flush=True)
        rows.append(r)
    b.close()
(OUT / "diag.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
