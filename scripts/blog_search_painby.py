import json, os, re, time, urllib.parse, urllib.request, html
ID=os.environ.get("NAVER_OPENAPI_CLIENT_ID",""); SEC=os.environ.get("NAVER_OPENAPI_CLIENT_SECRET","")
KW=["올위버 깔창 후기","올위버 쿠션깔창","올위버 기능성깔창","올위버 아치","올위버 군화","올위버 운동화 깔창","올위버 내돈내산","올위버 사용기","올위버 평발","올 위버 깔창","올,위버 깔창","Alluber 깔창","올위버 신발","올위버 구매","올위버 비교","올위버깔창 효과","올위버 인솔","올위버 아킬레스","올위버 솔직후기","올위버 장단점","올위버 단점"]
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
