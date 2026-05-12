"""main 단위 테스트.

T-M25 (2026-05-12): CAFE_WHITELIST 필터 검증.
run_cycle() 전체 흐름 테스트는 외부 의존성(Sheets, Crawler) 이 많아 integration 으로 분리.
여기서는 화이트리스트 필터 로직만 격리 검증.
"""
from src.config import CAFE_WHITELIST
from src.crawler import parse_cafe_url


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
