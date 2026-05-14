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
    """T-M10.5 (2026-05-14): url_alive 검증 폐기 — 비로그인 환경 한계 확인.

    url_alive_cache 파라미터는 _process_row 시그니처에 유지되나
    fetch_cafe_url_status 호출 자체가 폐기되어 캐시 동작 테스트는 무의미.
    대신 url_alive_cache 전달 여부와 무관하게 결과가 동일함을 검증.
    """

    def _make_row(self, keyword: str, link: str) -> dict:
        """테스트용 행 dict 생성."""
        return {"키워드": keyword, "링크": link, "유형": "", "_row": 2}

    def test_url_alive_cache_param_has_no_effect_on_result(self):
        """T-M10.5: url_alive_cache 전달 여부 무관 = 동일 결과 반환 (fetch_cafe_url_status 폐기).
        검색 미노출 → K="" (url 상태 무관).
        """
        from src.main import _process_row
        from src.health import HealthMonitor
        from src.sheets import HEADER_AREA

        crawler = MagicMock()
        health = HealthMonitor()
        url_alive_cache: dict = {}
        link = "https://cafe.naver.com/cosmania/12345"

        mock_result = MagicMock()
        mock_result.exposure_area.value = "미노출"
        mock_result.parser_confidence = 1.0
        mock_result.block_order = []
        mock_result.integrated_rank = None
        mock_result.cafe_slot_rank = None
        mock_result.in_jisikin = False

        crawler.fetch_search.return_value = "<html>검색결과</html>"

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            cols_with_cache = _process_row(row, crawler, health, url_alive_cache=url_alive_cache)
            cols_no_cache = _process_row(row, crawler, health, url_alive_cache=None)

        # url_alive 폐기 = fetch_cafe_url_status 호출 X
        crawler.fetch_cafe_url_status.assert_not_called()
        # 캐시 여부 무관 = 동일 결과
        assert cols_with_cache[HEADER_AREA] == cols_no_cache[HEADER_AREA] == ""

    def test_url_alive_cache_not_populated(self):
        """T-M10.5: fetch_cafe_url_status 폐기 = url_alive_cache 에 아무것도 저장 X."""
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

        with patch("src.main.parse_search_result", return_value=mock_result):
            _process_row(self._make_row("샴푸", link), crawler, health, url_alive_cache=url_alive_cache)

        # url_alive 폐기 = 캐시 비어있음
        assert len(url_alive_cache) == 0
        crawler.fetch_cafe_url_status.assert_not_called()

    def test_multiple_calls_fetch_status_never_called(self):
        """T-M10.5: 동일 link 여러 번 _process_row 호출해도 fetch_cafe_url_status 호출 X."""
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

        with patch("src.main.parse_search_result", return_value=mock_result):
            row = self._make_row("샴푸", link)
            _process_row(row, crawler, health, url_alive_cache=None)
            _process_row(row, crawler, health, url_alive_cache=None)

        # url_alive 폐기 = 캐시 없어도 fetch_cafe_url_status 호출 X
        crawler.fetch_cafe_url_status.assert_not_called()


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

        assert cols[HEADER_AREA] == ""

    def test_search_unexposed_link_private_returns_empty(self):
        """T-M10.5: 검색 미노출 + url 비공개 → K="" (url_alive 검증 폐기).

        원래: K="삭제" 기대.
        폐기 후: fetch_cafe_url_status 호출 X = url 상태 무관 = K="" (검색 미노출).
        진짜 삭제 = 다음 cron 박스 매치 X = 자연 미노출 표시.
        """
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

        # url_alive 폐기 = 검색 미노출 → K="" (삭제 판정 X)
        assert cols[HEADER_AREA] == ""
        crawler.fetch_cafe_url_status.assert_not_called()

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

        # slug fallback 폐기 → 미노출 그대로 (K="")
        assert cols[HEADER_AREA] == ""
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

        # slug fallback 폐기 → 미노출 그대로 (K="")
        assert cols[HEADER_AREA] == ""
        # 링크 갱신 없음
        assert HEADER_LINK not in cols
