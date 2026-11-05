"""일회용: 경쟁 카페 공개 글 원문·사진 원본 받기. 로그인 안 함 · 읽기만 · 막히면 응답 코드만 적고 우회하지 않음."""
import html, io, json, os, re, time, urllib.parse
from curl_cffi import requests as R
from PIL import Image
OUT = "out"; os.makedirs(OUT, exist_ok=True)
S = R.Session(impersonate="chrome"); LAST = [0.0]
PLACES = {"듀얼플랜": ["듀얼플랜", "듀얼플랜 후기", "듀얼플랜 유산균"], "무궁핏": ["무궁핏", "무궁핏 후기"], "애사컷정": ["애사컷정", "애사컷정 후기", "애사컷"]}
FIRST, EXTRA, MAXTRY = 10, 3, 80


def get(u, **k):
    d = 1.0 - (time.monotonic() - LAST[0])
    if d > 0:
        time.sleep(d)
    try:
        return S.get(u, timeout=45, **k)
    finally:
        LAST[0] = time.monotonic()


def cl(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def search(q, pg):
    u = "https://search.naver.com/search.naver?ssc=tab.cafe.all&query=" + urllib.parse.quote(q) + (f"&start={(pg-1)*15+1}" if pg > 1 else "")
    r = get(u, headers={"Accept-Language": "ko-KR,ko;q=0.9"})
    t = r.content.decode("utf-8", "ignore")
    items = []
    for m in re.finditer(r'href="(https://cafe\.naver\.com/([\w\-]+)/(\d+))[^"]*"[^>]*>(.*?)</a>', t, re.S):
        items.append(dict(주소=m.group(1), cafe=m.group(2), art=m.group(3), 제목=cl(m.group(4))[:120]))
    return r.status_code, len(t), items


CID = {}


def cafe_id(cafe, art):
    if cafe in CID:
        return CID[cafe]
    r = get(f"https://cafe.naver.com/{cafe}/{art}", headers={"Accept-Language": "ko-KR,ko;q=0.9"})
    t = r.content.decode("cp949", "ignore")
    m = re.search(r'g_sCafeIdForHistory\s*=\s*"(\d+)"', t) or re.search(r"clubid=(\d+)", t)
    CID[cafe] = m.group(1) if m else None
    return CID[cafe]


IMG = re.compile(r"(https?://(?:cafeptthumb-phinf|postfiles|blogfiles|mblogthumb-phinf|cafefiles|phinf)\.pstatic\.net/[^\"'\s<>)\\]+)")


def img_urls(h):
    out = []
    for a in IMG.findall(h):
        b = html.unescape(a).split("?")[0]
        if re.search(r"\.(jpe?g|png|gif|webp)$", b, re.I) and "emoticon" not in b and "sticker" not in b and b not in out:
            out.append(b)
    return out


HDR = {"Referer": "https://cafe.naver.com/", "User-Agent": "Mozilla/5.0"}


def fetch_img(b, typ):
    u = b + (f"?type={typ}" if typ else "")
    try:
        g = get(u, headers=HDR)
        return u, g.status_code, g.content
    except Exception as e:
        return u, repr(e)[:60], b""


def dims(c):
    try:
        return Image.open(io.BytesIO(c)).size
    except Exception:
        return (None, None)


def article(it):
    cid = cafe_id(it["cafe"], it["art"])
    if not cid:
        return None, "카페번호 못 찾음", None
    a = get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{cid}/articles/{it['art']}?query=&useCafeId=true&requestFrom=A", headers=HDR)
    if a.status_code != 200:
        try:
            j = a.json()["result"]
            return None, f"HTTP {a.status_code} {j.get('errorCode')} {j.get('reason')}", a.content
        except Exception:
            return None, f"HTTP {a.status_code}", a.content
    return a.json()["result"], "공개", a.content


summary = dict(곳={})
cand = {}
for place, qs in PLACES.items():
    seen = {}
    slog = []
    for q in qs:
        for pg in (1, 2, 3):
            st, n, items = search(q, pg)
            slog.append(dict(q=q, pg=pg, status=st, len=n, 글수=len(items)))
            for it in items:
                seen.setdefault((it["cafe"], it["art"]), it)
            if st != 200 or not items:
                break
    cand[place] = list(seen.values())
    summary["곳"][place] = dict(검색기록=slog, 검색된_고유글=len(seen))
    print(place, "검색된", len(seen), flush=True)

BEST = [None]
for place in PLACES:
    pdir = f"{OUT}/카페_글/{place}"
    os.makedirs(pdir, exist_ok=True)
    who = {}
    pub = 0
    tried = 0
    log = []
    batch = []
    stop = None
    for it in cand[place]:
        if tried >= MAXTRY:
            stop = "시도 상한"
            break
        tried += 1
        rec = dict(주소=it["주소"], 제목=it["제목"], 카페=it["cafe"], 글=it["art"])
        try:
            res, state, raw = article(it)
        except Exception as e:
            res, state, raw = None, "오류 " + repr(e)[:80], None
        rec["상태"] = state
        if not res:
            log.append(rec)
            continue
        ar = res["article"]
        wr = ar.get("writer") or {}
        key = wr.get("memberKey") or wr.get("nick")
        pub += 1
        rec["글쓴이"] = wr.get("nick")
        new = key not in who
        if len(who) >= FIRST:
            batch.append(new)
            if len(batch) == EXTRA:
                if not any(batch):
                    stop = f"{FIRST}편 뒤 이어서 {EXTRA}편에 새 글쓴이 없음"
                    log.append(rec)
                    break
                batch = []
        if not new:
            rec["저장"] = "같은 글쓴이라 건너뜀"
            log.append(rec)
            continue
        who[key] = it["art"]
        rec["저장"] = "저장"
        d = f"{pdir}/{it['cafe']}_{it['art']}"
        os.makedirs(d, exist_ok=True)
        body = ar.get("contentHtml") or ""
        open(f"{d}/원문.html", "w", encoding="utf-8").write(body)
        open(f"{d}/글.json", "wb").write(raw)
        cm = []
        cid = cafe_id(it["cafe"], it["art"])
        pg = 1
        while pg <= 5:
            c = get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{cid}/articles/{it['art']}/comments/pages/{pg}?requestFrom=A&orderBy=asc&pageSize=100", headers=HDR)
            if c.status_code != 200:
                break
            cj = c.json()["result"]
            cm += cj["comments"]["items"]
            if not cj.get("hasNext"):
                break
            pg += 1
        json.dump(cm, open(f"{d}/댓글.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rec["댓글"] = len(cm)
        rec["본문글자"] = len(cl(body))
        rec["제목_원문"] = ar.get("subject")
        urls = img_urls(body)
        if urls and BEST[0] is None:
            res_ = []
            for typ in ["", "w300", "w800", "w966", "w1600", "w2000", "w3840", "w5000"]:
                u, st, c = fetch_img(urls[0], typ)
                w, h = dims(c) if st == 200 else (None, None)
                res_.append(dict(type=typ or "(값 없음)", status=st, 가로=w, 세로=h, 바이트=len(c)))
            ok = [r for r in res_ if r["status"] == 200 and r["가로"]]
            top = max(ok, key=lambda r: (r["가로"], r["바이트"])) if ok else None
            BEST[0] = ("" if top["type"] == "(값 없음)" else top["type"]) if top else "w3840"
            summary["크기시험"] = dict(글=f"{it['cafe']}/{it['art']}", 사진=urls[0], 결과=res_)
            summary["고른_크기값"] = BEST[0]
            print("크기시험", json.dumps(res_, ensure_ascii=False), "->", repr(BEST[0]), flush=True)
        pics = []
        for i, b in enumerate(urls, 1):
            u, st, c = fetch_img(b, BEST[0] if BEST[0] is not None else "w3840")
            if st != 200 or not c:
                pics.append(dict(순서=i, 원주소=b, 받음=False, status=st))
                continue
            w, h = dims(c)
            ext = (os.path.splitext(b)[1] or ".jpg").lower()
            open(f"{d}/{i:02d}{ext}", "wb").write(c)
            pics.append(dict(순서=i, 파일=f"{i:02d}{ext}", 받은주소=u, 가로=w, 세로=h, 바이트=len(c)))
        json.dump(pics, open(f"{d}/사진.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        rec["사진"] = len(pics)
        rec["사진받음"] = sum(1 for p in pics if p.get("파일"))
        log.append(rec)
        print(place, it["cafe"], it["art"], "사진", rec["사진받음"], "/", len(pics), "글쓴이수", len(who), flush=True)
    summary["곳"][place].update(시도=tried, 공개=pub, 저장한_글쓴이수=len(who), 멈춤=stop or "후보 끝", 글목록=log)
    json.dump(summary, open(f"{OUT}/요약.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝")
