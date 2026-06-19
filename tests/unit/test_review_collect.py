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
