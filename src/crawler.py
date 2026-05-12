"""crawler: 네이버 검색 페이지 fetch (slowdown, UA rotation) + URL 정규화.

2026-05-11 T-M9.1: requests → curl_cffi 마이그레이션. impersonate="chrome131" 로
TLS/JA3 지문 위장 → 네이버 봇 차단 회피 (cron run 25647821456 손상 root cause 중 하나).

2026-05-12 T-M23~T-M26 (D-021):
- IMPERSONATE_POOL 회전 (chrome146/145/136/131) — fingerprint 다양성
- cookie warmup (네이버 메인 fetch 후 검색) — Cold session 차단 회피
- wait() base 값 정합 — config NAVER_SLOWDOWN_BASE_SEC 진짜 적용
- Accept-Encoding 헤더 추가 — 브라우저 동일 행동
"""
import random
import re
import time
from typing import Optional

from curl_cffi import requests

from src.config import USER_AGENTS, IMPERSONATE_POOL

# T-M24c: impersonate 회전. 매 Crawler 인스턴스 random 선택.
IMPERSONATE = "chrome146"  # 기본 = 최신 (test 호환성 유지)

CAFE_URL_RE = re.compile(r"https?://cafe\.naver\.com/([^/?#]+)/(\d+)")


def parse_cafe_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """cafe.naver.com URL에서 slug와 post_id 추출. 매칭 실패 시 (None, None)."""
    if not url:
        return (None, None)
    m = CAFE_URL_RE.match(url)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))


def resolve_short_url(url: str) -> str:
    """naver.me 단축 URL을 풀 cafe.naver.com URL로 해석. 단축 아니면 그대로 반환."""
    if not url or "naver.me" not in url:
        return url
    try:
        r = requests.head(url, impersonate=IMPERSONATE, allow_redirects=False, timeout=10)
        if 300 <= r.status_code < 400 and "Location" in r.headers:
            return r.headers["Location"]
    except requests.RequestsError:
        pass
    return url


def random_user_agent() -> str:
    """USER_AGENTS 풀에서 랜덤 선택."""
    return random.choice(USER_AGENTS)


class CircuitBreakerOpen(Exception):
    """5 차단 연속 시 발동. main.py 가 잡아서 cron 조기 종료."""
    pass


class SlowdownController:
    """차단 의심 시 자동 슬로우다운 (지수 backoff). 성공 시 천천히 회복.

    2026-05-11 architect Major 1 fix: 비대칭 회복 (×2 vs ×0.9) 이 1 차단 → 60s max → 30+ 성공 필요 회복.
    832 행 매 cron 무력화 위험. 두 가지 fix:
    1. 회복 가속: on_success × 0.5 (×0.9 대신) — 1 성공 만에 절반 감소
    2. Circuit breaker: 5 차단 연속 시 CircuitBreakerOpen raise → main.py 가 조기 종료
    """

    CONSECUTIVE_BLOCKS_THRESHOLD = 5  # 5 차단 연속 시 circuit breaker open

    def __init__(self, base: float = 1.5, max_: float = 60.0):
        self.base = base
        self.max_ = max_
        self.current_interval = base
        self.consecutive_blocks = 0

    def on_block_detected(self):
        self.consecutive_blocks += 1
        self.current_interval = min(self.max_, self.current_interval * 2)
        if self.consecutive_blocks >= self.CONSECUTIVE_BLOCKS_THRESHOLD:
            raise CircuitBreakerOpen(
                f"네이버 차단 {self.consecutive_blocks}회 연속. cron 조기 종료. "
                f"current_interval={self.current_interval:.1f}s."
            )

    def on_success(self):
        self.consecutive_blocks = 0
        # 2026-05-11 fix: ×0.9 (회복 30+ 성공) → ×0.5 (회복 1~7 성공). 사장님 가정용 IP 차단 위험 ↓
        self.current_interval = max(self.base, self.current_interval * 0.5)

    def wait(self):
        """2026-05-12 T-M26 fix: 정상 분기 = config NAVER_SLOWDOWN_BASE_SEC 정합.
        기존 하드코딩 random.uniform(1.5, 4.0) → self.base * 1.5 (5~7.5초 at base=5.0).
        backoff 발생 시 (current_interval > base) 그 값 + jitter, 정상 시 base~base×1.5초.
        """
        if self.current_interval > self.base:
            # backoff 발생 — 그 간격 사용 (차단 누적 위험 ↓)
            jitter = random.uniform(-0.3, 0.3)
            time.sleep(max(0.1, self.current_interval + jitter))
        else:
            # 정상 — config base 정합 (5~7.5초 at base=5.0, 봇 패턴 회피)
            time.sleep(random.uniform(self.base, self.base * 1.5))


from enum import Enum


class CafeStatus(Enum):
    ALIVE = "alive"
    DELETED = "deleted"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class CrawlerError(Exception):
    pass


_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    # T-M24b (2026-05-12): 브라우저 동일 행동 — gzip/br 압축 요청 추가
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.naver.com/",
}


class Crawler:
    """네이버 검색 + 카페 URL fetcher (slowdown + UA rotation 통합)."""

    SEARCH_URL = "https://search.naver.com/search.naver"

    def __init__(self, slowdown: Optional[SlowdownController] = None):
        self.slowdown = slowdown or SlowdownController()
        # T-M24 (2026-05-12): 매 인스턴스 random impersonate — fingerprint 다양성 ↑
        self.impersonate = random.choice(IMPERSONATE_POOL)
        self.session = requests.Session(impersonate=self.impersonate)

    def warmup(self) -> None:
        """네이버 메인 1회 fetch → Session cookie 적재 → 자연 사용자 흐름.

        document-specialist 검증 결과 (2026-05-12): Cold session = 검색 시 빈 응답
        soft 차단 위험. 메인 fetch 후 검색 = trust ↑.
        """
        try:
            self.session.get("https://www.naver.com/", headers=self._headers(), timeout=10)
        except Exception:
            pass  # warmup 실패 = 무시 (검색 자체는 진행)

    def _headers(self) -> dict:
        return {**_BROWSER_HEADERS, "User-Agent": random_user_agent()}

    def fetch_search(self, keyword: str) -> str:
        """키워드 검색 페이지 HTML 반환. 차단/오류 시 CrawlerError raise."""
        self.slowdown.wait()
        try:
            r = self.session.get(
                self.SEARCH_URL,
                params={"query": keyword},
                headers=self._headers(),
                timeout=15,
            )
        except requests.RequestsError as e:
            self.slowdown.on_block_detected()
            raise CrawlerError(f"network error: {e}") from e

        if r.status_code == 429 or self._looks_blocked(r):
            self.slowdown.on_block_detected()
            raise CrawlerError(f"rate limited (status={r.status_code})")

        if r.status_code != 200:
            raise CrawlerError(f"unexpected status {r.status_code}")

        self.slowdown.on_success()
        return r.text

    def fetch_cafe_url_status(self, url: str) -> CafeStatus:
        """카페 URL이 살아있는지 / 삭제됐는지 / 비공개인지 판정."""
        self.slowdown.wait()
        try:
            r = self.session.get(
                url,
                headers=self._headers(),
                allow_redirects=True,
                timeout=15,
            )
        except requests.RequestsError:
            return CafeStatus.UNKNOWN

        if r.status_code == 404:
            return CafeStatus.DELETED

        if r.status_code == 200:
            text_lower = r.text.lower()
            if "nidlogin.login" in text_lower or "로그인이 필요합니다" in r.text:
                return CafeStatus.PRIVATE
            if "삭제" in r.text and "게시글" in r.text and len(r.text) < 5000:
                return CafeStatus.DELETED
            return CafeStatus.ALIVE

        return CafeStatus.UNKNOWN

    @staticmethod
    def _looks_blocked(r: requests.Response) -> bool:
        """차단 의심 검출. 정상 네이버 페이지에 'captcha' 단어가 광고/스크립트 등에
        포함되어 false positive 났던 사례 있음 (2026-05-08) — strict 패턴으로 변경.
        """
        text = r.text
        if len(text) < 500:
            return True
        # 한국어 차단 페이지 명시적 신호
        block_signals = [
            "자동입력 방지문자",
            "비정상적인 트래픽",
            "비정상 트래픽",
            "보안문자를 입력",
            "사이트 접속이 일시적으로",
        ]
        return any(s in text for s in block_signals)
