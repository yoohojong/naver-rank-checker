# 11-03 카페 글 하나(본문 + 댓글 전부) 받아 저장만 — 읽기 전용 임시 진단. probe/ 가지 전용.
import json, os, sys, time, urllib.request, urllib.parse
CAFE = os.environ["CAFE"]; AID = os.environ["AID"]; ART = os.environ.get("ART", "")
os.makedirs("out", exist_ok=True)
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
def get(url, ref):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ref, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))
ref = "https://m.cafe.naver.com/%s/%s" % (CAFE, AID)
c, b = get("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % CAFE, ref)
open("out/gate.json", "w", encoding="utf-8").write(b); print("gate", c)
clubid = json.loads(b)["message"]["result"]["cafeInfoView"]["cafeId"]
art = ("&art=" + urllib.parse.quote(ART)) if ART else ""
c, b = get("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true&requestFrom=A%s" % (clubid, AID, art), ref)
open("out/article.json", "w", encoding="utf-8").write(b); print("article", c, len(b))
for p in range(1, 11):
    time.sleep(1)
    c, b = get("https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/%s/articles/%s/comments/pages/%d?requestFrom=A&orderBy=asc%s" % (clubid, AID, p, art), ref)
    open("out/comments_%02d.json" % p, "w", encoding="utf-8").write(b); print("comments", p, c, len(b))
    try:
        if len(json.loads(b)["result"]["comments"]["items"]) == 0: break
    except Exception: break
