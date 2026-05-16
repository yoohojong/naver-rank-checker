"""main 통합 흐름 component 테스트.

unit test 가 아니라 모듈 통합 — Sheets/Crawler 는 mock 으로 격리.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from src.main import _process_row, _carea_filter
from src.crawler import Crawler, SlowdownController, CafeStatus, CrawlerError
from src.health import HealthMonitor
from src.sheets import HEADER_AREA, HEADER_L, HEADER_M, HEADER_TYPE, HEADER_JISIKIN


class TestCareaFilter:
    def test_matches_사장님_tabs(self):
        assert _carea_filter("샴푸 카외") is True
        assert _carea_filter("바디워시 카외") is True
        assert _carea_filter("두드러기 카외") is True

    def test_rejects_other_tabs(self):
        assert _carea_filter("카페 발행작업") is False
        assert _carea_filter("한수연님") is False
        assert _carea_filter("틱톡") is False
        assert _carea_filter("ID") is False


class TestProcessRow:
    """_process_row 단위 검증 (crawler/parser mock)."""

    def _make_crawler(self, html_to_return="<html>fake</html>", url_status=CafeStatus.ALIVE):
        c = Crawler(slowdown=SlowdownController(base=0, max_=0))
        c.fetch_search = MagicMock(return_value=html_to_return)
        c.fetch_cafe_url_status = MagicMock(return_value=url_status)
        return c

    def test_link_empty_no_known_links_returns_unexposed(self):
        """D-026 Phase C+D (2026-05-16): link 빈 행 + all_known_links 빈 = 검색 X + K='미노출'.
        근거: all_known_links 없으면 매치 가능성 X = 검색 자체 skip.
        """
        crawler = self._make_crawler()
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "", "_row": 5}
        # all_known_links 빈 = 검색 X + 미노출 명시 표기
        result = _process_row(row, crawler, h, all_known_links=set())
        crawler.fetch_search.assert_not_called()
        assert result is not None
        assert result[HEADER_AREA] == "미노출"
        assert result[HEADER_L] == ""
        assert result[HEADER_M] == ""

    def test_link_empty_with_known_links_no_match_returns_unexposed(self):
        """D-026 Phase C+D (2026-05-16): link 빈 행 + all_known_links 있음 + 매치 X = K='미노출'.
        검색 수행됨 (= all_known_links 매치 시도). 매치 X = 미노출.
        """
        crawler = self._make_crawler()  # 기본 html = "<html>fake</html>" = 매치 X (짧음)
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "", "_row": 5}
        all_known_links = {"https://cafe.naver.com/pusanmommy/1445556"}
        result = _process_row(row, crawler, h, all_known_links=all_known_links)
        # D-026: all_known_links 있음 = 검색 수행
        crawler.fetch_search.assert_called_once_with("test")
        assert result is not None
        # 매치 X = K="미노출"
        assert result[HEADER_AREA] == "미노출"

    def test_skips_row_with_empty_keyword(self):
        crawler = self._make_crawler()
        h = HealthMonitor()
        row = {"키워드": "", "링크": "https://cafe.naver.com/x/1", "_row": 5}
        result = _process_row(row, crawler, h)
        assert result is None

    def test_processes_row_with_match(self, load_fixture):
        """fixture 통해 실 parser 동작 + sheet column dict 생성 검증."""
        html = load_fixture("naver/ab_cafe_top.html")
        crawler = self._make_crawler(html_to_return=html)
        h = HealthMonitor()
        row = {
            "키워드": "등드름해초필링",
            "링크": "https://cafe.naver.com/pusanmommy/1445556",
            HEADER_AREA: "",  # 첫 추적
            "_row": 3,
        }
        cols = _process_row(row, crawler, h)
        assert cols is not None
        assert cols[HEADER_AREA] == "AB"
        assert cols[HEADER_L] == "1"
        assert cols[HEADER_M] == "1"

    def test_transition_to_누락_when_was_exposed_now_missing(self, load_fixture):
        """D-026 Phase B (2026-05-16): 이전 인기글 → 지금 검색 0 → '누락' 자동 표기.
        근거: 박스 빠짐 (네이버 search 결과 X) = '누락' (≠ '삭제' = 진짜 URL X).
        D-022 ① 폐기 정합 (= "삭제" 단일 통합 컨벤션 폐기).
        """
        html = load_fixture("naver/no_match.html")
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.ALIVE)
        h = HealthMonitor()
        row = {
            "키워드": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",
            "링크": "https://cafe.naver.com/anywhere/999",
            HEADER_AREA: "인기글",  # 이전 노출
            "_row": 5,
        }
        cols = _process_row(row, crawler, h)
        # D-026: 검색 미노출 + 이전 노출 (인기글) → '누락'
        assert cols[HEADER_AREA] == "누락"

    def test_url_dead_first_run_search_unexposed_returns_deleted(self, load_fixture):
        """D-026 Phase E+F (2026-05-16): 첫 추적 + 검색 미노출 + 삭제 텍스트 검출 → K='삭제'.
        근거: fetch_cafe_url_status 부활 (사장님 명시 텍스트 검출 = 진짜 삭제 판정).
        """
        html = load_fixture("naver/no_match.html")
        # D-026 Phase E+F: DELETED 반환 = 삭제 텍스트 검출 = K="삭제"
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",
            "링크": "https://cafe.naver.com/anywhere/999",
            HEADER_AREA: "",  # 첫 추적 — prev_K 없음
            "_row": 5,
        }
        cols = _process_row(row, crawler, h)
        # D-026 Phase E+F: 삭제 텍스트 검출 = K='삭제'
        assert cols[HEADER_AREA] == "삭제"
        crawler.fetch_cafe_url_status.assert_called_once()

    def test_first_run_unexposed(self, load_fixture):
        """D-026 Phase B (2026-05-16): 첫 추적 + 검색 0 + url 살아있음 → '미노출' 명시 표기."""
        html = load_fixture("naver/no_match.html")
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.ALIVE)
        h = HealthMonitor()
        row = {
            "키워드": "asdf",
            "링크": "https://cafe.naver.com/foo/1",
            HEADER_AREA: "",
            "_row": 2,
        }
        cols = _process_row(row, crawler, h)
        assert cols[HEADER_AREA] == "미노출"  # D-026: 명시 표기 (빈 칸 X)

    def test_first_run_url_dead_search_unexposed_returns_deleted(self, load_fixture):
        """D-026 Phase E+F (2026-05-16): 첫 추적 + 검색 미노출 + 삭제 텍스트 검출 → K='삭제'.
        fetch_cafe_url_status 부활 = DELETED 반환 = K='삭제' 자동 적용.
        """
        html = load_fixture("naver/no_match.html")
        # D-026 Phase E+F: DELETED 반환 = 삭제 텍스트 검출
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "처음추적",
            "링크": "https://cafe.naver.com/dead/999",
            HEADER_AREA: "",  # 첫 추적 = 빈 칸
            "_row": 7,
        }
        cols = _process_row(row, crawler, h)
        # D-026 Phase E+F: 삭제 텍스트 검출 = K='삭제'
        assert cols[HEADER_AREA] == "삭제"
        # D-026 Phase E+F: fetch_cafe_url_status 호출 (= 삭제 검출)
        crawler.fetch_cafe_url_status.assert_called_once()

    def test_crawler_error_propagates(self):
        """차단 에러는 raise 되어 retry queue 로 흘러감."""
        c = Crawler(slowdown=SlowdownController(base=0))
        c.fetch_search = MagicMock(side_effect=CrawlerError("rate limited"))
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "https://cafe.naver.com/x/1", "_row": 1}
        with pytest.raises(CrawlerError):
            _process_row(row, c, h)
