"""일회용: 허브 키워드 남의 글 비율 재료 받기. 키워드마다 블로그 · 카페 첫 쪽 글 원문과 댓글. 로그인 안 함 · 읽기만 · 사진 안 받음 · 막히면 응답 코드만 적고 우회하지 않음."""
import html, json, os, re, time, urllib.parse
from curl_cffi import requests as R
OUT = "out"; os.makedirs(OUT, exist_ok=True)
S = R.Session(impersonate="chrome"); LAST = [0.0]
KWS = [x.strip() for x in open("tools/mark_hub_kw.txt", encoding="utf-8") if x.strip()]
PER = 30
H = {"Accept-Language": "ko-KR,ko;q=0.9"}
CH = {"Referer": "https://cafe.naver.com/", "User-Agent": "Mozilla/5.0"}
MH = {"Accept-Language": "ko-KR,ko;q=0.9", "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"}


def get(u, **k):
    d = 1.0 - (time.monotonic() - LAST[0])
    if d > 0:
        time.sleep(d)
    try:
        return S.get(u, timeout=45, **k)
    finally:
        LAST[0] = time.monotonic()


def cl(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def blog_list(kw):
    r = get("https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_opt&query=" + urllib.parse.quote(kw), headers=H)
    t = r.content.decode("utf-8", "ignore")
    seen = []
    for m in re.finditer(r'https?://(?:m\.)?blog\.naver\.com/([\w\-.]+)/(\d{6,})', t):
        if m.groups() not in seen:
            seen.append(m.groups())
    return r.status_code, len(t), seen[:PER]


def cafe_list(kw):
    r = get("https://search.naver.com/search.naver?ssc=tab.cafe.all&query=" + urllib.parse.quote(kw), headers=H)
    t = r.content.decode("utf-8", "ignore")
    seen = []
    for m in re.finditer(r'https://cafe\.naver\.com/([\w\-]+)/(\d+)', t):
        if m.groups() not in seen:
            seen.append(m.groups())
    return r.status_code, len(t), seen[:PER]


BLOG = {}


def blog_post(uid, no):
    k = f"{uid}/{no}"
    if k in BLOG:
        return BLOG[k]
    r = get(f"https://m.blog.naver.com/{uid}/{no}", headers=MH)
    rec = dict(갈래="블로그", 글=f"{uid}_{no}", 주소=f"https://blog.naver.com/{uid}/{no}", status=r.status_code)
    if r.status_code == 200:
        t = r.content.decode("utf-8", "replace")
        m = re.search(r"se-main-container(.*)", t, re.S)
        b = (m.group(1) if m else t).split("post_footer")[0]
        rec["제목"] = cl((re.findall(r'<meta property="og:title" content="([^"]*)"', t) or re.findall(r"<title>(.*?)</title>", t, re.S) or [""])[0])
        rec["날짜"] = cl((re.findall(r'class="[^"]*(?:blog_date|se_publishDate|date)[^"]*"[^>]*>(.*?)</', t, re.S) or [""])[0])
        rec["본문"] = cl(b)[:6000]
        rec["링크카드"] = [cl(x) for x in re.findall(r'se-oglink-(?:title|url|summary)[^>]*>([^<]+)', b)]
        rec["바깥링크"] = sorted({html.unescape(u) for u in re.findall(r'href="(https?://[^"]+)"', b) if not re.search(r"naver\.com/(?:[\w\-.]+/\d+|PostView)|pstatic|nid\.naver", u)})[:30]
        rec["댓글수_표시"] = cl((re.findall(r'class="[^"]*comment[^"]*"[^>]*>\s*<[^>]*>\s*(\d+)', t) or [""])[0])
    BLOG[k] = rec
    return rec


CID = {}
CAFE = {}


def cafe_id(cafe, art):
    if cafe in CID:
        return CID[cafe]
    r = get(f"https://cafe.naver.com/{cafe}/{art}", headers=H)
    t = r.content.decode("cp949", "ignore")
    m = re.search(r'g_sCafeIdForHistory\s*=\s*"(\d+)"', t) or re.search(r"clubid=(\d+)", t)
    CID[cafe] = m.group(1) if m else None
    return CID[cafe]


def cafe_post(cafe, art):
    k = f"{cafe}/{art}"
    if k in CAFE:
        return CAFE[k]
    rec = dict(갈래="카페", 글=f"{cafe}_{art}", 주소=f"https://cafe.naver.com/{k}")
    cid = cafe_id(cafe, art)
    if not cid:
        rec["상태"] = "카페번호 못 찾음"
    else:
        a = get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{cid}/articles/{art}?query=&useCafeId=true&requestFrom=A", headers=CH)
        rec["status"] = a.status_code
        if a.status_code == 200:
            ar = a.json()["result"]["article"]
            body = ar.get("contentHtml") or ""
            rec.update(상태="공개", 제목=ar.get("subject"), 날짜=ar.get("writeDate"), 글쓴이=(ar.get("writer") or {}).get("nick"), 본문=cl(body)[:6000])
            rec["바깥링크"] = sorted({html.unescape(u) for u in re.findall(r'https?://[^\s"\'<>]+', body) if "pstatic" not in u})[:30]
            cm, pg = [], 1
            while pg <= 5:
                c = get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{cid}/articles/{art}/comments/pages/{pg}?requestFrom=A&orderBy=asc&pageSize=100", headers=CH)
                if c.status_code != 200:
                    break
                cj = c.json()["result"]
                cm += [dict(누가=(x.get("writer") or {}).get("nick"), 말=x.get("content")) for x in cj["comments"]["items"]]
                if not cj.get("hasNext"):
                    break
                pg += 1
            rec["댓글"] = cm
        else:
            try:
                j = a.json()["result"]
                rec["상태"] = f"{j.get('errorCode')} {j.get('reason')}"
            except Exception:
                rec["상태"] = f"HTTP {a.status_code}"
    CAFE[k] = rec
    return rec


log = []
for kw in KWS:
    w = open(f"{OUT}/{kw}.jsonl", "w", encoding="utf-8")
    bs, bl, bi = blog_list(kw)
    cs, cl_, ci = cafe_list(kw)
    log.append(dict(키워드=kw, 블로그_응답=bs, 블로그_바이트=bl, 블로그_글=len(bi), 카페_응답=cs, 카페_바이트=cl_, 카페_글=len(ci)))
    print(kw, "블로그", bs, len(bi), "카페", cs, len(ci), flush=True)
    for i, (u, n) in enumerate(bi, 1):
        try:
            rec = dict(blog_post(u, n), 키워드=kw, 순위=i)
        except Exception as e:
            rec = dict(갈래="블로그", 글=f"{u}_{n}", 키워드=kw, 순위=i, 상태="오류 " + repr(e)[:80])
        w.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for i, (c, a) in enumerate(ci, 1):
        try:
            rec = dict(cafe_post(c, a), 키워드=kw, 순위=i)
        except Exception as e:
            rec = dict(갈래="카페", 글=f"{c}_{a}", 키워드=kw, 순위=i, 상태="오류 " + repr(e)[:80])
        w.write(json.dumps(rec, ensure_ascii=False) + "\n")
    w.close()
    json.dump(log, open(f"{OUT}/요약.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝")
