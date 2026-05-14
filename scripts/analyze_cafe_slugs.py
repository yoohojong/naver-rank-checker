"""T-M18: 사장님 시트 link 의 cafe slug 분포 분석 → 화이트리스트 후보 추출.

입력 1차: .harness/comparison-500-after-fix.json (500행 sample, 2026-05-11 시점)
- 사장님 시트의 link 있는 row 만 포함됨
- 카페 slug = link 의 cafe.naver.com 다음 첫 segment

출력: slug 별 행 수 표 (내림차순) + 화이트리스트 후보 (≥ 2 행 기준).

근거: 사장님 회사 카페 = 여러 키워드에 반복 작업되는 슬러그. 1회만 등장한 슬러그 = 외주/타사/실수 가능.
"""
from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def extract_cafe_slug(link: str) -> str | None:
    """cafe.naver.com/{slug}/... 에서 slug 추출. blog/web 은 None."""
    if not link or "cafe.naver.com" not in link:
        return None
    try:
        p = urlparse(link)
    except Exception:
        return None
    parts = [s for s in p.path.split("/") if s]
    if not parts:
        return None
    return parts[0]


def main() -> int:
    comparison_path = Path(__file__).resolve().parent.parent / ".harness" / "comparison-500-after-fix.json"
    if not comparison_path.exists():
        print(f"❌ {comparison_path} 없음")
        return 1

    with open(comparison_path, encoding="utf-8") as f:
        rows = json.load(f)

    cafe_counter: Counter[str] = Counter()
    blog_count = 0
    web_count = 0
    empty_count = 0
    sample_links: dict[str, list[str]] = {}

    for row in rows:
        link = (row.get("link") or "").strip()
        if not link:
            empty_count += 1
            continue
        slug = extract_cafe_slug(link)
        if slug is None:
            if "blog.naver.com" in link:
                blog_count += 1
            else:
                web_count += 1
            continue
        cafe_counter[slug] += 1
        if slug not in sample_links:
            sample_links[slug] = []
        if len(sample_links[slug]) < 2:
            sample_links[slug].append((row.get("kw"), link))

    total_with_link = len(rows) - empty_count
    print(f"=== T-M18 사장님 시트 cafe slug 분포 분석 ===")
    print(f"입력: {comparison_path.name} ({len(rows)} 행)")
    print(f"link 있는 행: {total_with_link} / link 빈 행: {empty_count}")
    print(f"cafe.naver.com: {sum(cafe_counter.values())} 행 ({len(cafe_counter)} distinct slugs)")
    print(f"blog.naver.com: {blog_count} 행")
    print(f"기타: {web_count} 행")
    print()
    print(f"=== cafe slug 분포 (내림차순) ===")
    print(f"{'rank':<5}{'slug':<25}{'rows':<8}{'sample_kw':<30}")
    print("-" * 80)
    for rank, (slug, count) in enumerate(cafe_counter.most_common(), start=1):
        first_sample = sample_links[slug][0]
        kw = first_sample[0] or ""
        print(f"{rank:<5}{slug:<25}{count:<8}{kw[:28]:<30}")

    print()
    print(f"=== 화이트리스트 후보 분석 ===")
    threshold_3 = [(s, c) for s, c in cafe_counter.most_common() if c >= 3]
    threshold_2 = [(s, c) for s, c in cafe_counter.most_common() if c >= 2]
    threshold_1 = [(s, c) for s, c in cafe_counter.most_common() if c == 1]
    print(f"≥ 3 행 ({len(threshold_3)} slugs): {[s for s, _ in threshold_3]}")
    print(f"= 2 행 ({len([x for x in threshold_2 if x[1] == 2])} slugs): {[s for s, c in threshold_2 if c == 2]}")
    print(f"= 1 행 ({len(threshold_1)} slugs): {[s for s, _ in threshold_1]}")
    print()
    print(f"=== 1 행만 등장한 slug 의 sample (외주/실수 의심) ===")
    for slug, _ in threshold_1[:20]:
        kw, link = sample_links[slug][0]
        print(f"  {slug:<22} kw={kw!r}  link={link[:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
