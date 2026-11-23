# 스마트스토어 손님 화면 8개(홈+상품3 x PC/휴대폰)를 서버에서 받아 저장(읽기만 · 2026-11-23)
import json, os, sys, time, datetime
from playwright.sync_api import sync_playwright
OUT = "out"; os.makedirs(OUT, exist_ok=True)
S = {"홈": "", "마사지기": "/products/13889380939", "이완기": "/products/13884386311", "교정기": "/products/13889385174"}
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
log = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--mute-audio"])
    for dev, host, ua, vp in [("PC", "https://smartstore.naver.com", UA_PC, {"width": 1280, "height": 900}), ("휴대폰", "https://m.smartstore.naver.com", UA_M, {"width": 390, "height": 844})]:
        ctx = b.new_context(locale="ko-KR", user_agent=ua, viewport=vp, is_mobile=(dev == "휴대폰"))
        pg = ctx.new_page()
        for name, path in S.items():
            url = f"{host}/goyu777{path}"; key = f"스토어{name}_{dev}"; rec = {"id": key, "url": url, "time": datetime.datetime.utcnow().isoformat() + "Z"}
            try:
                r = pg.goto(url, wait_until="domcontentloaded", timeout=40000); time.sleep(5)
                rec["status"] = r.status if r else None; rec["final_url"] = pg.url; rec["title"] = pg.title()
                html = pg.content(); txt = pg.inner_text("body")
                open(f"{OUT}/{key}.html", "w", encoding="utf-8").write(html)
                open(f"{OUT}/{key}.txt", "w", encoding="utf-8").write(url + "\n\n" + txt)
                rec["count_visible"] = {k: txt.count(k) for k in ["건강보법", "카테키산", "KoU", "옆으로베개", "스텝닥터"]}
                rec["count_html"] = {k: html.count(k) for k in ["건강보법", "카테키산", "KoU", "옆으로베개", "스텝닥터"]}
                pg.screenshot(path=f"{OUT}/{key}.png", full_page=False)
            except Exception as e:
                rec["error"] = repr(e)
            log.append(rec); print(rec, flush=True); time.sleep(3)
        ctx.close()
    b.close()
json.dump(log, open(f"{OUT}/log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
