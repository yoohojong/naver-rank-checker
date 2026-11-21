"""카페 글 본문 · 댓글 받기 (2026-11-18 · 족저근막염 잽 3단계 보강). 읽기 전용 · 새 파일만.
1) 공식 검색 API(cafearticle)로 키워드별 글 목록  2) 글마다 카페 글 API(공개 모바일 길)로 본문 · 댓글.
회원 전용 글은 상태 코드만 남긴다(로그인 우회 안 함). 설정: data/cafe_body_fetch_jj.json
"""
import html, json, os, re, time, urllib.parse, urllib.request
CFG = json.load(open("data/cafe_body_fetch_jj.json", encoding="utf-8"))
ID = os.environ.get("NAVER_OPENAPI_CLIENT_ID", ""); SEC = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
os.makedirs("out/articles", exist_ok=True)
TAG = re.compile(r"<[^>]+>")
REL = re.compile(CFG["relevance"])
def clean(t): return html.unescape(TAG.sub("", t or "")).strip()
def http(url, headers, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))
def search(q, start, sort):
    url = "https://openapi.naver.com/v1/search/cafearticle.json?" + urllib.parse.urlencode({"query": q, "display": 100, "start": start, "sort": sort})
    c, b = http(url, {"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC})
    if c != 200: return c, []
    return c, json.loads(b).get("items", [])
def key_of(link):
    m = re.search(r"cafe\.naver\.com/([A-Za-z0-9_\-]+)/(\d+)", link)
    return (m.group(1), m.group(2)) if m else None
cands = {}
for u in CFG["seed_urls"]:
    k = key_of(u)
    if k: cands.setdefault(k, {"link": u, "title": "", "desc": "", "q": ["seed"], "rel": True})
log = []
for q in CFG["keywords"]:
    for sort, pages in (("sim", CFG["pages_sim"]), ("date", CFG["pages_date"])):
        for p in range(pages):
            c, items = search(q, 1 + 100 * p, sort); log.append([q, sort, p, c, len(items)])
            time.sleep(0.15)
            for it in items:
                k = key_of(it.get("link", ""))
                if not k: continue
                title, desc = clean(it.get("title")), clean(it.get("description"))
                d = cands.setdefault(k, {"link": it["link"], "title": title, "desc": desc, "cafe": it.get("cafename"), "q": [], "rel": False})
                d["q"].append(q); d["title"] = d["title"] or title; d["desc"] = d["desc"] or desc
                if REL.search(title + " " + desc): d["rel"] = True
            if len(items) < 100: break
json.dump({"log": log, "cands": {"%s/%s" % k: v for k, v in cands.items()}}, open("out/search.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ALREADY = set(json.load(open("data/already_fetched.json", encoding="utf-8")))
todo = [k for k, v in cands.items() if v["rel"] and "%s/%s" % k not in ALREADY][: CFG["max_fetch"]]
print("이미 받은 것과 겹침", sum(1 for k, v in cands.items() if "%s/%s" % k in ALREADY))
print("후보", len(cands), "받을 글", len(todo), flush=True)
gate_cache, index, t0 = {}, [], time.time()
for i, (cafe, aid) in enumerate(todo):
    if time.time() - t0 > CFG["max_seconds"]:
        print("시간 끝 - 여기까지", i, flush=True); break
    v = cands[(cafe, aid)]; ref = "https://m.cafe.naver.com/%s/%s" % (cafe, aid)
    h = {"User-Agent": UA, "Referer": ref, "Accept": "application/json"}
    art = ""; m = re.search(r"[?&]art=([^&]+)", v["link"])
    if m: art = "&art=" + m.group(1)
    if cafe not in gate_cache:
        c, b = http("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % cafe, h)
        try: gate_cache[cafe] = json.loads(b)["message"]["result"]["cafeInfoView"]["cafeId"]
        except Exception: gate_cache[cafe] = None
        time.sleep(0.5)
    cid = gate_cache[cafe]; rec = {"cafe": cafe, "aid": aid, "cafeId": cid, "title": v["title"], "link": v["link"]}
    if not cid:
        rec["status"] = "카페 번호 못 얻음"; index.append(rec); continue
    c, b = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true&requestFrom=A%s" % (cid, aid, art), h)
    rec["article_status"] = c; out = {"article": b}
    try:
        j = json.loads(b); rec["ok"] = "article" in j.get("result", {})
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
    rec["comment_pages"] = len(comments); index.append(rec)
    time.sleep(0.8)
    if i % 25 == 0: print(i, rec.get("article_status"), rec.get("ok"), cafe, aid, flush=True)
json.dump(index, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(index), "성공", sum(1 for r in index if r.get("ok")))

# ---- 2회차 더함 (t_e9610256): 블로그 공식 검색 + 모바일 본문 받기 (읽기 전용) ----
if CFG.get("blog_keywords"):
    BREL = re.compile(CFG["blog_relevance"]); bh = {}; blog_log = []
    for q in CFG["blog_keywords"]:
        for sort, pages in (("sim", CFG.get("blog_pages_sim", 3)), ("date", CFG.get("blog_pages_date", 2))):
            for p in range(pages):
                url = "https://openapi.naver.com/v1/search/blog.json?" + urllib.parse.urlencode({"query": q, "display": 100, "start": 1 + 100 * p, "sort": sort})
                c, b = http(url, {"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SEC})
                try: items = json.loads(b).get("items", []) if c == 200 else []
                except Exception: items = []
                blog_log.append([q, sort, p, c, len(items)]); time.sleep(0.15)
                for it in items:
                    t, d = clean(it.get("title")), clean(it.get("description"))
                    if BREL.search(t + " " + d):
                        e = bh.setdefault(it["link"], {"title": t, "desc": d, "date": it.get("postdate", ""), "who": it.get("bloggername", ""), "q": []}); e["q"].append(q)
                if len(items) < 100: break
    os.makedirs("out/blog", exist_ok=True)
    stat = []
    SKIP = set(json.load(open("data/blog_skip.json", encoding="utf-8"))) if os.path.exists("data/blog_skip.json") else set()
    for link, v in bh.items():
        if link in SKIP: stat.append([link, "이미 받음 건너뜀", 0]); continue
        m = re.search(r"blog\.naver\.com/([^/?]+)/(\d+)", link) or re.search(r"blogId=([^&]+)&logNo=(\d+)", link)
        if not m: stat.append([link, "주소 못 읽음", 0]); continue
        bid, no = m.groups()
        u = "https://m.blog.naver.com/PostView.naver?blogId=%s&logNo=%s" % (bid, no)
        c, b = http(u, {"User-Agent": UA}, 25)
        open("out/blog/%s_%s.html" % (bid, no), "w", encoding="utf-8").write(b)
        stat.append([link, c, len(b)]); time.sleep(0.5)
    json.dump({"log": blog_log, "hits": bh, "stat": stat}, open("out/blog_hits.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("블로그 후보", len(bh), "호출", len(blog_log), "200 아님", sum(1 for l in blog_log if l[3] != 200), flush=True)
