"""쿠팡 검색결과 화면 연관검색어 시험 (읽기 전용, 씨앗 2개 x 1번, 5~8초 간격). 카드 t_06e2cfd5 2026-11-06."""
import json, os, random, sys, time, re, urllib.parse
import requests
sys.stdout.reconfigure(encoding="utf-8")
seeds = ["지루성두피염 샴푸", "두피 각질 샴푸"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://www.coupang.com/"}
out = []
for i, s in enumerate(seeds):
    rec = {"seed": s}
    url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": s, "channel": "user"})
    try:
        r = requests.get(url, headers=H, timeout=25)
        rec["status"] = r.status_code
        rec["len"] = len(r.text)
        rec["head"] = r.text[:600]
        rec["related"] = re.findall(r'relatedKeyword[^>]*>([^<]{1,40})<', r.text)[:40]
    except Exception as e:
        rec["error"] = repr(e)
    out.append(rec)
    print(json.dumps({k: (v if k != "head" else v[:200]) for k, v in rec.items()}, ensure_ascii=False), flush=True)
    if i < len(seeds) - 1:
        time.sleep(random.uniform(5, 8))
os.makedirs("out", exist_ok=True)
json.dump(out, open("out/coupang_search.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
