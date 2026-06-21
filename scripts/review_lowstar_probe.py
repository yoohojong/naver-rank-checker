# -*- coding: utf-8 -*-
"""
저점(1~3점) 리뷰 증거 추출 프로브.
- 상품 URL을 직접 받거나(brand.naver.com / smartstore.naver.com),
- 페이지/네트워크에서 originProductNo + checkoutMerchantNo 자동 추출
- in-session fetch로 page 1~MAXPAGE, REVIEW_CREATE_DATE_DESC(최신순) 수집
- reviewScore 1~3만 필터해서 출력
사용: python scripts/review_lowstar_probe.py <product_url> [--pages N] [--headful]
"""
import sys, json, time, re
args = [a for a in sys.argv[1:] if not a.startswith("--")]
HEADFUL = "--headful" in sys.argv
MAXPAGE = 5
for i, a in enumerate(sys.argv):
    if a == "--pages" and i + 1 < len(sys.argv):
        MAXPAGE = int(sys.argv[i + 1])
URL = args[0] if args else "https://brand.naver.com/aromatica/products/8734492045"

from playwright.sync_api import sync_playwright
def log(*a): print(*a, flush=True)

FETCH_JS = r"""
async (cfg) => {
  const {merchant, origin, page, sort} = cfg;
  const body = {checkoutMerchantNo:Number(merchant), originProductNo:Number(origin),
                page:page, pageSize:20, reviewSearchSortType:sort};
  const r = await fetch(location.origin + "/n/v1/contents/reviews/query-pages", {
    method:"POST", headers:{"Content-Type":"application/json","Accept":"application/json"},
    body: JSON.stringify(body), credentials:"include"});
  const txt = await r.text();
  let j=null; try{j=JSON.parse(txt);}catch(e){}
  let out=[];
  if(j && j.contents){
    out = j.contents.map(c=>({
      score: c.reviewScore,
      text: (c.reviewContent||"").trim(),
      date: c.createDate || c.registerDate || null,
      productName: c.productName || c.reviewProductName || null
    }));
  }
  return {status:r.status, total: j?j.totalElements:null, count: out.length, reviews: out};
}
"""

IDPICK_JS = r"""
() => {
  const html = document.documentElement.innerHTML;
  const pick = (re) => { const m = html.match(re); return m ? m[1] : null; };
  let origin = pick(/"originProductNo"\s*:\s*"?(\d+)"?/) || pick(/originProductNo[=:]\s*"?(\d+)"?/);
  let merchant = pick(/"checkoutMerchantNo"\s*:\s*"?(\d+)"?/) || pick(/checkoutMerchantNo[=:]\s*"?(\d+)"?/);
  let name = pick(/"productName"\s*:\s*"([^"]{2,80})"/) || (document.title||"").slice(0,80);
  return {origin, merchant, name};
}
"""

def run(url, headful, maxpage):
    sniff = {"origin": None, "merchant": None}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=not headful,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"), locale="ko-KR",
              viewport={"width":1366,"height":900})
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        pg = ctx.new_page()
        def on_req(req):
            u = req.url
            m = re.search(r"/reviews/product-summary/(\d+)", u)
            if m:
                sniff["origin"] = m.group(1)
                mm = re.search(r"checkoutMerchantNo=(\d+)", u)
                if mm: sniff["merchant"] = mm.group(1)
        pg.on("request", on_req)
        log(f"[nav] {url}")
        resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
        log(f"[nav] status={resp.status if resp else None} title={pg.title()[:60]!r}")
        time.sleep(6)
        ids = pg.evaluate(IDPICK_JS)
        origin = ids.get("origin") or sniff["origin"]
        merchant = ids.get("merchant") or sniff["merchant"]
        name = ids.get("name")
        log(f"[ids] origin={origin} merchant={merchant} name={name!r} (sniff={sniff})")
        if not (origin and merchant):
            log("[FAIL] could not resolve originProductNo/checkoutMerchantNo")
            b.close(); return None

        all_reviews = []
        total = None
        for page in range(1, maxpage + 1):
            res = pg.evaluate(FETCH_JS, {"merchant": merchant, "origin": origin,
                                         "page": page, "sort": "REVIEW_SCORE_ASC"})
            total = res.get("total")
            log(f"[fetch] page={page} status={res['status']} got={res['count']} total={total}")
            if not res.get("reviews"):
                break
            all_reviews.extend(res["reviews"])
            time.sleep(1.2)
        b.close()

    low = [r for r in all_reviews if r["score"] in (1, 2, 3)]
    log("=" * 70)
    log(f"[SUMMARY] product={name!r} total_reviews={total} "
        f"fetched={len(all_reviews)} low(1-3)={len(low)}")
    log(f"[SCORE DIST] " + ", ".join(
        f"{s}점:{sum(1 for r in all_reviews if r['score']==s)}" for s in (1,2,3,4,5)))
    log("=" * 70)
    for i, r in enumerate(low, 1):
        txt = r["text"].replace("\n", " ").replace("\r", " ").strip()
        log(f"[{i}] ★{r['score']} | {r['date']} | {txt[:300]}")
    return {"name": name, "total": total, "low": low, "all": all_reviews}

if __name__ == "__main__":
    run(URL, HEADFUL, MAXPAGE)
