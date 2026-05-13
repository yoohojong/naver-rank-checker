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

    def test_link_empty_returns_empty_no_search(self):
        """T-M14 폐기 (2026-05-14): link 빈 행 = 사장님 미작업 = 검색 X + K/L/M 빈칸.
        all_known_links 전달 여부 무관하게 동일 결과 (link_set fallback 폐기).
        """
        crawler = self._make_crawler()
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "", "_row": 5}
        # all_known_links 전달해도 검색 X + 빈칸 반환
        result = _process_row(row, crawler, h, all_known_links={"https://cafe.naver.com/pusanmommy/1445556"})
        crawler.fetch_search.assert_not_called()
        assert result is not None
        assert result[HEADER_AREA] == ""
        assert result[HEADER_L] == ""
        assert result[HEADER_M] == ""

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

    def test_transition_to_삭제_when_was_exposed_now_missing(self, load_fixture):
        """이전 인기글 → 지금 검색 0 → '삭제' 자동 표기 (사장님 차별화 D-009)."""
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
        # 검색 미노출 + 이전 노출 (인기글) → transitions.compute_new_K → "삭제"
        # T-M10.5: url_alive 검증 폐기. url_alive=True 고정 → prev_K=인기글 + search_found=False → "삭제" 정합.
        assert cols[HEADER_AREA] == "삭제"

    def test_url_dead_first_run_search_unexposed_returns_empty(self, load_fixture):
        """T-M10.5 (2026-05-14): url_alive 검증 폐기 — 비로그인 환경 한계.
        첫 추적 (prev_K='') + url DELETED + 검색 미노출 → K="" (url 상태 무관).
        기존 동작: url DELETED → K="삭제". 폐기 후: 검색 미노출만 반영 = K="".
        fetch_cafe_url_status 호출 X.
        """
        html = load_fixture("naver/no_match.html")
        # url_status 는 이제 _process_row 에서 호출 X — CafeStatus.DELETED 전달해도 무의미
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",
            "링크": "https://cafe.naver.com/anywhere/999",
            HEADER_AREA: "",  # 첫 추적 — prev_K 없음
            "_row": 5,
        }
        cols = _process_row(row, crawler, h)
        # url_alive 폐기 = 검색 미노출 + 첫 추적 → K="" (삭제 판정 X)
        assert cols[HEADER_AREA] == ""
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_first_run_unexposed(self, load_fixture):
        """첫 추적 (prev_K = '') + 검색 0 + url 살아있음 → 빈 칸 유지."""
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
        assert cols[HEADER_AREA] == ""  # 미노출 + url 살아있음 = 빈 칸

    def test_first_run_url_dead_search_unexposed_returns_empty(self, load_fixture):
        """T-M10.5 (2026-05-14): url_alive 검증 폐기 — 비로그인 환경 한계.
        첫 추적 (prev_K='') + 검색 미노출 → K="" (url 상태 무관).
        진짜 삭제 = 다음 cron 박스 매치 X = 자연 미노출 표시.
        fetch_cafe_url_status 호출 X (폐기).
        """
        html = load_fixture("naver/no_match.html")
        # url_status 는 이제 _process_row 에서 호출 X — CafeStatus.DELETED 전달해도 무의미
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "처음추적",
            "링크": "https://cafe.naver.com/dead/999",
            HEADER_AREA: "",  # 첫 추적 = 빈 칸
            "_row": 7,
        }
        cols = _process_row(row, crawler, h)
        # url_alive 폐기 = 검색 미노출 → K="" (삭제 판정 X)
        assert cols[HEADER_AREA] == ""
        # fetch_cafe_url_status 호출 X (폐기)
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_crawler_error_propagates(self):
        """차단 에러는 raise 되어 retry queue 로 흘러감."""
        c = Crawler(slowdown=SlowdownController(base=0))
        c.fetch_search = MagicMock(side_effect=CrawlerError("rate limited"))
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "https://cafe.naver.com/x/1", "_row": 1}
        with pytest.raises(CrawlerError):
            _process_row(row, c, h)
