# -*- coding: utf-8 -*-
"""족저근막염 대안 24종 — 네이버 상품 1·2점 후기 받기 (읽기 전용, 손으로 부를 때만). 지시 1118-0231.
통합검색에서 brand/smartstore 상품 주소를 모으고, 상품 화면이 쓰는 후기 목록 주소(query-pages)를
별점 낮은 순으로 불러 1·2점만 남긴다. 쿠팡은 서버에서 403 이라 첫 화면 상태만 기록한다."""
import json, os, re, sys, time, random, pathlib, urllib.parse
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("out"); OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
KEYWORDS = [k.strip() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]
TOP = int(os.environ.get("TOP_PRODUCTS", "8"))
MAXPAGES = int(os.environ.get("MAX_PAGES", "12"))
MAXSCORE = 2
LOG = []
URL_RE = re.compile(r"https?://(?:brand|smartstore)\.naver\.com/[A-Za-z0-9_\-]+/products/\d+")
LOGINWALL = re.compile(r"^https?://smartstore\.naver\.com/main/products/\d+$")
ORIGIN_RE = re.compile(r"/reviews/product-summary/(\d+)")
MERCH_RE = re.compile(r"checkoutMerchantNo=(\d+)")


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


FETCH_JS = r"""
async (cfg) => {
  try {
    const r = await fetch(location.origin + cfg.path, {method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify({checkoutMerchantNo: Number(cfg.merchant), originProductNo: Number(cfg.origin),
        page: cfg.page, pageSize: 20, reviewSearchSortType: "REVIEW_SCORE_ASC"}), credentials: "include"});
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) {}
    return {status: r.status, total: j ? j.totalElements : null, contents: j && j.contents ? j.contents : [], head: j ? null : t.slice(0, 200)};
  } catch (e) { return {status: -1, contents: [], error: String(e)}; }
}
"""
INFO_JS = r"""
() => {
  const h = document.documentElement.innerHTML;
  const pick = re => { const m = h.match(re); return m ? m[1] : null; };
  const meta = n => { const e = document.querySelector('meta[property="'+n+'"]'); return e ? e.content : null; };
  return {origin: pick(/"originProductNo"\s*:\s*"?(\d+)"?/), merchant: pick(/"checkoutMerchantNo"\s*:\s*"?(\d+)"?/),
    name: meta('og:title') || document.title, price: meta('product:price:amount') || pick(/"salePrice"\s*:\s*(\d+)/),
    reviewCount: pick(/"totalReviewCount"\s*:\s*(\d+)/), rating: pick(/"averageReviewScore"\s*:\s*([0-9.]+)/),
    wall: location.href.includes('nid.naver.com')}
}
"""


def search_products(pg, kw):
    pg.goto("https://search.naver.com/search.naver?query=" + urllib.parse.quote(kw), wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(3000)
    for _ in range(3):
        pg.mouse.wheel(0, 2200)
        pg.wait_for_timeout(900)
    try:
        anchors = pg.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)")
    except Exception:
        anchors = []
    blob = "\n".join(anchors) + "\n" + pg.content()
    seen = {}
    for m in URL_RE.finditer(blob):
        u = m.group(0)
        if LOGINWALL.match(u):
            continue
        seen.setdefault(u, None)
    return sorted(seen, key=lambda u: 0 if "brand.naver.com" in u else 1)


with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=["--mute-audio", "--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1366, "height": 2200})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    pg = ctx.new_page()
    sniff = {"o": None, "m": None}

    def on_req(req):
        m = ORIGIN_RE.search(req.url)
        if m:
            sniff["o"] = m.group(1)
            mm = MERCH_RE.search(req.url)
            if mm:
                sniff["m"] = mm.group(1)

    pg.on("request", on_req)
    try:
        r = pg.goto("https://www.coupang.com/", wait_until="domcontentloaded", timeout=30000)
        log("coupang home", r.status if r else None, pg.title())
    except Exception as e:
        log("coupang ERR", repr(e)[:150])
    for kw in KEYWORDS:
        rec = {"keyword": kw, "products": []}
        try:
            urls = search_products(pg, kw)
        except Exception as e:
            log("search ERR", kw, repr(e)[:150])
            urls = []
        log("search", kw, "상품주소", len(urls))
        rec["found_urls"] = urls
        for u in urls[:TOP]:
            sniff["o"] = sniff["m"] = None
            p = {"url": u, "reviews": []}
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(5000)
                info = pg.evaluate(INFO_JS)
                p["info"] = info
                o = info.get("origin") or sniff["o"]
                m = info.get("merchant") or sniff["m"]
                if info.get("wall") or not (o and m):
                    p["error"] = "식별자 못 얻음(로그인 벽 또는 화면 구조)"
                    log("  skip", u, p["error"], info.get("wall"))
                    rec["products"].append(p)
                    continue
                for page in range(1, MAXPAGES + 1):
                    res = pg.evaluate(FETCH_JS, {"merchant": m, "origin": o, "page": page, "path": "/n/v1/contents/reviews/query-pages"})
                    if res.get("status") != 200:
                        p["error"] = "후기 주소 %s %s" % (res.get("status"), res.get("head"))
                        break
                    p["total"] = res.get("total")
                    cs = res.get("contents") or []
                    if not cs:
                        break
                    stop = False
                    for c in cs:
                        sc = c.get("reviewScore")
                        if isinstance(sc, int) and sc > MAXSCORE:
                            stop = True
                            continue
                        p["reviews"].append(c)
                    if stop:
                        break
                    time.sleep(1.2)
                log("  product", u, "총후기", p.get("total"), "1·2점", len(p["reviews"]), p.get("error", ""))
            except Exception as e:
                p["error"] = repr(e)[:200]
                log("  product ERR", u, p["error"])
            rec["products"].append(p)
            time.sleep(random.uniform(4, 9))
        (OUT / ("kw_" + re.sub(r"[^0-9A-Za-z가-힣]+", "_", kw) + ".json")).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    b.close()
(OUT / "log.txt").write_text("\n".join(LOG), encoding="utf-8")
