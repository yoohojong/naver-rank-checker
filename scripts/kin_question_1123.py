"""지식인 질문 본문 받기 (2026-11-23 · 카드 t_39be783b · 읽기 전용 · 로그인 우회 없음).
data/kin_q_list_1123.json 의 글을 공개 상세 주소로 받아 첫 답변 앞 쪽(질문 영역)까지 저장.
MODE=probe: 앞 N편을 PC·모바일 두 주소로 통째 저장 / MODE=full: SHARD/NSHARD 몫만 질문 영역 저장."""
import json, os, re, time, urllib.request
MODE = os.environ.get("MODE", "full"); SHARD = int(os.environ.get("SHARD", "0")); NSH = int(os.environ.get("NSHARD", "1"))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def http(url, ref="https://kin.naver.com/", timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ref, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), (e.read().decode("utf-8", "replace") if hasattr(e, "read") else str(e))
items = json.load(open("data/kin_q_list_1123.json", encoding="utf-8"))["items"]
os.makedirs("out/q", exist_ok=True); index = []
def pc(i): return "https://kin.naver.com/qna/detail.naver?" + ("d1id=%s&" % i["d1"] if i["d1"] else "") + "dirId=%s&docId=%s" % (i["dir"], i["doc"])
def mo(i): return "https://m.kin.naver.com/mobile/qna/detail.naver?dirId=%s&docId=%s" % (i["dir"], i["doc"])
if MODE == "probe":
    N = int(os.environ.get("N", "6"))
    for i in items[:N]:
        for name, u in (("pc", pc(i)), ("mo", mo(i))):
            c, b = http(u); open("out/q/probe_%s_%s_%s.html" % (name, i["dir"], i["doc"]), "w", encoding="utf-8").write(b)
            index.append({"dir": i["dir"], "doc": i["doc"], "kind": name, "status": c, "len": len(b)}); print(name, i["dir"], i["doc"], c, len(b), flush=True); time.sleep(0.8)
else:
    mine = [i for n, i in enumerate(items) if n % NSH == SHARD]; t0 = time.time(); print("몫", len(mine), flush=True)
    for n, i in enumerate(mine):
        c, b = http(pc(i)); rec = {"dir": i["dir"], "doc": i["doc"], "d1": i["d1"], "title": i["title"], "status": c, "len": len(b)}
        if c == 200:
            e = b.find('class="answerArea'); e2 = b.find("endContentsText")
            cut = e if e > 0 else (e2 if e2 > 0 else 60000)
            s = b.find('<div class="questionArea'); s = s if s > 0 else max(0, cut - 40000)
            body = b[s:cut + 200]; body = re.sub(r"<script.*?</script>", "", body, flags=re.S); body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
            rec.update({"qstart": s, "qend": cut, "saved": len(body)}); open("out/q/%s_%s.html" % (i["dir"], i["doc"]), "w", encoding="utf-8").write(body)
        index.append(rec); time.sleep(0.9)
        if n % 25 == 0: print(n, c, len(b), flush=True)
    print("끝", len(index), "200:", sum(1 for r in index if r["status"] == 200))
json.dump(index, open("out/q/index_q_%s_%d.json" % (MODE, SHARD), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
