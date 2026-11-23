# 네이버 쇼핑 검색 API(공식)로 우리 스토어 상품명 · 판매처 · 브랜드 받기(읽기만 · 2026-11-23)
import json, os, urllib.request, urllib.parse
OUT = "out"; os.makedirs(OUT, exist_ok=True)
H = {"X-Naver-Client-Id": os.environ["NAVER_OPENAPI_CLIENT_ID"], "X-Naver-Client-Secret": os.environ["NAVER_OPENAPI_CLIENT_SECRET"]}
res = {}
for q in ["스텝닥터 무지외반 마사지기", "스텝닥터 족저근 이완기", "스텝닥터 무지외반 교정기", "스텝닥터", "건강보법 마사지기", "건강보법 이완기", "건강보법 교정기", "건강보법 스토어 goyu777"]:
    u = "https://openapi.naver.com/v1/search/shop.json?display=100&query=" + urllib.parse.quote(q)
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30)
        d = json.loads(r.read().decode()); d["_http"] = r.status
        d["items"] = [i for i in d.get("items", []) if "goyu777" in i.get("link", "") or "건강보법" in i.get("mallName", "")  or "스텝닥터" in i.get("title", "") or "건강보법" in i.get("title", "") or "13889380939" in i.get("link","") or "13884386311" in i.get("link","") or "13889385174" in i.get("link","")]
        res[q] = d
    except Exception as e:
        res[q] = {"error": repr(e)}
json.dump(res, open(f"{OUT}/api.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for q, d in res.items(): print(q, d.get("_http"), d.get("total"), len(d.get("items", [])), d.get("error"))
