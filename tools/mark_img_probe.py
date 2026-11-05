"""일회용: 경쟁 마킹글 사진을 어느 크기 값에서 가장 크게 받는지 잰다. 로그인 안 함 · 읽기만."""
import io, json, os, re, time
from curl_cffi import requests as R
from PIL import Image
OUT = "out"; os.makedirs(OUT, exist_ok=True)
URLS = os.environ["URLS"].split()
MH = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Accept-Language": "ko-KR,ko;q=0.9"}
S = R.Session(impersonate="chrome")
VARS = ["", "?type=w3840", "?type=w2", "?type=w966", "?type=w800", "?type=w1"]
rep = []
for u in URLS:
    m = re.search(r"blog\.naver\.com/([^/?]+)/(\d+)", u)
    time.sleep(2)
    r = S.get(f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}", headers=MH, timeout=40)
    open(f"{OUT}/{m.group(2)}.html", "w", encoding="utf-8").write(r.text)
    srcs = []
    for a in re.findall(r'(?:data-lazy-src|data-src|src)="(https://(?:postfiles|blogfiles|mblogthumb-phinf)\.pstatic\.net/[^"]+)"', r.text):
        b = a.split("?")[0]
        if b not in srcs: srcs.append(b)
    rec = {"주소": u, "status": r.status_code, "사진수": len(srcs), "시험": []}
    for b in srcs[:3]:
        for host in {b, re.sub(r"https://mblogthumb-phinf", "https://postfiles", b)}:
            for v in VARS:
                time.sleep(1)
                try:
                    g = S.get(host + v, headers={**MH, "Referer": "https://m.blog.naver.com/"}, timeout=40)
                    w = h = None
                    if g.status_code == 200:
                        im = Image.open(io.BytesIO(g.content)); w, h = im.size
                    rec["시험"].append({"주소": host + v, "status": g.status_code, "바이트": len(g.content), "가로": w, "세로": h, "종류": g.headers.get("content-type")})
                except Exception as e:
                    rec["시험"].append({"주소": host + v, "오류": str(e)[:120]})
    rep.append(rec)
json.dump(rep, open(f"{OUT}/결과.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
