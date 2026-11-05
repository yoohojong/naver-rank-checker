"""일회용: 오프밀정 · 버나덱스정 판매처 찾기. 네이버 검색 화면 읽기만 · 로그인 안 함."""
import json, os, re, time, urllib.parse, html
from curl_cffi import requests as R
OUT = "out"; os.makedirs(OUT, exist_ok=True)
S = R.Session(impersonate="chrome"); H = {"Accept-Language": "ko-KR,ko;q=0.9"}
NAMES = ["오프밀정", "오프밀 정", "오프밀", "오프밀정 다이어트", "버나덱스정", "버나덱스 정", "버나덱스", "버나덱스정 다이어트"]
URLS = {
 "통합": "https://search.naver.com/search.naver?query=%s",
 "쇼핑": "https://search.shopping.naver.com/search/all?query=%s",
 "쇼핑검색": "https://search.shopping.naver.com/ns/v1/search/paged-composite-cards?cursor=1&pageSize=20&query=%s",
 "블로그": "https://search.naver.com/search.naver?ssc=tab.blog.all&query=%s",
 "카페": "https://search.naver.com/search.naver?ssc=tab.cafe.all&query=%s",
}
res = []
for n in NAMES:
    for k, u in URLS.items():
        try:
            time.sleep(1.5)
            r = S.get(u % urllib.parse.quote(n), headers=H, timeout=40)
            t = r.content.decode("utf-8", "ignore")
            fn = f"{OUT}/{k}_{n.replace(' ','_')}.html"; open(fn, "w", encoding="utf-8").write(t)
            hits = len(re.findall(n.replace(" ", r"\s?"), t))
            mall = sorted(set(re.findall(r'https?://(?:smartstore|brand|shopping|m\.smartstore)\.naver\.com/[\w\-./]+', t)))[:15]
            other = sorted(set(re.findall(r'https?://[\w.\-]+\.(?:kr|com|co\.kr|shop)/[\w\-./?=&%]*', html.unescape(t))))
            other = [o for o in other if not re.search(r'naver|pstatic|google|nid\.|kakao|youtube', o)][:20]
            res.append(dict(이름=n, 곳=k, status=r.status_code, 바이트=len(t), 이름등장=hits, 네이버몰=mall, 다른주소=other))
            print(n, k, r.status_code, len(t), hits, flush=True)
        except Exception as e:
            res.append(dict(이름=n, 곳=k, 오류=repr(e)[:100]))
json.dump(res, open(f"{OUT}/목록.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
