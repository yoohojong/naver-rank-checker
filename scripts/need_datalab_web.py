"""욕구 검색어의 달마다 검색 흐름 받기 — 네이버 데이터랩 공개 화면(로그인 없음) · GitHub 서버 전용.

2026-10-26 노력 욕구 창. 공식 API 열쇠에 데이터랩 권한이 없어(024) 공개 화면 길로 받는다.
한 번에 묶음 5개(기준 1 + 검색어 4). 결과: out/need_datalab_web.json
"""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright

ANCHOR = os.environ.get("ANCHOR") or "다이어트"
START = (os.environ.get("START") or "2023-10-01").replace("-", "")
END = (os.environ.get("END") or "2026-09-30").replace("-", "")
words, seen = [], set()
for w in (os.environ.get("KEYWORDS") or "").replace("\n", ",").split(","):
    w = w.strip()
    if w and w != ANCHOR and w not in seen:
        seen.add(w)
        words.append(w)
if not words:
    sys.exit("검색어 없음")
os.makedirs("out", exist_ok=True)
SEARCH = "https://datalab.naver.com/keyword/trendSearch.naver"
FETCH_JS = """async (f) => {
  const r = await fetch('/qcHash.naver', {method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'},
    body: new URLSearchParams(f).toString()});
  return await r.text();
}"""


def groups_str(names):
    return "__OUML__".join(f"{n}__SZLIG__{n}" for n in names)


result, failed, raw_first = {}, [], None
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(locale="ko-KR")
    p.goto(SEARCH, wait_until="networkidle", timeout=60000)
    for i in range(0, len(words), 4):
        chunk = words[i:i + 4]
        names = [ANCHOR] + chunk
        try:
            txt = p.evaluate(FETCH_JS, {"queryGroups": groups_str(names), "startDate": START, "endDate": END,
                                        "timeUnit": "date", "gender": "", "age": "", "device": ""})
            if raw_first is None and i == 0:
                open("out/qchash_first.txt", "w", encoding="utf-8").write(txt[:200000])
            m = re.search(r"N_[0-9a-f]{20,}", txt)
            if not m:
                raise RuntimeError("hashKey 없음: " + txt[:200])
            caught = []
            def _on(r):
                try:
                    if r.request.resource_type in ("xhr", "fetch"):
                        caught.append((r.url, r.text()))
                except Exception:
                    pass
            p.on("response", _on)
            p.goto(f"https://datalab.naver.com/keyword/trendResult.naver?hashKey={m.group(0)}",
                   wait_until="networkidle", timeout=60000)
            p.wait_for_timeout(3000)
            p.remove_listener("response", _on)
            g = p.eval_on_selector("input#graphData, input[name=graphData]", "e => e.value") or ""
            data = None
            if g.strip():
                data = json.loads(g)
            else:
                for u, t in caught:
                    if '"period"' in t:
                        j = json.loads(t)
                        data = j.get("results") or j.get("result") or j.get("data") or j
                        break
            if raw_first is None:
                open("out/caught_first.json", "w", encoding="utf-8").write(
                    json.dumps([(u, t[:3000]) for u, t in caught], ensure_ascii=False, indent=1))
            if data is None:
                # 결과 화면은 값을 그래프(billboard.js) 안에 담는다 — 그래프에서 바로 읽는다
                bbd = p.evaluate("""() => (window.bb && bb.instance || []).map(c => c.data().map(d => ({
                    title: d.id, data: d.values.map(v => ({period: (v.x instanceof Date ? v.x.toISOString() : String(v.x)), value: v.value}))})))""")
                bbd = [x for x in bbd if x]
                if bbd:
                    data = bbd[0]
                    names_order = names
                    # 그래프 id 가 data1.. 같은 이름이면 넣은 순서대로 붙인다
                    if all(grp["title"] not in names_order for grp in data) and len(data) == len(names_order):
                        for grp, n in zip(data, names_order):
                            grp["title"] = n
            if data is None:
                st = p.evaluate("() => JSON.stringify({s: Object.entries(sessionStorage).map(([k,v])=>[k,v.slice(0,3000)]), l: Object.entries(localStorage).map(([k,v])=>[k,v.slice(0,3000)]), w: Object.keys(window).filter(k=>/data|graph|chart|bb|trend/i.test(k))})")
                open("out/storage.json", "w", encoding="utf-8").write(st)
                open("out/full_page.html", "w", encoding="utf-8").write(p.content())
                raise RuntimeError("값 자리 못 찾음 · 잡힌 요청 " + ", ".join(u for u, _ in caught)[:400])
            if isinstance(data, dict):
                data = data.get("results") or data.get("data") or [data]
            if raw_first is None:
                raw_first = data
            series = {}
            for grp in data:
                title = grp.get("title") or grp.get("keyword") or grp.get("name")
                rows = grp.get("data") or grp.get("datas") or []
                # 달마다 단위는 이 화면에서 받지 않아(INVALID_PARAMS) 날마다 값을 받아 달 평균으로 묶는다
                acc = {}
                for r in rows:
                    d = re.sub(r"\D", "", str(r.get("period")))
                    acc.setdefault(f"{d[:4]}-{d[4:6]}", []).append(float(r.get("value", r.get("ratio", 0)) or 0))
                series[title] = {k: round(sum(v) / len(v), 3) for k, v in acc.items()}
            base = series.get(ANCHOR, {})
            for w in chunk:
                result[w] = [{"달": k, "원값": v, "기준대비": round(v / base[k], 4) if base.get(k) else None}
                             for k, v in sorted(series.get(w, {}).items())]
            print(f"{min(i + 4, len(words))}/{len(words)}", flush=True)
            p.goto(SEARCH, wait_until="domcontentloaded", timeout=60000)
            time.sleep(1.0)
        except Exception as e:  # 한 묶음이 실패해도 나머지는 받는다
            print("실패", chunk, e, file=sys.stderr)
            failed += chunk
            if raw_first is None and i == 0:
                try:
                    open("out/first_fail_page.txt", "w", encoding="utf-8").write(p.content()[:200000])
                except Exception:
                    pass
    b.close()

json.dump({"기준": ANCHOR, "기간": [START, END], "검색어": result, "실패": failed, "원자료_첫묶음": raw_first},
          open("out/need_datalab_web.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"받음 {len(result)} · 실패 {len(failed)}")
if not result:
    sys.exit(1)
