"""회원 카페 298편 제목 검색 길 (2026-11-23 · 읽기 전용 · 로그인 0). 통합검색 카페 탭 HTML 에서 같은 카페 · 글 번호의 ?art= 주소를 찾아 글 API 로 받는다. 캡차 · 차단이 나오면 그 자리에서 멈춘다."""
import html, json, os, re, time, random, urllib.parse, urllib.request
SH = int(os.environ.get("SHARD", "0")); NS = int(os.environ.get("NSHARD", "1"))
CFG = json.load(open("data/cafe_title298.json", encoding="utf-8")); items = CFG["items"]
lim = CFG.get("limit")
if lim: items = items[:lim]
items = [x for i, x in enumerate(items) if i % NS == SH]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def http(url, headers, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))
os.makedirs("out/articles", exist_ok=True); os.makedirs("out/html", exist_ok=True)
index, gate, stop = [], {}, ""
t0 = time.time()
for i, it in enumerate(items):
    cafe, aid, title = it["cafe"], str(it["aid"]), it["title"]; rec = {"cafe": cafe, "aid": aid, "title": title}
    if not title: rec["result"] = "못 받음"; rec["reason"] = "제목 없음"; index.append(rec); continue
    q = urllib.parse.quote('"%s"' % title)
    c, b = http("https://search.naver.com/search.naver?ssc=tab.cafe.all&query=" + q, {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    rec["search_status"] = c; rec["html_len"] = len(b)
    open("out/html/%s_%s.html" % (cafe, aid), "w", encoding="utf-8").write(b[:400000])
    time.sleep(random.uniform(5, 7.5))
    if c in (403, 429) or "보안문자" in b or "자동입력 방지" in b or ("<title>" in b and "captcha" in b.split("</title>")[0].lower()):
        rec["result"] = "못 받음"; rec["reason"] = "막힘"; rec["detail"] = "검색 %s / 캡차·차단 문구" % c; index.append(rec); stop = "막힘에서 멈춤 %s %s" % (cafe, aid); break
    if c != 200: rec["result"] = "못 받음"; rec["reason"] = "막힘"; rec["detail"] = "검색 %s" % c; index.append(rec); stop = "검색 %s 에서 멈춤" % c; break
    links = re.findall(r"https?://cafe\.naver\.com/([A-Za-z0-9_\-]+)/(\d+)([^\"'\s<>]*)", html.unescape(b))
    same = [l for l in links if l[0] == cafe and l[1] == aid]; art = ""
    for l in same:
        m = re.search(r"[?&]art=([^&\"']+)", l[2])
        if m: art = m.group(1); break
    rec["cafe_links"] = len(links); rec["same_links"] = len(same); rec["has_art"] = bool(art)
    if not same: rec["result"] = "못 받음"; rec["reason"] = "검색 결과 없음" if not links else "번호 다름"; index.append(rec); continue
    if not art: rec["result"] = "못 받음"; rec["reason"] = "번호 다름"; rec["detail"] = "같은 글 주소는 있으나 ?art= 없음"; index.append(rec); continue
    ref = "https://m.cafe.naver.com/%s/%s" % (cafe, aid); h = {"User-Agent": UA, "Referer": ref, "Accept": "application/json"}
    if cafe not in gate:
        c2, b2 = http("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % cafe, h)
        try: gate[cafe] = json.loads(b2)["message"]["result"]["cafeInfoView"]["cafeId"]
        except Exception: gate[cafe] = None
        time.sleep(0.5)
    cid = gate[cafe]
    if not cid: rec["result"] = "못 받음"; rec["reason"] = "막힘"; rec["detail"] = "카페 번호 못 얻음"; index.append(rec); continue
    c3, b3 = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true&requestFrom=A&art=%s" % (cid, aid, art), h)
    rec["article_status"] = c3; ok = False
    try: j = json.loads(b3); ok = "article" in j.get("result", {}); rec["err"] = j.get("result", {}).get("errorCode", "")
    except Exception: pass
    comments = []
    if ok:
        for p in range(1, 8):
            time.sleep(0.8)
            c4, b4 = http("https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/%s/articles/%s/comments/pages/%d?requestFrom=A&orderBy=asc&art=%s" % (cid, aid, p, art), h)
            comments.append(b4)
            try:
                if not json.loads(b4)["result"]["comments"]["items"]: break
            except Exception: break
        json.dump({"article": b3, "comments": comments}, open("out/articles/%s_%s.json" % (cafe, aid), "w", encoding="utf-8"), ensure_ascii=False)
        rec["result"] = "받음"
    else:
        rec["result"] = "못 받음"; rec["reason"] = "막힘"; rec["detail"] = "글 API %s %s" % (c3, rec.get("err", ""))
    index.append(rec)
    if i % 10 == 0: print(i, rec["result"], rec.get("reason"), flush=True)
    time.sleep(random.uniform(5, 7.5))
    if time.time() - t0 > 5000: stop = "시간 끝 %d" % i; break
json.dump({"stop": stop, "shard": SH, "index": index, "start": t0, "end": time.time()}, open("out/index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(index), "받음", sum(1 for r in index if r["result"] == "받음"), stop)
