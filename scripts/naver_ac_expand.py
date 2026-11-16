"""네이버 검색창 자동완성을 조금씩 늘려 쳐서 모으기 — GitHub 서버 전용(이 PC 에서 네이버를 부르지 않으려고).

2026-11-16 여성탈모 욕구 창. 씨앗마다 [씨앗 · 씨앗+띄어쓰기 · 씨앗+띄어쓰기+ㄱ~ㅎ] 를 PC · 모바일 두 곳에 친다.
새로 나온 말 중 씨앗 낱말이 든 것은 한 번 더 늘려 친다(깊이 2 · 상한 MAX_CALLS). 결과: out/naver_ac.json
"""
import json, os, random, sys, time, urllib.parse
import requests

sys.stdout.reconfigure(encoding="utf-8")
SEEDS = [s.strip() for s in open(os.environ.get("SEEDS_FILE", "data/need_ac_seeds.txt"), encoding="utf-8").read().replace(",", "\n").splitlines() if s.strip()]
MAX_CALLS = int(os.environ.get("MAX_CALLS") or 4000)
JAMO = list("ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
UAM = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
ENDS = {
    "pc": ("https://ac.search.naver.com/nx/ac", {"con": "1", "frm": "nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8",
                                                 "r_unicode": "0", "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100"}, UA),
    "mo": ("https://mac.search.naver.com/mobile/ac", {"con": "1", "frm": "mobile_nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8",
                                                      "r_unicode": "0", "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "1"}, UAM),
}
s = requests.Session()
calls, errors, got = 0, [], {}   # got[말] = {"곳": set, "친말": set}


def ac(q, where):
    global calls
    url, params, ua = ENDS[where]
    calls += 1
    try:
        r = s.get(url, params={**params, "q": q}, headers={"User-Agent": ua, "Referer": "https://www.naver.com/"}, timeout=15)
        if r.status_code != 200:
            errors.append([q, where, r.status_code])
            return []
        j = r.json()
        out = []
        for grp in j.get("items") or []:
            for it in grp or []:
                w = it[0] if isinstance(it, list) else it
                if isinstance(w, list):
                    w = w[0]
                if isinstance(w, str) and w.strip():
                    out.append(w.strip())
        return out
    except Exception as e:
        errors.append([q, where, repr(e)[:120]])
        return []
    finally:
        time.sleep(random.uniform(0.25, 0.5))


def expand(seed, depth):
    qs = [seed, seed + " "] + [seed + " " + j for j in JAMO]
    new = []
    for q in qs:
        for where in ("pc", "mo"):
            if calls >= MAX_CALLS:
                return new
            for w in ac(q, where):
                rec = got.setdefault(w, {"곳": set(), "친말": set(), "깊이": depth})
                if not rec["곳"]:
                    new.append(w)
                rec["곳"].add(where)
                rec["친말"].add(q)
    return new


core = [w.replace(" ", "") for w in SEEDS]
lvl2 = []
for i, sd in enumerate(SEEDS):
    for w in expand(sd, 1):
        if w not in SEEDS and any(c[:2] in w.replace(" ", "") for c in core):
            lvl2.append(w)
    print(f"씨앗 {i + 1}/{len(SEEDS)} · 부름 {calls} · 모은 말 {len(got)}", flush=True)
for w in dict.fromkeys(lvl2):
    if calls >= MAX_CALLS:
        break
    expand(w, 2)
print(f"끝 · 부름 {calls} · 모은 말 {len(got)} · 오류 {len(errors)}", flush=True)
os.makedirs("out", exist_ok=True)
json.dump({"씨앗": SEEDS, "부름": calls, "상한": MAX_CALLS, "오류": errors[:200], "오류수": len(errors),
           "말": {w: {"곳": sorted(v["곳"]), "친말": sorted(v["친말"])[:5], "깊이": v["깊이"]} for w, v in got.items()}},
          open("out/naver_ac.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
if not got:
    sys.exit(1)
