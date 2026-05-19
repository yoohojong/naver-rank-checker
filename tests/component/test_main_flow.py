"""main 통합 흐름 component 테스트.

unit test 가 아니라 모듈 통합 — Sheets/Crawler 는 mock 으로 격리.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from src.main import _process_row, _carea_filter
from src.crawler import Crawler, SlowdownController, CafeStatus, CrawlerError
from src.health import HealthMonitor
from src.sheets import HEADER_AREA, HEADER_L, HEADER_M, HEADER_TYPE, HEADER_JISIKIN, HEADER_LINK
from src.transitions import parse_K_with_stamp  # D-030 (2026-05-18): K base 추출 헬퍼


def _K_base(k_value: str) -> str:
    """D-030 (2026-05-18) test 헬퍼: K full → base 추출."""
    base, _ = parse_K_with_stamp(k_value or "")
    return base


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
        assert _K_base(result[HEADER_AREA]) == "미노출"
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
        assert _K_base(result[HEADER_AREA]) == "미노출"

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
        assert _K_base(cols[HEADER_AREA]) == "AB"
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
        assert _K_base(cols[HEADER_AREA]) == "누락"

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
        assert _K_base(cols[HEADER_AREA]) == "삭제"
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
        assert _K_base(cols[HEADER_AREA]) == "미노출"  # D-026: 명시 표기 (빈 칸 X) + D-030: base 추출

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
        assert _K_base(cols[HEADER_AREA]) == "삭제"
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


class TestT_M81BackupAutomation:
    """T-M81 (D-027 2026-05-17) 회귀 test — main.py run_cycle 백업 자동화.

    사장님 명시 컨벤션:
    - run_cycle 시작 시 = 시트 K/L/M/링크/유형 전체 read → .harness/backups/{run_id}_{ts}.json 저장
    - 폴더 자동 생성
    - 백업 실패 = log + 진행 (cron 중단 X)
    - shadow mode 폐기 정합 (= 시트 즉시 갱신 + 사고 시 백업 복원)
    """

    def test_run_cycle_creates_backup_file(self, tmp_path, monkeypatch):
        """run_cycle 호출 시 .harness/backups/{run_id}_{ts}.json 파일 생성 검증."""
        import os
        # working dir = tmp_path (= 격리 환경)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_RUN_ID", "test12345")
        # SPREADSHEET_ID / SERVICE_ACCOUNT_JSON 환경 = src.config = module-level eval = monkeypatch X
        # → src.main 안 SPREADSHEET_ID/SERVICE_ACCOUNT_JSON 직접 patch
        monkeypatch.setattr("src.main.SPREADSHEET_ID", "fake_id")
        monkeypatch.setattr("src.main.SERVICE_ACCOUNT_JSON", '{"type":"service_account","client_email":"x@x.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}')

        # SheetsClient = mock = read 결과 = fake 1 탭 + 2 행
        from unittest.mock import patch as upatch, MagicMock as UMM
        mock_client = UMM()
        mock_client.load_all_data_tabs.return_value = {
            "샴푸 카외": [
                {"_row": 2, "_tab": "샴푸 카외", "키워드": "kw1", "링크": "https://cafe.naver.com/cosmania/111", "노출영역": "AB"},
                {"_row": 3, "_tab": "샴푸 카외", "키워드": "kw2", "링크": "", "노출영역": ""},
            ]
        }
        mock_client.write_results.return_value = 0
        mock_client.write_timestamp.return_value = None

        # crawler = mock = 검색 X (모든 row skip)
        mock_crawler = UMM()
        mock_crawler.warmup.return_value = None
        mock_crawler.fetch_search.side_effect = CrawlerError("dummy = skip")

        with upatch("src.main.SheetsClient", return_value=mock_client), \
             upatch("src.main.Crawler", return_value=mock_crawler):
            from src.main import run_cycle
            summary = run_cycle()

        # 백업 파일 생성 검증 (m1: gzip 압축 = .json.gz)
        backup_dir = tmp_path / ".harness" / "backups"
        assert backup_dir.exists(), "백업 디렉토리 생성 X"
        backup_files = list(backup_dir.glob("test12345_*.json.gz"))
        assert len(backup_files) == 1, f"백업 파일 수 ≠ 1: {backup_files}"

        # 백업 파일 내용 검증 (m1: gzip read)
        import gzip
        with gzip.open(backup_files[0], "rt", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["run_id"] == "test12345"
        assert payload["spreadsheet_id"] == "fake_id"
        assert "샴푸 카외" in payload["tabs"]
        assert len(payload["tabs"]["샴푸 카외"]) == 2

    def test_run_cycle_backup_failure_does_not_stop_cron(self, tmp_path, monkeypatch):
        """T-M81: 백업 실패 = log + cron 진행 (= cron 자체 중단 X)."""
        import os
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("src.main.SPREADSHEET_ID", "fake_id")
        monkeypatch.setattr("src.main.SERVICE_ACCOUNT_JSON", '{"type":"service_account","client_email":"x@x.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}')

        from unittest.mock import patch as upatch, MagicMock as UMM
        mock_client = UMM()
        # load_all_data_tabs 결과 = json.dump 시 직렬화 불가능 객체 (= 백업 실패 trigger)
        mock_client.load_all_data_tabs.return_value = {
            "샴푸 카외": [{"_row": 2, "_tab": "샴푸 카외", "키워드": "kw1", "링크": "x", "fake_obj": object()}],
        }
        mock_client.write_results.return_value = 0
        mock_client.write_timestamp.return_value = None

        mock_crawler = UMM()
        mock_crawler.warmup.return_value = None
        mock_crawler.fetch_search.side_effect = CrawlerError("dummy")

        with upatch("src.main.SheetsClient", return_value=mock_client), \
             upatch("src.main.Crawler", return_value=mock_crawler):
            from src.main import run_cycle
            # 백업 실패해도 run_cycle 계속 진행 = summary 반환 의무
            summary = run_cycle()
        # cron 안 중단 = summary 반환 확인
        assert isinstance(summary, dict)
        assert "tabs_processed" in summary


class TestD032TraceAuditInvariant:
    """D-032: row trace + invariant gate + post-write audit."""

    def test_run_cycle_filters_invalid_update_and_writes_trace_audit(self, tmp_path, monkeypatch):
        import os

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_RUN_ID", "trace123")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setattr("src.main.SPREADSHEET_ID", "fake_id")
        monkeypatch.setattr("src.main.SERVICE_ACCOUNT_JSON", '{"type":"service_account","client_email":"x@x.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}')

        from unittest.mock import patch as upatch, MagicMock as UMM
        from src.sheets import RowUpdate

        initial_rows = {
            "바디워시 카외": [
                {"_row": 2, "_tab": "바디워시 카외", "키워드": "퍼퓸바디워시", HEADER_LINK: "", HEADER_AREA: "미노출"},
                {"_row": 3, "_tab": "바디워시 카외", "키워드": "정상", HEADER_LINK: "https://cafe.naver.com/cosmania/999", HEADER_AREA: ""},
            ]
        }
        post_write_rows = {
            "바디워시 카외": [
                {"_row": 2, "_tab": "바디워시 카외", "키워드": "퍼퓸바디워시", HEADER_LINK: "", HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"},
                {"_row": 3, "_tab": "바디워시 카외", "키워드": "정상", HEADER_LINK: "https://cafe.naver.com/cosmania/999", HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"},
            ]
        }

        mock_client = UMM()
        mock_client.load_all_data_tabs.side_effect = [initial_rows, post_write_rows]
        mock_client.write_results.return_value = 3
        mock_client.write_timestamp.return_value = None

        mock_crawler = UMM()
        mock_crawler.warmup.return_value = None

        def fake_process(row, *_args, **_kwargs):
            if row["_row"] == 2:
                return {HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"}
            return {HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"}

        with upatch("src.main.SheetsClient", return_value=mock_client), \
             upatch("src.main.Crawler", return_value=mock_crawler), \
             upatch("src.main.random.shuffle", side_effect=lambda rows: None), \
             upatch("src.main._process_row", side_effect=fake_process):
            from src.main import run_cycle
            summary = run_cycle()

        written_updates = mock_client.write_results.call_args_list[0].args[1]
        assert [u.row for u in written_updates] == [3]
        assert all(isinstance(u, RowUpdate) for u in written_updates)
        assert summary["prewrite_invariant_violations"] == 1
        assert summary["post_write_audit_violations"] == 1
        assert summary["code_change_suspected"] is True

        trace_files = list((tmp_path / ".harness" / "traces").glob("trace123_*_row-trace.jsonl"))
        audit_files = list((tmp_path / ".harness" / "audits").glob("trace123_*_post-write-audit.jsonl"))
        assert len(trace_files) == 1
        assert len(audit_files) == 1
        assert '"row": 2' in trace_files[0].read_text(encoding="utf-8")

    def test_preexisting_untouched_audit_issue_is_nonblocking(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_RUN_ID", "debt123")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setattr("src.main.SPREADSHEET_ID", "fake_id")
        monkeypatch.setattr("src.main.SERVICE_ACCOUNT_JSON", '{"type":"service_account","client_email":"x@x.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}')

        from unittest.mock import patch as upatch, MagicMock as UMM

        rows_with_preexisting_debt = {
            "바디워시 카외": [
                {"_row": 2, "_tab": "바디워시 카외", "키워드": "", HEADER_LINK: "", HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"},
                {"_row": 3, "_tab": "바디워시 카외", "키워드": "", HEADER_LINK: "", HEADER_AREA: ""},
            ]
        }
        mock_client = UMM()
        mock_client.load_all_data_tabs.side_effect = [rows_with_preexisting_debt, rows_with_preexisting_debt]
        mock_client.write_results.return_value = 0
        mock_client.write_timestamp.return_value = None

        mock_crawler = UMM()
        mock_crawler.warmup.return_value = None

        with upatch("src.main.SheetsClient", return_value=mock_client), \
             upatch("src.main.Crawler", return_value=mock_crawler):
            from src.main import run_cycle
            summary = run_cycle()

        assert summary["post_write_audit_total_issues"] == 1
        assert summary["post_write_audit_preexisting_issues"] == 1
        assert summary["post_write_audit_violations"] == 0
        assert summary.get("code_change_suspected") is not True
