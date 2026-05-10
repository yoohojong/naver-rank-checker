"""config: 환경변수 + 상수 로드."""
import os

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON", "")
NAVER_SLOWDOWN_BASE_SEC = float(os.environ.get("NAVER_SLOWDOWN_BASE_SEC", "5.0"))  # 사장님 발화 정합 (2026-05-08), 5/8 사례에서 차단 발생한 1.5 → 5.0 보수화
NAVER_SLOWDOWN_MAX_SEC = float(os.environ.get("NAVER_SLOWDOWN_MAX_SEC", "60"))
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
]
