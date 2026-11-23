"""지식인 본문 + 회원 카페 310편 본문 받기 (2026-11-23 · 읽기 전용 · 새 파일만 · 로그인 우회 없음).
PART=A 지식인: 공식 검색 API(kin) 주소 → 공개 상세 주소 본문.
PART=B 카페 310편: 글 제목을 공식 검색 API(cafearticle)로 찾아 나온 ?art= 주소로 글 API 호출."""
import html, json, os, re, time, urllib.parse, urllib.request
PART = os.environ.get("PART", "A")
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
def search(kind, q, start, sort):
    url = "https://openapi.naver.com/v1/search/%s.json?" % kind + urllib.parse.urlencode({"query": q, "display": 100, "start": start, "sort": sort})
    c, b = http(url, {"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC})
    if c != 200: return c, []
    return c, json.loads(b).get("items", [])
os.makedirs("out/articles", exist_ok=True); os.makedirs("out/kin", exist_ok=True)
index, log = [], []
if PART == "A":
    CFG = json.load(open("data/kin_fetch_1123.json", encoding="utf-8")); REL = re.compile(CFG["relevance"])
    cands = {}
    for q in CFG["kin_keywords"]:
        for sort in ("sim", "date"):
            for p in range(CFG["pages_kin"] if sort == "sim" else 1):
                c, items = search("kin", q, 1 + 100 * p, sort); log.append([q, sort, p, c, len(items)]); time.sleep(0.15)
                for it in items:
                    m = re.search(r"dirId=(\d+).*?docId=(\d+)", it.get("link", ""))
                    if not m: continue
                    d1 = re.search(r"d1id=(\d+)", it["link"]); k = (d1.group(1) if d1 else "", m.group(1), m.group(2))
                    t, ds = clean(it.get("title")), clean(it.get("description"))
                    d = cands.setdefault(k, {"link": it["link"], "title": t, "desc": ds, "q": [], "rel": False}); d["q"].append(q)
                    if REL.search(t + " " + ds): d["rel"] = True
                if len(items) < 100: break
    json.dump({"log": log, "cands": {"/".join(k): v for k, v in cands.items()}}, open("out/search.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    todo = [k for k, v in cands.items() if v["rel"]][: CFG["max_kin"]]
    print("후보", len(cands), "받을", len(todo), flush=True); t0 = time.time()
    for i, (d1, dr, doc) in enumerate(todo):
        if time.time() - t0 > CFG["max_seconds"]: print("시간 끝", i, flush=True); break
        url = "https://kin.naver.com/qna/detail.naver?" + ("d1id=%s&" % d1 if d1 else "") + "dirId=%s&docId=%s" % (dr, doc)
        c, b = http(url, {"User-Agent": UA, "Referer": "https://kin.naver.com/"})
        rec = {"kind": "kin", "d1": d1, "dir": dr, "doc": doc, "status": c, "len": len(b), "title": cands[(d1, dr, doc)]["title"], "q": cands[(d1, dr, doc)]["q"]}
        if c == 200:
            j = b.find("endContentsText")
            if j < 0: j = b.find("questionDetail")
            if j < 0: j = b.find("c-heading")
            rec["marker"] = j
            open("out/kin/%s_%s_%s.html" % (d1, dr, doc), "w", encoding="utf-8").write(b[max(0, j - 3000): j + 60000] if j >= 0 else b[:30000])
        index.append(rec); time.sleep(0.9)
        if i % 25 == 0: print("kin", i, c, len(b), flush=True)
    json.dump(index, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("끝", len(index), "200:", sum(1 for r in index if r["status"] == 200))
else:
    items = json.load(open("data/cafe_member310.json", encoding="utf-8"))["items"]; gate = {}; t0 = time.time()
    for i, it in enumerate(items):
        cafe, aid, title = it["cafe"], it["aid"], it["title"]; rec = {"cafe": cafe, "aid": aid, "title": title}
        link = ""
        if title:
            for sort in ("sim", "date"):
                c, res = search("cafearticle", title, 1, sort); time.sleep(0.15)
                for r in res:
                    m = re.search(r"cafe\.naver\.com/([A-Za-z0-9_\-]+)/(\d+)", r.get("link", ""))
                    if m and m.group(1) == cafe and m.group(2) == aid: link = r["link"]; break
                if link: break
        rec["search_link"] = link; rec["has_art"] = "art=" in link
        ref = "https://m.cafe.naver.com/%s/%s" % (cafe, aid); h = {"User-Agent": UA, "Referer": ref, "Accept": "application/json"}
        art = ""; m = re.search(r"[?&]art=([^&]+)", link)
        if m: art = "&art=" + m.group(1)
        if cafe not in gate:
            c, b = http("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % cafe, h)
            try: gate[cafe] = json.loads(b)["message"]["result"]["cafeInfoView"]["cafeId"]
            except Exception: gate[cafe] = None
            time.sleep(0.4)
        cid = gate[cafe]
        if not cid: rec["status"] = "카페 번호 못 얻음"; index.append(rec); continue
        c, b = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true&requestFrom=A%s" % (cid, aid, art), h)
        rec["article_status"] = c; out = {"article": b}
        try: j = json.loads(b); rec["ok"] = "article" in j.get("result", {}); rec["err"] = j.get("result", {}).get("errorCode", "")
        except Exception: rec["ok"] = False
        comments = []
        if rec["ok"]:
            for p in range(1, 8):
                time.sleep(0.6)
                c2, b2 = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/%s/articles/%s/comments/pages/%d?requestFrom=A&orderBy=asc%s" % (cid, aid, p, art), h)
                comments.append(b2)
                try:
                    if not json.loads(b2)["result"]["comments"]["items"]: break
                except Exception: break
        out["comments"] = comments
        json.dump(out, open("out/articles/%s_%s.json" % (cafe, aid), "w", encoding="utf-8"), ensure_ascii=False)
        index.append(rec); time.sleep(0.8)
        if i % 25 == 0: print(i, rec.get("article_status"), rec.get("ok"), rec["has_art"], cafe, aid, flush=True)
        if time.time() - t0 > 2400: print("시간 끝", i, flush=True); break
    json.dump(index, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("끝", len(index), "성공", sum(1 for r in index if r.get("ok")), "art주소", sum(1 for r in index if r.get("has_art")))
