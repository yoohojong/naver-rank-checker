"""KC 인증 후기 받기 (2026-11-23 · 읽기 전용): 검색 API kin/cafearticle -> 지식인 공개 본문, 카페는 검색 요약 + 공개 글 API 시도."""
import html, json, os, re, time, urllib.parse, urllib.request
ID = os.environ.get("NAVER_OPENAPI_CLIENT_ID", ""); SEC = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
TAG = re.compile(r"<[^>]+>")
def clean(t): return html.unescape(TAG.sub("", t or "")).strip()
def http(url, headers, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))
calls = [0]
def search(kind, q, start, sort):
    calls[0] += 1
    url = "https://openapi.naver.com/v1/search/%s.json?" % kind + urllib.parse.urlencode({"query": q, "display": 100, "start": start, "sort": sort})
    c, b = http(url, {"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC})
    if c != 200: return c, []
    return c, json.loads(b).get("items", [])
CFG = json.load(open("data/kc_review_1123.json", encoding="utf-8"))
os.makedirs("out/kin", exist_ok=True); os.makedirs("out/cafe", exist_ok=True)
REL = re.compile(r"KC|인증|전자파|안전확인|적합|공급자|어댑터")
cands = {"kin": {}, "cafe": {}}; log = []
for kind in ("kin", "cafearticle"):
    key = "kin" if kind == "kin" else "cafe"
    for q in CFG["queries"]:
        for sort in ("sim", "date"):
            for p in range(CFG["pages"] if sort == "sim" else 1):
                c, items = search(kind, q, 1 + 100 * p, sort); log.append([kind, q, sort, p, c, len(items)]); time.sleep(0.15)
                for it in items:
                    l = it.get("link", ""); t, d = clean(it.get("title")), clean(it.get("description"))
                    if not REL.search(t + " " + d): continue
                    k = l.split("&", 1)[0] if key == "cafe" else l
                    cands[key].setdefault(k, {"link": l, "title": t, "desc": d, "q": [], "date": it.get("postdate", ""), "cafe": it.get("cafename", "")})["q"].append(q)
                if len(items) < 100: break
json.dump({"log": log, "cands": cands, "api_calls": calls[0]}, open("out/search.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("후보 kin", len(cands["kin"]), "cafe", len(cands["cafe"]), "api", calls[0], flush=True)
index = []
for i, (k, v) in enumerate(list(cands["kin"].items())[: CFG["max_kin"]]):
    c, b = http(v["link"], {"User-Agent": UA, "Referer": "https://kin.naver.com/"})
    rec = {"kind": "kin", "link": v["link"], "title": v["title"], "status": c, "len": len(b), "q": v["q"]}
    if c == 200:
        j = b.find("endContentsText")
        if j < 0: j = b.find("questionDetail")
        open("out/kin/%03d.html" % i, "w", encoding="utf-8").write(b[max(0, j - 3000): j + 60000] if j >= 0 else b[:30000]); rec["file"] = "kin/%03d.html" % i
    index.append(rec); time.sleep(0.9)
gate = {}
for i, (k, v) in enumerate(list(cands["cafe"].items())[: CFG["max_cafe"]]):
    m = re.search(r"cafe\.naver\.com/([A-Za-z0-9_\-]+)/(\d+)", v["link"])
    rec = {"kind": "cafe", "link": v["link"], "title": v["title"], "desc": v["desc"], "date": v["date"], "cafename": v["cafe"], "q": v["q"]}
    if m:
        cafe, aid = m.group(1), m.group(2); h = {"User-Agent": UA, "Referer": "https://m.cafe.naver.com/%s/%s" % (cafe, aid), "Accept": "application/json"}
        if cafe not in gate:
            c, b = http("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % cafe, h)
            try: gate[cafe] = json.loads(b)["message"]["result"]["cafeInfoView"]["cafeId"]
            except Exception: gate[cafe] = None
            time.sleep(0.4)
        if gate[cafe]:
            c, b = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true&requestFrom=A" % (gate[cafe], aid), h)
            rec["article_status"] = c
            try:
                j = json.loads(b); rec["ok"] = "article" in j.get("result", {}); rec["err"] = j.get("result", {}).get("errorCode", "")
            except Exception: rec["ok"] = False
            open("out/cafe/%03d.json" % i, "w", encoding="utf-8").write(b); rec["file"] = "cafe/%03d.json" % i
        else: rec["article_status"] = "카페 번호 못 얻음"
        time.sleep(0.8)
    index.append(rec)
json.dump(index, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(index), "kin200", sum(1 for r in index if r["kind"]=="kin" and r["status"]==200), "cafe ok", sum(1 for r in index if r.get("ok")))
