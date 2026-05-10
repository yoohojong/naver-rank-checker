"""cache: 카페매핑 메모리 캐시 (Sheets backed, M5.5 와 연동).

사장님 시트엔 현재 "카페매핑" 탭 없음 (2026-05-08 확인). 그러나 미래 추가 가능 +
한 cron 사이클 안에서 같은 cafe slug 여러 번 fetch 방지 위해 메모리 캐시 유지.
"""
from typing import Callable, Optional


class CafeMappingCache:
    """카페 slug → {full_name, short_name} 메모리 캐시.

    사용 흐름 (T-M7.2 main.py):
    1. cron 시작 시 시트의 "카페매핑" 탭 read → initial 로 로드 (있으면)
    2. 검색 결과에서 새 slug 발견 시 ensure(slug, ...) → 자동 fetch + 캐시 + 시트 추가
    3. cron 종료 시 캐시는 메모리에서 사라짐 (다음 cron 에 시트에서 다시 로드)
    """

    def __init__(self, initial: Optional[dict] = None):
        self._mem: dict[str, dict] = dict(initial) if initial else {}

    def get(self, slug: str) -> Optional[dict]:
        """캐시 hit 시 mapping dict, miss 시 None. fetch 없음."""
        return self._mem.get(slug)

    def set(self, slug: str, mapping: dict) -> None:
        """수동 set (initial 외 추가)."""
        self._mem[slug] = mapping

    def __contains__(self, slug: str) -> bool:
        return slug in self._mem

    def __len__(self) -> int:
        return len(self._mem)

    def ensure(
        self,
        slug: str,
        fetcher_fn: Callable[[str], str],
        sheets_writer_fn: Optional[Callable[[str, str], None]] = None,
    ) -> dict:
        """slug 캐시 hit 면 그대로, miss 면 fetch + 시트 추가 + 캐시.

        Args:
            slug: 카페 slug (예: "pusanmommy")
            fetcher_fn: slug → 카페 full_name (한글). 실패 시 raise 또는 빈 string.
            sheets_writer_fn: 선택 — (slug, full_name) → None. 시트 "카페매핑" 탭에 새 행 추가.
                              실패해도 무시 (다음 cron 에 재시도).

        Returns:
            mapping dict: {"full_name": str, "short_name": str}. fetch 실패 시 빈 mapping.
        """
        if slug in self._mem:
            return self._mem[slug]

        full_name = ""
        try:
            full_name = fetcher_fn(slug) or ""
        except Exception:
            full_name = ""

        mapping = {"full_name": full_name, "short_name": ""}
        self._mem[slug] = mapping

        if full_name and sheets_writer_fn is not None:
            try:
                sheets_writer_fn(slug, full_name)
            except Exception:
                pass

        return mapping
