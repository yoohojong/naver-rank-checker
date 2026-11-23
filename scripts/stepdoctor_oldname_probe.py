# -*- coding: utf-8 -*-
"""t_7417763e: 네이버에서 옛 이름(옆으로베개·건강보법·카테키산) 보이는 자리 찾기. 읽기만."""
import os, json, re, time, urllib.parse, urllib.request
QS = ["스텝닥터","스텝닥터 족저근이완기","스텝닥터 무지외반 교정기","스텝닥터 깔창","옆으로베개","건강보법","카테키산"]
OLD = ["옆으로베개","건강보법","카테키산"]
H = {"X-Naver-Client-Id": os.environ["NAVER_OPENAPI_CLIENT_ID"], "X-Naver-Client-Secret": os.environ["NAVER_OPENAPI_CLIENT_SECRET"]}
os.makedirs("out/html", exist_ok=True)
def api(path, q, **kw):
    p = {"query": q, **kw}
    u = f"https://openapi.naver.com/v1/search/{path}?" + urllib.parse.urlencode(p)
    r = urllib.request.Request(u, headers=H)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=20).read().decode("utf-8"))
    except Exception as e:
        return {"error": repr(e)}
res = {}
for q in QS:
    d = {}
    d["shop"] = [api("shop.json", q, display=100, start=1, sort="sim")]
    d["shop_page2"] = api("shop.json", q, display=100, start=101, sort="sim")
    for k in ("webkr", "blog", "cafearticle", "kin"):
        d[k] = api(f"{k}.json", q, display=30)
    res[q] = d
    time.sleep(0.3)
json.dump(res, open("out/api.json", "w", encoding="utf-8"), ensure_ascii=False)
# 화면 글(통합검색 PC·휴대폰, 쇼핑 검색 PC·휴대폰)
try:
    from curl_cffi import requests as cr
except Exception as e:
    cr = None; print("curl_cffi 없음", e)
log = []
if cr:
    for i, q in enumerate(QS):
        qq = urllib.parse.quote(q)
        for tag, url, ua in [
            ("pc_통합", f"https://search.naver.com/search.naver?where=nexearch&query={qq}", "chrome"),
            ("m_통합", f"https://m.search.naver.com/search.naver?where=m&query={qq}", "chrome_android"),
            ("pc_쇼핑", f"https://search.shopping.naver.com/search/all?query={qq}", "chrome"),
            ("m_쇼핑", f"https://msearch.shopping.naver.com/search/all?query={qq}", "chrome_android"),
        ]:
            try:
                r = cr.get(url, impersonate=ua, timeout=25)
                t = r.text
                open(f"out/html/{i}_{tag}.html", "w", encoding="utf-8").write(t)
                log.append((q, tag, r.status_code, len(t), {o: t.count(o) for o in OLD}))
            except Exception as e:
                log.append((q, tag, "ERR", repr(e)[:120], {}))
            time.sleep(4)
json.dump(log, open("out/fetch_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for l in log: print(l)
