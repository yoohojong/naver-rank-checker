import json,re,html,time,urllib.request,os
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
os.makedirs("out",exist_ok=True);res=[]
for b,n in json.load(open("data/photo_blog_1122.json")):
    u=f"https://m.blog.naver.com/PostView.naver?blogId={b}&logNo={n}";st=0;h=""
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=25);h=r.read().decode("utf-8","replace");st=r.status
    except Exception as e: st=getattr(e,"code",0) or str(e)[:40]
    m=re.search(r'<div class="se-main-container">(.*)',h,re.S) or re.search(r'id="postViewArea"(.*)',h,re.S)
    body=m.group(1) if m else ""
    imgs=[];prev=""
    for p in re.split(r'(<img\b[^>]*>)',body):
        if p.startswith("<img"):
            s=re.search(r'(?:data-lazy-src|data-src|src)="([^"]+)"',p)
            if not s: continue
            s=html.unescape(s.group(1))
            if re.search(r'sticker|static\.|storep|profile|blogpfthumb|\.gif|ader\.naver',s): continue
            imgs.append([s,prev[-120:]])
        else:
            t=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'<(script|style)[^>]*>.*?</\1>','',p,flags=re.S)))).replace("\u200b","").strip()
            if t: prev=t
    res.append({"blog":b,"no":n,"status":st,"len":len(h),"has_body":bool(m),"imgs":imgs});print(b,n,st,len(h),len(imgs),flush=True);time.sleep(0.5)
json.dump(res,open("out/photo_blog_1122.json","w",encoding="utf-8"),ensure_ascii=False)
