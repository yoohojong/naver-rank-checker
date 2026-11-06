"""쿠팡 검색창 자동완성 + 검색결과 연관검색어 시험 (읽기 전용, 씨앗마다 1번, 5~8초 간격). 2026-11-06 카드 t_cfc8c1ba."""
import json, os, random, sys, time, re, urllib.parse
import requests
sys.stdout.reconfigure(encoding="utf-8")
seeds = [s.strip() for s in os.environ.get("KEYWORDS", "").split(",") if s.strip()]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://www.coupang.com/"}
out = []
for i, s in enumerate(seeds):
    rec = {"seed": s}
    url = "https://www.coupang.com/np/search/autoComplete?" + urllib.parse.urlencode({"keyword": s, "callback": ""})
    try:
        r = requests.get(url, headers=H, timeout=20)
        rec["auto_status"] = r.status_code
        rec["auto_len"] = len(r.text)
        rec["auto_head"] = r.text[:1500]
    except Exception as e:
        rec["auto_error"] = repr(e)
    out.append(rec)
    print(json.dumps({k: (v if k != "auto_head" else v[:300]) for k, v in rec.items()}, ensure_ascii=False), flush=True)
    if i < len(seeds) - 1:
        time.sleep(random.uniform(5, 8))
os.makedirs("out", exist_ok=True)
json.dump(out, open("out/coupang_autocomplete.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
