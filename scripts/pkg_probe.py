"""피퓨 · 나보소 구매 후기 속 상자 · 택 · 라벨 사진 찾기 (읽기 전용 · 지시 1117-1610).
네이버 공식 검색 API(블로그 · 카페 목록)로 후기 글을 찾고, 공개 블로그 글(모바일 보기)의 본문 글자와 사진을 받는다.
로그인이 필요한 글(카페 본문 등)은 열지 않고 목록만 남긴다."""
import json, os, re, sys, time, random, hashlib, pathlib, urllib.parse, html
import requests
from io import BytesIO
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
OUT = pathlib.Path("out")
(OUT / "img").mkdir(parents=True, exist_ok=True)
(OUT / "posts").mkdir(exist_ok=True)
CID, SEC = os.environ.get("NCID", ""), os.environ.get("NSEC", "")
QUERIES = [q for q in os.environ.get("QUERIES", "").split("|") if q]
LOG = []
UA = "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"
PKG = re.compile(r"박스|상자|택\b|태그|라벨|제조국|원산지|제조원|수입원|수입판매|made in|MADE IN|Made in|중국산|베트남|국산|한국산|메이드|언박싱|개봉|포장|패키지|바코드|정품", re.I)


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def api(kind, q, start=1):
    r = requests.get(f"https://openapi.naver.com/v1/search/{kind}.json", params={"query": q, "display": 100, "start": start, "sort": "sim"},
                     headers={"X-Naver-Client-Id": CID, "X-Naver-Client-Secret": SEC}, timeout=20)
    log("api", kind, q, start, r.status_code)
    return r.json() if r.ok else {"error": r.status_code, "body": r.text[:300]}


def strip(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t or ""))


def main():
    found = {}
    for q in QUERIES:
        for kind in ("blog", "cafearticle"):
            for start in (1, 101):
                d = api(kind, q, start)
                for it in d.get("items", []):
                    link = it.get("link", "")
                    key = link
                    if key not in found:
                        found[key] = {"kind": kind, "q": q, "title": strip(it.get("title")), "desc": strip(it.get("description")),
                                      "link": link, "name": it.get("bloggername") or it.get("cafename"), "date": it.get("postdate", "")}
                time.sleep(0.3)
    (OUT / "search.json").write_text(json.dumps(list(found.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    log("found", len(found))
    # 제목 · 요약에 상표가 든 블로그 글만 연다
    brand = re.compile(r"피퓨|pipiu|힐링바운스|나보소|naboso|뉴로볼", re.I)
    posts = [v for v in found.values() if v["kind"] == "blog" and "blog.naver.com" in v["link"] and brand.search(v["title"] + " " + v["desc"])]
    log("blog posts to open", len(posts))
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    res = []
    nimg = 0
    for i, p in enumerate(posts[:220]):
        m = re.search(r"blog\.naver\.com/([^/?]+)/(\d+)", p["link"]) or re.search(r"blogId=([^&]+).*logNo=(\d+)", p["link"])
        if not m:
            continue
        bid, no = m.group(1), m.group(2)
        u = f"https://m.blog.naver.com/PostView.naver?blogId={bid}&logNo={no}"
        try:
            r = s.get(u, timeout=25)
        except Exception as e:
            log("post ERR", u, repr(e)[:100])
            continue
        t = r.text
        body = t
        mm = re.search(r'<div class="se-main-container">(.*?)<div class="(?:post_footer|comment_area|se_footer)', t, re.S)
        if mm:
            body = mm.group(1)
        text = strip(re.sub(r"<(br|/p|/div)[^>]*>", "\n", body))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        imgs = []
        for im in re.findall(r'(?:data-lazy-src|src)="(https://(?:postfiles|blogfiles|mblogthumb-phinf)\.pstatic\.net/[^"]+)"', body):
            base = im.split("?")[0]
            if base not in imgs:
                imgs.append(base)
        rec = {"i": i, "url": u, "status": r.status_code, "title": p["title"], "name": p["name"], "date": p["date"], "q": p["q"],
               "pkg_words": sorted(set(x.group(0) for x in PKG.finditer(text))), "n_imgs": len(imgs), "imgs": [], "text_len": len(text)}
        (OUT / "posts" / f"{i:03d}_{bid}_{no}.txt").write_text(f"URL: {u}\n제목: {p['title']}\n글쓴이: {p['name']}\n날짜: {p['date']}\n검색어: {p['q']}\n\n{text}", encoding="utf-8")
        # 사진은 전부 받되 가로 900 으로 줄여 저장
        for k, im in enumerate(imgs[:40]):
            try:
                ir = s.get(im + "?type=w966", headers={"Referer": "https://m.blog.naver.com/"}, timeout=25)
                if not ir.ok or len(ir.content) < 3000:
                    continue
                img = Image.open(BytesIO(ir.content))
                img = img.convert("RGB")
                if img.width > 900:
                    img = img.resize((900, int(img.height * 900 / img.width)))
                fn = f"{i:03d}_{k:02d}.jpg"
                img.save(OUT / "img" / fn, quality=82)
                rec["imgs"].append({"fn": fn, "src": im})
                nimg += 1
            except Exception as e:
                log("img ERR", im[:100], repr(e)[:80])
        res.append(rec)
        log("post", i, r.status_code, len(text), len(imgs), rec["pkg_words"][:6])
        (OUT / "posts.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(random.uniform(1.0, 2.0))
    log("done posts", len(res), "imgs", nimg)


try:
    main()
except Exception as e:
    import traceback
    log("fatal", traceback.format_exc()[-1500:])
(OUT / "log.txt").write_text("\n".join(LOG), encoding="utf-8")
