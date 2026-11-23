"""족저근막염 대안 49개 국내 제품 수 (2026-11-23 · 읽기 전용 · 공식 네이버 쇼핑 검색 API · 새 파일만).
검색어 = 대안 이름. total = 검색 API가 돌려준 결과 총수, items = 앞 100개 상품 제목(어떤 상품이 걸렸는지 보려고)."""
import html, json, os, re, time, urllib.parse, urllib.request
ID = os.environ.get("NAVER_OPENAPI_CLIENT_ID", ""); SEC = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
TAG = re.compile(r"<[^>]+>")
def clean(t): return html.unescape(TAG.sub("", t or "")).strip()
def call(q, sort="sim"):
    url = "https://openapi.naver.com/v1/search/shop.json?" + urllib.parse.urlencode({"query": q, "display": 100, "start": 1, "sort": sort})
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC})
    try:
        with urllib.request.urlopen(req, timeout=25) as r: return r.status, json.loads(r.read().decode("utf-8"))
    except Exception as e:
        body = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
        return getattr(e, "code", 0), {"error": str(e)[:200], "body": body}
os.makedirs("out", exist_ok=True)
probe = {}
for nm, url in (("shop.json", "https://openapi.naver.com/v1/search/shop.json?query=%s&display=1"), ("shop.xml", "https://openapi.naver.com/v1/search/shop.xml?query=%s&display=1"), ("shop", "https://openapi.naver.com/v1/search/shop?query=%s&display=1"), ("shopping.json", "https://openapi.naver.com/v1/search/shopping.json?query=%s&display=1"), ("encyc.json", "https://openapi.naver.com/v1/search/encyc.json?query=%s&display=1"), ("news.json", "https://openapi.naver.com/v1/search/news.json?query=%s&display=1")):
    try:
        with urllib.request.urlopen(urllib.request.Request(url % urllib.parse.quote("깔창"), headers={"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC}), timeout=25) as r: probe[nm] = [r.status, r.read().decode()[:120]]
    except Exception as e: probe[nm] = [getattr(e, "code", 0), e.read().decode()[:160] if hasattr(e, "read") else str(e)]
print("probe", probe, flush=True)
json.dump(probe, open("out/probe.json", "w", encoding="utf-8"), ensure_ascii=False)
res = []
for q in json.load(open("data/shop_count_1123.json", encoding="utf-8"))["queries"]:
    c, j = call(q)
    rec = {"query": q, "status": c, "total": j.get("total"), "n_items": len(j.get("items", [])),
           "items": [{"title": clean(i.get("title")), "mall": i.get("mallName"), "lprice": i.get("lprice"), "cat": "/".join(x for x in [i.get("category1"), i.get("category2"), i.get("category3"), i.get("category4")] if x)} for i in j.get("items", [])]}
    if c != 200: rec["error"] = j
    res.append(rec); print(q, c, rec["total"], flush=True); time.sleep(0.2)
json.dump(res, open("out/shop_count.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(res), "200:", sum(1 for r in res if r["status"] == 200))
