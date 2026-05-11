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

    def test_link_empty_returns_empty_K_L_M_no_search(self):
        """2026-05-12 T-M13 (T-M10 revert): 사장님 명시 — link 빈 row = 검색 X + K/L/M 빈칸 박음.
        이전 T-M10 박은 결과 (link 빈 row K/L/M 박힘) 정리 의무 — 빈칸으로 덮어쓰기.
        사장님 의도 = 마케팅 예정 row 박지 X.
        """
        crawler = self._make_crawler()
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "", "_row": 5}
        result = _process_row(row, crawler, h)
        # 검색 박지 X ✅
        crawler.fetch_search.assert_not_called()
        # K/L/M 빈칸 박음 (이전 박힌 데이터 정리)
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
        # 검색 결과에 없음 + 이전 노출이라 url_alive 체크 → ALIVE 라 "삭제"
        assert cols[HEADER_AREA] == "삭제"

    def test_url_dead_returns_삭제(self, load_fixture):
        """url 죽음 (404 / 비공개) → '삭제'."""
        html = load_fixture("naver/no_match.html")
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",
            "링크": "https://cafe.naver.com/anywhere/999",
            HEADER_AREA: "AB",  # 이전 노출
            "_row": 5,
        }
        cols = _process_row(row, crawler, h)
        assert cols[HEADER_AREA] == "삭제"

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

    def test_first_run_url_dead_returns_삭제(self, load_fixture):
        """2026-05-12 T-M10.1: 첫 추적 (prev_K='') + 검색 0 + url 죽음 → '삭제'.
        사장님 요구: 게시글 조회 시 "삭제됐다" 뜨는 거 = K=삭제. prev_K 조건 무관.
        """
        html = load_fixture("naver/no_match.html")
        crawler = self._make_crawler(html_to_return=html, url_status=CafeStatus.DELETED)
        h = HealthMonitor()
        row = {
            "키워드": "처음추적",
            "링크": "https://cafe.naver.com/dead/999",
            HEADER_AREA: "",  # 첫 추적 = 빈 칸
            "_row": 7,
        }
        cols = _process_row(row, crawler, h)
        assert cols[HEADER_AREA] == "삭제"
        crawler.fetch_cafe_url_status.assert_called_once()  # url alive 검증 박힘 ✅

    def test_crawler_error_propagates(self):
        """차단 에러는 raise 되어 retry queue 로 흘러감."""
        c = Crawler(slowdown=SlowdownController(base=0))
        c.fetch_search = MagicMock(side_effect=CrawlerError("rate limited"))
        h = HealthMonitor()
        row = {"키워드": "test", "링크": "https://cafe.naver.com/x/1", "_row": 1}
        with pytest.raises(CrawlerError):
            _process_row(row, c, h)
