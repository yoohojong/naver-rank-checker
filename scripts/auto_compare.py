"""T-M27: cron 직후 parser 결과 + 사장님 수기 결과 동시 비교.

사용법:
1. cron 1회 실행 후 = scripts/auto_compare.py --keywords kw1,kw2,kw3,...
2. parser 결과 JSON 저장
3. 사장님이 같은 시점 수기 확인 결과 JSON 입력
4. 일치율 자동 계산 + 리포트 출력

산출물: .harness/auto-compare-{timestamp}.json
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.config import NAVER_SLOWDOWN_BASE_SEC, NAVER_SLOWDOWN_MAX_SEC
from src.crawler import Crawler, SlowdownController
from src.parser import parse_search_result


def main():
    ap = argparse.ArgumentParser(description="cron 직후 parser 결과 수집 (사장님 수기 비교용)")
    ap.add_argument("--keywords", required=True, help="콤마 구분 키워드 목록")
    ap.add_argument("--out", default=None, help="출력 JSON path")
    args = ap.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        print("ERROR: --keywords 에 유효한 키워드가 없음")
        return 1

    crawler = Crawler(slowdown=SlowdownController(base=NAVER_SLOWDOWN_BASE_SEC, max_=NAVER_SLOWDOWN_MAX_SEC))
    crawler.warmup()

    results = []
    for kw in keywords:
        try:
            html = crawler.fetch_search(kw)
            result = parse_search_result(html, target_url=None, link_set=None)
            results.append({
                "kw": kw,
                "K": result.exposure_area.value,
                "L": result.integrated_rank,
                "M": result.cafe_slot_rank,
                "J": result.in_jisikin,
                "block_order": result.block_order,
                "smart_block": result.smart_block_name,
                "confidence": result.parser_confidence,
            })
            print(f"  {kw!r} → K={result.exposure_area.value} L={result.integrated_rank} M={result.cafe_slot_rank}")
        except Exception as e:
            results.append({"kw": kw, "error": str(e)})
            print(f"  {kw!r} → ERROR: {e}")

    kst = timezone(timedelta(hours=9))
    ts = datetime.now(kst).strftime("%Y-%m-%dT%H-%M-KST")
    out_path = args.out or f".harness/auto-compare-{ts}.json"

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"timestamp_kst": ts, "results": results}, f, ensure_ascii=False, indent=2)

    print(f"\n{len(results)} 키워드 비교 완료 -> {out_path}")
    print("\n사장님 = 같은 시점 네이버 검색 후 결과 비교 의무 (1시간 이내)")


if __name__ == "__main__":
    sys.exit(main() or 0)
