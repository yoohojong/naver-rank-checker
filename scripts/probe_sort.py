# -*- coding: utf-8 -*-
"""리뷰 API의 sort/필터 파라미터 탐색 — 저점 리뷰를 효율적으로 모으는 방법 찾기."""
import sys, time, json
from playwright.sync_api import sync_playwright
def log(*a): print(*a, flush=True)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://brand.naver.com/headandshoulderskr/products/4918620985"

# 시도할 sort 타입들 + score 필터 후보
SORTS = ["REVIEW_RANKING", "REVIEW_CREATE_DATE_DESC", "REVIEW_CREATE_DATE_ASC",
         "REVIEW_SCORE_ASC", "REVIEW_SCORE_DESC", "LOW_SCORE", "SCORE_ASC"]

TRY_JS = r"""
async (cfg) => {
  const results = {};
  // 1) sort 타입별 page1 첫 5개 점수
  for (const sort of cfg.sorts) {
    const body = {checkoutMerchantNo:Number(cfg.merchant), originProductNo:Number(cfg.origin),
                  page:1, pageSize:20, reviewSearchSortType:sort};
    try {
      const r = await fetch(location.origin+"/n/v1/contents/reviews/query-pages",{method:"POST",
        headers:{"Content-Type":"application/json","Accept":"application/json"},
        body:JSON.stringify(body),credentials:"include"});
      const txt = await r.text(); let j=null; try{j=JSON.parse(txt);}catch(e){}
      results[sort] = {status:r.status,
        scores: (j&&j.contents)? j.contents.map(c=>c.reviewScore).slice(0,12): null,
        total: j? j.totalElements : null};
    } catch(e){ results[sort] = {err:String(e)}; }
  }
  // 2) score 필터 파라미터 후보 (REVIEW_CREATE_DATE_DESC + 추가키)
  const filterTries = [
    {name:"reviewScoreArray", extra:{reviewScoreArray:[1,2,3]}},
    {name:"scores", extra:{scores:[1,2,3]}},
    {name:"reviewScore", extra:{reviewScore:1}},
  ];
  results._filters = {};
  for (const ft of filterTries) {
    const body = Object.assign({checkoutMerchantNo:Number(cfg.merchant), originProductNo:Number(cfg.origin),
                  page:1, pageSize:20, reviewSearchSortType:"REVIEW_CREATE_DATE_DESC"}, ft.extra);
    try {
      const r = await fetch(location.origin+"/n/v1/contents/reviews/query-pages",{method:"POST",
        headers:{"Content-Type":"application/json","Accept":"application/json"},
        body:JSON.stringify(body),credentials:"include"});
      const txt = await r.text(); let j=null; try{j=JSON.parse(txt);}catch(e){}
      results._filters[ft.name] = {status:r.status,
        scores:(j&&j.contents)? j.contents.map(c=>c.reviewScore).slice(0,12): null,
        total:j?j.totalElements:null};
    } catch(e){ results._filters[ft.name] = {err:String(e)}; }
  }
  return results;
}
"""

import re
def run(url):
    sniff={"origin":None,"merchant":None}
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=["--disable-blink-features=AutomationControlled"])
        ctx=b.new_context(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),locale="ko-KR",
            viewport={"width":1366,"height":900})
        pg=ctx.new_page()
        def on_req(req):
            m=re.search(r"/reviews/product-summary/(\d+)",req.url)
            if m:
                sniff["origin"]=m.group(1)
                mm=re.search(r"checkoutMerchantNo=(\d+)",req.url)
                if mm: sniff["merchant"]=mm.group(1)
        pg.on("request",on_req)
        pg.goto(url,wait_until="domcontentloaded",timeout=45000)
        time.sleep(6)
        # HTML 기반 폴백 추출
        ids = pg.evaluate(r"""() => {
          const html=document.documentElement.innerHTML;
          const pick=(re)=>{const m=html.match(re);return m?m[1]:null;};
          return {origin: pick(/"originProductNo"\s*:\s*"?(\d+)"?/),
                  merchant: pick(/"checkoutMerchantNo"\s*:\s*"?(\d+)"?/)};
        }""")
        origin=sniff["origin"] or ids.get("origin")
        merchant=sniff["merchant"] or ids.get("merchant")
        log(f"[ids] origin={origin} merchant={merchant} (sniff={sniff} html={ids})")
        res=pg.evaluate(TRY_JS,{"sorts":SORTS,"origin":origin,"merchant":merchant})
        log(json.dumps(res,ensure_ascii=False,indent=2))
        b.close()

if __name__=="__main__":
    run(URL)
