"""여성향 성인물 국내 글 모으기 (2026-11-23 · 읽기 전용 · 공식 검색 API · 제목/요약/주소만 저장)."""
import html, json, os, re, time, urllib.parse, urllib.request
ID=os.environ.get("NAVER_OPENAPI_CLIENT_ID",""); SEC=os.environ.get("NAVER_OPENAPI_CLIENT_SECRET","")
TAG=re.compile(r"<[^>]+>")
def clean(t): return html.unescape(TAG.sub("",t or "")).strip()
def search(kind,q,start,sort):
    url="https://openapi.naver.com/v1/search/%s.json?"%kind+urllib.parse.urlencode({"query":q,"display":100 if kind!="doc" else 100,"start":start,"sort":sort})
    req=urllib.request.Request(url,headers={"X-Naver-Client-Id":ID,"X-Naver-Client-Secret":SEC})
    try:
        with urllib.request.urlopen(req,timeout=25) as r: return r.status,json.loads(r.read().decode()).get("items",[])
    except Exception as e: return getattr(e,"code",0),[]
KW=json.load(open("data/women_adult_1123.json",encoding="utf-8"))
os.makedirs("out",exist_ok=True); out=[]; log=[]
for kind in KW["kinds"]:
    for q in KW["queries"]:
        for sort in ("sim","date"):
            if kind=="doc" and sort=="date": continue
            for p in range(KW["pages"]):
                c,items=search(kind,q,1+100*p,sort); log.append([kind,q,sort,p,c,len(items)]); time.sleep(0.15)
                for it in items:
                    out.append({"kind":kind,"q":q,"title":clean(it.get("title")),"desc":clean(it.get("description")),"link":it.get("link"),"date":it.get("postdate") or it.get("pubDate") or "","who":it.get("cafename") or it.get("bloggername") or it.get("publisher") or ""})
                if len(items)<100: break
json.dump({"log":log,"items":out},open("out/search.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("총",len(out))
