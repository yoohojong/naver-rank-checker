"""일회용: smartstore.naver.com/cutsulin 공개 화면 글자·사진 받기. 로그인 안 함 · 막히면 응답 코드만 적고 우회하지 않음."""
import html, io, json, os, re, time
from curl_cffi import requests as R
from PIL import Image
OUT = "out/컷슬린"; os.makedirs(OUT, exist_ok=True)
S = R.Session(impersonate="chrome"); LAST = [0.0]
H = {"Accept-Language": "ko-KR,ko;q=0.9"}
log = []


def get(u, **k):
    d = 1.5 - (time.monotonic() - LAST[0])
    if d > 0:
        time.sleep(d)
    try:
        return S.get(u, timeout=45, headers={**H, **k.pop("headers", {})}, **k)
    finally:
        LAST[0] = time.monotonic()


def rec(name, r):
    open(f"{OUT}/{name}", "wb").write(r.content)
    log.append(dict(파일=name, 주소=str(r.url), status=r.status_code, 바이트=len(r.content)))
    print(name, r.status_code, len(r.content), flush=True)


r = get("https://smartstore.naver.com/cutsulin")
rec("가게_첫화면.html", r)
t = r.content.decode("utf-8", "ignore")
prods = []
for m in re.finditer(r"/cutsulin/products/(\d+)", t):
    if m.group(1) not in prods:
        prods.append(m.group(1))
print("상품", prods[:10], flush=True)
if r.status_code == 200 and not prods:
    r2 = get("https://smartstore.naver.com/cutsulin/category/ALL?cp=1")
    rec("가게_전체상품.html", r2)
    for m in re.finditer(r"/cutsulin/products/(\d+)", r2.content.decode("utf-8", "ignore")):
        if m.group(1) not in prods:
            prods.append(m.group(1))
imgs_all = {}
for pid in prods[:5]:
    p = get(f"https://smartstore.naver.com/cutsulin/products/{pid}")
    rec(f"상품_{pid}.html", p)
    if p.status_code != 200:
        continue
    pt = p.content.decode("utf-8", "ignore")
    ims = []
    for a in re.findall(r'(https?://[\w\-.]*(?:pstatic\.net|shop-phinf\.pstatic\.net)/[^"\'\s<>)\\]+\.(?:jpe?g|png|gif|webp))', pt, re.I):
        b = html.unescape(a).split("?")[0]
        if b not in ims:
            ims.append(b)
    imgs_all[pid] = ims
os.makedirs(OUT + "/상세", exist_ok=True)
pics = []
for pid, ims in imgs_all.items():
    for i, b in enumerate(ims, 1):
        best = None
        for typ in ("", "w860", "w1600", "w3840"):
            u = b + (f"?type={typ}" if typ else "")
            try:
                g = get(u, headers={"Referer": "https://smartstore.naver.com/"})
            except Exception as e:
                continue
            if g.status_code == 200 and (not best or len(g.content) > len(best[1])):
                best = (u, g.content)
        if not best:
            pics.append(dict(상품=pid, 순서=i, 원주소=b, 받음=False))
            continue
        try:
            w, h = Image.open(io.BytesIO(best[1])).size
        except Exception:
            w = h = None
        ext = (os.path.splitext(b)[1] or ".jpg").lower()
        fn = f"{pid}_{i:02d}{ext}"
        open(f"{OUT}/상세/{fn}", "wb").write(best[1])
        pics.append(dict(상품=pid, 순서=i, 파일=fn, 받은주소=best[0], 가로=w, 세로=h, 바이트=len(best[1])))
json.dump(dict(기록=log, 상품=prods, 사진=pics), open(f"{OUT}/기록.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(pics))
