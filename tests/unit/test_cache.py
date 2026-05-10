"""cache 단위 테스트."""
import pytest

from src.cache import CafeMappingCache


class TestCafeMappingCacheBasic:
    def test_hit_returns_mapping(self):
        cache = CafeMappingCache(initial={"slug1": {"full_name": "카페1", "short_name": "C1"}})
        result = cache.get("slug1")
        assert result == {"full_name": "카페1", "short_name": "C1"}

    def test_miss_returns_none(self):
        cache = CafeMappingCache()
        assert cache.get("unknown") is None

    def test_contains_operator(self):
        cache = CafeMappingCache(initial={"slug1": {}})
        assert "slug1" in cache
        assert "slug2" not in cache

    def test_set_adds_mapping(self):
        cache = CafeMappingCache()
        cache.set("new_slug", {"full_name": "신규카페"})
        assert cache.get("new_slug") == {"full_name": "신규카페"}

    def test_len_reflects_count(self):
        cache = CafeMappingCache(initial={"a": {}, "b": {}})
        assert len(cache) == 2


class TestCafeMappingCacheEnsure:
    def test_ensure_hit_skips_fetcher(self):
        cache = CafeMappingCache(initial={"pusanmommy": {"full_name": "부산맘카페"}})
        fetcher_called = []
        def fetcher(slug):
            fetcher_called.append(slug)
            return "절대 호출되면 안 됨"
        result = cache.ensure("pusanmommy", fetcher)
        assert result["full_name"] == "부산맘카페"
        assert fetcher_called == []  # cache hit 라 fetcher 호출 X

    def test_ensure_miss_calls_fetcher(self):
        cache = CafeMappingCache()
        def fetcher(slug):
            return f"카페-{slug}"
        result = cache.ensure("newslug", fetcher)
        assert result["full_name"] == "카페-newslug"
        assert "newslug" in cache  # 캐시에 자동 등록

    def test_ensure_fetcher_exception_returns_empty_mapping(self):
        """fetcher 실패해도 빈 mapping 캐시 (다음 cron 재시도)."""
        cache = CafeMappingCache()
        def fetcher(slug):
            raise RuntimeError("네트워크 오류")
        result = cache.ensure("err_slug", fetcher)
        assert result == {"full_name": "", "short_name": ""}
        assert "err_slug" in cache  # 빈 mapping 도 캐시

    def test_ensure_writes_to_sheets_on_success(self):
        cache = CafeMappingCache()
        writes = []
        def fetcher(slug):
            return f"카페-{slug}"
        def writer(slug, full_name):
            writes.append((slug, full_name))
        cache.ensure("new", fetcher, sheets_writer_fn=writer)
        assert writes == [("new", "카페-new")]

    def test_ensure_skips_sheets_when_fetch_empty(self):
        cache = CafeMappingCache()
        writes = []
        def fetcher(slug):
            return ""  # 빈 결과
        def writer(slug, full_name):
            writes.append((slug, full_name))
        cache.ensure("emptyslug", fetcher, sheets_writer_fn=writer)
        assert writes == []  # 빈 full_name 이면 시트 추가 X

    def test_ensure_sheets_failure_ignored(self):
        """시트 write 실패는 무시 (다음 cron 재시도)."""
        cache = CafeMappingCache()
        def fetcher(slug):
            return "카페명"
        def writer(slug, full_name):
            raise RuntimeError("Sheets API 5분 차단")
        # 예외 안 나야 함
        result = cache.ensure("xyz", fetcher, sheets_writer_fn=writer)
        assert result["full_name"] == "카페명"  # 캐시는 정상

    def test_ensure_works_without_writer(self):
        """sheets_writer_fn 없어도 동작 (메모리 캐시만)."""
        cache = CafeMappingCache()
        def fetcher(slug):
            return "카페명"
        result = cache.ensure("slug", fetcher)
        assert result["full_name"] == "카페명"
