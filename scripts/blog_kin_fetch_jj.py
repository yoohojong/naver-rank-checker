"""블로그 · 지식인 글 본문 받기 (2026-11-21 · 족저근막염 키워드 9장 보강 · 읽기 전용 · 새 파일만).
1) 공식 검색 API(blog · kin)로 글 목록  2) 블로그는 공개 모바일 글 주소, 지식인은 공개 상세 주소로 본문.
로그인 필요 글은 상태 코드만 남긴다(우회 안 함). 설정: data/blog_kin_fetch_jj.json"""
import html, json, os, re, time, urllib.parse, urllib.request
CFG = json.load(open("data/blog_kin_fetch_jj.json", encoding="utf-8"))
ID = os.environ.get("NAVER_OPENAPI_CLIENT_ID", ""); SEC = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
os.makedirs("out/blog", exist_ok=True); os.makedirs("out/kin", exist_ok=True)
TAG = re.compile(r"<[^>]+>")
REL = re.compile(CFG["relevance"])
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
def blog_key(link):
    m = re.search(r"blog\.naver\.com/([A-Za-z0-9_\-\.]+)/(\d+)", link) or re.search(r"blog\.naver\.com/PostView\.naver\?blogId=([A-Za-z0-9_\-\.]+)&logNo=(\d+)", link)
    return (m.group(1), m.group(2)) if m else None
def kin_key(link):
    m = re.search(r"d1id=(\d+).*?dirId=(\d+).*?docId=(\d+)", link)
    if m: return m.groups()
    m = re.search(r"dirId=(\d+).*?docId=(\d+)", link)
    return ("", m.group(1), m.group(2)) if m else None
cands = {"blog": {}, "kin": {}}; log = []
for q in CFG["keywords"]:
    for kind, pages in (("blog", CFG["pages_blog"]), ("kin", CFG["pages_kin"])):
        for sort in ("sim", "date"):
            for p in range(pages if sort == "sim" else 1):
                c, items = search(kind, q, 1 + 100 * p, sort); log.append([kind, q, sort, p, c, len(items)])
                time.sleep(0.15)
                for it in items:
                    k = (blog_key if kind == "blog" else kin_key)(it.get("link", ""))
                    if not k: continue
                    title, desc = clean(it.get("title")), clean(it.get("description"))
                    d = cands[kind].setdefault(k, {"link": it["link"], "title": title, "desc": desc, "q": [], "rel": False, "date": it.get("postdate", ""), "who": it.get("bloggername", "")})
                    d["q"].append(q)
                    if REL.search(title + " " + desc): d["rel"] = True
                if len(items) < 100: break
json.dump({"log": log, "blog": {"%s/%s" % k: v for k, v in cands["blog"].items()}, "kin": {"/".join(k): v for k, v in cands["kin"].items()}}, open("out/search.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
tb = [k for k, v in cands["blog"].items() if v["rel"]][: CFG["max_blog"]]
tk = [k for k, v in cands["kin"].items() if v["rel"]][: CFG["max_kin"]]
print("후보 blog", len(cands["blog"]), "kin", len(cands["kin"]), "받을 blog", len(tb), "kin", len(tk), flush=True)
index, t0 = [], time.time()
for i, (bid, no) in enumerate(tb):
    if time.time() - t0 > CFG["max_seconds"]: print("시간 끝", i, flush=True); break
    url = "https://m.blog.naver.com/PostView.naver?blogId=%s&logNo=%s" % (bid, no)
    c, b = http(url, {"User-Agent": UA, "Referer": "https://m.blog.naver.com/"})
    rec = {"kind": "blog", "blogId": bid, "logNo": no, "status": c, "len": len(b), "title": cands["blog"][(bid, no)]["title"]}
    if c == 200:
        j = b.find("se-main-container")
        if j < 0: j = b.find("post_ct")
        if j < 0: j = b.find("postViewArea")
        rec["marker"] = j
        seg = b[j - 200:j + 60000] if j >= 0 else b[:20000]
        open("out/blog/%s_%s.html" % (bid, no), "w", encoding="utf-8").write(seg)
        mt = re.search(r"<title>(.*?)</title>", b, re.S); rec["page_title"] = clean(mt.group(1)) if mt else ""
        md = re.search(r"se_publishDate[^>]*>([^<]+)<", b); rec["pub"] = md.group(1) if md else ""
    index.append(rec); time.sleep(0.9)
    if i % 25 == 0: print("blog", i, c, len(b), bid, no, flush=True)
for i, (d1, dr, doc) in enumerate(tk):
    if time.time() - t0 > CFG["max_seconds"]: print("시간 끝 kin", i, flush=True); break
    url = "https://kin.naver.com/qna/detail.naver?d1id=%s&dirId=%s&docId=%s" % (d1, dr, doc) if d1 else "https://kin.naver.com/qna/detail.naver?dirId=%s&docId=%s" % (dr, doc)
    c, b = http(url, {"User-Agent": UA, "Referer": "https://kin.naver.com/"})
    rec = {"kind": "kin", "d1": d1, "dir": dr, "doc": doc, "status": c, "len": len(b), "title": cands["kin"][(d1, dr, doc)]["title"]}
    if c == 200:
        j = b.find("endContentsText"); 
        if j < 0: j = b.find("questionDetail")
        if j < 0: j = b.find("c-heading")
        rec["marker"] = j
        seg = b[max(0, j - 3000):j + 60000] if j >= 0 else b[:30000]
        open("out/kin/%s_%s_%s.html" % (d1, dr, doc), "w", encoding="utf-8").write(seg)
    index.append(rec); time.sleep(0.9)
    if i % 25 == 0: print("kin", i, c, len(b), dr, doc, flush=True)
json.dump(index, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(index), "blog 200", sum(1 for r in index if r["kind"] == "blog" and r["status"] == 200), "kin 200", sum(1 for r in index if r["kind"] == "kin" and r["status"] == 200))
