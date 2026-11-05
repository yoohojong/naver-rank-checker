"""일회용: 글에 적힌 짧은 주소 도착지 보기. 첫 화면 제목까지만 · 로그인 안 함."""
import json, os, re, time, html
from curl_cffi import requests as R
os.makedirs("out", exist_ok=True)
S = R.Session(impersonate="chrome"); res = []
for u in [x.strip() for x in open("tools/mark_hub_short.txt", encoding="utf-8") if x.strip()]:
    time.sleep(1.0)
    try:
        r = S.get(u, timeout=30, allow_redirects=True)
        t = r.content[:300000].decode("utf-8", "ignore")
        og = re.findall(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', t) or re.findall(r"<title[^>]*>(.*?)</title>", t, re.S)
        res.append(dict(짧은주소=u, 응답=r.status_code, 도착=str(r.url)[:300], 제목=html.unescape(og[0]).strip()[:120] if og else ""))
    except Exception as e:
        res.append(dict(짧은주소=u, 오류=repr(e)[:100]))
    print(res[-1], flush=True)
json.dump(res, open("out/짧은주소.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
