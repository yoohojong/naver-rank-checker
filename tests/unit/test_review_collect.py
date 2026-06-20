"""review_collect 단위 테스트 (HTTP 모킹 — 토큰/네트워크 없이 검증)."""
from unittest.mock import MagicMock, patch

import pytest

from src.review_collect import _first, _to_star, fetch_low_star_reviews


def test_to_star():
    assert _to_star("2") == 2
    assert _to_star(3.0) == 3
    assert _to_star(None) is None
    assert _to_star("없음") is None


def test_first_picks_available_key():
    assert _first({"rating": 1}, ("score", "rating")) == 1
    assert _first({"score": "", "rating": 4}, ("score", "rating")) == 4
    assert _first({}, ("score",)) is None


def test_filters_low_star_and_normalizes_varied_keys():
    fake = [
        {"score": 1, "content": "최악이에요 환불함", "date": "2026-01-01", "url": "u1"},
        {"rating": 5, "review": "너무 좋아요"},                       # 고점 → 제외
        {"stars": "3", "reviewContent": "<b>그냥</b> 그래요", "writeDate": "2026-02"},
        {"score": 4, "content": "괜찮"},                              # 4점 → 제외
        {"content": "별점없음"},                                      # 별점 없음 → 제외
    ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    with patch("src.review_collect.requests.post", return_value=resp) as p:
        out = fetch_low_star_reviews(
            ["https://smartstore.naver.com/x/products/1"],
            apify_token="t", actor_id="a~b",
        )

    assert [o["star"] for o in out] == [1, 3]          # 저점만, 순서 유지
    assert out[0]["content"] == "최악이에요 환불함"
    assert out[1]["content"] == "그냥 그래요"            # 태그 제거됨
    # 토큰은 Authorization 헤더로 전송(URL 쿼리 아님) — 노출 회피 검증
    _, kwargs = p.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer t"
    assert "token" not in kwargs.get("params", {})


def test_empty_urls_no_api_call():
    with patch("src.review_collect.requests.post") as p:
        assert fetch_low_star_reviews([], apify_token="t", actor_id="a") == []
    p.assert_not_called()


def test_missing_token_raises():
    with pytest.raises(RuntimeError, match="APIFY_TOKEN"):
        fetch_low_star_reviews(["u"], apify_token="", actor_id="a")


def test_non_2xx_raises():
    resp = MagicMock(status_code=402, text="Payment Required")
    with patch("src.review_collect.requests.post", return_value=resp):
        with pytest.raises(RuntimeError, match="402"):
            fetch_low_star_reviews(["u"], apify_token="t", actor_id="a")


def test_custom_max_star():
    fake = [{"score": 2}, {"score": 1}, {"score": 3}]
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    with patch("src.review_collect.requests.post", return_value=resp):
        out = fetch_low_star_reviews(["u"], apify_token="t", actor_id="a", max_star=1)
    assert [o["star"] for o in out] == [1]


def test_real_actor_schema_accurate_dancer():
    """추천 액터(accurate_dancer~naver-smart-store-monitor)의 *실제 출력 스키마*(2026-06-20 공식페이지 검증)를
    우리 파서가 올바로 처리하는지 — 상품 레코드 스킵 + 저점 리뷰만 + createDate 추출 + brandUrls 입력."""
    fake = [
        # 상품 레코드(type=product) — score/content 없음(avgScore≠score) → 스킵돼야 함
        {"type": "product", "brand": "myshampoo", "name": "두피샴푸 500ml",
         "reviewCount": 1200, "avgScore": 4.6, "category": "헤어"},
        # 리뷰 레코드 — 2점(저점) → 포함, createDate 추출
        {"type": "review", "brand": "myshampoo", "productId": "p1",
         "productName": "두피샴푸 500ml", "score": 2,
         "content": "향이 너무 강하고 두피가 따가워요", "writerId": "user***",
         "createDate": "2026-05-30"},
        # 리뷰 레코드 — 5점(고점) → 제외
        {"type": "review", "brand": "myshampoo", "score": 5, "content": "최고",
         "createDate": "2026-05-31"},
        # 리뷰 레코드 — 1점 → 포함
        {"type": "review", "brand": "myshampoo", "productId": "p2",
         "productName": "두피샴푸 리필", "score": 1,
         "content": "한 달 썼는데 효과 없음", "createDate": "2026-06-01"},
    ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    with patch("src.review_collect.requests.post", return_value=resp) as p:
        out = fetch_low_star_reviews(
            ["myshampoo"],
            apify_token="t", actor_id="accurate_dancer~naver-smart-store-monitor",
            input_field="brandUrls",
            extra_input={"includeReviews": True, "maxReviewPages": 3},
        )

    # 상품 레코드 스킵 + 저점 리뷰만(2,1)·고점 제외
    assert [o["star"] for o in out] == [2, 1]
    assert out[0]["content"] == "향이 너무 강하고 두피가 따가워요"
    # createDate → date 추출(이전 버그: _DATE_KEYS 에 createDate 누락 → 빈값 반환했음)
    assert out[0]["date"] == "2026-05-30"
    assert out[1]["date"] == "2026-06-01"
    # 입력: brandUrls = 문자열 슬러그 리스트([{url}] 아님), includeReviews/maxReviewPages 전달, startUrls 없음
    _, kwargs = p.call_args
    body = kwargs["json"]
    assert body["brandUrls"] == ["myshampoo"]
    assert body["includeReviews"] is True
    assert body["maxReviewPages"] == 3
    assert "startUrls" not in body
