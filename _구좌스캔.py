# -*- coding: utf-8 -*-
"""키워드 리스트 → 카페 구좌 유형(AB/스마트블록/인기글/없음) 스캔. 증분 CSV 저장."""
import os, sys, csv, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.crawler import Crawler, SlowdownController
from src.parser import parse_search_result
from src.type_preview import suggested_type_from_block_order

KWFILE = sys.argv[1] if len(sys.argv)>1 else None
OUT    = sys.argv[2] if len(sys.argv)>2 else "_구좌스캔결과.csv"
LIMIT  = int(sys.argv[3]) if len(sys.argv)>3 else 0

kws=[l.strip() for l in open(KWFILE,encoding="utf-8") if l.strip()]
if LIMIT: kws=kws[:LIMIT]
print(f"[스캔시작] {len(kws)}개 → {OUT}", flush=True)

# 이미 있는 결과 이어받기(재개)
done=set()
if os.path.exists(OUT):
    for row in csv.reader(open(OUT,encoding="utf-8-sig")):
        # ERROR 행은 완료로 치지 않음(차단 풀렸으니 재시도)
        if row and row[0]!="keyword" and len(row)>1 and not row[1].startswith("ERROR"):
            done.add(row[0])
    print(f"[재개] 이미 {len(done)}개 완료(ERROR 제외 재시도)", flush=True)

crawler=Crawler(slowdown=SlowdownController(base=4.0, max_=90.0))
crawler.warmup()

f=open(OUT,"a",encoding="utf-8-sig",newline="")
w=csv.writer(f)
if not done: w.writerow(["keyword","slot_type","has_cafe"]); f.flush()

ok=err=streak=0
for i,kw in enumerate(kws,1):
    if kw in done: continue
    try:
        html=crawler.fetch_search(kw)
        res=parse_search_result(html, None)
        slot=suggested_type_from_block_order(res.block_order)
        w.writerow([kw, slot, int(bool(slot))]); f.flush()
        ok+=1; streak=0
        if i%20==0: print(f"  [{i}/{len(kws)}] ok={ok} err={err} 최근:{kw}={slot or '없음'}", flush=True)
    except Exception as e:
        w.writerow([kw, f"ERROR:{type(e).__name__}", ""]); f.flush()
        err+=1; streak+=1
        print(f"  [{i}] ERROR {kw}: {e} (연속{streak})", flush=True)
        # 차단 의심 시 하드 스톱 대신 백오프(연속에 비례, 최대 5분) 후 계속. 15연속이면 중단.
        back=min(30*streak, 300)
        print(f"  [백오프] {back}s 대기 후 계속", flush=True); time.sleep(back)
        if streak>=15:
            print("[중단] 15연속 오류 — 재개 스크립트로 나중에 이어감", flush=True); break
f.close()
print(f"[완료] ok={ok} err={err} → {OUT}", flush=True)
