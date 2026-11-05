"""일회용: 경쟁 마킹글 원문과 사진 원본 크기를 서버에서 받는다. 로그인 안 함 · 읽기만 · 막히면 응답 코드만 적는다."""
import html, io, json, os, re, time, urllib.parse
from curl_cffi import requests as R
from PIL import Image
OUT = "out"; os.makedirs(OUT, exist_ok=True)
S = R.Session(impersonate="chrome"); H = {"Accept-Language": "ko-KR,ko;q=0.9"}
MH = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "Accept-Language": "ko-KR,ko;q=0.9"}
PLACES = {"지엘틱스": ["지엘틱스 후기", "지엘틱정 후기"], "애사컷정": ["애사컷정 후기"], "리바디": ["리바디 유산균 후기"], "듀얼플랜": ["듀얼플랜 유산균 후기"], "맥스컷": ["맥스컷 프로 크롬 후기"], "비너톡": ["비너톡 후기"], "무궁핏": ["무궁핏 후기"]}
ADS = ["다이어트보조제", "다이어트 보조제 추천", "다이어트유산균", "식욕억제", "위고비 대신", "뱃살 빼는 법"]
PER = 10
def get(u, **k):
    time.sleep(1.2); return S.get(u, timeout=40, **k)
def links(q):
    t = get("https://search.naver.com/search.naver?ssc=tab.blog.all&sm=tab_opt&query=" + urllib.parse.quote(q), headers=H).content.decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'https?://(?:m\.)?blog\.naver\.com/([\w\-.]+)/(\d+)', t):
        if (m.group(1), m.group(2)) not in out: out.append((m.group(1), m.group(2)))
    return out
os.makedirs(OUT + "/검색화면", exist_ok=True)
for q in ADS:
    r = get("https://search.naver.com/search.naver?query=" + urllib.parse.quote(q), headers=H)
    open(f"{OUT}/검색화면/{q.replace(' ', '_')}.html", "wb").write(r.content); print("광고", q, r.status_code, flush=True)
    r = get("https://m.search.naver.com/search.naver?query=" + urllib.parse.quote(q), headers=MH)
    open(f"{OUT}/검색화면/모바일_{q.replace(' ', '_')}.html", "wb").write(r.content)
index = []
for place, qs in PLACES.items():
    who = set(); n = 0
    for q in qs:
        for uid, no in links(q):
            if n >= PER or uid in who: continue
            d = f"{OUT}/{place}/{uid}_{no}"; os.makedirs(d, exist_ok=True)
            r = get(f"https://m.blog.naver.com/{uid}/{no}", headers=MH)
            if r.status_code != 200:
                index.append(dict(곳=place, 검색어=q, 글=f"{uid}/{no}", status=r.status_code)); continue
            tx = r.content.decode("utf-8", "replace"); open(f"{d}/원문.html", "w", encoding="utf-8").write(tx)
            who.add(uid); n += 1
            src = []
            for a in re.findall(r'(?:data-lazy-src|data-src|src)="(https://(?:postfiles|blogfiles|mblogthumb-phinf)\.pstatic\.net/[^"]+)"', tx):
                b = html.unescape(a).split("?")[0]
                if b not in src: src.append(b)
            pics = []
            for i, b in enumerate(src, 1):
                best = None
                for host in ("https://mblogthumb-phinf.pstatic.net", "https://postfiles.pstatic.net"):
                    u = re.sub(r"https://[^/]+", host, b) + "?type=w3840"
                    try:
                        time.sleep(0.4); g = S.get(u, headers={**MH, "Referer": "https://m.blog.naver.com/"}, timeout=60)
                        if g.status_code == 200 and (not best or len(g.content) > len(best[1])): best = (u, g.content)
                    except Exception as e:
                        print("사진 오류", u, repr(e)[:80], flush=True)
                if not best: pics.append(dict(순서=i, 원주소=b, 받음=False)); continue
                w = h = None
                try: w, h = Image.open(io.BytesIO(best[1])).size
                except Exception: pass
                ext = (os.path.splitext(urllib.parse.urlparse(b).path)[1] or ".jpg").lower()
                open(f"{d}/{i:02d}{ext}", "wb").write(best[1])
                pics.append(dict(순서=i, 파일=f"{i:02d}{ext}", 받은주소=best[0], 가로=w, 세로=h, 바이트=len(best[1])))
            json.dump(pics, open(f"{d}/사진.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            index.append(dict(곳=place, 검색어=q, 글=f"{uid}/{no}", status=200, 사진=len(pics), 받음=sum(1 for p in pics if p.get("파일"))))
            print(place, uid, no, len(pics), flush=True)
    json.dump(index, open(f"{OUT}/목록.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("끝", len(index))
