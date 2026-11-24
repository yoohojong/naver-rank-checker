# -*- coding: utf-8 -*-
"""지시 1124-0120: 네이버 웹문서 결과의 사이트 이름 '카테키산 유산균' 자리 찾기. 읽기만."""
import os, json, re, time, urllib.parse, urllib.request
API_QS = ["site:yeopropillow.com", "yeopropillow.com 카테키산", "yeopropillow.com 여리손", "yeopropillow.com 뷰티움랩", "yeopropillow.com 건강보법"]
PAGE_QS = []
OLD = ["옆으로베개", "건강보법", "카테키산"]
H = {"X-Naver-Client-Id": os.environ["NAVER_OPENAPI_CLIENT_ID"], "X-Naver-Client-Secret": os.environ["NAVER_OPENAPI_CLIENT_SECRET"]}
os.makedirs("out/html", exist_ok=True)
def api(path, q, **kw):
    u = f"https://openapi.naver.com/v1/search/{path}?" + urllib.parse.urlencode({"query": q, **kw})
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=20).read().decode("utf-8"))
    except Exception as e:
        return {"error": repr(e)}
res = {q: api("webkr.json", q, display=100, start=1) for q in API_QS}
json.dump(res, open("out/api_webkr.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for q, d in res.items():
    print("API", q, d.get("total"), [(i.get("title"), i.get("link")) for i in d.get("items", [])][:10], d.get("error"))
from curl_cffi import requests as cr
log = []
for i, q in enumerate(PAGE_QS):
    qq = urllib.parse.quote(q)
    for tag, url, ua in [
        ("pc_통합", f"https://search.naver.com/search.naver?where=nexearch&query={qq}", "chrome"),
        ("m_통합", f"https://m.search.naver.com/search.naver?where=m&query={qq}", "chrome_android"),
        ("pc_웹", f"https://search.naver.com/search.naver?where=web&query={qq}", "chrome"),
    ]:
        try:
            r = cr.get(url, impersonate=ua, timeout=25)
            t = r.text
            open(f"out/html/{i}_{tag}.html", "w", encoding="utf-8").write(t)
            near = [t[max(0, m.start()-300):m.end()+300] for m in re.finditer("yeopropillow", t)][:6]
            log.append({"q": q, "tag": tag, "code": r.status_code, "len": len(t), "old": {o: t.count(o) for o in OLD}, "near": near})
        except Exception as e:
            log.append({"q": q, "tag": tag, "err": repr(e)[:160]})
        time.sleep(4)
json.dump(log, open("out/fetch_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for l in log: print(l.get("q"), l.get("tag"), l.get("code"), l.get("len"), l.get("old"))
