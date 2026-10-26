"""데이터랩 공개 화면(검색어트렌드)이 로그인 없이 열리는지 · 어떤 요청으로 값을 받는지 보기 — GitHub 서버 전용."""
import json, os
from playwright.sync_api import sync_playwright
os.makedirs("out", exist_ok=True)
log = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(locale="ko-KR")
    def on_resp(r):
        if "datalab.naver.com" in r.url and r.request.method == "POST":
            try: body = r.text()[:3000]
            except Exception: body = ""
            log.append({"url": r.url, "post": (r.request.post_data or "")[:1500], "status": r.status, "body": body})
    p.on("response", on_resp)
    p.goto("https://datalab.naver.com/keyword/trendSearch.naver", wait_until="networkidle", timeout=60000)
    p.screenshot(path="out/1_first.png", full_page=True)
    txt = p.inner_text("body")
    inputs = p.eval_on_selector_all("input", "els=>els.map(e=>[e.id,e.name,e.type,e.placeholder])")
    try:
        p.fill("#item_keyword1", "지루성두피염")
        p.fill("#item_sub_keyword1_1", "지루성두피염")
        p.fill("#item_keyword2", "비염")
        p.fill("#item_sub_keyword2_1", "비염")
        p.click("text=네이버 검색 데이터 조회")
        p.wait_for_timeout(8000)
    except Exception as e:
        log.append({"error": str(e)})
    p.screenshot(path="out/2_after.png", full_page=True)
    json.dump({"url": p.url, "text": txt[:3000], "inputs": inputs, "after_url": p.url,
               "after_text": p.inner_text("body")[:4000], "posts": log},
              open("out/datalab_web_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    b.close()
print(open("out/datalab_web_probe.json", encoding="utf-8").read()[:6000])
