# -*- coding: utf-8 -*-
"""족저근막염 쇼핑 낮은 별점 길 찾기 시험(t_0f26d1d6 · 2026-11-23) — 읽기 전용 · 1회만 · 우회 없음.
상품 1개씩: 네이버 브랜드스토어 주소 · 스마트스토어 실제 가게 주소 · 쿠팡 상품 · 쿠팡 후기 주소의
응답 코드 · 화면 제목 · 막힌 글자를 남기고, 상품 번호를 얻으면 별점 낮은 순 후기 1쪽(20개)만 부른다.
"""
import json, pathlib, re, sys, time

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("out"); OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TARGETS = [
    ("naver_brand", "https://brand.naver.com/healingsole/products/13069137475"),
    ("naver_smart_real", "https://smartstore.naver.com/bentiflexier/products/8315525663"),
    ("naver_m_smart_real", "https://m.smartstore.naver.com/bentiflexier/products/8315525663"),
    ("coupang_product", "https://www.coupang.com/vp/products/9068759301"),
]
FETCH_JS = r"""
async (cfg) => {
  try {
    const r = await fetch(location.origin + "/n/v1/contents/reviews/query-pages", {method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify({checkoutMerchantNo: Number(cfg.merchant), originProductNo: Number(cfg.origin),
        page: 1, pageSize: 20, reviewSearchSortType: "REVIEW_SCORE_ASC"}), credentials: "include"});
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) {}
    return {status: r.status, total: j ? j.totalElements : null,
      scores: j && j.contents ? j.contents.map(c => c.reviewScore) : [],
      n: j && j.contents ? j.contents.length : 0, head: j ? null : t.slice(0, 300),
      sample: j && j.contents && j.contents[0] ? String(j.contents[0].reviewContent || "").slice(0, 80) : null};
  } catch (e) { return {status: -1, error: String(e)}; }
}
"""
INFO_JS = r"""
() => { const h = document.documentElement.innerHTML;
  const pick = re => { const m = h.match(re); return m ? m[1] : null; };
  return {origin: pick(/"originProductNo"\s*:\s*"?(\d+)"?/), merchant: pick(/"checkoutMerchantNo"\s*:\s*"?(\d+)"?/),
    text: (document.body ? document.body.innerText : "").slice(0, 400)}; }
"""
CP_REVIEW_JS = r"""
async (pid) => { try {
  const r = await fetch("/next-api/review?productId=" + pid + "&page=1&size=10&sortBy=ORDER_SCORE_ASC&ratingSummary=true&ratings=1", {credentials: "include"});
  const t = await r.text(); return {status: r.status, head: t.slice(0, 300)}; } catch (e) { return {status: -1, error: String(e)}; } }
"""
res = []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--mute-audio"])
    ctx = b.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1366, "height": 1800})
    pg = ctx.new_page()
    sniff = {}
    def on_req(req):
        m = re.search(r"/reviews/product-summary/(\d+)", req.url)
        if m:
            sniff["o"] = m.group(1)
            mm = re.search(r"checkoutMerchantNo=(\d+)", req.url)
            if mm: sniff["m"] = mm.group(1)
    pg.on("request", on_req)
    for name, url in TARGETS:
        sniff.clear()
        rec = {"name": name, "url": url, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        try:
            r = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
            rec.update(status=r.status if r else None, final=pg.url, title=pg.title())
            info = pg.evaluate(INFO_JS)
            rec["text"] = info.get("text")
            o, m = info.get("origin") or sniff.get("o"), info.get("merchant") or sniff.get("m")
            rec.update(origin=o, merchant=m)
            if name.startswith("naver") and o and m and "nid.naver.com" not in pg.url:
                rec["review_low"] = pg.evaluate(FETCH_JS, {"origin": o, "merchant": m})
            if name == "coupang_product" and r and r.status == 200:
                rec["review_low"] = pg.evaluate(CP_REVIEW_JS, "9068759301")
        except Exception as e:
            rec["error"] = repr(e)[:300]
        print(json.dumps({k: v for k, v in rec.items() if k != "text"}, ensure_ascii=False), flush=True)
        res.append(rec)
        time.sleep(7)
    b.close()
(OUT / "probe.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
