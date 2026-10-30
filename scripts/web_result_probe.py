# 네이버 검색 화면 · 서치어드바이저 안내를 GitHub 서버에서 받아 저장 (읽기만 · 2026-10-30 뷰티움랩 검색 표시 조사)
import json, os, re, sys, time, urllib.parse
from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
QUERIES = [q.strip() for q in os.environ.get("QUERIES", "").split(",") if q.strip()]
GUIDE_START = "https://searchadvisor.naver.com/guide"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--mute-audio"])
    ctx = b.new_context(locale="ko-KR", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
    pg = ctx.new_page()
    # 1) 검색 화면 (통합 · 웹문서)
    for i, q in enumerate(QUERIES):
        for where in ["nexearch", "web"]:
            url = f"https://search.naver.com/search.naver?where={where}&query={urllib.parse.quote(q)}"
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=30000); time.sleep(2)
                open(f"{OUT}/search_{i}_{where}.html", "w", encoding="utf-8").write(pg.content())
                open(f"{OUT}/search_{i}_{where}.txt", "w", encoding="utf-8").write(q + "\n" + url + "\n\n" + pg.inner_text("body"))
            except Exception as e:
                open(f"{OUT}/search_{i}_{where}.err", "w", encoding="utf-8").write(repr(e))
            time.sleep(4)
    # 2) 서치어드바이저 안내 (목차에서 guide 링크를 따라감, 최대 60쪽)
    seen, todo, pages = set(), [GUIDE_START], []
    while todo and len(seen) < 60:
        u = todo.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            pg.goto(u, wait_until="networkidle", timeout=30000); time.sleep(1)
            txt = pg.inner_text("body")
            pages.append({"url": u, "text": txt})
            for h in pg.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
                h = h.split("#")[0]
                if h.startswith("https://searchadvisor.naver.com/guide") and h not in seen and h not in todo:
                    todo.append(h)
        except Exception as e:
            pages.append({"url": u, "error": repr(e)})
        time.sleep(1.5)
    json.dump(pages, open(f"{OUT}/guide_pages.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    b.close()
print("done", len(QUERIES), "queries,", len(pages), "guide pages")
