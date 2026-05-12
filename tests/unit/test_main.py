"""main 단위 테스트.

T-M25 (2026-05-12): CAFE_WHITELIST 필터 검증.
T-M10.2 (2026-05-13): url_alive_cache 중복 호출 방지 검증.
run_cycle() 전체 흐름 테스트는 외부 의존성(Sheets, Crawler) 이 많아 integration 으로 분리.
여기서는 화이트리스트 필터 로직 및 캐시 로직만 격리 검증.
"""
from unittest.mock import MagicMock, patch

from src.config import CAFE_WHITELIST
from src.crawler import parse_cafe_url, CafeStatus


def _build_known_links(rows: list[dict]) -> set:
    """run_cycle 의 all_known_links 구성 로직 추출 (T-M25 화이트리스트 필터 포함).

    run_cycle 과 동일한 로직을 여기서 재현해 격리 단위 테스트 가능하게 함.
    """
    all_known_links: set = set()
    for row in rows:
        row_link = (row.get("링크") or "").strip()
        if not row_link:
            continue
        slug, _ = parse_cafe_url(row_link)
        if slug and slug in CAFE_WHITELIST:
            all_known_links.add(row_link)
    return all_known_links


class TestCafeWhitelistFilter:
    """T-M25 (2026-05-12): CAFE_WHITELIST 필터 단위 검증."""

    def test_whitelist_slug_included(self):
        """화이트리스트 slug 의 카페 링크 = all_known_links 에 포함."""
        rows = [{"링크": "https://cafe.naver.com/cosmania/12345"}]
        links = _build_known_links(rows)
        assert "https://cafe.naver.com/cosmania/12345" in links

    def test_non_whitelist_slug_excluded(self):
        """화이트리스트 외부 slug 의 카페 링크 = all_known_links 에서 제외."""
        rows = [{"링크": "https://cafe.naver.com/외주카페/99999"}]
        links = _build_known_links(rows)
        assert len(links) == 0

    def test_empty_link_skipped(self):
        """링크 빈 row = all_known_links 에 포함 안 됨."""
        rows = [{"링크": ""}, {"링크": None}, {}]
        links = _build_known_links(rows)
        assert len(links) == 0

    def test_non_cafe_url_excluded(self):
        """blog.naver.com 등 카페 아닌 URL = parse_cafe_url 반환 (None, None) → 제외."""
        rows = [{"링크": "https://blog.naver.com/testuser/12345"}]
        links = _build_known_links(rows)
        assert len(links) == 0

    def test_mixed_rows_only_whitelist_included(self):
        """화이트리스트 내 + 외 slug 혼재 시 화이트리스트 내 slug 만 포함."""
        rows = [
            {"링크": "https://cafe.naver.com/pusanmommy/111"},   # 화이트리스트 내
            {"링크": "https://cafe.naver.com/타사카페/222"},      # 화이트리스트 외
            {"링크": "https://cafe.naver.com/iroid/333"},         # 화이트리스트 내
            {"링크": ""},                                          # 빈 링크
        ]
        links = _build_known_links(rows)
        assert "https://cafe.naver.com/pusanmommy/111" in links
        assert "https://cafe.naver.com/iroid/333" in links
        assert "https://cafe.naver.com/타사카페/222" not in links
        assert len(links) == 2

    def test_all_whitelist_slugs_are_valid_cafe_slugs(self):
        """CAFE_WHITELIST 안 slug 전체 = parse_cafe_url 로 추출 가능한 형태인지 확인.

        실제 URL 을 구성해서 parse_cafe_url 이 정상 파싱하는지 검증.
        """
        for slug in CAFE_WHITELIST:
            url = f"https://cafe.naver.com/{slug}/12345"
            extracted_slug, post_id = parse_cafe_url(url)
            assert extracted_slug == slug, f"slug {slug!r} parse 실패"
            assert post_id == "12345"


class TestUrlAliveCache:
    """T-M10.2 (2026-05-13): url_alive_cache 중복 호출 방지 검증."""

    def _make_row(self, keyword: str, link: str) -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "유형": "", "_row": 2}

    def test_same_link_fetched_only_once_with_cache(self):
        """같은 link 2회 _process_row 호출 시 fetch_cafe_url_status 1회만 호출 확인."""
        from src.main import _process_row
        from src.health import HealthMonitor

        crawler = MagicMock()
        health = HealthMonitor()
        url_alive_cache: dict = {}
        link = "https://cafe.naver.com/cosmania/12345"

        # 검색 결과 = 미노출 (url_alive 검증 진행되도록)
        mock_result = MagicMock()
        mock_result.exposure_area.value = "미노출"
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = None
        mock_result.cafe_slot_rank = None
        mock_result.in_jisikin = False

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            _process_row(row, crawler, health, url_alive_cache=url_alive_cache)
            # 두 번째 호출 — 캐시 적중해야 함
            _process_row(row, crawler, health, url_alive_cache=url_alive_cache)

        # fetch_cafe_url_status 는 캐시로 인해 1회만 호출되어야 함
        assert crawler.fetch_cafe_url_status.call_count == 1

    def test_cache_stores_result_correctly(self):
        """캐시에 fetch_cafe_url_status 결과가 올바르게 저장되는지 확인."""
        from src.main import _process_row
        from src.health import HealthMonitor

        crawler = MagicMock()
        health = HealthMonitor()
        url_alive_cache: dict = {}
        link = "https://cafe.naver.com/cosmania/99999"

        mock_result = MagicMock()
        mock_result.exposure_area.value = "미노출"
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = None
        mock_result.cafe_slot_rank = None
        mock_result.in_jisikin = False

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=mock_result):
            _process_row(self._make_row("샴푸", link), crawler, health, url_alive_cache=url_alive_cache)

        # 캐시에 결과 저장 확인
        assert link in url_alive_cache
        assert url_alive_cache[link] is True  # ALIVE → True

    def test_no_cache_calls_fetch_each_time(self):
        """url_alive_cache=None 시 매 호출마다 fetch_cafe_url_status 호출 확인."""
        from src.main import _process_row
        from src.health import HealthMonitor

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/cosmania/12345"

        mock_result = MagicMock()
        mock_result.exposure_area.value = "미노출"
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = None
        mock_result.cafe_slot_rank = None
        mock_result.in_jisikin = False

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            _process_row(row, crawler, health, url_alive_cache=None)
            _process_row(row, crawler, health, url_alive_cache=None)

        # 캐시 없음 = 2회 모두 호출
        assert crawler.fetch_cafe_url_status.call_count == 2
