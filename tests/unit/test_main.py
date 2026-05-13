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


class TestUrlAliveOnExposedRows:
    """T-M10.4 (2026-05-13): 검색 노출 행도 url_alive 검증 적용 확인.

    수정 전: `if link and not search_found:` → 검색 노출 행 url_alive 검증 X.
    수정 후: `if link:` → 검색 노출 + 비공개/삭제 케이스도 K="삭제" 정합.
    예: pusanmommy/1463516 = 검색 노출 + HTTP 200 + "nidlogin.login" (비공개) → K="삭제" 필요.
    """

    def _make_row(self, keyword: str, link: str, prev_K: str = "") -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "유형": prev_K, "_row": 2}

    def _mock_exposed_result(self, area: str = "AB"):
        """검색 노출 결과 mock 생성."""
        mock_result = MagicMock()
        mock_result.exposure_area.value = area
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = 3
        mock_result.cafe_slot_rank = 1
        mock_result.in_jisikin = False
        return mock_result

    def _mock_unexposed_result(self):
        """검색 미노출 결과 mock 생성."""
        mock_result = MagicMock()
        mock_result.exposure_area.value = "미노출"
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = None
        mock_result.cafe_slot_rank = None
        mock_result.in_jisikin = False
        return mock_result

    def test_search_exposed_link_private_returns_deleted(self):
        """검색 노출 + link 비공개 (PRIVATE) → K="삭제" (T-M10.4 핵심 케이스).

        pusanmommy/1463516 실측 케이스 재현: 검색 결과에 노출 + 실제 URL은 비공개.
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/pusanmommy/1463516"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.PRIVATE  # 비공개

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("부산맘", link)
            cols = _process_row(row, crawler, health)

        # 검색 노출이어도 URL 비공개 → K="삭제"
        assert cols[HEADER_AREA] == "삭제"
        # url_alive 검증 호출됨 (수정 전에는 호출 안 됨)
        crawler.fetch_cafe_url_status.assert_called_once_with(link)

    def test_search_exposed_link_alive_returns_AB(self):
        """검색 노출 + link 정상 (ALIVE) → K=AB (기존 정합 유지)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/cosmania/12345"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("샴푸", link)
            cols = _process_row(row, crawler, health)

        assert cols[HEADER_AREA] == "AB"

    def test_search_unexposed_link_alive_returns_empty(self):
        """검색 미노출 + link 정상 (ALIVE) → K="" (기존 정합 유지)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/cosmania/55555"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("샴푸", link, prev_K="")
            cols = _process_row(row, crawler, health)

        assert cols[HEADER_AREA] == ""

    def test_search_unexposed_link_private_returns_deleted(self):
        """검색 미노출 + link 비공개 → K="삭제" (기존 정합 유지)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/pusanmommy/1459022"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.PRIVATE

        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("부산맘", link, prev_K="")
            cols = _process_row(row, crawler, health)

        assert cols[HEADER_AREA] == "삭제"

    def test_search_exposed_no_link_returns_AB_without_status_check(self):
        """검색 노출 + link 빈칸 → K=AB, url_alive 검증 X (link 없음)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()

        crawler.fetch_search.return_value = "<html>검색결과</html>"

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("샴푸", "")  # link 빈칸
            cols = _process_row(row, crawler, health, all_known_links={"https://cafe.naver.com/cosmania/9"})

        # link 없음 = url_alive 검증 X
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_exposed_row_fetch_called_once_with_cache(self):
        """검색 노출 행 동일 link 2회 처리 시 fetch_cafe_url_status 1회만 호출 (캐시 동작)."""
        from src.main import _process_row
        from src.health import HealthMonitor

        crawler = MagicMock()
        health = HealthMonitor()
        url_alive_cache: dict = {}
        link = "https://cafe.naver.com/cosmania/77777"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("샴푸", link)
            _process_row(row, crawler, health, url_alive_cache=url_alive_cache)
            _process_row(row, crawler, health, url_alive_cache=url_alive_cache)

        # 검색 노출 행도 캐시 동작 → 1회만 호출
        assert crawler.fetch_cafe_url_status.call_count == 1


class TestLinkAutoUpdate:
    """T-M14.2 (D-022 보완): 행 link 매치 X + 다른 행 link 매치 시 link 자동 갱신 검증."""

    def _make_row(self, keyword: str, link: str, prev_K: str = "") -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "노출영역": prev_K, "_row": 2}

    def _mock_result(self, area: str, matched_url: str = None):
        """parse_search_result 반환용 mock RankResult."""
        from src.parser import RankResult, ExposureArea
        r = RankResult()
        r.exposure_area = ExposureArea(area) if area != "미노출" else ExposureArea.UNEXPOSED
        r.matched_url = matched_url
        r.parser_confidence = 0.9
        r.integrated_rank = 1 if area != "미노출" else None
        r.cafe_slot_rank = 1 if area != "미노출" else None
        r.block_order = [area] if area != "미노출" else []
        r.in_jisikin = False
        return r

    def test_link_auto_update_when_other_link_matches(self):
        """행 link 매치 X + 다른 행 link B 매치 → HEADER_LINK 컬럼 = link B (자동 갱신)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        link_a = "https://cafe.naver.com/pusanmommy/1111"
        link_b = "https://cafe.naver.com/cosmania/2222"
        all_known_links = {link_a, link_b}

        unexposed = self._mock_result("미노출")
        matched = self._mock_result("AB", matched_url=link_b)

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        call_count = [0]

        def fake_parse(html, target_url=None, link_set=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # 1차: link_a 단독 매치 → 미노출
                return unexposed
            else:
                # 2차: link_set fallback → link_b 매치
                return matched

        with patch("src.main.parse_search_result", side_effect=fake_parse):
            row = self._make_row("샴푸", link_a)
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        # K = AB (link_b 매치)
        assert cols[HEADER_AREA] == "AB"
        # 링크 컬럼 = link_b (자동 갱신)
        assert cols[HEADER_LINK] == link_b

    def test_link_no_update_when_original_matches(self):
        """행 link 매치 성공 → HEADER_LINK 컬럼 갱신 X (기존 정합 유지)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        link_a = "https://cafe.naver.com/pusanmommy/1111"
        all_known_links = {link_a}

        matched = self._mock_result("AB", matched_url=link_a)
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=matched):
            row = self._make_row("샴푸", link_a)
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        # K = AB (link_a 매치)
        assert cols[HEADER_AREA] == "AB"
        # 링크 컬럼 갱신 없음 (matched_url == link_a 이므로 auto_updated_link = None)
        assert HEADER_LINK not in cols
