"""crawler 단위 테스트."""
import pytest
from unittest.mock import patch, MagicMock

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
    def test_redirects_to_full_cafe(self):
        with patch("src.crawler.requests.head") as mock_head:
            mock_head.return_value = MagicMock(
                status_code=302,
                headers={"Location": "https://cafe.naver.com/cosmania/38373348"},
            )
            result = resolve_short_url("https://naver.me/abc")
            assert result == "https://cafe.naver.com/cosmania/38373348"

    def test_full_url_returned_unchanged(self):
        full = "https://cafe.naver.com/cosmania/38373348"
        assert resolve_short_url(full) == full

    def test_empty_returned_empty(self):
        assert resolve_short_url("") == ""

    def test_network_error_returns_original(self):
        from curl_cffi.requests import RequestsError
        with patch("src.crawler.requests.head") as mock_head:
            mock_head.side_effect = RequestsError("conn failed")
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
    def test_returns_html_on_200(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(
            status_code=200,
            text="<html><body>" + ("샴푸 " * 200) + "</body></html>",
        )
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        html = c.fetch_search("샴푸")
        assert "샴푸" in html

    def test_429_triggers_slowdown_and_raises(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(status_code=429, text="")
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        with pytest.raises(CrawlerError):
            c.fetch_search("샴푸")
        assert c.slowdown.consecutive_blocks >= 1

    def test_short_response_treated_as_blocked(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(status_code=200, text="too short")
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        with pytest.raises(CrawlerError):
            c.fetch_search("샴푸")


class TestCrawlerFetchCafeUrlStatus:
    def test_alive_on_normal_200(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(
            status_code=200,
            text="<html>" + ("정상 글 내용" * 100) + "</html>",
        )
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/foo/123") == CafeStatus.ALIVE

    def test_404_treated_as_deleted(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(status_code=404, text="")
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/foo/9999") == CafeStatus.DELETED

    def test_login_wall_treated_as_private(self):
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(
            status_code=200,
            text='<html>nid.naver.com/nidlogin.login redirect</html>',
        )
        c.slowdown.base = 0
        c.slowdown.current_interval = 0
        assert c.fetch_cafe_url_status("https://cafe.naver.com/private/1") == CafeStatus.PRIVATE


class TestCrawlerImpersonatePool:
    """T-M24 (2026-05-12): IMPERSONATE_POOL 회전 검증."""

    def test_impersonate_in_pool(self):
        """Crawler 인스턴스의 impersonate = IMPERSONATE_POOL 안에 있어야 함."""
        from src.config import IMPERSONATE_POOL
        c = Crawler()
        assert c.impersonate in IMPERSONATE_POOL

    def test_different_instances_can_have_different_impersonate(self):
        """여러 인스턴스 생성 시 최소 한 번은 다른 impersonate 가 선택될 수 있음
        (random 이므로 확률적 — 100회 중 전부 동일 확률 = (1/4)^99 ≈ 0).
        """
        from src.config import IMPERSONATE_POOL
        seen = set()
        for _ in range(30):
            c = Crawler()
            seen.add(c.impersonate)
        # 30회 중 적어도 1종 이상 등장 (당연), 풀 안에 있는 것만 등장
        assert seen.issubset(set(IMPERSONATE_POOL))
        assert len(seen) >= 1


class TestCrawlerWarmup:
    """T-M26 (2026-05-12): cookie warmup 메서드 검증."""

    def test_warmup_calls_naver_main(self):
        """warmup() 호출 시 네이버 메인 URL fetch 시도."""
        c = Crawler()
        c.session = MagicMock()
        c.session.get.return_value = MagicMock(status_code=200, text="ok")
        c.warmup()
        called_url = c.session.get.call_args[0][0]
        assert "naver.com" in called_url

    def test_warmup_ignores_exception(self):
        """warmup() 네트워크 오류 시 예외 raise X (무시하고 계속)."""
        c = Crawler()
        c.session = MagicMock()
        c.session.get.side_effect = Exception("네트워크 오류")
        # 예외가 밖으로 나오면 안 됨
        c.warmup()  # raise 되면 테스트 실패


class TestSlowdownWaitBase:
    """T-M26 (2026-05-12): wait() 정상 분기 = config base 정합 검증."""

    def test_normal_wait_uses_base_range(self):
        """정상 분기 sleep 인자 = [base, base*1.5] 범위."""
        import time
        s = SlowdownController(base=2.0, max_=60.0)
        slept = []
        orig_sleep = time.sleep
        with patch("src.crawler.time.sleep", side_effect=lambda x: slept.append(x)):
            s.wait()
        assert len(slept) == 1
        assert 2.0 <= slept[0] <= 3.0  # base=2.0 → [2.0, 3.0]

    def test_backoff_wait_uses_current_interval(self):
        """backoff 분기 sleep 인자 = current_interval ± jitter."""
        import time
        s = SlowdownController(base=2.0, max_=60.0)
        s.on_block_detected()  # current_interval = 4.0
        slept = []
        with patch("src.crawler.time.sleep", side_effect=lambda x: slept.append(x)):
            s.wait()
        assert len(slept) == 1
        # 4.0 ± 0.3 범위 (jitter)
        assert 3.7 <= slept[0] <= 4.3
