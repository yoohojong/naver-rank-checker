"""피퓨 · 나보소 상세페이지 받기 (읽기 전용 · 손으로 부를 때만). 지시 1117-1610 · 2026-11-17.
네이버 · 쿠팡 공개 상품 화면의 글자 · 상세 이미지 · 상품정보 고시를 받아 out/ 에 남긴다. 아무것도 쓰지 않는다."""
import json, os, re, sys, time, random, hashlib, pathlib, urllib.parse, traceback
import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("out")
(OUT / "img").mkdir(parents=True, exist_ok=True)
(OUT / "pages").mkdir(exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
BRAND = re.compile(r"피퓨|PIPIU|힐링바운스|나보소|NABOSO|뉴로볼|뉴로스틱|neuro ?ball", re.I)
MODE = os.environ.get("MODE", "all")
EXTRA = [u.strip() for u in os.environ.get("EXTRA_URLS", "").split(",") if u.strip()]
NAVER_STORES = [u.strip() for u in os.environ.get("NAVER_STORES", "").split(",") if u.strip()]
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(u):
    return re.sub(r"[^A-Za-z0-9]+", "_", u)[-90:]


def naver_api():
    cid, sec = os.environ.get("NCID"), os.environ.get("NSEC")
    if not cid:
        log("api: 열쇠 없음")
        return []
    qs = ["피퓨", "피퓨 힐링바운스", "피퓨 슬리퍼", "피퓨 샌들", "피퓨 클로그", "피퓨 깔창", "PIPIU",
          "나보소", "나보소 뉴로볼", "나보소 스플레이", "나보소 뉴로스틱", "naboso", "뉴로볼"]
    items = []
    for q in qs:
        for start in (1, 101):
            r = requests.get("https://openapi.naver.com/v1/search/shop.json",
                             params={"query": q, "display": 100, "start": start, "sort": "sim"},
                             headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec}, timeout=20)
            j = r.json() if r.ok else {}
            got = j.get("items", [])
            log("api", q, start, r.status_code, len(got))
            for it in got:
                it["_q"] = q
                items.append(it)
            time.sleep(0.3)
            if len(got) < 100:
                break
    dump("naver_api_all.json", items)
    keep = [it for it in items if BRAND.search(re.sub("<[^>]+>", "", it.get("title", "")) + " " + it.get("brand", "") + " " + it.get("maker", ""))]
    dedup = {}
    for it in keep:
        dedup[it["productId"] + "|" + it["mallName"]] = it
    keep = list(dedup.values())
    dump("naver_api_brand.json", keep)
    log("api brand items", len(keep))
    return keep


IMG_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const im of document.querySelectorAll('img')) {
    const src = im.currentSrc || im.src || '';
    const ds = im.getAttribute('data-src') || im.getAttribute('data-original') || '';
    for (const u of [src, ds]) {
      if (!u || u.startsWith('data:') || seen.has(u)) continue;
      seen.add(u);
      const r = im.getBoundingClientRect();
      out.push({u, w: im.naturalWidth, h: im.naturalHeight, y: Math.round(r.top + window.scrollY), alt: (im.alt||'').slice(0,120)});
    }
  }
  return out;
}
"""

LINKS_JS = r"""
() => [...document.querySelectorAll('a[href]')].map(a => [a.href, (a.innerText||a.title||'').replace(/\s+/g,' ').trim().slice(0,160)])
"""


def scroll_all(page, rounds=40):
    last = -1
    for i in range(rounds):
        try:
            page.mouse.wheel(0, 2500)
        except Exception:
            page.evaluate("window.scrollBy(0, 2500)")
        page.wait_for_timeout(500)
        h = page.evaluate("document.body ? document.body.scrollHeight : 0")
        y = page.evaluate("window.scrollY + window.innerHeight")
        if y >= h - 10 and i > 4:
            if h == last:
                break
            last = h


def click_texts(page, texts):
    for t in texts:
        try:
            loc = page.get_by_text(t, exact=False)
            n = loc.count()
            for k in range(min(n, 3)):
                try:
                    loc.nth(k).click(timeout=2000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
        except Exception:
            pass


def grab(page, url, tag, net):
    rec = {"tag": tag, "url": url}
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        rec["status"] = resp.status if resp else None
        page.wait_for_timeout(4000)
        rec["final"] = page.url
        rec["title"] = page.title()
        click_texts(page, ["상세정보 펼쳐보기", "상품정보 더보기", "상세정보 더보기"])
        scroll_all(page)
        click_texts(page, ["상세정보 펼쳐보기", "상품정보 더보기", "필수 표기정보", "판매자 정보", "판매자정보"])
        scroll_all(page, 15)
        rec["text"] = page.evaluate("document.body ? document.body.innerText : ''")
        rec["imgs"] = page.evaluate(IMG_JS)
        html = page.content()
        rec["html_len"] = len(html)
        (OUT / "pages" / f"{tag}_{slug(url)}.html").write_text(html, encoding="utf-8")
        rec["net"] = net[:]
        log("grab", tag, url, rec.get("status"), rec["final"], len(rec["text"]), len(rec["imgs"]))
        if rec.get("status") and rec["status"] >= 400:
            rec["body_head"] = rec["text"][:1500]
    except Exception as e:
        rec["error"] = repr(e)[:500]
        log("grab ERR", tag, url, rec["error"][:200])
    return rec


def harvest_links(page, pat):
    hrefs = page.evaluate(LINKS_JS)
    return [(h, t) for h, t in hrefs if re.search(pat, h)]


def run_naver(pw, api_items):
    b = pw.chromium.launch(headless=True, args=["--mute-audio"])
    ctx = b.new_context(user_agent=UA, locale="ko-KR", viewport={"width": 1400, "height": 1000})
    page = ctx.new_page()
    net = []

    def on_resp(r):
        u = r.url
        ct = r.headers.get("content-type") or ""
        if "json" in ct and re.search(r"/i/v\d/|product-info|contents|channels/.+/products|products/\d+", u):
            try:
                body = r.text()
                if len(body) < 3_000_000:
                    net.append({"u": u, "s": r.status, "b": body})
            except Exception:
                pass

    page.on("response", on_resp)
    cands = {}
    for q in ["피퓨", "피퓨 힐링바운스", "피퓨 슬리퍼", "피퓨 샌들", "피퓨 스마트스토어", "나보소 뉴로볼", "나보소", "나보소 스마트스토어", "필라티슈 나보소"]:
        try:
            page.goto("https://search.naver.com/search.naver?" + urllib.parse.urlencode({"query": q}), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            scroll_all(page, 6)
            links = harvest_links(page, r"(smartstore|brand)\.naver\.com/[A-Za-z0-9_\-]+")
            alll = harvest_links(page, r".")
            (OUT / f"naver_search_{slug(q)}_{abs(hash(q))%10000}.txt").write_text(
                page.evaluate("document.body.innerText") + "\n\n=== LINKS ===\n" + "\n".join(f"{t} -> {h}" for h, t in alll), encoding="utf-8")
            for h, t in links:
                cands.setdefault(h.split("?")[0], t)
            log("nsearch", q, len(links))
        except Exception as e:
            log("nsearch ERR", q, repr(e)[:200])
        time.sleep(random.uniform(2, 4))
    stores = set(NAVER_STORES)
    for u in cands:
        m = re.match(r"https?://(smartstore|brand)\.naver\.com/([A-Za-z0-9_\-]+)", u)
        if m and m.group(2) not in ("main", "inflow"):
            stores.add(f"https://{m.group(1)}.naver.com/{m.group(2)}")
    for s in ["https://smartstore.naver.com/balancedbody", "https://smartstore.naver.com/pipiu", "https://brand.naver.com/pipiu",
              "https://brand.naver.com/naboso", "https://smartstore.naver.com/naboso"]:
        stores.add(s)
    log("stores", sorted(stores))
    store_products = {}
    for s in sorted(stores):
        for path in ["/category/ALL?st=POPULAR&dt=LIST&page=1&size=80", ""]:
            try:
                r = page.goto(s + path, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                scroll_all(page, 10)
                txt = page.evaluate("document.body.innerText")
                links = harvest_links(page, r"/products/\d+")
                (OUT / f"store_{slug(s + path)}.txt").write_text(
                    f"STATUS {r.status if r else None}\nFINAL {page.url}\n\n{txt}\n\n=== LINKS ===\n" + "\n".join(f"{t} -> {h}" for h, t in links), encoding="utf-8")
                for h, t in links:
                    if BRAND.search(t) or re.search(r"pipiu|naboso", s):
                        store_products.setdefault(h.split("?")[0], t)
                log("store", s + path, r.status if r else None, page.url, len(links))
                if links:
                    break
            except Exception as e:
                log("store ERR", s, repr(e)[:200])
            time.sleep(random.uniform(2, 4))
    for it in api_items:
        link = it["link"]
        if "naver.com" in link:
            cands.setdefault(link, re.sub("<[^>]+>", "", it["title"]))
    targets = {}
    for u, t in list(cands.items()) + list(store_products.items()):
        if re.search(r"/products/\d+", u):
            targets.setdefault(u, t)
    for u in EXTRA:
        if "naver.com" in u:
            targets.setdefault(u, "extra")
    log("naver targets", len(targets))
    dump("naver_targets.json", targets)
    recs = []
    for i, (u, t) in enumerate(targets.items()):
        if i >= 70:
            break
        net.clear()
        recs.append(grab(page, u, "naver", net))
        dump("naver_pages.json", recs)
        time.sleep(random.uniform(3, 7))
    b.close()
    return recs


def run_coupang(pw):
    recs = []
    args = ["--disable-blink-features=AutomationControlled", "--mute-audio"]
    try:
        b = pw.chromium.launch(channel="chrome", headless=False, args=args)
    except Exception as e:
        log("chrome channel 실패, chromium", repr(e)[:200])
        b = pw.chromium.launch(headless=False, args=args)
    ctx = b.new_context(locale="ko-KR", viewport={"width": 1400, "height": 1000})
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()
    net = []

    def on_resp(r):
        u = r.url
        ct = r.headers.get("content-type") or ""
        if "coupang" in u and re.search(r"vendor|itemAttributes|essential|seller|btf|sdp|notice", u, re.I) and ("json" in ct or "html" in ct):
            try:
                body = r.text()
                if len(body) < 2_000_000:
                    net.append({"u": u, "s": r.status, "b": body[:400000]})
            except Exception:
                pass

    page.on("response", on_resp)
    try:
        r = page.goto("https://www.coupang.com/", wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3000)
        log("coupang home", r.status if r else None, page.title())
        (OUT / "coupang_home.txt").write_text(f"STATUS {r.status if r else None}\nTITLE {page.title()}\n" + page.evaluate("document.body ? document.body.innerText.slice(0,3000) : ''"), encoding="utf-8")
    except Exception as e:
        log("coupang home ERR", repr(e)[:200])
    targets = {}
    for q in ["피퓨", "피퓨 힐링바운스", "피퓨 슬리퍼", "나보소 뉴로볼", "나보소", "naboso"]:
        try:
            r = page.goto("https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": q, "channel": "user"}), wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(4000)
            scroll_all(page, 8)
            txt = page.evaluate("document.body ? document.body.innerText : ''")
            links = harvest_links(page, r"/vp/products/\d+")
            (OUT / f"coupang_search_{abs(hash(q))%100000}.txt").write_text(
                f"QUERY {q}\nSTATUS {r.status if r else None}\nFINAL {page.url}\n\n{txt}\n\n=== LINKS ===\n" + "\n".join(f"{t} -> {h}" for h, t in links), encoding="utf-8")
            log("csearch", q, r.status if r else None, len(links))
            for h, t in links:
                if BRAND.search(t):
                    targets.setdefault(h, t)
        except Exception as e:
            log("csearch ERR", q, repr(e)[:200])
        time.sleep(random.uniform(4, 8))
    for u in EXTRA + ["https://www.coupang.com/vp/products/8042533910"]:
        if "coupang" in u:
            targets.setdefault(u, "extra")
    by_pid = {}
    for u, t in targets.items():
        m = re.search(r"/vp/products/(\d+)", u)
        if m:
            by_pid.setdefault(m.group(1), (u, t))
    dump("coupang_targets.json", by_pid)
    log("coupang targets", len(by_pid))
    for i, (pid, (u, t)) in enumerate(by_pid.items()):
        if i >= 50:
            break
        net.clear()
        recs.append(grab(page, u, "coupang", net))
        dump("coupang_pages.json", recs)
        time.sleep(random.uniform(5, 10))
    b.close()
    return recs


def download(recs):
    mp = {}
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    for rec in recs:
        ref = rec.get("final") or rec["url"]
        for im in rec.get("imgs", []):
            u = im["u"]
            if u in mp:
                continue
            if not re.search(r"pstatic|phinf|coupangcdn|naver\.net", u):
                continue
            if im.get("w") and im["w"] < 300 and im.get("h", 0) < 300:
                continue
            try:
                r = s.get(u, headers={"Referer": ref}, timeout=30)
                if r.ok and len(r.content) > 3000:
                    m = re.search(r"\.(jpe?g|png|gif|webp)", u.lower())
                    ext = m.group(1) if m else "jpg"
                    fn = hashlib.sha1(u.encode()).hexdigest()[:16] + "." + ext
                    (OUT / "img" / fn).write_bytes(r.content)
                    mp[u] = fn
            except Exception as e:
                log("img ERR", u[:120], repr(e)[:100])
    dump("img_map.json", mp)
    log("images", len(mp))


with sync_playwright() as pw:
    allrecs = []
    if MODE in ("all", "naver"):
        try:
            api = naver_api()
            allrecs += run_naver(pw, api)
        except Exception:
            log("naver fatal", traceback.format_exc()[-800:])
    if MODE in ("all", "coupang"):
        try:
            allrecs += run_coupang(pw)
        except Exception:
            log("coupang fatal", traceback.format_exc()[-800:])
    try:
        download(allrecs)
    except Exception:
        log("download fatal", traceback.format_exc()[-800:])
(OUT / "log.txt").write_text("\n".join(LOG), encoding="utf-8")
