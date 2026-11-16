"""네이버 자동완성을 조금씩 늘려 치며 모으기 — GitHub 서버 전용(11-16 잇몸치아 욕구 창).
씨앗마다: 씨앗 · '씨앗 ' · '씨앗 ㄱ'~'씨앗 ㅎ'. 나온 말 중 핵심 낱말이 든 것은 한 번 더 넓힘(깊이 2).
결과: out/naver_ac.json = {씨앗/물은말: [자동완성들]}"""
import json, os, time, urllib.parse, urllib.request
SEEDS = [w.strip() for w in open("inputs/ac_seeds.txt", encoding="utf-8").read().replace(",", "\n").splitlines() if w.strip()]
CORE = [w.strip() for w in (os.environ.get("CORE") or "잇몸,치주,치은,시린,시림,풍치,치석,스케일링,구강,입냄새,구취,치아,이빨,이가탄,인사돌,임플란트,치간,치실,치약,가글").split(",") if w.strip()]
JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
MAXQ = int(os.environ.get("MAXQ") or 3500)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
os.makedirs("out", exist_ok=True)
got, n, first = {}, 0, None
def ac(q):
    global n, first
    n += 1
    u = "https://ac.search.naver.com/nx/ac?" + urllib.parse.urlencode({"q": q, "con": "1", "frm": "nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8", "r_unicode": "0", "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100"})
    for k in range(3):
        try:
            t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.naver.com/"}), timeout=15).read().decode("utf-8")
            if first is None:
                first = t[:3000]
            d = json.loads(t)
            out = []
            for grp in d.get("items") or []:
                for it in grp or []:
                    w = it[0] if isinstance(it, list) and it else it
                    if isinstance(w, list):
                        w = w[0] if w else ""
                    if isinstance(w, str) and w.strip():
                        out.append(w.strip())
            return out
        except Exception as e:
            time.sleep(2 + k * 3)
            err = repr(e)
    return ["__실패__ " + err]
def widen(s):
    for q in [s, s + " "] + [s + " " + j for j in JAMO]:
        if n >= MAXQ or q in got:
            continue
        got[q] = ac(q)
        time.sleep(0.35)
for s in SEEDS:
    widen(s)
lv2 = []
for q, ws in list(got.items()):
    for w in ws:
        if w not in got and w not in lv2 and any(c in w for c in CORE):
            lv2.append(w)
for w in lv2:
    if n >= MAXQ:
        break
    if w in got:
        continue
    got[w] = ac(w)
    time.sleep(0.35)
    if n < MAXQ and (w + " ") not in got:
        got[w + " "] = ac(w + " ")
        time.sleep(0.35)
allw = sorted({w for ws in got.values() for w in ws if not w.startswith("__실패__")})
json.dump({"물은수": n, "씨앗": SEEDS, "깊이2": len(lv2), "모든말": allw, "물은말별": got, "첫응답": first}, open("out/naver_ac.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("물은수", n, "모든말", len(allw))
