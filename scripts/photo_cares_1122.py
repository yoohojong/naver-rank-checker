import json,re,html,time,urllib.request,os,concurrent.futures as cf
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mobile/15E148) AppleWebKit/605.1.15 Mobile/15E148".replace("like Mobile/15E148)","like Mac OS X)")
os.makedirs("out",exist_ok=True)
def go(bn):
    b,n=bn
    u=f"https://m.blog.naver.com/PostView.naver?blogId={b}&logNo={n}";st=0;h=""
    for t in range(2):
        try:
            r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=25);h=r.read().decode("utf-8","replace");st=r.status;break
        except Exception as e: st=getattr(e,"code",0) or str(e)[:40];time.sleep(1)
    m=re.search(r'<div class="se-main-container">(.*)',h,re.S) or re.search(r'id="postViewArea"(.*)',h,re.S)
    body=m.group(1) if m else ""
    imgs=[];prev="";raws=[]
    for p in re.split(r'(<img\b[^>]*>)',body):
        if p.startswith("<img"):
            at=dict(re.findall(r'([\w-]+)="([^"]*)"',p))
            if len(raws)<6 and "blur" in p: raws.append(p[:700])
            s=at.get("data-lazy-src") or at.get("data-src") or at.get("src")
            if not s: continue
            s=html.unescape(s)
            if re.search(r'sticker|ssl.pstatic.net/static|storep|bstatic.naver|profile|blogpfthumb|\.gif|ader\.naver',s): continue
            imgs.append([s,prev[-120:]])
        else:
            t=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'<(script|style)[^>]*>.*?</\1>','',p,flags=re.S)))).replace("\u200b","").strip()
            if t: prev=t
    time.sleep(0.3)
    return {"blog":b,"no":n,"status":st,"len":len(h),"has_body":bool(m),"imgs":imgs,"raws":raws}
with cf.ThreadPoolExecutor(4) as ex: res=list(ex.map(go,json.load(open("data/photo_cares_1122.json"))))
print(len(res),sum(1 for r in res if r["has_body"]),sum(len(r["imgs"]) for r in res))
json.dump(res,open("out/photo_cares_1122.json","w",encoding="utf-8"),ensure_ascii=False)
# r3
