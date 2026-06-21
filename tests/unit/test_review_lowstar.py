"""review_lowstar 단위 테스트 (네트워크/브라우저는 목·픽스처로 — 실호출 없음)."""
from unittest.mock import MagicMock, patch

from src.review_lowstar import (
    _clean,
    _collect_for_product,
    _extract_ids_from_summary_url,
    _is_product_url,
    fetch_low_star_reviews,
    parse_product_urls,
)


# ── HTML 엔티티 디코딩 ────────────────────────────────────────────────────────
def test_clean_decodes_html_entities():
    assert _clean("머릿결 &amp; 두피") == "머릿결 & 두피"
    assert _clean("별로에요&rsquo;&hellip;") == "별로에요’…"
    assert _clean("  앞뒤공백  ") == "앞뒤공백"
    assert _clean("") == ""
    assert _clean(None) == ""


# ── URL 파싱 / 식별 ──────────────────────────────────────────────────────────
def test_parse_product_urls_extracts_dedupes_and_prefers_brand():
    blob = (
        "noise https://smartstore.naver.com/abc/products/123 noise\n"
        "<a href='https://brand.naver.com/aromatica/products/8734492045'>x</a>\n"
        "dup https://brand.naver.com/aromatica/products/8734492045 again\n"
        "https://search.naver.com/irrelevant"
    )
    # brand.naver.com 이 smartstore 보다 앞으로 정렬, 중복 제거.
    assert parse_product_urls(blob) == [
        "https://brand.naver.com/aromatica/products/8734492045",
        "https://smartstore.naver.com/abc/products/123",
    ]


def test_parse_product_urls_drops_loginwall_main_slug():
    blob = (
        "https://smartstore.naver.com/main/products/7215010479\n"  # 로그인월 → 제외
        "https://brand.naver.com/realbrand/products/999"
    )
    assert parse_product_urls(blob) == [
        "https://brand.naver.com/realbrand/products/999"
    ]


def test_parse_product_urls_empty():
    assert parse_product_urls("") == []
    assert parse_product_urls(None) == []


def test_is_product_url():
    assert _is_product_url("https://brand.naver.com/headandshoulderskr/products/4918620985")
    assert _is_product_url(" https://smartstore.naver.com/abc/products/9 ")
    assert not _is_product_url("지루성두피염샴푸")
    assert not _is_product_url("https://search.naver.com/search.naver?query=x")
    # products 경로 뒤에 군더더기가 붙으면 fullmatch 실패(키워드로 취급)
    assert not _is_product_url("https://brand.naver.com/a/products/1/extra")


def test_extract_ids_from_summary_url():
    url = (
        "https://brand.naver.com/n/v1/contents/reviews/product-summary/8693285760"
        "?checkoutMerchantNo=500131124&foo=bar"
    )
    assert _extract_ids_from_summary_url(url) == ("8693285760", "500131124")
    # merchant 없는 경우 origin만
    assert _extract_ids_from_summary_url(
        "https://x/reviews/product-summary/777"
    ) == ("777", None)
    # 무관 URL
    assert _extract_ids_from_summary_url("https://x/other") == (None, None)


# ── 빈 입력 가드(브라우저 안 띄움) ───────────────────────────────────────────
def test_empty_input_returns_empty_without_browser():
    with patch("src.review_lowstar.sync_playwright") as sp:
        assert fetch_low_star_reviews("   ") == []
        assert fetch_low_star_reviews("x", max_reviews=0) == []
    sp.assert_not_called()


# ── score<=max_score 필터 + 목표 건수 중단 (page fetch 목) ─────────────────────
def _fake_page_with_reviews(pages):
    """pages: page번호별 fetch 결과 리스트. _resolve_ids/_FETCH_JS evaluate를 목."""
    pg = MagicMock()
    state = {"page": 0}

    def _evaluate(js, arg=None):
        # 첫 evaluate(_IDPICK_JS, 인자없음) → 식별자 반환
        if arg is None:
            return {"origin": "100", "merchant": "200", "name": "테스트샴푸"}
        # 이후 _FETCH_JS(arg=cfg) → page 순서대로 결과
        state["page"] += 1
        idx = state["page"] - 1
        return pages[idx] if idx < len(pages) else {"status": 200, "total": 0, "reviews": []}

    pg.evaluate.side_effect = _evaluate
    pg.goto.return_value = MagicMock(status=200)
    return pg


def test_collect_filters_low_scores_only():
    pages = [
        {
            "status": 200,
            "total": 10,
            "reviews": [
                {"score": 1, "content": "최악 &amp; 환불", "date": "2026-01-01", "productName": "샴푸A"},
                {"score": 3, "content": "그냥그래요", "date": "2026-01-02", "productName": "샴푸A"},
                {"score": 5, "content": "최고!", "date": "2026-01-03", "productName": "샴푸A"},
                {"score": 4, "content": "괜찮음", "date": "2026-01-04", "productName": "샴푸A"},
            ],
        },
    ]
    pg = _fake_page_with_reviews(pages)
    with patch("src.review_lowstar.time.sleep"):
        out = _collect_for_product(
            pg,
            "https://brand.naver.com/x/products/1",
            {"origin": None, "merchant": None},
            max_reviews=20,
            max_score=3,
            max_pages=10,
        )
    assert [r["score"] for r in out] == [1, 3]  # 4·5점 제외
    assert out[0]["content"] == "최악 & 환불"  # 엔티티 디코딩됨
    assert out[0]["source_url"] == "https://brand.naver.com/x/products/1"
    assert out[0]["product_name"] == "샴푸A"


def test_collect_stops_at_max_reviews():
    pages = [
        {
            "status": 200,
            "total": 99,
            "reviews": [
                {"score": 1, "content": "a", "date": None, "productName": "P"},
                {"score": 2, "content": "b", "date": None, "productName": "P"},
                {"score": 1, "content": "c", "date": None, "productName": "P"},
            ],
        },
    ]
    pg = _fake_page_with_reviews(pages)
    with patch("src.review_lowstar.time.sleep"):
        out = _collect_for_product(
            pg,
            "https://brand.naver.com/x/products/1",
            {"origin": None, "merchant": None},
            max_reviews=2,
            max_score=3,
            max_pages=10,
        )
    assert len(out) == 2  # 목표 2건에서 중단


def test_collect_returns_empty_when_ids_unresolved():
    pg = MagicMock()
    pg.goto.return_value = MagicMock(status=200)
    # _IDPICK_JS 가 식별자 없이 반환 → 수집 불가
    pg.evaluate.return_value = {"origin": None, "merchant": None, "name": None}
    with patch("src.review_lowstar.time.sleep"):
        out = _collect_for_product(
            pg,
            "https://brand.naver.com/x/products/1",
            {"origin": None, "merchant": None},
            max_reviews=10,
            max_score=3,
            max_pages=5,
        )
    assert out == []


def test_collect_breaks_on_non_200():
    pages = [{"status": 403, "total": None, "reviews": []}]
    pg = _fake_page_with_reviews(pages)
    with patch("src.review_lowstar.time.sleep"):
        out = _collect_for_product(
            pg,
            "https://brand.naver.com/x/products/1",
            {"origin": None, "merchant": None},
            max_reviews=10,
            max_score=3,
            max_pages=5,
        )
    assert out == []
