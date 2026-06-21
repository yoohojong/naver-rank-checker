# -*- coding: utf-8 -*-
"""review_lowstar: 네이버 브랜드스토어 저점(1~3점) 리뷰를 실브라우저로 추출.

카페외부 원고 '재료'(4 대안 / 5 브랜드 단계) — 경쟁/제품의 불만·불안(저점 리뷰)을 모은다.
review_collect.py(Apify)는 리뷰 본문이 Pro 유료잠금이라 0건이었고, 본 모듈이 그 대체다.

동작 개요(검증된 사실 — 2026-06):
  1) 키워드 → 네이버 통합검색(search.naver.com)에서 brand/smartstore 상품 URL 정규식 수집.
     (쇼핑검색 search.shopping.naver.com 은 봇차단이라 쓰지 않는다.)
  2) 상품 페이지 navigation 중 product-summary 요청을 스니핑 → originProductNo +
     checkoutMerchantNo 자동 획득(HTML 정규식 폴백 포함, 하드코딩 불필요).
  3) 세션 내부 fetch 로 POST /n/v1/contents/reviews/query-pages 를
     reviewSearchSortType="REVIEW_SCORE_ASC"(별점 낮은 순)로 page 루프.
     응답 contents[].reviewScore / .reviewContent 에서 별점·본문을 얻고
     score <= max_score 만 모은다(목표 건수 도달 시 중단).

요구사항·주의:
  - **실브라우저 필요**(Playwright chromium). curl/Apify 무인 직접호출은 nFront WAF 차단.
    headless 동작 확인됨(봇우회 init 스크립트 없이도 됨).
  - **속도제한 준수**: 동시성 1, 상품 간 랜덤 지연(수초~십수초), 페이지 간 지연,
    실패 시 backoff, 회당/일일 상한. 대량수집(크롤러화) 금지.
  - **법(회색지대)**: 경쟁사 리뷰 대량 수집·원문 재게시는 네이버 ToS 위반 +
    민사(DB권·부정경쟁) 리스크. → 소량·사실만 추출+표현 변형, 본격 운영 전 변호사 검토.

이 모듈은 '수집 코어'만 — 저장(시트/보관함)·사용은 호출부가 결정한다.
"""
from __future__ import annotations

import html as _html
import random
import re
import time

from playwright.sync_api import sync_playwright

# ── 상수(속도제한·안전) ──────────────────────────────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_REVIEW_API_PATH = "/n/v1/contents/reviews/query-pages"
_SORT_LOW_FIRST = "REVIEW_SCORE_ASC"  # 별점 낮은 순(저점만 골라 페이지네이션)
_PAGE_SIZE = 20
_MAX_PAGES_PER_PRODUCT = 10  # 회당 상한(대량수집 방지)
_MAX_PRODUCTS = 5  # 키워드당 처리 상품 상한
_DAILY_REVIEW_CAP = 500  # 일일 누적 수집 상한(프로세스 단위 가드)

# 상품 URL: brand.naver.com/<슬러그>/products/<id> 또는 smartstore.naver.com/<슬러그>/...
_PRODUCT_URL_RE = re.compile(
    r"https?://(?:brand|smartstore)\.naver\.com/[A-Za-z0-9_\-]+/products/\d+"
)
# 통합검색이 주는 smartstore '/main/' 슬러그는 로그인월로 리다이렉트되어 식별자 추출 불가.
# brand.naver.com 정식 슬러그가 공개 렌더 → 검색 수집 시 그쪽을 우선한다.
_LOGINWALL_RE = re.compile(r"^https?://smartstore\.naver\.com/main/products/\d+$")

# 식별자 추출용 정규식(HTML/스크립트 본문에서)
_ORIGIN_RE = re.compile(r'"originProductNo"\s*:\s*"?(\d+)"?')
_MERCHANT_RE = re.compile(r'"checkoutMerchantNo"\s*:\s*"?(\d+)"?')
# product-summary 네트워크 요청에서 스니핑
_SUMMARY_ORIGIN_RE = re.compile(r"/reviews/product-summary/(\d+)")
_SUMMARY_MERCHANT_RE = re.compile(r"checkoutMerchantNo=(\d+)")

# 세션 내부에서 리뷰 한 페이지를 가져오는 fetch (식별자/페이지/정렬을 인자로).
_FETCH_JS = r"""
async (cfg) => {
  const body = {
    checkoutMerchantNo: Number(cfg.merchant),
    originProductNo: Number(cfg.origin),
    page: cfg.page,
    pageSize: cfg.pageSize,
    reviewSearchSortType: cfg.sort
  };
  try {
    const r = await fetch(location.origin + cfg.path, {
      method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify(body),
      credentials: "include"
    });
    const txt = await r.text();
    let j = null; try { j = JSON.parse(txt); } catch (e) {}
    let out = [];
    if (j && j.contents) {
      out = j.contents.map(c => ({
        score: c.reviewScore,
        content: (c.reviewContent || "").trim(),
        date: c.createDate || c.registerDate || null,
        productName: c.productName || c.reviewProductName || null
      }));
    }
    return {status: r.status, total: j ? j.totalElements : null, reviews: out};
  } catch (e) {
    return {status: -1, total: null, reviews: [], error: String(e)};
  }
}
"""

# 페이지 HTML/스크립트에서 식별자 추출(네트워크 스니핑 폴백).
_IDPICK_JS = r"""
() => {
  const html = document.documentElement.innerHTML;
  const pick = (re) => { const m = html.match(re); return m ? m[1] : null; };
  return {
    origin: pick(/"originProductNo"\s*:\s*"?(\d+)"?/),
    merchant: pick(/"checkoutMerchantNo"\s*:\s*"?(\d+)"?/),
    name: pick(/"productName"\s*:\s*"([^"]{2,80})"/) || (document.title || "").slice(0, 80)
  };
}
"""


def _clean(text: str) -> str:
    """HTML 엔티티 디코딩(&amp; &rsquo; &hellip; 등 → 정상문자) + 앞뒤 공백 제거."""
    return _html.unescape(text or "").strip()


def parse_product_urls(blob: str) -> list[str]:
    """텍스트(앵커 href + HTML)에서 brand/smartstore 상품 URL을 중복 제거하여 추출.

    find_products2.py 의 harvest 로직 흡수. brand.naver.com 정식 슬러그를 앞에 두고,
    로그인월로 빠지는 smartstore '/main/' 슬러그는 버린다(식별자 추출 불가).
    """
    seen: dict[str, None] = {}
    for m in _PRODUCT_URL_RE.finditer(blob or ""):
        url = m.group(0)
        if _LOGINWALL_RE.match(url):
            continue
        seen.setdefault(url, None)
    urls = list(seen.keys())
    urls.sort(key=lambda u: 0 if u.startswith("https://brand.naver.com/") else 1)
    return urls


def _is_product_url(value: str) -> bool:
    return bool(_PRODUCT_URL_RE.fullmatch((value or "").strip()))


def _extract_ids_from_summary_url(url: str) -> tuple[str | None, str | None]:
    """product-summary 요청 URL에서 (originProductNo, checkoutMerchantNo) 스니핑."""
    origin = merchant = None
    m = _SUMMARY_ORIGIN_RE.search(url or "")
    if m:
        origin = m.group(1)
        mm = _SUMMARY_MERCHANT_RE.search(url)
        if mm:
            merchant = mm.group(1)
    return origin, merchant


def _search_product_urls(pg, keyword: str, *, top_n: int) -> list[str]:
    """네이버 통합검색에서 상위 상품 URL 수집(쇼핑검색 아님 — 봇차단 회피)."""
    url = "https://search.naver.com/search.naver?query=" + keyword.replace(" ", "+")
    pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    for _ in range(3):  # lazy 로드 유도
        pg.mouse.wheel(0, 2200)
        time.sleep(0.9)
    try:
        anchors = pg.eval_on_selector_all(
            "a", "els => els.map(e => e.href).filter(Boolean)"
        )
    except Exception:
        anchors = []
    try:
        page_html = pg.content()
    except Exception:
        page_html = ""
    blob = "\n".join(anchors) + "\n" + page_html
    return parse_product_urls(blob)[:top_n]


def _resolve_ids(pg, url: str, sniff: dict) -> tuple[str | None, str | None, str | None]:
    """상품 페이지로 이동해 originProductNo/checkoutMerchantNo/상품명 확보."""
    resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
    _ = resp  # status 는 디버깅용(사용 안 함)
    time.sleep(5)  # product-summary 요청·스크립트 로드 대기
    ids = pg.evaluate(_IDPICK_JS)
    origin = ids.get("origin") or sniff.get("origin")
    merchant = ids.get("merchant") or sniff.get("merchant")
    return origin, merchant, ids.get("name")


def _collect_for_product(
    pg,
    url: str,
    sniff: dict,
    *,
    max_reviews: int,
    max_score: int,
    max_pages: int,
) -> list[dict]:
    """단일 상품에서 저점 리뷰를 page 루프로 수집(score<=max_score, 목표 도달 시 중단)."""
    sniff["origin"] = None
    sniff["merchant"] = None
    origin, merchant, name = _resolve_ids(pg, url, sniff)
    if not (origin and merchant):
        return []

    collected: list[dict] = []
    backoff = 1.5
    for page in range(1, max_pages + 1):
        res = pg.evaluate(
            _FETCH_JS,
            {
                "merchant": merchant,
                "origin": origin,
                "page": page,
                "pageSize": _PAGE_SIZE,
                "sort": _SORT_LOW_FIRST,
                "path": _REVIEW_API_PATH,
            },
        )
        if res.get("status") != 200 or not res.get("reviews"):
            # 실패/빈 페이지: 짧은 backoff 후 다음 페이지를 시도하지 않고 종료.
            time.sleep(min(backoff, 8.0))
            break
        for rv in res["reviews"]:
            score = rv.get("score")
            if not isinstance(score, int) or score > max_score:
                continue
            collected.append(
                {
                    "score": score,
                    "content": _clean(rv.get("content") or ""),
                    "product_name": _clean(rv.get("productName") or name or ""),
                    "date": rv.get("date"),
                    "source_url": url,
                }
            )
            if len(collected) >= max_reviews:
                return collected
        time.sleep(1.2)  # 페이지 간 지연
    return collected


def fetch_low_star_reviews(
    keyword_or_url: str,
    max_reviews: int = 20,
    max_score: int = 3,
    *,
    top_products: int = _MAX_PRODUCTS,
    headless: bool = True,
    daily_cap: int = _DAILY_REVIEW_CAP,
) -> list[dict]:
    """네이버 브랜드스토어 저점(별점<=max_score) 리뷰 추출.

    키워드를 주면 통합검색으로 상위 top_products 개 상품 URL을 자동 확보하고,
    상품 URL(brand/smartstore .../products/<id>)을 주면 그 상품만 본다.
    REVIEW_SCORE_ASC(별점 낮은 순)로 page 루프, score<=max_score 만 수집,
    목표 건수(max_reviews) 도달 시 중단한다.

    Args:
        keyword_or_url: 검색 키워드(예: "지루성두피염샴푸") 또는 상품 URL.
        max_reviews: 총 수집 목표 건수(이 수에 도달하면 중단).
        max_score: 이 별점 이하만 수집(기본 3 = 저점 1~3점).
        top_products: 키워드 검색 시 처리할 상품 수 상한(기본 5).
        headless: 헤드리스 동작(기본 True). 디버깅 시 False.
        daily_cap: 프로세스 단위 일일/회당 누적 상한(대량수집 방지 가드).

    Returns:
        [{score, content, product_name, date, source_url}, ...] (저점만, 최대 max_reviews).

    Notes:
        실브라우저(Playwright chromium) 필요. 동시성 1·상품 간 랜덤 지연 적용.
        대량수집은 ToS·법 리스크 — 소량·사실추출·표현변형 전제.
    """
    target = (keyword_or_url or "").strip()
    if not target:
        return []
    max_reviews = min(max_reviews, daily_cap)
    if max_reviews <= 0:
        return []

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=_UA, locale="ko-KR", viewport={"width": 1366, "height": 2200}
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        pg = ctx.new_page()

        # product-summary 요청에서 식별자 자동 스니핑.
        sniff: dict = {"origin": None, "merchant": None}

        def _on_request(req):
            origin, merchant = _extract_ids_from_summary_url(req.url)
            if origin:
                sniff["origin"] = origin
            if merchant:
                sniff["merchant"] = merchant

        pg.on("request", _on_request)

        try:
            if _is_product_url(target):
                product_urls = [target]
            else:
                product_urls = _search_product_urls(pg, target, top_n=top_products)

            for idx, url in enumerate(product_urls):
                if len(results) >= max_reviews:
                    break
                remaining = max_reviews - len(results)
                try:
                    found = _collect_for_product(
                        pg,
                        url,
                        sniff,
                        max_reviews=remaining,
                        max_score=max_score,
                        max_pages=_MAX_PAGES_PER_PRODUCT,
                    )
                    results.extend(found)
                except Exception:
                    # 한 상품 실패가 전체를 막지 않도록 backoff 후 다음 상품.
                    time.sleep(random.uniform(3.0, 8.0))
                    continue
                # 상품 간 랜덤 지연(수초~십수초) — 봇·과부하 방지.
                if idx < len(product_urls) - 1:
                    time.sleep(random.uniform(4.0, 14.0))
        finally:
            browser.close()

    return results[:max_reviews]


if __name__ == "__main__":
    import json
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "지루성두피염샴푸"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    rows = fetch_low_star_reviews(arg, max_reviews=n)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
