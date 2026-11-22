import json,re,html,time,urllib.request,os,concurrent.futures as cf
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
os.makedirs("out",exist_ok=True)
def fetch(u):
    st=0;h=""
    for t in range(3):
        try:
            r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA,"Accept-Language":"ko"}),timeout=30)
            raw=r.read();st=r.status
            m=re.search(rb'charset=["\']?([\w-]+)',raw[:3000]);enc=m.group(1).decode() if m else "utf-8"
            try:h=raw.decode(enc,"replace")
            except Exception:h=raw.decode("utf-8","replace")
            break
        except Exception as e:
            st=getattr(e,"code",0) or str(e)[:60];time.sleep(2)
    return st,h
def body_of(h):
    pats=[r'<div class="(?:tt_article_useless_p_margin[^"]*|contents_style[^"]*)"[^>]*>(.*?)(?=<div class="(?:container_postbtn|another_category|area_reaction)|<div class="comment|</article>)',
          r'<div class="[^"]*entry-content[^"]*"[^>]*>(.*?)(?=<div class="[^"]*(?:comment|related|sharing)|</article>)',
          r'<div class=[\'"][^\'"]*post-body[^\'"]*[\'"][^>]*>(.*?)(?=<div class=[\'"]post-footer|<div class=[\'"]comments)',
          r'<article[^>]*>(.*?)</article>']
    for i,p in enumerate(pats):
        m=re.search(p,h,re.S)
        if m and len(m.group(1))>300: return i,m.group(1)
    return -1,""
SKIP=re.compile(r'sticker|emoticon|profile|blogpfthumb|\.gif|ader\.naver|coupangcdn|ads-partners|coupang\.com|tistory_admin|/static/|favicon|blank\.(?:gif|png)|spacer|gravatar|2x2')
def go(r):
    u=r["url"];st,h=fetch(u);k,b=body_of(h);imgs=[];prev="";texts=[];drop=0
    for p in re.split(r'(<img\b[^>]*>)',b):
        if p.startswith("<img"):
            at=dict(re.findall(r'([\w:-]+)=["\']([^"\']*)["\']',p))
            s=at.get("data-src") or at.get("data-lazy-src") or at.get("data-original") or at.get("src")
            if not s: continue
            s=html.unescape(s)
            if s.startswith("//"):s="https:"+s
            if s.startswith("data:") or SKIP.search(s): drop+=1;continue
            imgs.append([s,prev[-120:]])
        else:
            t=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',re.sub(r'<(script|style)[^>]*>.*?</\1>','',p,flags=re.S)))).replace("\u200b","").strip()
            if t: prev=t;texts.append(t)
    time.sleep(0.3)
    return {**r,"status":st,"len":len(h),"pat":k,"has_body":bool(b),"imgs":imgs,"dropped":drop,"text":" ".join(texts)[:20000]}
with cf.ThreadPoolExecutor(6) as ex: res=list(ex.map(go,json.load(open("data/photo_nn_1122.json"))))
print(len(res),sum(1 for r in res if r["has_body"]),sum(len(r["imgs"]) for r in res))
json.dump(res,open("out/photo_nn_1122.json","w",encoding="utf-8"),ensure_ascii=False)
