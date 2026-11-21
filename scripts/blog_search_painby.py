import json, os, re, time, urllib.parse, urllib.request, html
ID=os.environ.get("NAVER_OPENAPI_CLIENT_ID",""); SEC=os.environ.get("NAVER_OPENAPI_CLIENT_SECRET","")
KW=["올위버","올위버깔창","올위버 깔창","올,위버","올위버 후기","올위버깔창 후기","올위버 뒤꿈치","올위버 포론","올위버 족저근막염","올위버 추천","뒤꿈치 전문 깔창","족저근막염 깔창 추천 올위버","allubermall","올위버몰"]
REL=re.compile("올\W{0,3}위\W{0,3}버|allubermall")
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
