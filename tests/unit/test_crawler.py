"""crawler 단위 테스트."""
import pytest
import responses

from src.crawler import (
    CafeStatus,
    Crawler,
    CrawlerError,
    SlowdownController,
    parse_cafe_url,
    random_user_agent,
    resolve_short_url,
)


class TestParseCafeUrl:
    def test_full_url(self):
        slug, post_id = parse_cafe_url("https://cafe.naver.com/cosmania/38373348")
        assert slug == "cosmania"
        assert post_id == "38373348"

    def test_with_query(self):
        slug, post_id = parse_cafe_url("https://cafe.naver.com/pusanmommy/1445556?ref=foo")
        assert slug == "pusanmommy"
        assert post_id == "1445556"

    def test_with_fragment(self):
        slug, post_id = parse_cafe_url("https://cafe.naver.com/foo/123#anchor")
        assert slug == "foo"
        assert post_id == "123"

    def test_http_scheme(self):
        slug, post_id = parse_cafe_url("http://cafe.naver.com/foo/123")
        assert slug == "foo"
        assert post_id == "123"

    def test_non_cafe_url(self):
        assert parse_cafe_url("https://google.com/") == (None, None)

    def test_empty_string(self):
        assert parse_cafe_url("") == (None, None)

    def test_naver_me_not_matched(self):
        # naver.me는 별도 함수에서 처리, parse_cafe_url은 풀 URL만
        assert parse_cafe_url("https://naver.me/abc") == (None, None)


class TestResolveShortUrl:
    @responses.activate
    def test_redirects_to_full_cafe(self):
        responses.add(
            responses.HEAD,
            "https://naver.me/abc",
            status=302,
            headers={"Location": "https://cafe.naver.com/cosmania/38373348"},
        )
        result = resolve_short_url("https://naver.me/abc")
        assert result == "https://cafe.naver.com/cosmania/38373348"

    def test_full_url_returned_unchanged(self):
        full = "https://cafe.naver.com/cosmania/38373348"
        assert resolve_short_url(full) == full

    def test_empty_returned_empty(self):
        assert resolve_short_url("") == ""

    @responses.activate
    def test_network_error_returns_original(self):
        # responses 미등록 URL → ConnectionError → 원본 반환
        result = resolve_short_url("https://naver.me/xyz")
        assert result == "https://naver.me/xyz"


class TestSlowdownController:
    def test_starts_at_base(self):
        s = SlowdownController(base=1.5, max_=60)
        assert s.current_interval == 1.5

    def test_doubles_on_block(self):
        s = SlowdownController(base=1.5, max_=60)
        s.on_block_detected()
        assert s.current_interval == 3.0
        s.on_block_detected()
        assert s.current_interval == 6.0

    def test_caps_at_max(self):
        """2026-05-11 v4 fix: 5 차단 연속 시 CircuitBreakerOpen. max 도달 검증 = 4까지."""
        from src.crawler import CircuitBreakerOpen
        import pytest
        s = SlowdownController(base=1.5, max_=10)
        s.on_block_detected()  # 3.0
        s.on_block_detected()  # 6.0
        s.on_block_detected()  # 10.0 max
        s.on_block_detected()  # 10.0 cap
        assert s.current_interval == 10.0
        with pytest.raises(CircuitBreakerOpen):
            s.on_block_detected()  # 5번째 = raise

    def test_circuit_breaker_opens_at_5_blocks(self):
        """architect Major 1 fix: 5 차단 연속 = CircuitBreakerOpen raise."""
        from src.crawler import CircuitBreakerOpen
        import pytest
        s = SlowdownController(base=5.0, max_=120)
        for _ in range(4):
            s.on_block_detected()
        with pytest.raises(CircuitBreakerOpen):
            s.on_block_detected()

    def test_circuit_breaker_resets_on_success(self):
        """on_success → consecutive_blocks reset → 다음 차단 누적 0부터."""
        s = SlowdownController(base=5.0, max_=120)
        s.on_block_detected()
        s.on_block_detected()
        s.on_success()
        assert s.consecutive_blocks == 0
        for _ in range(4):
            s.on_block_detected()  # 4 차단 — raise 안 됨

    def test_recovers_on_success(self):
        s = SlowdownController(base=1.5, max_=60)
        s.on_block_detected()
        s.on_block_detected()
        prev = s.current_interval
        s.on_success()
        assert s.current_interval < prev
        assert s.consecutive_blocks == 0

    def test_recovery_floor_is_base(self):
        s = SlowdownController(base=1.5, max_=60)
        for _ in range(50):
            s.on_success()
        assert s.current_interval == 1.5


class TestRandomUserAgent:
    def test_returns_valid_ua(self):
        ua = random_user_agent()
        assert "Mozilla" in ua
        assert len(ua) > 30

    def test_varies_across_calls(self):
        seen = {random_user_agent() for _ in range(50)}
        assert len(seen) >= 2  # 풀이 4개라 50회 중 최소 2종 이상 등장 보장


class TestCrawlerFetchSearch:
    @responses.activate
    def test_returns_html_on_200(self):
        responses.add(
            responses.GET,
            "https://search.naver.com/search.naver",
            body="<html><body>" + ("샴푸 " * 200) + "</body></html>",
            status=200,
        )
        c = Crawler()
        c.slowdown.base = 0  # 테스트 빠르게
        c.slowdown.current_interval = 0
        html = c.fetch_search("샴푸")
        assert "샴푸" in html

    @responses.activate
    def test_429_triggers_slowdown_and_raises(self):
        responses.add(
            responses.GET,
            "https://search.naver.com/search.naver",
            status=429,
        )
        c = Crawler()
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        with pytest.raises(CrawlerError):
            c.fetch_search("샴푸")
        assert c.slowdown.consecutive_blocks >= 1

    @responses.activate
    def test_short_response_treated_as_blocked(self):
        responses.add(
            responses.GET,
            "https://search.naver.com/search.naver",
            body="too short",
            status=200,
        )
        c = Crawler()
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        with pytest.raises(CrawlerError):
            c.fetch_search("샴푸")


class TestCrawlerFetchCafeUrlStatus:
    @responses.activate
    def test_alive_on_normal_200(self):
        responses.add(
            responses.GET,
            "https://cafe.naver.com/foo/123",
            body="<html>" + ("정상 글 내용" * 100) + "</html>",
            status=200,
        )
        c = Crawler()
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/foo/123") == CafeStatus.ALIVE

    @responses.activate
    def test_404_treated_as_deleted(self):
        responses.add(
            responses.GET,
            "https://cafe.naver.com/foo/9999",
            status=404,
        )
        c = Crawler()
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/foo/9999") == CafeStatus.DELETED

    @responses.activate
    def test_login_wall_treated_as_private(self):
        responses.add(
            responses.GET,
            "https://cafe.naver.com/private/1",
            body='<html>nid.naver.com/nidlogin.login redirect</html>',
            status=200,
        )
        c = Crawler()
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/private/1") == CafeStatus.PRIVATE
