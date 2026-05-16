"""config: 환경변수 + 상수 로드."""
import os

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON", "")
NAVER_SLOWDOWN_BASE_SEC = float(os.environ.get("NAVER_SLOWDOWN_BASE_SEC", "3.5"))  # 2026-05-13 사장님 시간 ↓ 요구. run 25747754727 = 차단 0건 검증 후 5.0 → 3.5 단축. wait() = random(3.5, 5.25) 평균 4.4초 × 832 = 61분 + 기타 = 약 90분 (139 → 90, -49분).
NAVER_SLOWDOWN_MAX_SEC = float(os.environ.get("NAVER_SLOWDOWN_MAX_SEC", "60"))

# T-M23 (2026-05-12): 모바일 UA 제거 (PC Chrome만). 모바일 UA + curl_cffi PC Chrome impersonate
# = fingerprint mismatch = 봇 감지 트리거. critic agent 검증 완료.
# Chrome 131/136/145/146 4종 = curl_cffi 0.15.0 진짜 지원 (chrome.update 검증).
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]

# T-M24c (2026-05-12): impersonate 회전 풀. curl_cffi 0.15.0 진짜 지원 버전만.
# document-specialist 권장 = chrome146 최신. 4종 회전 = fingerprint 다양성 ↑ + 봇 감지 ↓.
IMPERSONATE_POOL = ["chrome146", "chrome145", "chrome136", "chrome131"]

# T-M25 (2026-05-12): 사장님 운영 카페 slug 화이트리스트.
# T-M90 (D-027 보강 2026-05-17): repo Public 전환 = CAFE_WHITELIST 환경변수 이전 = 사장님 카페 정보 노출 회피.
# 환경변수 = CAFE_WHITELIST_SLUGS = "slug1,slug2,slug3" 콤마 구분.
# 미설정 시 = 빈 set = D-026 link_set 매치 X = 자동 채움 X (= 안전 default).
CAFE_WHITELIST = frozenset(
    s.strip() for s in os.environ.get("CAFE_WHITELIST_SLUGS", "").split(",") if s.strip()
)
