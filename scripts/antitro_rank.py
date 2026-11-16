"""키워드 파일 → 통합검색 카페 칸 글 + 그 글 댓글 원문 → raw148 꼴 jsonl (작업 가지 전용 · 카드 t_3005d9f5).

부르는 것은 셋뿐: Crawler.fetch_search · collect_slot_items · CommentFetcher.comments.
AI 판정 · 시트 · 기억 저장 · 텔레그램 · 열쇠 없음(돈 0 · main 쓰기 0).
우리 글 빼기는 여기서 하지 않는다 — 카페 칸 글을 앞에서부터 POSTS 편 받아 두고, 집 PC 가 우리 글 주소로 뺀다.

쓰는 법: python -m scripts.antitro_rank --keywords data/antitro_rank_kw.txt --shard 0 --shards 6 --out out.jsonl
끝 번호: 0 끝(못 받은 키워드는 줄마다 err) · 1 그 밖 오류
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.collect_comment_brands import CommentFetcher, 글쓴이_찾기, _CAFE_URL  # noqa: E402
from src.crawler import Crawler, CircuitBreakerOpen  # noqa: E402
from src.parser import collect_slot_items  # noqa: E402

KEEP = ("id", "content", "isArticleWriter", "isDeleted", "refId", "isRef")


def now() -> str:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")


def one(crawler: Crawler, fetcher: CommentFetcher, kw: str, posts: int) -> dict:
    rec: dict = {"kw": kw, "at": now(), "길": "GitHub 서버 · antitro_rank.py · 196식 잣대(우리 글 빼기는 집 PC)"}
    html = crawler.fetch_search(kw)
    items = [i for i in collect_slot_items(html) if i.kind == "cafe"]
    rec["카페칸"] = [{"구좌": i.area, "순위": i.rank, "글": i.url, "카페": i.source_name or "", "제목": i.title or ""} for i in items]
    rec["mentions"], rec["raw"], rec["못받은글"] = [], {}, []
    seen = set()
    for it in items:
        if len(seen) >= posts:
            break
        if it.url in seen:
            continue
        seen.add(it.url)
        cs = fetcher.comments(it.url) if _CAFE_URL.search(it.url) else []
        m = _CAFE_URL.search(it.url)
        club = fetcher._club.get(m.group(1)) if m else ""
        if not m:
            rec["못받은글"].append({"글": it.url, "까닭": "주소 꼴 다름"})
        elif not club:
            rec["못받은글"].append({"글": it.url, "까닭": "카페 번호 못 받음"})
        rec["raw"][it.url] = [{k: v for k, v in (x or {}).items() if k in KEEP or "ate" in k} for x in cs]
        w = 글쓴이_찾기(cs)
        rec["mentions"].append({"댓글": "", "키워드": kw, "글": it.url, "카페": it.source_name or "", "순위": it.rank, "구좌": it.area,
                                "제목": it.title or "", "글쓴이": w.get("닉", ""), "글쓴이키": w.get("키", ""),
                                "카페번호": club or "", "원천": "글", "댓글수": len(cs)})
        time.sleep(1.0)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--posts", type=int, default=6, help="키워드마다 댓글 받을 카페 칸 글 수(우리 글 포함 · 앞에서부터)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    kws = [l.strip() for l in open(a.keywords, encoding="utf-8") if l.strip()]
    mine = [k for i, k in enumerate(kws) if i % a.shards == a.shard]
    print(f"키워드 {len(kws)} 중 이 묶음({a.shard}/{a.shards}) {len(mine)}", flush=True)
    done = set()
    if os.path.exists(a.out):
        for l in open(a.out, encoding="utf-8"):
            try:
                j = json.loads(l)
            except Exception:
                continue
            if not j.get("err"):
                done.add(j["kw"])
    crawler, fetcher = Crawler(), CommentFetcher()
    crawler.warmup()
    stop = ""
    with open(a.out, "a", encoding="utf-8") as f:
        for n, kw in enumerate(mine, 1):
            if kw in done:
                continue
            if stop:
                f.write(json.dumps({"kw": kw, "at": now(), "err": stop}, ensure_ascii=False) + "\n")
                continue
            try:
                rec = one(crawler, fetcher, kw, a.posts)
            except CircuitBreakerOpen as e:
                stop = f"서버 차단 연속(circuit breaker) — 이 뒤 안 부름: {e}"
                rec = {"kw": kw, "at": now(), "err": stop}
            except Exception as e:  # 이 키워드만 못 받음 — 까닭을 남기고 다음
                rec = {"kw": kw, "at": now(), "err": f"{type(e).__name__}: {str(e)[:200]}"}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if n % 25 == 0:
                print(f"  {n}/{len(mine)} · 댓글 연 글 {fetcher.stat['열림']} · 못 연 글 {fetcher.stat['막힘']}", flush=True)
    print("끝 · 통계", json.dumps(fetcher.stat, ensure_ascii=False), "· 멈춤:", stop or "없음", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
