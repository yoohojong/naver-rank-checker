# -*- coding: utf-8 -*-
"""10-31 12:00 회차 dupilab 노출 급감 원인 가리기 (읽기 전용 · 임시 가지).

글마다: ① 글이 살아 있나(글 API) ② 그 키워드 검색 화면에 그 글이 어디 있나(순위체커 parser 그대로)
③ 검색 화면 안 dupilab 링크 수. 시트 · 카페 아무것도 쓰지 않는다.
"""
import json, os, re, sys, time, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.crawler import Crawler            # noqa: E402
from src.parser import parse_search_result  # noqa: E402
from scripts.probe_cafe_article_access import 찔러보기  # noqa: E402

pairs = json.load(open("data/probe/dupilab_pairs.json", encoding="utf-8"))
c = Crawler(); c.warmup()
for p in pairs:
    r = {"kind": p["kind"], "keyword": p["keyword"], "article": re.search(r"dupilab/(\d+)", p["link"]).group(1)}
    try:
        a = 찔러보기(p["link"])
        r["page"] = a.get("페이지"); r["api"] = a.get("글API")
    except Exception as e:
        r["api_err"] = repr(e)[:120]
    try:
        html = c.fetch_search(p["keyword"])
        res = parse_search_result(html, p["link"])
        r["area"] = str(res.exposure_area); r["rank"] = getattr(res, "rank", None)
        r["dupilab_links_in_page"] = len(set(re.findall(r"cafe\.naver\.com/dupilab/\d+", html)))
        r["this_article_in_page"] = ("dupilab/" + r["article"]) in html
        r["html_len"] = len(html)
    except Exception as e:
        r["search_err"] = repr(e)[:160]
    print(json.dumps(r, ensure_ascii=False), flush=True)
    time.sleep(random.uniform(4, 6))
try:
    x = c.session.get("https://cafe.naver.com/dupilab", timeout=15)
    print("CAFE_MAIN", x.status_code, len(x.text), flush=True)
except Exception as e:
    print("CAFE_MAIN_ERR", repr(e)[:120])
