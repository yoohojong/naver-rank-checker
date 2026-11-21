import json, os, re, time, urllib.parse, urllib.request, html
ID=os.environ.get("NAVER_OPENAPI_CLIENT_ID",""); SEC=os.environ.get("NAVER_OPENAPI_CLIENT_SECRET","")
KW=["페인바이","페인버리","painbury","디프티 페인바이","디프티페인바이","페인바이 후기","페인바이 내돈내산","페인바이 효과","페인바이 족저근막염","페인바이 발","페인바이 저주파기","속근 저주파기","저주파 100hz 족저근막염","저주파 보호대 100Hz","difti 저주파","페인버리 바디이지","페인바이 단점","페인바이 광고"]
REL=re.compile("페인바이|페인버리|painbury|difti|디프티")
os.makedirs("out",exist_ok=True)
res={}; log=[]
for kind in ("blog","webkr"):
  for q in KW:
    for sort in ("sim","date"):
      for p in range(3 if sort=="sim" else 2):
        url="https://openapi.naver.com/v1/search/%s.json?"%kind+urllib.parse.urlencode({"query":q,"display":100,"start":1+100*p,"sort":sort})
        req=urllib.request.Request(url,headers={"X-Naver-Client-Id":ID,"X-Naver-Client-Secret":SEC})
        try:
            with urllib.request.urlopen(req,timeout=25) as r: items=json.loads(r.read().decode()).get("items",[]); c=200
        except Exception as e:
            c=getattr(e,"code",0); items=[]
        log.append([kind,q,sort,p,c,len(items)]); time.sleep(0.12)
        for it in items:
            t=html.unescape(re.sub("<[^>]+>","",it.get("title",""))); d=html.unescape(re.sub("<[^>]+>","",it.get("description","")))
            if REL.search(t+d):
                k=it["link"]; e=res.setdefault(k,{"title":t,"desc":d,"date":it.get("postdate",""),"who":it.get("bloggername",""),"q":[],"kind":kind})
                e["q"].append(q)
        if len(items)<100: break
json.dump({"log":log,"hits":res},open("out/blog_hits.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("hits",len(res),"calls",len(log),"non200",sum(1 for l in log if l[4]!=200))
