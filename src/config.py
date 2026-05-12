"""config: 환경변수 + 상수 로드."""
import os

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON", "")
NAVER_SLOWDOWN_BASE_SEC = float(os.environ.get("NAVER_SLOWDOWN_BASE_SEC", "5.0"))  # 사장님 발화 정합 (2026-05-08), 5/8 사례에서 차단 발생한 1.5 → 5.0 보수화
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
# comparison-500 분석 결과 26 slug 발견. link_set 매치 시 = 화이트리스트 안 slug 만 매치.
# 사장님 추가 카페 시 = 여기 추가 (재배포 의무).
CAFE_WHITELIST = {
    "pusanmommy", "iroid", "move79", "culturebloom", "cosmania",
    "multiroader", "llchyll", "jejutip", "workee", "happyibook",
    "ite", "allumpc", "mindy7857", "minecraftpe", "0404ab",
    "tgpia", "engmstudy", "vinpearl", "michiexam", "linchpinedu",
    "kig", "dokchi", "firenze", "trotkingpjh", "hawaiiphoto",
    "guamfree",
}
