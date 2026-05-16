"""main 단위 테스트.

T-M25 (2026-05-12): CAFE_WHITELIST 필터 검증.
T-M10.2 (2026-05-13): url_alive_cache 중복 호출 방지 검증.
D-026 Phase C+D+E+F (2026-05-16): 빈 link 자동 채움 + 삭제 텍스트 검출 검증.
T-M90 (D-027 보강 2026-05-17): CAFE_WHITELIST 환경변수 이전 = test 안 = 사장님 운영 정보 분리 의무.
                                = _TEST_CAFE_WHITELIST 전용 set 사용 (= 일반 마케팅 slug 예시).
run_cycle() 전체 흐름 테스트는 외부 의존성(Sheets, Crawler) 이 많아 integration 으로 분리.
여기서는 화이트리스트 필터 로직 및 캐시 로직만 격리 검증.
"""
from unittest.mock import MagicMock, patch

from src.config import CAFE_WHITELIST  # noqa: F401 (T-M90: import 호환 유지, test 안 사용 X)
from src.crawler import parse_cafe_url, CafeStatus
from src.parser import ExposureArea, RankResult


# T-M90 (D-027 보강 2026-05-17): test 전용 화이트리스트 = 사장님 운영 정보 X.
# repo Public 후 = 일반 마케팅 카페 slug 예시 만 노출 = 사장님 카페 보호.
_TEST_CAFE_WHITELIST = frozenset({"cosmania", "pusanmommy", "iroid", "workee", "move79", "culturebloom"})


def _build_known_links(rows: list[dict], whitelist: frozenset = _TEST_CAFE_WHITELIST) -> set:
    """run_cycle 의 all_known_links 구성 로직 추출 (T-M25 화이트리스트 필터 포함).

    run_cycle 과 동일한 로직을 여기서 재현해 격리 단위 테스트 가능하게 함.
    T-M90 (2026-05-17): whitelist 인자 명시 = test 안 = _TEST_CAFE_WHITELIST 직접 전달.
    """
    all_known_links: set = set()
    for row in rows:
        row_link = (row.get("링크") or "").strip()
        if not row_link:
            continue
        slug, _ = parse_cafe_url(row_link)
        if slug and slug in whitelist:
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
        """_TEST_CAFE_WHITELIST 안 slug 전체 = parse_cafe_url 로 추출 가능한 형태인지 확인.

        T-M90 (2026-05-17): _TEST_CAFE_WHITELIST 사용 = 사장님 운영 정보 분리.
        실제 URL 을 구성해서 parse_cafe_url 이 정상 파싱하는지 검증.
        """
        for slug in _TEST_CAFE_WHITELIST:
            url = f"https://cafe.naver.com/{slug}/12345"
            extracted_slug, post_id = parse_cafe_url(url)
            assert extracted_slug == slug, f"slug {slug!r} parse 실패"
            assert post_id == "12345"


class TestUrlAliveCache:
    """D-026 Phase E+F (2026-05-16): 삭제 텍스트 검출 부활 — 검색 미노출 시 fetch_cafe_url_status 호출.

    T-M10.5 폐기 reverse:
    - 사장님 명시 = "게시글이 삭제되었습니다" exact substring 검출만 → K="삭제"
    - 로그인 페이지 / 404 / 네트워크 fail = UNKNOWN (= 정상 가정 = 시트 보존)
    - 검색 노출 = fetch_cafe_url_status 호출 X (= 검색 노출 = 진짜 살아있음)
    - 검색 미노출 + link 있음 = fetch_cafe_url_status 호출 (= 삭제 텍스트 검출)
    - 검색 미노출 + link 빈 = fetch_cafe_url_status 호출 X (= link 자체 없음)
    """

    def _make_row(self, keyword: str, link: str) -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "유형": "", "_row": 2}

    def test_unexposed_link_calls_fetch_cafe_url_status(self):
        """D-026 Phase E+F: 검색 미노출 + link 있음 = fetch_cafe_url_status 호출 (= 삭제 검출)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

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
        # 삭제 텍스트 검출 X (= ALIVE 또는 UNKNOWN) = K="미노출"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            cols = _process_row(row, crawler, health, url_alive_cache=None)

        # D-026 Phase E+F: 검색 미노출 + link 있음 = fetch_cafe_url_status 호출
        crawler.fetch_cafe_url_status.assert_called()
        # 삭제 텍스트 검출 X + 검색 미노출 + 첫 추적 = K="미노출"
        assert cols[HEADER_AREA] == "미노출"

    def test_unexposed_link_deleted_text_detected_K_삭제(self):
        """D-026 Phase E+F: 검색 미노출 + 삭제 텍스트 검출 = K="삭제"."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

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
        # D-026 Phase E+F: DELETED 반환 = K="삭제"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.DELETED

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            cols = _process_row(row, crawler, health, url_alive_cache=None)

        crawler.fetch_cafe_url_status.assert_called_once_with(link)
        # D-026 핵심: 삭제 텍스트 검출 = K="삭제"
        assert cols[HEADER_AREA] == "삭제"

    def test_unexposed_link_unknown_keeps_prev_K(self):
        """D-026 Phase E+F: 검색 미노출 + UNKNOWN (= 로그인/404) = 텍스트 검출 X = 시트 보존."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

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
        # D-026 Phase E+F: UNKNOWN = 텍스트 검출 X = 시트 보존
        crawler.fetch_cafe_url_status.return_value = CafeStatus.UNKNOWN

        row = self._make_row("샴푸", link)
        row["노출영역"] = ""  # 첫 추적

        with patch("src.main.parse_search_result", return_value=mock_result):
            cols = _process_row(row, crawler, health)

        # UNKNOWN = 텍스트 검출 X + 첫 추적 = K="미노출"
        assert cols[HEADER_AREA] == "미노출"


class TestUrlAliveOnExposedRows:
    """T-M10.5 (2026-05-14): url_alive 검증 폐기 — 비로그인 환경 한계.

    원래 T-M10.4: 검색 노출 행도 fetch_cafe_url_status 호출해 비공개 판정.
    T-M10.5 폐기 사유: 네이버 카페 비로그인 접근 = 로그인 페이지 HTML 반환 =
    nidlogin.login 키워드로 정상 ALIVE 글도 PRIVATE 잘못 판정 → K="삭제" 시트 손상.
    = 비로그인 환경에서 url_alive 검증 자체 무효 = 폐기.
    검색 노출/미노출 결과만으로 K 결정. 진짜 삭제 = 다음 cron 자연 미노출.
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

    def test_search_exposed_link_private_returns_AB(self):
        """T-M10.5: 검색 노출 + url 비공개 (PRIVATE) → K="AB" (url_alive 검증 폐기).

        원래 T-M10.4: K="삭제" 기대.
        폐기 후: fetch_cafe_url_status 호출 X = url 상태 무관 = K=AB (검색 노출 결과 우선).
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/pusanmommy/1463516"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        # fetch_cafe_url_status 반환값 설정해도 _process_row 에서 호출 X
        crawler.fetch_cafe_url_status.return_value = CafeStatus.PRIVATE

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("부산맘", link)
            cols = _process_row(row, crawler, health)

        # url_alive 폐기 = 검색 노출 → K=AB (url 비공개여도 삭제 X)
        assert cols[HEADER_AREA] == "AB"
        # fetch_cafe_url_status 호출 X
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_search_exposed_link_alive_returns_AB(self):
        """검색 노출 + link 정상 (ALIVE) → K=AB (정합 유지)."""
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
        """검색 미노출 + link 정상 (ALIVE) → K="" (정합 유지)."""
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

        # D-026 Phase B (2026-05-16): '미노출' 명시 표기 (= 빈 칸 X)
        assert cols[HEADER_AREA] == "미노출"

    def test_search_unexposed_link_unknown_returns_unexposed(self):
        """D-026 Phase E+F (2026-05-16): 검색 미노출 + UNKNOWN (= 로그인/404) → K="미노출".

        D-026: fetch_cafe_url_status 호출 됨 (= 삭제 텍스트 검출 시도).
        UNKNOWN 반환 = 텍스트 검출 X + 첫 추적 = K="미노출" 명시 표기.
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/pusanmommy/1459022"

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        # D-026 Phase E+F: UNKNOWN = 텍스트 검출 X = 시트 보존
        crawler.fetch_cafe_url_status.return_value = CafeStatus.UNKNOWN

        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("부산맘", link, prev_K="")
            cols = _process_row(row, crawler, health)

        # D-026 Phase E+F: UNKNOWN + 검색 미노출 → K='미노출' 명시 표기
        assert cols[HEADER_AREA] == "미노출"
        # D-026 Phase E+F: 검색 미노출 + link 있음 = fetch_cafe_url_status 호출
        crawler.fetch_cafe_url_status.assert_called()

    def test_search_exposed_no_link_returns_AB_without_status_check(self):
        """검색 노출 + link 빈칸 → K=AB, fetch_cafe_url_status 호출 X (link 없음 + 폐기)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()

        crawler.fetch_search.return_value = "<html>검색결과</html>"

        with patch("src.main.parse_search_result", return_value=self._mock_exposed_result("AB")):
            row = self._make_row("샴푸", "")  # link 빈칸
            cols = _process_row(row, crawler, health, all_known_links={"https://cafe.naver.com/cosmania/9"})

        # link 없음 + url_alive 폐기 = fetch_cafe_url_status 호출 X
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_exposed_row_fetch_status_never_called_with_cache(self):
        """T-M10.5: 검색 노출 행 동일 link 2회 처리 — fetch_cafe_url_status 호출 X (폐기).

        원래 T-M10.4: 캐시로 1회만 호출 검증.
        폐기 후: 캐시 여부 무관 = fetch_cafe_url_status 호출 자체 X.
        """
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

        # url_alive 폐기 = 2회 호출해도 fetch_cafe_url_status 호출 X
        crawler.fetch_cafe_url_status.assert_not_called()


class TestD024ExceptionPreservation:
    """D-024 (2026-05-14) 신규 회귀 test — main.py 예외 시 시트 보존 (K="삭제" 자동 적용 폐기).

    critic Opus 발견 Major 1 정합 — except Exception silent K="삭제" = D-023 화이트리스트 우회.
    T-M10.5 학습 정합 — 예측 못한 상태 = 시트 보존 우선.

    검증 패턴:
    - run_cycle 안 _process_row 가 raise 시 = updates 에 row 추가 X (시트 그대로)
    - retry_queue 에 추가 (다음 cycle 자연 재처리)
    - d024_skipped_rows 카운트 증가 (사장님 가시성)
    """

    def _patch_run_cycle_deps(self, fake_rows: dict, raise_exception: bool = True):
        """run_cycle 의존성 mock — SheetsClient / Crawler / parse_search_result.

        Args:
            fake_rows: {탭이름: [행 dict, ...]} 시뮬 시트
            raise_exception: True 면 _process_row 가 RuntimeError raise
        """
        # SheetsClient mock
        mock_client_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.load_all_data_tabs.return_value = fake_rows
        mock_client_instance.write_results.return_value = 0
        mock_client_class.return_value = mock_client_instance

        # Crawler mock
        mock_crawler_class = MagicMock()
        mock_crawler_instance = MagicMock()
        mock_crawler_instance.warmup.return_value = None
        if raise_exception:
            mock_crawler_instance.fetch_search.side_effect = RuntimeError("예측 못한 에러")
        else:
            mock_crawler_instance.fetch_search.return_value = "<html></html>"
        mock_crawler_class.return_value = mock_crawler_instance

        return mock_client_class, mock_crawler_class, mock_client_instance

    def test_예외_시_시트_보존_K_삭제_적용_X(self):
        """D-024: _process_row 가 raise 시 = updates 에 row 추가 X = 시트 보존 (K="삭제" 자동 적용 폐기).

        critic Opus 발견 Major 1 (main.py:188 except Exception → updates.append RowUpdate K="삭제") 폐기 검증.
        """
        from src.sheets import HEADER_AREA

        fake_rows = {
            "샴푸 카외": [
                {"키워드": "탈모샴푸", "링크": "https://cafe.naver.com/cosmania/12345", "_row": 2, "_tab": "샴푸 카외"},
            ],
        }
        mc, mcrw, client_inst = self._patch_run_cycle_deps(fake_rows, raise_exception=True)

        with patch("src.main.SheetsClient", mc), \
             patch("src.main.Crawler", mcrw), \
             patch("src.main.SPREADSHEET_ID", "fake_id"), \
             patch("src.main.SERVICE_ACCOUNT_JSON", "{}"):
            from src.main import run_cycle
            summary = run_cycle()

        # D-024 핵심 검증 1: write_results 호출 시 updates 에 K="삭제" 포함 X
        # write_results 가 호출됐다면 updates list 검증
        for call_args in client_inst.write_results.call_args_list:
            tab_name, updates = call_args[0]
            for upd in updates:
                # K="삭제" 절대 적용되지 않아야 함 (D-024 핵심)
                assert upd.columns.get(HEADER_AREA) != "삭제", \
                    f"D-024 위반: 예외 시 K='삭제' 자동 적용됨 (tab={tab_name}, row={upd.row})"

        # D-024 핵심 검증 2: d024_skipped_rows >= 1 (예외 1건 = skip 1건)
        assert summary.get("d024_skipped_rows", 0) >= 1, \
            f"D-024 위반: 예외 시 d024_skipped_rows 증가 X (summary={summary})"

    def test_예외_시_retry_queue_추가(self):
        """D-024: _process_row 가 raise 시 = retry_queue 에 추가 (T-M11 정합).

        다음 cycle 자연 재처리 = 사장님 시트 손상 X.
        """
        fake_rows = {
            "샴푸 카외": [
                {"키워드": "탈모샴푸", "링크": "https://cafe.naver.com/cosmania/12345", "_row": 2, "_tab": "샴푸 카외"},
            ],
        }
        mc, mcrw, client_inst = self._patch_run_cycle_deps(fake_rows, raise_exception=True)

        # RetryQueue.add 호출 추적
        from src.retry import RetryQueue
        original_add = RetryQueue.add
        add_call_records = []

        def tracked_add(self, row, error=""):
            add_call_records.append({"row": row, "error": error})
            return original_add(self, row, error=error)

        with patch("src.main.SheetsClient", mc), \
             patch("src.main.Crawler", mcrw), \
             patch("src.main.SPREADSHEET_ID", "fake_id"), \
             patch("src.main.SERVICE_ACCOUNT_JSON", "{}"), \
             patch.object(RetryQueue, "add", tracked_add):
            from src.main import run_cycle
            run_cycle()

        # D-024: 예외 1건 = retry_queue.add 호출 >= 1
        assert len(add_call_records) >= 1, \
            f"D-024 위반: 예외 시 retry_queue.add 호출 X (records={add_call_records})"

    def test_summary_d024_skipped_rows_필드_존재(self):
        """D-024: run_cycle summary 에 d024_skipped_rows 필드 항상 존재 (예외 0건도 0 으로 기록)."""
        fake_rows = {
            "샴푸 카외": [],  # 빈 탭 = 예외 없음
        }
        mc, mcrw, client_inst = self._patch_run_cycle_deps(fake_rows, raise_exception=False)

        with patch("src.main.SheetsClient", mc), \
             patch("src.main.Crawler", mcrw), \
             patch("src.main.SPREADSHEET_ID", "fake_id"), \
             patch("src.main.SERVICE_ACCOUNT_JSON", "{}"):
            from src.main import run_cycle
            summary = run_cycle()

        # D-024: 예외 0건 = d024_skipped_rows = 0 (필드 존재 의무)
        assert "d024_skipped_rows" in summary, f"D-024 위반: summary 에 d024_skipped_rows 필드 누락 ({summary})"
        assert summary["d024_skipped_rows"] == 0


class TestSlugWhitelistFallback:
    """T-M14.7 폐기 확인 (2026-05-14): slug 매치 fallback 제거 후 동작 검증.

    slug 매치 fallback 폐기 = 1차(target_url) + 2차(link_set) 모두 미노출 시
    추가 slug 검출 없이 미노출 그대로 반환.
    사장님 진짜 의도 = 시트 등록 link 정확 매치만 (D-022 옵션 A).
    """

    def _make_row(self, keyword: str, link: str, prev_K: str = "") -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "노출영역": prev_K, "_row": 2}

    def _mock_result(self, area: str, matched_url: str = None):
        """parse_search_result 반환용 mock RankResult."""
        from src.parser import RankResult, ExposureArea
        r = RankResult()
        r.exposure_area = ExposureArea(area) if area != "미노출" else ExposureArea.UNEXPOSED
        r.matched_url = matched_url
        r.parser_confidence = 0.85 if area != "미노출" else 0.0
        r.integrated_rank = 1 if area != "미노출" else None
        r.cafe_slot_rank = 1 if area != "미노출" else None
        r.block_order = [area] if area != "미노출" else []
        r.in_jisikin = False
        return r

    def test_slug_fallback_removed_unregistered_post_stays_unexposed(self):
        """slug 매치 fallback 폐기 확인: 시트 미등록 새 글이 노출되어도 slug 매치 없이 미노출 반환.

        시나리오: 시트 link = pusanmommy/1111, 검색 결과에 pusanmommy/9999 노출.
        폐기 전: slug 매치로 자동 검출 + link 갱신.
        폐기 후: 1차 target_url 미노출 → 2차 link_set 없음(공집합) → 미노출 그대로.
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        old_link = "https://cafe.naver.com/pusanmommy/1111"
        # all_known_links 에 현재 행 link 만 있으면 other_links = {} → 2차 link_set skip
        all_known_links = {old_link}

        unexposed = self._mock_result("미노출")

        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=unexposed):
            row = self._make_row("부산맘", old_link)
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        # D-026 Phase B (2026-05-16): slug fallback 폐기 → '미노출' 명시 표기
        assert cols[HEADER_AREA] == "미노출"
        # 링크 갱신 없음
        assert HEADER_LINK not in cols

    def test_slug_match_no_update_when_all_unexposed(self):
        """1차+2차 모두 미노출 → K=미노출, 링크 갱신 없음 (slug fallback 폐기로 3차 없음)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        link = "https://cafe.naver.com/pusanmommy/1111"
        all_known_links = {link}

        unexposed = self._mock_result("미노출")
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        with patch("src.main.parse_search_result", return_value=unexposed):
            row = self._make_row("부산맘", link)
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        # D-026 Phase B (2026-05-16): slug fallback 폐기 → '미노출' 명시 표기
        assert cols[HEADER_AREA] == "미노출"
        # 링크 갱신 없음
        assert HEADER_LINK not in cols


class TestD026EmptyLinkAutoFill:
    """D-026 Phase C+D (2026-05-16) — 빈 link 행 자동 채움 logic 회귀 test.

    사장님 컨벤션 (2026-05-16):
    - 빈 link 행 + 다른 행 우리 link 매치 = K="중복노출" + HEADER_LINK 자동 채움
    - 빈 link 행 + 매치 X = K="미노출"
    - 빈 link 행 + all_known_links 빈 = 검색 X + K="미노출"
    """

    def _make_row(self, keyword: str, link: str = "", prev_K: str = "") -> dict:
        return {"키워드": keyword, "링크": link, "노출영역": prev_K, "_row": 7}

    def _mock_matched_result(self, matched_url: str, area: str = "AB"):
        """parse_search_result 가 매치 성공 시 반환할 RankResult mock."""
        r = RankResult()
        r.exposure_area = ExposureArea(area) if area != "미노출" else ExposureArea.UNEXPOSED
        r.matched_url = matched_url
        r.parser_confidence = 0.85
        r.integrated_rank = 3
        r.cafe_slot_rank = 2
        r.block_order = [area]
        r.in_jisikin = False
        return r

    def _mock_unmatched_result(self):
        """parse_search_result 가 매치 X 시 반환할 RankResult mock."""
        r = RankResult()
        r.exposure_area = ExposureArea.UNEXPOSED
        r.matched_url = None
        r.parser_confidence = 0.0
        r.integrated_rank = None
        r.cafe_slot_rank = None
        r.block_order = []
        r.in_jisikin = False
        return r

    def test_d026_empty_link_match_fills_link_K_DUPLICATE(self):
        """D-026 Phase C+D: 빈 link 행 + 다른 행 우리 link 매치 = K='중복노출' + link 자동 채움."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK, HEADER_L, HEADER_M

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"

        matched = "https://cafe.naver.com/cosmania/9999"
        all_known_links = {matched, "https://cafe.naver.com/pusanmommy/1111"}

        with patch("src.main.parse_search_result", return_value=self._mock_matched_result(matched, "AB")):
            row = self._make_row("탈모샴푸")
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        # D-026 Phase C+D 핵심 검증
        assert cols[HEADER_AREA] == "중복노출"
        assert cols[HEADER_LINK] == matched  # 자동 채움
        assert cols[HEADER_L] == "3"
        assert cols[HEADER_M] == "2"
        # 검색 수행됨
        crawler.fetch_search.assert_called_once_with("탈모샴푸")

    def test_d026_empty_link_no_match_unexposed(self):
        """D-026 Phase C+D: 빈 link 행 + 매치 X = K='미노출' (link 갱신 X)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"

        all_known_links = {"https://cafe.naver.com/pusanmommy/1111"}

        with patch("src.main.parse_search_result", return_value=self._mock_unmatched_result()):
            row = self._make_row("탈모샴푸")
            cols = _process_row(row, crawler, health, all_known_links=all_known_links)

        assert cols[HEADER_AREA] == "미노출"
        # 매치 X = link 갱신 없음
        assert HEADER_LINK not in cols

    def test_d026_empty_link_no_known_links_no_search(self):
        """D-026 Phase C+D: 빈 link 행 + all_known_links 빈 = 검색 X + K='미노출'."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()

        row = self._make_row("탈모샴푸")
        cols = _process_row(row, crawler, health, all_known_links=set())

        assert cols[HEADER_AREA] == "미노출"
        # 검색 자체 skip
        crawler.fetch_search.assert_not_called()

    def test_d026_existing_link_not_overwritten(self):
        """D-026 Phase C+D 정합: link 있는 행 = 빈 link 분기 X (= 기존 link 보존, HEADER_LINK 갱신 X)."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA, HEADER_LINK

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        # 사장님 작업 link
        existing_link = "https://cafe.naver.com/cosmania/12345"

        with patch("src.main.parse_search_result", return_value=self._mock_matched_result(existing_link, "AB")):
            row = self._make_row("탈모샴푸", link=existing_link)
            cols = _process_row(row, crawler, health, all_known_links={existing_link})

        # K = "AB" (= 정상 노출)
        assert cols[HEADER_AREA] == "AB"
        # HEADER_LINK 자동 갱신 X (= D-023 가드 유지)
        assert HEADER_LINK not in cols

    def test_d026_naver_me_short_url_resolved_before_link_set(self):
        """D-026 Phase C+D + naver.me 정합: 사장님 시트 link = naver.me 단축 URL = resolve_short_url 후 매치 시도.

        근거: 사장님 컨벤션 = 시트에 naver.me 단축 URL 입력 가능. main.py 가 resolve_short_url 호출 후 검색 수행 의무.
        link 있는 행 = 단축 URL → resolve 후 정상 검색 진행. 빈 link 행 분기 X.
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        # 사장님 작업 link = naver.me 단축 URL
        short_link = "https://naver.me/x9z8y7"
        resolved_link = "https://cafe.naver.com/cosmania/12345"

        with patch("src.main.resolve_short_url", return_value=resolved_link) as mock_resolve:
            with patch("src.main.parse_search_result", return_value=self._mock_matched_result(resolved_link, "AB")) as mock_parse:
                row = self._make_row("탈모샴푸", link=short_link)
                cols = _process_row(row, crawler, health, all_known_links={resolved_link})

        # naver.me resolve 가 link 있는 행 처리 흐름 안 호출됨 검증
        mock_resolve.assert_called_once_with(short_link)
        # parser 호출 시 = resolve 된 link 전달 검증
        mock_parse.assert_called_once()
        parser_args, parser_kwargs = mock_parse.call_args
        # parse_search_result(html, target_url, link_set=...) 시그너처
        assert parser_args[1] == resolved_link
        # K = "AB" 정상 노출
        assert cols[HEADER_AREA] == "AB"


class TestD026DeletionTextDetection:
    """D-026 Phase E+F (2026-05-16) — 삭제 텍스트 검출 회귀 test.

    사장님 명시 컨벤션:
    - "게시글이 삭제되었습니다" exact substring 검출 → K="삭제"
    - 우산 패턴 = "삭제된 게시물입니다" / "존재하지 않는 게시글"
    - 로그인 페이지 / 404 / 네트워크 fail = UNKNOWN (= 시트 보존)
    """

    def _make_row(self, keyword: str, link: str, prev_K: str = "") -> dict:
        return {"키워드": keyword, "링크": link, "노출영역": prev_K, "_row": 5}

    def _mock_unexposed_result(self):
        r = RankResult()
        r.exposure_area = ExposureArea.UNEXPOSED
        r.matched_url = None
        r.parser_confidence = 0.0
        r.integrated_rank = None
        r.cafe_slot_rank = None
        r.block_order = []
        r.in_jisikin = False
        return r

    def test_deletion_detected_K_삭제(self):
        """D-026 Phase E+F: 검색 미노출 + 삭제 텍스트 검출 = K='삭제'."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.DELETED

        link = "https://cafe.naver.com/cosmania/12345"
        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("탈모샴푸", link, prev_K="AB")
            cols = _process_row(row, crawler, health)

        # D-026 Phase E+F 핵심 검증
        assert cols[HEADER_AREA] == "삭제"
        crawler.fetch_cafe_url_status.assert_called_once_with(link)

    def test_deletion_text_not_detected_K_preserved(self):
        """D-026 Phase E+F 위험 1 fix: prev_K='삭제' + 검색 미노출 + 텍스트 검출 X = '삭제' 보존.
        근거: 사장님 시트 832 행 보호 (= 기존 '삭제' 값 자동 '누락' 마이그레이션 X 의무).
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        # ALIVE = 텍스트 검출 X = '삭제' 보존 (위험 1 fix)
        crawler.fetch_cafe_url_status.return_value = CafeStatus.ALIVE

        link = "https://cafe.naver.com/cosmania/12345"
        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("탈모샴푸", link, prev_K="삭제")
            cols = _process_row(row, crawler, health)

        # 위험 1 fix 핵심: prev='삭제' + 텍스트 검출 X = '삭제' 보존
        assert cols[HEADER_AREA] == "삭제"

    def test_deletion_unknown_keeps_state(self):
        """D-026 Phase E+F: 검색 미노출 + UNKNOWN (= 로그인/404) = 텍스트 검출 X = 시트 보존."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.return_value = CafeStatus.UNKNOWN

        link = "https://cafe.naver.com/cosmania/12345"
        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("탈모샴푸", link, prev_K="AB")
            cols = _process_row(row, crawler, health)

        # UNKNOWN + prev='AB' + 검색 미노출 = '누락' (= 박스 빠짐)
        assert cols[HEADER_AREA] == "누락"

    def test_deletion_exception_safe_preserves_prev(self):
        """D-026 Phase E+F 안전 회로: fetch_cafe_url_status 예외 = deletion_detected=False = 보존."""
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        crawler.fetch_search.return_value = "<html>검색결과</html>"
        crawler.fetch_cafe_url_status.side_effect = RuntimeError("network down")

        link = "https://cafe.naver.com/cosmania/12345"
        with patch("src.main.parse_search_result", return_value=self._mock_unexposed_result()):
            row = self._make_row("탈모샴푸", link, prev_K="삭제")
            cols = _process_row(row, crawler, health)

        # 예외 = deletion_detected=False = prev '삭제' + 검색 미노출 = '삭제' 보존
        assert cols[HEADER_AREA] == "삭제"
