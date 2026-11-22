import json,re,html,os,urllib.request,urllib.parse,time
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
os.makedirs("out/img",exist_ok=True)
def get(u,ref="https://m.blog.naver.com/",ua=UA):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":ua,"Referer":ref}),timeout=30);return r.status,r.read(),r.headers.get("content-type","")
    except Exception as e: return getattr(e,"code",0) or str(e)[:80],b"",""
T=json.load(open("data/photo_rest_1122.json"));log=[]
def save(name,d): open("out/img/"+name,"wb").write(d)
def isimg(d): return d[:4] in (b"\x89PNG",b"\xff\xd8\xff\xe0",b"\xff\xd8\xff\xe1",b"\xff\xd8\xff\xdb",b"GIF8") or d[:4]==b"RIFF" or d[:3]==b"\xff\xd8\xff"
cache={}
for t in T:
    nm=t["file"].rsplit(".",1)[0];u=t["url"];res=[]
    cands=[u]
    host=urllib.parse.urlparse(u).netloc
    if host=="post-phinf.pstatic.net":
        for h in ("mblogthumb-phinf.pstatic.net","postfiles.pstatic.net"): cands.append(u.replace(host,h))
    if "%EB%B8%94" in host:
        pu=urllib.parse.urlparse(u);cands.append("http://xn--2i0bl9gt7ekxgr7lzzb.com"+pu.path+("?"+pu.query if pu.query else ""))
    ok=False
    for c in cands:
        st,d,ct=get(c);res.append([c[:90],st,len(d),ct])
        if st==200 and isimg(d): save(nm+".bin",d);ok=True;break
    if not ok and "blog.naver.com" in t["post"]:
        m=re.search(r"blog.naver.com/([^/]+)/(\d+)",t["post"])
        if m and m.group(2) not in cache:
            st,d,ct=get(f"https://m.blog.naver.com/PostView.naver?blogId={m.group(1)}&logNo={m.group(2)}");cache[m.group(2)]=d.decode("utf-8","replace");res.append(["page",st,len(d),ct])
        h=cache.get(m.group(2),"") if m else ""
        key=u.split("/")[3] if u.count("/")>3 else ""
        for s in set(re.findall(r'(?:data-lazy-src|data-src|src)="([^"]+)"',h)):
            s=html.unescape(s)
            if key and key in s:
                st,d,ct=get(s);res.append([s[:90],st,len(d),ct])
                if st==200 and isimg(d): save(nm+".bin",d);ok=True;break
    log.append({"t":t,"ok":ok,"res":res})
# camback
st,d,ct=get("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/camback/articles/38781?useCafeId=false","https://cafe.naver.com/","Mozilla/5.0")
imgs=[];cres=[st,len(d)]
if st==200:
    h=json.loads(d)["result"]["article"].get("contentHtml","")
    prev="";
    for p in re.split(r"(<img\b[^>]*>)",h):
        if p.startswith("<img"):
            m=re.search(r'src="([^"]+)"',p)
            if m: imgs.append([html.unescape(m.group(1)),prev[-120:]])
        else:
            tx=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",p))).replace("\u200b","").strip()
            if tx: prev=tx
cam=[]
for i,(s,pv) in enumerate(imgs,1):
    st,d,ct=get(s,"https://cafe.naver.com/")
    n="camback_38781_%02d"%i
    if st==200 and isimg(d): save(n+".bin",d)
    cam.append({"n":n,"url":s,"prev":pv,"st":st,"len":len(d),"ct":ct})
json.dump({"log":log,"cam":cam,"camapi":cres},open("out/photo_rest_1122.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(sum(1 for l in log if l["ok"]),len(log),sum(1 for c in cam if c["st"]==200),len(cam))
