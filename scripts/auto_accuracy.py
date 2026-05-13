"""자동 정확도 측정 - 사장님 직접 검증 없이 parser 자체 결함 자동 발견.

방법:
1. 사장님 시트 832 행 중 random 100 키워드 선택 (SPREADSHEET_ID 탭 필터: "카외" 끝)
2. HTML fetch + parser 결과 = parser_K (AB / 인기글 / 미노출)
3. 같은 HTML = 박스 안 CAFE_WHITELIST 카페 글 직접 검출 = direct_K (ground truth)
4. parser_K vs direct_K 일치율 = 진짜 정확도
5. mismatch 사례 = JSON 저장 + 콘솔 리포트

산출물: .harness/auto-accuracy-{timestamp}.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.config import (
    SPREADSHEET_ID,
    SERVICE_ACCOUNT_JSON,
    NAVER_SLOWDOWN_BASE_SEC,
    NAVER_SLOWDOWN_MAX_SEC,
    CAFE_WHITELIST,
)
from src.crawler import Crawler, SlowdownController
from src.parser import parse_search_result, _POPULAR_SKIP_PATTERNS
from src.sheets import SheetsClient


def _normalize_url(url: str):
    """URL 정규화 = (netloc, path) 튜플 반환 (parser._urls_match 와 동일 로직).

    - m. 서브도메인 제거
    - path 끝 슬래시 제거
    - 파싱 실패 시 None 반환
    """
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    netloc = p.netloc
    if netloc.startswith("m."):
        netloc = netloc[2:]
    path = p.path.rstrip("/")
    return (netloc, path)


def detect_direct_K(html: str, target_link: str, all_known_links: set) -> dict:
    """ground truth 검출 (사장님 의도 정합):

    - HTML 박스 안 link 가 target_link 또는 all_known_links 안 link 중 하나와 정확 매치
    - 매치 시 = 박스 분류 (h2 없음 = AB / h2 있음 = 인기글)
    - 매치 X 시 = 미노출

    시트 미등록 새 글(화이트리스트 slug 일치)은 ground truth에서 제외 = 사장님 의도 정합.

    반환값:
        K: "AB" / "인기글" / "미노출"
        boxes_with_cafe: 시트 등록 link 매치된 박스 정보 리스트 (디버깅용)
    """
    # 매치 대상 link set 구성 (target_link + all_known_links 정규화)
    target_norm = {_normalize_url(target_link)} if target_link else set()
    known_norm = {_normalize_url(l) for l in all_known_links if l}
    valid_matches = target_norm | known_norm
    valid_matches.discard(None)

    if not html or not valid_matches:
        return {"K": "미노출", "boxes_with_cafe": []}

    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    boxes_with_match = []
    for i, box in enumerate(boxes, 1):
        h2 = box.find("h2")
        h2_text = h2.get_text(strip=True) if h2 else None

        # h2 있고 skip 패턴이면 검출 대상 제외 (광고/이미지/AI 등)
        if h2_text and any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
            continue

        # 박스 안 link = 시트 등록 link 정확 매치 검증 (화이트리스트 slug 매치 X)
        matches = []
        for a in box.find_all("a", href=True):
            href = a["href"]
            if "cafe.naver.com" not in href:
                continue
            href_norm = _normalize_url(href)
            if href_norm and href_norm in valid_matches:
                matches.append(href[:100])

        if matches:
            box_kind = "no_h2" if h2 is None else "h2_box"
            boxes_with_match.append({
                "idx": i,
                "h2": h2_text,
                "kind": box_kind,
                "matches": len(matches),
            })

    if not boxes_with_match:
        return {"K": "미노출", "boxes_with_cafe": []}

    # 첫 번째 매치 박스 기준으로 K 분류
    first_box = boxes_with_match[0]
    if first_box["kind"] == "no_h2":
        # h2 없음 + 시트 등록 link 매치 = AB
        K = "AB"
    else:
        # h2 있음 + skip 패턴 아님 + 시트 등록 link 매치 = 인기글
        K = "인기글"

    return {"K": K, "boxes_with_cafe": boxes_with_match}


def main() -> Optional[int]:
    ap = argparse.ArgumentParser(
        description="parser 자동 정확도 측정: CAFE_WHITELIST 카페 글 직접 검출 vs parser 결과 비교"
    )
    ap.add_argument("--sample", type=int, default=100, help="random sample 키워드 수 (기본: 100)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (재현 가능성, 기본: 42)")
    args = ap.parse_args()

    # 환경변수 누락 검사
    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("[ERROR] SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 환경변수 누락")
        print("   GitHub Actions Secrets 또는 로컬 .env 설정 후 재실행 의무")
        return 1

    # 1. 시트 read = 키워드 + 링크 목록 수집
    print("시트 데이터 로드 중...")
    client = SheetsClient(
        spreadsheet_id=SPREADSHEET_ID,
        service_account_json=SERVICE_ACCOUNT_JSON,
    )
    data = client.load_all_data_tabs(tab_filter=lambda t: t.endswith("카외"))
    all_rows: list[tuple[str, str]] = []
    for tab_rows in data.values():
        for r in tab_rows:
            kw = r.get("키워드", "").strip()
            link = r.get("링크", "").strip()
            if kw:
                all_rows.append((kw, link))

    if not all_rows:
        print("[ERROR] 시트에서 유효한 키워드를 찾지 못함 (탭 필터 = '카외' 끝)")
        return 1

    print(f"전체 {len(all_rows)} 키워드 수집 완료")

    # T-M14.2 정합: 시트 전체 link set 박... 박... = link_set fallback 매치 활용 (사장님 의도 정합)
    all_known_links: set = set()
    for kw, link in all_rows:
        if link:
            all_known_links.add(link)
    print(f"link_set 크기: {len(all_known_links)} (T-M14.2 fallback 매치 활용)")

    # 2. random sample 선택
    random.seed(args.seed)
    sample = random.sample(all_rows, min(args.sample, len(all_rows)))
    print(f"=== {len(sample)} 키워드 자동 정확도 측정 시작 ===")

    # 3. crawler 초기화 + warmup
    crawler = Crawler(
        slowdown=SlowdownController(
            base=NAVER_SLOWDOWN_BASE_SEC,
            max_=NAVER_SLOWDOWN_MAX_SEC,
        )
    )
    crawler.warmup()

    # 4. 각 키워드 처리
    results: list[dict] = []
    parser_K_counter: Counter = Counter()
    direct_K_counter: Counter = Counter()
    match_count = 0

    for idx, (kw, link) in enumerate(sample, 1):
        try:
            html = crawler.fetch_search(kw)
        except Exception as e:
            print(f"  [{idx:3d}] {kw!r}: ERROR ({e})")
            continue

        # parser 결과 (T-M14.2 정합 = target_url + link_set fallback)
        target_url: Optional[str] = link if link else None
        parser_result = parse_search_result(html, target_url=target_url)
        # T-M14.2 fallback: 시트 link 매치 X = 다른 행 link 매치 시도 (사장님 의도 정합)
        if parser_result.exposure_area.value == "미노출" and all_known_links:
            other_links = all_known_links - {link} if link else all_known_links
            if other_links:
                fallback = parse_search_result(html, target_url=None, link_set=other_links)
                if fallback.exposure_area.value != "미노출":
                    parser_result = fallback
        # T-M14.7 폐기 (2026-05-14): slug 매치 fallback 제거 (사장님 의도 = 시트 등록 link 정확 매치만).
        parser_K = parser_result.exposure_area.value

        # direct 검출 (ground truth) — 시트 등록 link 정확 매치만 (사장님 의도 정합)
        direct = detect_direct_K(html, target_link=link, all_known_links=all_known_links)
        direct_K = direct["K"]

        match = (parser_K == direct_K)
        if match:
            match_count += 1
        parser_K_counter[parser_K] += 1
        direct_K_counter[direct_K] += 1

        results.append({
            "kw": kw,
            "link": link[:80] if link else "",
            "parser_K": parser_K,
            "direct_K": direct_K,
            "match": match,
            "boxes_with_cafe": direct["boxes_with_cafe"][:3],  # 디버깅용 (최대 3개)
        })

        # 진행 상황 출력 (10개 단위)
        if idx % 10 == 0:
            print(f"  진행: {idx}/{len(sample)} (일치율 {match_count/idx*100:.1f}%)")

    if not results:
        print("[ERROR] 처리된 결과 없음 - 네트워크 / 차단 확인 의무")
        return 1

    # 5. 결과 저장
    kst = timezone(timedelta(hours=9))
    ts = datetime.now(kst).strftime("%Y-%m-%dT%H-%M-KST")
    out_path = Path(".harness") / f"auto-accuracy-{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    accuracy = match_count / len(results) * 100
    mismatch_cases = [r for r in results if not r["match"]]

    summary = {
        "timestamp_kst": ts,
        "sample_size": len(results),
        "match_count": match_count,
        "accuracy_pct": round(accuracy, 2),
        "parser_K_distribution": dict(parser_K_counter),
        "direct_K_distribution": dict(direct_K_counter),
        "mismatch_count": len(mismatch_cases),
        "results": results,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 6. 결과 출력
    print()
    print("=== 결과 ===")
    print(f"전체: {len(results)} 키워드")
    print(f"일치: {match_count} / {len(results)} = {accuracy:.1f}%")
    print(f"parser K 분포: {dict(parser_K_counter)}")
    print(f"direct K 분포: {dict(direct_K_counter)}")
    print(f"mismatch: {len(mismatch_cases)} 건")
    print(f"결과 저장: {out_path}")
    print()

    if mismatch_cases:
        print("mismatch 사례 (상위 5건):")
        for r in mismatch_cases[:5]:
            print(f"  kw={r['kw']!r:30s} parser={r['parser_K']:5s} direct={r['direct_K']:5s}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
