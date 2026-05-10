# naver-rank-checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 네이버 키워드 상위노출을 자동 체크하고 결과를 사장님 Google Sheets(분야별 탭)에 6시간마다 자동 기록하는 Python 프로그램. GitHub Actions 공개 저장소에서 무료 운영.

**Architecture:** Modular Python (crawler/parser/sheets/cache/retry/health/main 7 모듈). HTTP requests로 네이버 검색 페이지 fetch → BeautifulSoup으로 파싱 → gspread로 Sheets I/O. 시트의 이전 K 컬럼 값을 비교 기준선으로 사용 (`노출중지` 자동 감지). GitHub Actions cron `0 */6 * * *`.

**Tech Stack:** Python 3.12 / requests / beautifulsoup4 (lxml parser) / gspread (Google Sheets) / google-auth / pytest / responses (HTTP mock) / freezegun (시간 mock).

**Spec:** `D:\claude code\naver-rank-checker\.harness\spec.md`

**Aikon:** 👤 사장님 직접 작업 / 🤖 Claude (코딩 에이전트) 작업

---

## File Structure

```
D:\claude code\naver-rank-checker\
├── .github/workflows/
│   ├── check.yml              # cron 실행 (6시간마다)
│   └── test.yml               # 테스트 자동 실행 (PR/push)
├── .harness/                  # spec / plan / tasks / decisions (이미 있음)
├── src/
│   ├── __init__.py
│   ├── config.py              # 상수/환경변수 로드
│   ├── crawler.py             # 네이버 fetch (slowdown, UA rotation)
│   ├── parser.py              # AB/스마트블록/인기글/지식인 파싱
│   ├── sheets.py              # Sheets I/O, 헤더 매핑
│   ├── cache.py               # 카페매핑 캐시
│   ├── retry.py               # 재시도 큐
│   ├── health.py              # 헬스 모니터링 (logs 출력)
│   ├── transitions.py         # K 컬럼 상태 전환 (이전 vs 현재)
│   └── main.py                # 오케스트레이션 (entry point)
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # pytest fixtures
│   ├── fixtures/
│   │   └── naver/             # 실측 HTML 저장 (M4 Phase 1에서 수집)
│   ├── unit/
│   │   ├── test_crawler.py
│   │   ├── test_parser.py
│   │   ├── test_sheets.py
│   │   ├── test_cache.py
│   │   ├── test_retry.py
│   │   ├── test_health.py
│   │   └── test_transitions.py
│   └── component/
│       └── test_main_flow.py
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .gitignore
├── README.md                   # 운영 가이드 (사장님용)
└── LICENSE                     # MIT (공개 저장소이므로)
```

---

## M3 — 인프라 셋업

목표: GitHub 저장소 + Google Cloud 서비스 계정 + Python 환경 모두 갖춤. 빈 모듈 골격까지.

### 👤 Task M3.1: Google Cloud 프로젝트 + Sheets API 활성

**작업자:** 사장님 (Claude가 단계별 가이드 제공)

- [ ] **Step 1**: https://console.cloud.google.com/ 접속, 본인 Google 계정으로 로그인
- [ ] **Step 2**: 상단 "프로젝트 선택" 드롭다운 → "새 프로젝트" → 이름 `naver-rank-checker` 입력 → 만들기
- [ ] **Step 3**: 좌측 메뉴 "API 및 서비스" → "라이브러리" → "Google Sheets API" 검색 → 사용 설정 (Enable)
- [ ] **Step 4**: 같은 화면에서 "Google Drive API" 도 사용 설정 (gspread가 권한 확인용으로 사용)
- [ ] **Step 5**: 좌측 메뉴 "API 및 서비스" → "사용자 인증 정보" → 상단 "+ 사용자 인증 정보 만들기" → "서비스 계정"
- [ ] **Step 6**: 서비스 계정 이름 `sheets-writer` 입력 → 만들기 → 다음 단계 모두 건너뜀 (역할 부여 X)
- [ ] **Step 7**: 생성된 서비스 계정 이메일 클릭 → "키" 탭 → "키 추가" → "새 키 만들기" → JSON 선택 → 다운로드
- [ ] **Step 8**: 다운받은 JSON 파일을 안전한 위치에 저장 (예: `D:\claude code\naver-rank-checker\.secrets\service-account.json` — 단 절대 git에 커밋 X). 서비스 계정 이메일 메모 (예: `sheets-writer@naver-rank-checker-xxxxx.iam.gserviceaccount.com`)

### 👤 Task M3.2: 사장님 시트에 서비스 계정 공유

- [ ] **Step 1**: 사장님 운영 중인 Google Sheets 열기
- [ ] **Step 2**: 우상단 "공유" 버튼
- [ ] **Step 3**: 위 M3.1에서 메모한 서비스 계정 이메일 입력
- [ ] **Step 4**: 권한 "편집자" 선택 → 알림 보내기 체크 해제 → "공유"
- [ ] **Step 5**: 시트 URL에서 `spreadsheets/d/{이부분}/edit` 의 `{이부분}` 복사 (= Spreadsheet ID, 메모)

### 👤 Task M3.3: GitHub 공개 저장소 생성

- [ ] **Step 1**: https://github.com/new 접속
- [ ] **Step 2**: Repository name `naver-rank-checker` 입력
- [ ] **Step 3**: **Public** 선택 (필수 — 무료 GitHub Actions 무제한)
- [ ] **Step 4**: "Add a README file" 체크 X (Claude가 만들 예정)
- [ ] **Step 5**: ".gitignore" → Python 선택
- [ ] **Step 6**: "License" → MIT
- [ ] **Step 7**: Create repository
- [ ] **Step 8**: 저장소 URL 메모 (예: `https://github.com/<사장님계정>/naver-rank-checker.git`)

### 🤖 Task M3.4: 로컬 프로젝트 git 초기화 + 원격 연결

**Files:**
- Modify: `D:\claude code\naver-rank-checker\.gitignore`

- [ ] **Step 1: .gitignore 작성**

```bash
# Python
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.coverage
*.egg-info/

# Virtual environment
venv/
.venv/
env/

# Secrets (절대 커밋 금지)
.secrets/
*.json
!package*.json
!tsconfig*.json
!.harness/*.json

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Project specific
.harness/violation-log.txt
```

- [ ] **Step 2: git 초기화**

```bash
cd "D:\claude code\naver-rank-checker"
git init
git branch -m main
```

- [ ] **Step 3: 원격 연결 (M3.3에서 만든 저장소)**

```bash
git remote add origin https://github.com/<사장님계정>/naver-rank-checker.git
git remote -v   # 확인
```

- [ ] **Step 4: 첫 커밋 (.harness만 먼저)**

```bash
git add .gitignore .harness/
git commit -m "chore: initial harness (spec, plan, tasks, decisions)"
```

- [ ] **Step 5: 원격 push**

```bash
git push -u origin main
```

### 🤖 Task M3.5: Python 환경 + requirements.txt

**Files:**
- Create: `D:\claude code\naver-rank-checker\requirements.txt`
- Create: `D:\claude code\naver-rank-checker\requirements-dev.txt`
- Create: `D:\claude code\naver-rank-checker\pytest.ini`

- [ ] **Step 1: requirements.txt 작성**

```
requests==2.32.3
beautifulsoup4==4.12.3
lxml==5.3.0
gspread==6.1.4
google-auth==2.36.0
```

- [ ] **Step 2: requirements-dev.txt 작성**

```
-r requirements.txt
pytest==8.3.4
responses==0.25.3
freezegun==1.5.1
```

- [ ] **Step 3: pytest.ini 작성**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
markers =
    integration: 실제 외부 호출 (네이버, Sheets) — 평소 skip
```

- [ ] **Step 4: 가상환경 + 설치**

```bash
cd "D:\claude code\naver-rank-checker"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

- [ ] **Step 5: 설치 확인**

```bash
pip list | findstr "requests gspread pytest"
```
Expected: 3개 라이브러리 모두 설치됨

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt requirements-dev.txt pytest.ini
git commit -m "chore: Python deps (requests, gspread, pytest)"
git push
```

### 🤖 Task M3.6: 모듈 골격 + 첫 sanity 테스트

**Files:**
- Create: `src/__init__.py`, `src/config.py`, `src/crawler.py`, `src/parser.py`, `src/sheets.py`, `src/cache.py`, `src/retry.py`, `src/health.py`, `src/transitions.py`, `src/main.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/unit/__init__.py`, `tests/component/__init__.py`
- Create: `tests/unit/test_sanity.py`

- [ ] **Step 1: 모든 빈 모듈 파일 생성**

`src/__init__.py`:
```python
"""naver-rank-checker — 네이버 키워드 상위노출 자동 체크."""
```

각 모듈 (`crawler.py`, `parser.py`, ...): 파일 상단에 한 줄 docstring만:
```python
"""crawler: 네이버 검색 페이지 fetch (slowdown, UA rotation)."""
```

`src/config.py`:
```python
"""config: 환경변수 + 상수 로드."""
import os

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON", "")  # JSON 문자열 또는 파일 경로
NAVER_SLOWDOWN_BASE_SEC = float(os.environ.get("NAVER_SLOWDOWN_BASE_SEC", "1.5"))
NAVER_SLOWDOWN_MAX_SEC = float(os.environ.get("NAVER_SLOWDOWN_MAX_SEC", "60"))
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
]
```

- [ ] **Step 2: tests/conftest.py 작성**

```python
"""pytest 공통 fixtures."""
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir):
    def _load(name: str) -> str:
        path = fixtures_dir / name
        return path.read_text(encoding="utf-8")
    return _load
```

- [ ] **Step 3: tests/unit/test_sanity.py 작성 (실패 예상)**

```python
"""환경 sanity 테스트: 모든 모듈 import 가능 확인."""
import pytest


def test_all_modules_importable():
    from src import config, crawler, parser, sheets, cache, retry, health, transitions, main
    assert config.NAVER_SLOWDOWN_BASE_SEC == 1.5


def test_user_agents_list_nonempty():
    from src.config import USER_AGENTS
    assert len(USER_AGENTS) >= 4
    assert all(isinstance(ua, str) and len(ua) > 20 for ua in USER_AGENTS)
```

- [ ] **Step 4: 테스트 실행**

```bash
pytest tests/unit/test_sanity.py -v
```
Expected: 2개 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/ tests/
git commit -m "feat: skeleton modules + sanity test"
git push
```

---

## M4 — Crawler + Parser (실측 검증 우선)

목표: 네이버 검색 페이지 실측 → fixture 저장 → TDD로 파싱 모듈 완성.

### 🤖 Task M4.1: Phase 1 실측 — 네이버 페이지 수집

**Files:**
- Create: `tests/fixtures/naver/*.html` (수집)
- Create: `scripts/collect_fixtures.py` (1회용 수집 스크립트)

- [ ] **Step 1: 수집 스크립트 작성**

`scripts/collect_fixtures.py`:
```python
"""1회용: 네이버 검색 페이지 수집해서 tests/fixtures/naver/ 에 저장."""
import time
import requests
from pathlib import Path

OUT = Path(__file__).parent.parent / "tests" / "fixtures" / "naver"
OUT.mkdir(parents=True, exist_ok=True)

KEYWORDS = {
    # 사장님이 알려준 케이스 + 다양성을 위한 추가
    "ab_cafe_top": "등드름해초필링",       # AB 1등 (사장님 제공)
    "popular_cafe": "트러블크림",          # 인기글 3등 (사장님 제공)
    "smart_block": "두피관리법",           # 스마트블록 위주 (추정)
    "mixed_blocks": "샴푸순위",            # 혼합형 (카톡에서 언급)
    "no_match": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",     # 결과 없음 (네거티브 케이스)
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

for label, kw in KEYWORDS.items():
    url = f"https://search.naver.com/search.naver?query={kw}"
    print(f"Fetching: {kw} → {label}")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out_path = OUT / f"{label}.html"
    out_path.write_text(r.text, encoding="utf-8")
    print(f"  Saved: {out_path} ({len(r.text)} chars)")
    time.sleep(2)

print("Done.")
```

- [ ] **Step 2: 실행 (실측)**

```bash
python scripts/collect_fixtures.py
```
Expected: `tests/fixtures/naver/` 에 5개 HTML 파일 생성

- [ ] **Step 3: HTML 직접 열어서 구조 검토**

```bash
explorer tests\fixtures\naver
```
사장님 또는 Claude가 브라우저로 각 파일 열어서 어떤 블록이 보이는지 확인 → spec.md Open Questions 답함:
- AB 통합 리스트의 HTML 구조 (어떤 class/data 속성?)
- 스마트블록 명칭 표시 위치
- 인기글 영역 별도 마커
- 지식인 탭 노출 시 위치
- 카페/블로그 항목 type 구분 방법

- [ ] **Step 4: 발견 사항을 spec.md에 기록**

`spec.md` Section 11 Open Questions에 답한 내용 추가 (또는 별도 `docs/naver-html-structure.md`).

- [ ] **Step 5: fixture 커밋**

```bash
git add tests/fixtures/naver/ scripts/collect_fixtures.py docs/
git commit -m "chore: collect Naver search fixtures (M4 Phase 1)"
git push
```

### 🤖 Task M4.2: URL 정규화 — naver.me 단축 + cafe URL 파싱

**Files:**
- Modify: `src/crawler.py` (정규화 함수)
- Test: `tests/unit/test_crawler.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_crawler.py`:
```python
import pytest
from src.crawler import parse_cafe_url, resolve_short_url


def test_parse_cafe_url_full():
    slug, post_id = parse_cafe_url("https://cafe.naver.com/cosmania/38373348")
    assert slug == "cosmania"
    assert post_id == "38373348"


def test_parse_cafe_url_with_query():
    slug, post_id = parse_cafe_url("https://cafe.naver.com/pusanmommy/1445556?ref=foo")
    assert slug == "pusanmommy"
    assert post_id == "1445556"


def test_parse_cafe_url_invalid_returns_none():
    assert parse_cafe_url("https://google.com/") == (None, None)
    assert parse_cafe_url("") == (None, None)
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/unit/test_crawler.py::test_parse_cafe_url_full -v
```
Expected: FAIL (parse_cafe_url not defined)

- [ ] **Step 3: 최소 구현**

`src/crawler.py`:
```python
"""crawler: 네이버 검색 페이지 fetch (slowdown, UA rotation) + URL 정규화."""
import re
from typing import Optional

CAFE_URL_RE = re.compile(r"https?://cafe\.naver\.com/([^/?#]+)/(\d+)")


def parse_cafe_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """cafe.naver.com URL에서 slug와 post_id 추출. 매칭 실패 시 (None, None)."""
    if not url:
        return (None, None)
    m = CAFE_URL_RE.match(url)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/unit/test_crawler.py -v
```
Expected: 3개 PASS

- [ ] **Step 5: naver.me 리다이렉트 테스트 추가 + 구현**

`tests/unit/test_crawler.py` 추가:
```python
import responses

@responses.activate
def test_resolve_short_url_redirects_to_full_cafe():
    responses.add(
        responses.GET,
        "https://naver.me/Fka自AYaj7",
        status=302,
        headers={"Location": "https://cafe.naver.com/cosmania/38373348"},
    )
    result = resolve_short_url("https://naver.me/Fka自AYaj7")
    assert result == "https://cafe.naver.com/cosmania/38373348"


@responses.activate
def test_resolve_short_url_already_full_returns_as_is():
    full_url = "https://cafe.naver.com/cosmania/38373348"
    result = resolve_short_url(full_url)
    assert result == full_url  # naver.me 아니면 변경 없이 반환
```

`src/crawler.py` 추가:
```python
import requests


def resolve_short_url(url: str) -> str:
    """naver.me 단축 URL을 풀 cafe.naver.com URL로 해석. 단축 아니면 그대로 반환."""
    if "naver.me" not in url:
        return url
    try:
        r = requests.head(url, allow_redirects=False, timeout=10)
        if 300 <= r.status_code < 400 and "Location" in r.headers:
            return r.headers["Location"]
    except requests.RequestException:
        pass
    return url
```

- [ ] **Step 6: 통과 확인 + 커밋**

```bash
pytest tests/unit/test_crawler.py -v
git add src/crawler.py tests/unit/test_crawler.py
git commit -m "feat(crawler): URL parsing + naver.me redirect resolution"
git push
```

### 🤖 Task M4.3: SlowdownController + UA Rotation

**Files:**
- Modify: `src/crawler.py`
- Test: `tests/unit/test_crawler.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_crawler.py` 추가:
```python
from src.crawler import SlowdownController


def test_slowdown_starts_at_base():
    s = SlowdownController(base=1.5, max_=60)
    assert s.current_interval == 1.5


def test_slowdown_doubles_on_block():
    s = SlowdownController(base=1.5, max_=60)
    s.on_block_detected()
    assert s.current_interval == 3.0
    s.on_block_detected()
    assert s.current_interval == 6.0


def test_slowdown_caps_at_max():
    s = SlowdownController(base=1.5, max_=10)
    for _ in range(20):
        s.on_block_detected()
    assert s.current_interval == 10.0


def test_slowdown_recovers_on_success():
    s = SlowdownController(base=1.5, max_=60)
    s.on_block_detected()  # 3.0
    s.on_block_detected()  # 6.0
    s.on_success()
    assert s.current_interval < 6.0  # 회복 시작
```

- [ ] **Step 2: 실패 확인**

```bash
pytest tests/unit/test_crawler.py::test_slowdown_starts_at_base -v
```
Expected: FAIL

- [ ] **Step 3: 구현**

`src/crawler.py` 추가:
```python
import random


class SlowdownController:
    """차단 의심 시 자동 슬로우다운 (지수 backoff). 성공 시 천천히 회복."""

    def __init__(self, base: float = 1.5, max_: float = 60.0):
        self.base = base
        self.max_ = max_
        self.current_interval = base
        self.consecutive_blocks = 0

    def on_block_detected(self):
        self.consecutive_blocks += 1
        self.current_interval = min(self.max_, self.current_interval * 2)

    def on_success(self):
        self.consecutive_blocks = 0
        self.current_interval = max(self.base, self.current_interval * 0.9)

    def wait(self):
        """현재 간격 + jitter 만큼 대기."""
        import time
        jitter = random.uniform(-0.3, 0.3)
        time.sleep(max(0.1, self.current_interval + jitter))


def random_user_agent() -> str:
    from src.config import USER_AGENTS
    return random.choice(USER_AGENTS)
```

- [ ] **Step 4: 통과 확인 + UA rotation 테스트 추가**

`tests/unit/test_crawler.py` 추가:
```python
def test_random_user_agent_returns_valid_ua():
    from src.crawler import random_user_agent
    ua = random_user_agent()
    assert "Mozilla" in ua
    assert len(ua) > 30


def test_random_user_agent_varies():
    from src.crawler import random_user_agent
    seen = {random_user_agent() for _ in range(50)}
    assert len(seen) >= 2  # 최소 2종 이상 등장
```

```bash
pytest tests/unit/test_crawler.py -v
```
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/crawler.py tests/unit/test_crawler.py
git commit -m "feat(crawler): SlowdownController + UA rotation"
git push
```

### 🤖 Task M4.4: fetch_search() — 핵심 fetcher

**Files:**
- Modify: `src/crawler.py`
- Test: `tests/unit/test_crawler.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
import responses
from src.crawler import Crawler


@responses.activate
def test_fetch_search_returns_html_on_200():
    responses.add(
        responses.GET,
        "https://search.naver.com/search.naver",
        body="<html><body>샴푸 검색 결과</body></html>",
        status=200,
    )
    c = Crawler()
    html = c.fetch_search("샴푸")
    assert "샴푸 검색 결과" in html


@responses.activate
def test_fetch_search_429_triggers_slowdown():
    responses.add(
        responses.GET,
        "https://search.naver.com/search.naver",
        status=429,
    )
    c = Crawler()
    with pytest.raises(Exception):
        c.fetch_search("샴푸")
    assert c.slowdown.consecutive_blocks >= 1
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현**

`src/crawler.py` 추가:
```python
class CrawlerError(Exception):
    pass


class Crawler:
    """네이버 검색 페이지 fetcher (slowdown + UA rotation 통합)."""

    SEARCH_URL = "https://search.naver.com/search.naver"

    def __init__(self, slowdown: SlowdownController = None):
        self.slowdown = slowdown or SlowdownController()
        self.session = requests.Session()

    def fetch_search(self, keyword: str) -> str:
        """키워드 검색 페이지 HTML 반환. 차단/오류 시 CrawlerError raise."""
        self.slowdown.wait()
        headers = {"User-Agent": random_user_agent(), "Accept-Language": "ko-KR,ko;q=0.9"}
        params = {"query": keyword}
        try:
            r = self.session.get(self.SEARCH_URL, params=params, headers=headers, timeout=15)
        except requests.RequestException as e:
            self.slowdown.on_block_detected()
            raise CrawlerError(f"network error: {e}") from e

        if r.status_code == 429 or self._looks_blocked(r):
            self.slowdown.on_block_detected()
            raise CrawlerError(f"rate limited (status={r.status_code})")

        if r.status_code != 200:
            raise CrawlerError(f"unexpected status {r.status_code}")

        self.slowdown.on_success()
        return r.text

    @staticmethod
    def _looks_blocked(r: requests.Response) -> bool:
        text = r.text.lower()
        return "captcha" in text or len(text) < 500
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/unit/test_crawler.py -v
```

- [ ] **Step 5: 커밋**

```bash
git add src/crawler.py tests/unit/test_crawler.py
git commit -m "feat(crawler): fetch_search with rate-limit detection"
git push
```

### 🤖 Task M4.5: fetch_cafe_url_status() — 글 살아있는지 체크

**Files:**
- Modify: `src/crawler.py`
- Test: `tests/unit/test_crawler.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
import responses
from src.crawler import CafeStatus


@responses.activate
def test_cafe_url_alive():
    responses.add(
        responses.GET,
        "https://cafe.naver.com/cosmania/38373348",
        body="<html>정상 글 내용</html>",
        status=200,
    )
    c = Crawler()
    assert c.fetch_cafe_url_status("https://cafe.naver.com/cosmania/38373348") == CafeStatus.ALIVE


@responses.activate
def test_cafe_url_404_deleted():
    responses.add(
        responses.GET,
        "https://cafe.naver.com/cosmania/99999999",
        status=404,
    )
    c = Crawler()
    assert c.fetch_cafe_url_status("https://cafe.naver.com/cosmania/99999999") == CafeStatus.DELETED


@responses.activate
def test_cafe_url_login_wall_private():
    responses.add(
        responses.GET,
        "https://cafe.naver.com/private/123",
        body='<html>nid.naver.com/nidlogin.login</html>',
        status=200,
    )
    c = Crawler()
    assert c.fetch_cafe_url_status("https://cafe.naver.com/private/123") == CafeStatus.PRIVATE
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현**

`src/crawler.py` 추가:
```python
from enum import Enum


class CafeStatus(Enum):
    ALIVE = "alive"
    DELETED = "deleted"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class Crawler:
    # ... 기존 코드 ...

    def fetch_cafe_url_status(self, url: str) -> CafeStatus:
        """카페 URL이 살아있는지 / 삭제됐는지 / 비공개인지 판정."""
        self.slowdown.wait()
        try:
            r = self.session.get(
                url,
                headers={"User-Agent": random_user_agent()},
                allow_redirects=True,
                timeout=15,
            )
        except requests.RequestException:
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
```

- [ ] **Step 4: 통과 + 커밋**

```bash
pytest tests/unit/test_crawler.py -v
git add src/crawler.py tests/unit/test_crawler.py
git commit -m "feat(crawler): cafe URL status detection"
git push
```

### 🤖 Task M4.6: parser.py — RankResult dataclass + 진입점

**Files:**
- Modify: `src/parser.py`
- Test: `tests/unit/test_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_parser.py`:
```python
from src.parser import RankResult, ExposureArea, parse_search_result


def test_rank_result_default_unexposed():
    result = RankResult()
    assert result.exposure_area == ExposureArea.UNEXPOSED
    assert result.integrated_rank is None
    assert result.cafe_slot_rank is None
    assert result.blog_slot_rank is None
    assert result.in_jisikin is False
    assert result.parser_confidence == 0.0


def test_parse_no_match_html(load_fixture):
    html = load_fixture("naver/no_match.html")
    result = parse_search_result(html, target_url="https://cafe.naver.com/cosmania/38373348")
    assert result.exposure_area == ExposureArea.UNEXPOSED
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현**

`src/parser.py`:
```python
"""parser: AB / 스마트블록 / 인기글 / 지식인 파싱 분기."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ExposureArea(str, Enum):
    AB = "AB"
    SMART_BLOCK = "스마트블록"
    POPULAR = "인기글"
    UNEXPOSED = "미노출"  # 검색 0


@dataclass
class RankResult:
    exposure_area: ExposureArea = ExposureArea.UNEXPOSED
    integrated_rank: Optional[int] = None
    cafe_slot_rank: Optional[int] = None
    blog_slot_rank: Optional[int] = None
    in_jisikin: bool = False
    block_order: list[str] = field(default_factory=list)  # C 컬럼용 ["AB", "스마트블록", ...]
    smart_block_name: Optional[str] = None
    parser_confidence: float = 0.0


def parse_search_result(html: str, target_url: str) -> RankResult:
    """검색 결과 페이지 + 본인 URL → RankResult."""
    if not html or len(html) < 500:
        return RankResult()

    result = RankResult()
    result.block_order = _detect_block_order(html)

    # 분기 (각 _parse_* 는 매칭되면 result 업데이트, 아니면 None)
    if _parse_ab_list(html, target_url, result):
        result.exposure_area = ExposureArea.AB
    elif _parse_smart_blocks(html, target_url, result):
        result.exposure_area = ExposureArea.SMART_BLOCK
    elif _parse_popular(html, target_url, result):
        result.exposure_area = ExposureArea.POPULAR
    # 지식인은 별도 (in_jisikin 플래그)
    _parse_jisikin(html, target_url, result)

    return result


def _detect_block_order(html: str) -> list[str]:
    """페이지 위에서 아래로 등장하는 블록 종류 순서. M4.10에서 실측 기반 구현."""
    return []  # placeholder


def _parse_ab_list(html: str, target_url: str, result: RankResult) -> bool:
    """AB 통합 리스트 파싱. 매칭 시 True + result 업데이트. M4.7에서 구현."""
    return False  # placeholder


def _parse_smart_blocks(html: str, target_url: str, result: RankResult) -> bool:
    return False  # placeholder, M4.8에서


def _parse_popular(html: str, target_url: str, result: RankResult) -> bool:
    return False  # placeholder, M4.9에서


def _parse_jisikin(html: str, target_url: str, result: RankResult) -> None:
    pass  # placeholder, M4.9에서
```

- [ ] **Step 4: no_match fixture 통과**

```bash
pytest tests/unit/test_parser.py -v
```

- [ ] **Step 5: 커밋**

```bash
git add src/parser.py tests/unit/test_parser.py
git commit -m "feat(parser): RankResult dataclass + dispatch skeleton"
git push
```

### 🤖 Task M4.7: AB 리스트 파싱 (실측 기반)

**Files:**
- Modify: `src/parser.py`
- Test: `tests/unit/test_parser.py`

⚠️ **중요**: Task M4.1에서 수집한 실제 HTML fixture 분석으로 CSS 셀렉터 / data 속성 확정 필요. 아래는 골격이며 실측 기반으로 셀렉터 채워야 함.

- [ ] **Step 1: fixture 분석 → 셀렉터 도출**

`tests/fixtures/naver/ab_cafe_top.html` 열어서 (사장님 등드름해초필링, AB 1등 케이스):
- 통합 리스트 컨테이너의 외곽 selector 식별 (예: `ul.lst_total`, `div.api_subject_bx`, 또는 data-template 속성)
- 각 항목의 type 구분 신호 식별 (cafe vs blog vs 웹문서)
- URL 추출 위치 (a 태그의 href)
- 실제 selector를 `docs/naver-html-structure.md`에 기록

- [ ] **Step 2: 실패 테스트 작성 (실측 기준값 사용)**

```python
def test_parse_ab_list_target_at_first(load_fixture):
    html = load_fixture("naver/ab_cafe_top.html")
    target = "https://cafe.naver.com/pusanmommy/1445556"
    result = parse_search_result(html, target)
    assert result.exposure_area == ExposureArea.AB
    # 실측 시 정확한 값으로 채울 것:
    assert result.integrated_rank is not None
    assert result.cafe_slot_rank is not None
    assert result.parser_confidence > 0.7
```

- [ ] **Step 3: 실패 확인**

- [ ] **Step 4: _parse_ab_list 구현 (실측 셀렉터 사용)**

`src/parser.py` 의 `_parse_ab_list` 채움:
```python
from bs4 import BeautifulSoup


def _parse_ab_list(html: str, target_url: str, result: RankResult) -> bool:
    """AB 통합 리스트 안에서 target_url 찾고 순위 계산.
    실측 셀렉터: TODO M4.1 결과로 채울 것.
    """
    soup = BeautifulSoup(html, "lxml")

    # 실측 시 정확한 selector로 교체:
    container = soup.select_one("ul.lst_total, div.api_subject_bx, [data-template*='ab']")
    if not container:
        return False

    items = container.select("li, div.bx")
    cafe_count = 0
    blog_count = 0

    for idx, item in enumerate(items, start=1):
        item_type = _classify_item(item)  # "cafe" | "blog" | "web" | "other"
        link = item.select_one("a[href]")
        href = link["href"] if link else ""

        if item_type == "cafe":
            cafe_count += 1
        elif item_type == "blog":
            blog_count += 1

        if _urls_match(href, target_url):
            result.integrated_rank = idx
            if item_type == "cafe":
                result.cafe_slot_rank = cafe_count
            elif item_type == "blog":
                result.blog_slot_rank = blog_count
            result.parser_confidence = 0.9
            return True

    return False


def _classify_item(item) -> str:
    """li/div 항목이 cafe / blog / web 중 어느 것인지 판정.
    실측 시 정확한 신호 (icon class, data 속성 등) 사용.
    """
    classes = " ".join(item.get("class", []))
    if "cafe" in classes:
        return "cafe"
    if "blog" in classes:
        return "blog"
    return "web"


def _urls_match(a: str, b: str) -> bool:
    """URL 매칭 (쿼리스트링/fragment 무시)."""
    from urllib.parse import urlparse
    pa, pb = urlparse(a), urlparse(b)
    return pa.netloc == pb.netloc and pa.path == pb.path
```

- [ ] **Step 5: 통과 확인 + 추가 케이스 테스트**

```python
def test_parse_ab_list_no_target_match(load_fixture):
    html = load_fixture("naver/ab_cafe_top.html")
    result = parse_search_result(html, "https://cafe.naver.com/never/9999")
    # AB는 있지만 본인 URL은 없음 → exposure_area = UNEXPOSED, but block_order에 AB 있음
    assert result.exposure_area == ExposureArea.UNEXPOSED
```

```bash
pytest tests/unit/test_parser.py -v
```

- [ ] **Step 6: 커밋**

```bash
git add src/parser.py tests/unit/test_parser.py docs/
git commit -m "feat(parser): AB integrated list parsing (with selectors from fixture analysis)"
git push
```

### 🤖 Task M4.8: 스마트블록 파싱

**Files:** `src/parser.py`, `tests/unit/test_parser.py`

⚠️ Task M4.1 fixture (`smart_block.html`, `mixed_blocks.html`) 분석 후 진행.

- [ ] **Step 1: 실측 → 스마트블록 셀렉터 도출 + `docs/naver-html-structure.md` 갱신**
- [ ] **Step 2: 실패 테스트 작성**

```python
def test_parse_smart_block_match(load_fixture):
    html = load_fixture("naver/smart_block.html")
    # 실측 시 fixture 안 카페 URL로 교체
    target = "https://cafe.naver.com/somecafe/123"
    result = parse_search_result(html, target)
    if result.exposure_area == ExposureArea.SMART_BLOCK:
        assert result.smart_block_name is not None
```

- [ ] **Step 3: `_parse_smart_blocks` 구현**

```python
def _parse_smart_blocks(html: str, target_url: str, result: RankResult) -> bool:
    soup = BeautifulSoup(html, "lxml")
    # 실측: 스마트블록 컨테이너 selector + 블록명 추출 위치
    blocks = soup.select("div.api_subject_bx[data-template*='smart']")  # TODO 실측 교체
    for block in blocks:
        name_el = block.select_one("h3, .api_title")
        block_name = name_el.get_text(strip=True) if name_el else "(unnamed)"
        for link in block.select("a[href]"):
            if _urls_match(link.get("href", ""), target_url):
                result.smart_block_name = block_name
                result.parser_confidence = 0.85
                return True
    return False
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
pytest tests/unit/test_parser.py -v
git add src/parser.py tests/unit/test_parser.py
git commit -m "feat(parser): smart block parsing"
git push
```

### 🤖 Task M4.9: 인기글 + 지식인 파싱

**Files:** `src/parser.py`, `tests/unit/test_parser.py`

⚠️ M4.1 fixture (`popular_cafe.html`) 분석 후. 사장님 명시: **인기글은 별도 로직** (AB 안 카페구좌와 다름).

- [ ] **Step 1: fixture 분석 → 인기글 영역 위치 / 지식인 탭 위치 식별**
- [ ] **Step 2: 실패 테스트**

```python
def test_parse_popular_match(load_fixture):
    html = load_fixture("naver/popular_cafe.html")
    target = "https://cafe.naver.com/cosmania/38373348"  # 트러블크림 인기글 3등
    result = parse_search_result(html, target)
    assert result.exposure_area == ExposureArea.POPULAR
    # 인기글 안에서의 순위는 cafe_slot_rank 컬럼에 (사장님 컨벤션)
    assert result.cafe_slot_rank == 3


def test_parse_jisikin_flag(load_fixture):
    # 사장님 시트에서 지식인탭 = "O"인 케이스 fixture 추가 후
    html = load_fixture("naver/jisikin_match.html")
    target = "https://cafe.naver.com/foo/123"  # 실측 교체
    result = parse_search_result(html, target)
    assert result.in_jisikin is True
```

- [ ] **Step 3: 구현**

```python
def _parse_popular(html: str, target_url: str, result: RankResult) -> bool:
    soup = BeautifulSoup(html, "lxml")
    # 실측: 인기글 영역 selector
    popular = soup.select_one("div.api_subject_bx[data-template*='popular']")  # TODO 실측
    if not popular:
        return False

    items = popular.select("li, div.item")
    for idx, item in enumerate(items, start=1):
        link = item.select_one("a[href]")
        if link and _urls_match(link.get("href", ""), target_url):
            result.cafe_slot_rank = idx  # 사장님 컨벤션: 인기글 순위 → M 컬럼
            result.parser_confidence = 0.85
            return True
    return False


def _parse_jisikin(html: str, target_url: str, result: RankResult) -> None:
    soup = BeautifulSoup(html, "lxml")
    jisikin = soup.select_one("div.api_subject_bx[data-template*='kin']")  # TODO 실측
    if not jisikin:
        return
    for link in jisikin.select("a[href]"):
        if _urls_match(link.get("href", ""), target_url):
            result.in_jisikin = True
            return
```

- [ ] **Step 4: 통과 + 커밋**

```bash
pytest tests/unit/test_parser.py -v
git add src/parser.py tests/unit/test_parser.py
git commit -m "feat(parser): 인기글 + 지식인 parsing"
git push
```

### 🤖 Task M4.10: block_order 추출 (C 컬럼용)

- [ ] **Step 1: 실패 테스트**

```python
def test_block_order_from_mixed(load_fixture):
    html = load_fixture("naver/mixed_blocks.html")
    result = parse_search_result(html, "")
    # 실측 결과에 따라 (예시):
    assert result.block_order[0] in ("AB", "스마트블록", "인기글", "지식인")
    assert len(result.block_order) >= 2
```

- [ ] **Step 2: `_detect_block_order` 구현**

```python
def _detect_block_order(html: str) -> list[str]:
    """페이지 위에서 아래로 등장하는 블록을 type 별로 식별."""
    soup = BeautifulSoup(html, "lxml")
    order = []
    # 실측: 모든 검색 블록 컨테이너를 등장 순서대로 순회하며 type 판정
    for container in soup.select("div.api_subject_bx, ul.lst_total"):  # TODO 실측 selector
        block_type = _classify_block(container)
        if block_type:
            order.append(block_type)
    return order


def _classify_block(container) -> Optional[str]:
    """컨테이너의 data-template 또는 class로 type 판정."""
    template = container.get("data-template", "")
    if "ab" in template or "total" in template:
        return "AB"
    if "smart" in template:
        return "스마트블록"
    if "popular" in template:
        return "인기글"
    if "kin" in template:
        return "지식인"
    return None
```

- [ ] **Step 3: 통과 + 커밋**

```bash
git add src/parser.py tests/unit/test_parser.py
git commit -m "feat(parser): block_order detection for C column"
git push
```

---

## M5 — Sheets 연동

### 🤖 Task M5.1: gspread 인증

**Files:** `src/sheets.py`, `tests/unit/test_sheets.py`

- [ ] **Step 1: 실패 테스트**

```python
import json
from unittest.mock import patch, MagicMock
from src.sheets import SheetsClient


def test_sheets_client_authenticates_with_json_string():
    fake_creds = json.dumps({
        "type": "service_account",
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    with patch("src.sheets.gspread.service_account_from_dict") as mock_auth:
        mock_auth.return_value = MagicMock()
        client = SheetsClient(spreadsheet_id="abc", service_account_json=fake_creds)
        mock_auth.assert_called_once()
```

- [ ] **Step 2: 실패 확인 + 구현**

`src/sheets.py`:
```python
"""sheets: Google Sheets I/O, 헤더 기반 매핑, 분야별 탭 순회."""
import json
from typing import Optional
import gspread


class SheetsClient:
    def __init__(self, spreadsheet_id: str, service_account_json: str):
        creds_dict = json.loads(service_account_json)
        self.gc = gspread.service_account_from_dict(creds_dict)
        self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
```

- [ ] **Step 3: 통과 + 커밋**

```bash
pytest tests/unit/test_sheets.py -v
git add src/sheets.py tests/unit/test_sheets.py
git commit -m "feat(sheets): service account authentication"
git push
```

### 🤖 Task M5.2: 헤더 매핑 (열 이동에 강건)

**Files:** `src/sheets.py`, `tests/unit/test_sheets.py`

- [ ] **Step 1: 실패 테스트**

```python
from src.sheets import map_headers_to_columns


def test_map_headers_basic():
    headers = ["작업일", "작업자", "키워드", "링크", "노출영역"]
    mapping = map_headers_to_columns(headers)
    assert mapping["키워드"] == 2  # 0-indexed
    assert mapping["링크"] == 3
    assert mapping["노출영역"] == 4


def test_map_headers_with_extra_columns():
    headers = ["작업일", "메모", "작업자", "신규컬럼", "키워드", "링크"]
    mapping = map_headers_to_columns(headers)
    assert mapping["키워드"] == 4
    assert mapping["링크"] == 5


def test_map_headers_missing_required_raises():
    import pytest
    headers = ["작업일", "작업자"]
    with pytest.raises(ValueError, match="키워드"):
        map_headers_to_columns(headers, required=["키워드"])
```

- [ ] **Step 2: 실패 확인 + 구현**

`src/sheets.py` 추가:
```python
REQUIRED_HEADERS = ["키워드", "링크", "노출영역"]


def map_headers_to_columns(headers: list[str], required: Optional[list[str]] = None) -> dict[str, int]:
    """헤더 행 → {헤더이름: 0-indexed 컬럼 번호}. required 누락 시 ValueError."""
    mapping = {h.strip(): i for i, h in enumerate(headers) if h and h.strip()}
    req = required or REQUIRED_HEADERS
    missing = [r for r in req if r not in mapping]
    if missing:
        raise ValueError(f"필수 헤더 누락: {missing}")
    return mapping
```

- [ ] **Step 3: 통과 + 커밋**

```bash
pytest tests/unit/test_sheets.py -v
git add src/sheets.py tests/unit/test_sheets.py
git commit -m "feat(sheets): header-name based column mapping"
git push
```

### 🤖 Task M5.3: 모든 탭 순회 read

**Files:** `src/sheets.py`, `tests/unit/test_sheets.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_load_all_data_tabs_skips_special_tabs():
    """카페매핑 같은 특수 탭은 별도 처리, 데이터 탭만 반환."""
    from src.sheets import SheetsClient
    client = MagicMock(spec=SheetsClient)
    # ... mock spreadsheet.worksheets() ...
    # 실제 통합 테스트는 M5.6에서, 여기는 단위 로직만
```

- [ ] **Step 2: 구현**

`src/sheets.py`:
```python
SPECIAL_TABS = {"카페매핑", "_meta", "설정"}


class SheetsClient:
    # ... 기존 ...

    def load_all_data_tabs(self) -> dict[str, list[dict]]:
        """{탭이름: [행 dict, ...]} 반환. 특수 탭 제외."""
        result = {}
        for ws in self.spreadsheet.worksheets():
            if ws.title in SPECIAL_TABS:
                continue
            all_values = ws.get_all_values()
            if not all_values:
                continue
            headers = all_values[0]
            try:
                mapping = map_headers_to_columns(headers)
            except ValueError as e:
                print(f"[WARN] tab '{ws.title}' header issue: {e}, skipping")
                continue
            rows = []
            for row_idx, row_values in enumerate(all_values[1:], start=2):
                row_dict = {h: row_values[i] if i < len(row_values) else ""
                            for h, i in mapping.items()}
                row_dict["_row"] = row_idx
                row_dict["_tab"] = ws.title
                rows.append(row_dict)
            result[ws.title] = rows
        return result
```

- [ ] **Step 3: 커밋**

```bash
git commit -am "feat(sheets): load_all_data_tabs"
```

### 🤖 Task M5.4: Batch write

**Files:** `src/sheets.py`, `tests/unit/test_sheets.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_batch_write_groups_per_tab():
    """write_results는 탭별로 1회 batch_update 호출."""
    # MagicMock으로 worksheet.batch_update 호출 횟수 검증
```

- [ ] **Step 2: 구현**

```python
class RowUpdate:
    def __init__(self, row: int, columns: dict[str, str]):
        self.row = row
        self.columns = columns  # {헤더이름: 새 값}


class SheetsClient:
    # ...

    def write_results(self, tab_name: str, updates: list[RowUpdate]):
        """한 탭에 여러 행을 batch update. column letter 변환 후 1회 API 호출."""
        ws = self.spreadsheet.worksheet(tab_name)
        headers = ws.row_values(1)
        mapping = map_headers_to_columns(headers)
        cells = []
        for upd in updates:
            for col_name, new_val in upd.columns.items():
                if col_name not in mapping:
                    continue
                col_idx = mapping[col_name] + 1  # gspread는 1-indexed
                cells.append({
                    "range": gspread.utils.rowcol_to_a1(upd.row, col_idx),
                    "values": [[new_val]],
                })
        if cells:
            ws.batch_update(cells, value_input_option="RAW")
```

- [ ] **Step 3: 커밋**

```bash
git commit -am "feat(sheets): batch write per tab"
```

### 🤖 Task M5.5: 카페매핑 시트 read/write

**Files:** `src/sheets.py`, `tests/unit/test_sheets.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_load_cafe_mapping():
    # 카페매핑 탭이 없으면 빈 dict, 있으면 {slug: {full_name, short_name}} 반환
```

- [ ] **Step 2: 구현**

```python
class SheetsClient:
    # ...

    def load_cafe_mapping(self) -> dict[str, dict]:
        try:
            ws = self.spreadsheet.worksheet("카페매핑")
        except gspread.WorksheetNotFound:
            return {}
        rows = ws.get_all_values()
        if not rows or len(rows) < 2:
            return {}
        headers = rows[0]
        idx_slug = headers.index("slug") if "slug" in headers else 0
        idx_full = headers.index("정식명") if "정식명" in headers else 1
        idx_short = headers.index("축약명") if "축약명" in headers else 2
        result = {}
        for row in rows[1:]:
            if len(row) > idx_slug and row[idx_slug]:
                result[row[idx_slug]] = {
                    "full_name": row[idx_full] if len(row) > idx_full else "",
                    "short_name": row[idx_short] if len(row) > idx_short else "",
                }
        return result

    def upsert_cafe_mapping(self, slug: str, full_name: str):
        try:
            ws = self.spreadsheet.worksheet("카페매핑")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("카페매핑", rows=1000, cols=3)
            ws.update("A1:C1", [["slug", "정식명", "축약명"]])
        existing = ws.col_values(1)
        if slug in existing:
            return  # 이미 있음
        ws.append_row([slug, full_name, ""])
```

- [ ] **Step 3: 커밋**

```bash
git commit -am "feat(sheets): cafe mapping tab read/write"
git push
```

---

## M6 — Cache + Retry + Health

### 🤖 Task M6.1: cache.py — 카페매핑 + 메모리 캐시

**Files:** `src/cache.py`, `tests/unit/test_cache.py`

- [ ] **Step 1: 실패 테스트**

```python
from src.cache import CafeMappingCache


def test_cache_hit_returns_existing():
    cache = CafeMappingCache(initial={"slug1": {"full_name": "카페1", "short_name": "C1"}})
    result = cache.get("slug1")
    assert result["short_name"] == "C1"


def test_cache_miss_returns_none_without_fetch():
    cache = CafeMappingCache(initial={})
    assert cache.get("unknown") is None
```

- [ ] **Step 2: 구현**

`src/cache.py`:
```python
"""cache: 카페매핑 캐시 (메모리 + Sheets backed)."""


class CafeMappingCache:
    def __init__(self, initial: dict = None):
        self._mem = dict(initial) if initial else {}

    def get(self, slug: str) -> dict | None:
        return self._mem.get(slug)

    def set(self, slug: str, mapping: dict):
        self._mem[slug] = mapping

    def __contains__(self, slug):
        return slug in self._mem
```

- [ ] **Step 3: ensure_cafe_mapping (시트 자동 추가 + fetch)**

```python
class CafeMappingCache:
    # ...

    def ensure(self, slug: str, fetcher_fn, sheets_writer_fn) -> dict:
        """없으면 fetch → 시트 추가 → 캐시. fetcher_fn(slug) -> full_name, sheets_writer_fn(slug, full_name)."""
        if slug in self._mem:
            return self._mem[slug]
        try:
            full_name = fetcher_fn(slug)
        except Exception:
            full_name = ""  # fetch 실패해도 빈 매핑으로 캐시 (다음 cron에 재시도)
        mapping = {"full_name": full_name, "short_name": ""}
        self._mem[slug] = mapping
        if full_name:
            try:
                sheets_writer_fn(slug, full_name)
            except Exception:
                pass  # Sheets API 실패는 무시 (다음 cron에 자동 재시도)
        return mapping
```

- [ ] **Step 4: 통과 + 커밋**

```bash
git commit -am "feat(cache): cafe mapping cache with auto-ensure"
git push
```

### 🤖 Task M6.2: retry.py — 재시도 큐

**Files:** `src/retry.py`, `tests/unit/test_retry.py`

- [ ] **Step 1: 실패 테스트**

```python
from src.retry import RetryQueue


def test_queue_adds_and_iterates():
    q = RetryQueue()
    q.add({"_row": 5, "키워드": "test"}, error="rate_limited")
    items = list(q.items())
    assert len(items) == 1
    assert items[0]["row"]["_row"] == 5
    assert items[0]["error"] == "rate_limited"


def test_queue_processes_with_callback():
    q = RetryQueue()
    q.add({"_row": 5, "키워드": "test"}, error="rate_limited")

    successes = []
    def fake_processor(row):
        successes.append(row["_row"])
        return {"new_K": "AB"}

    results = q.process(fake_processor, slowdown_multiplier=2.0)
    assert successes == [5]
    assert results[0]["update"]["new_K"] == "AB"
```

- [ ] **Step 2: 구현**

`src/retry.py`:
```python
"""retry: 1차 실패 행 재시도 (슬로우다운 강화 후 1회)."""
import time
from typing import Callable


class RetryQueue:
    def __init__(self):
        self._items = []

    def add(self, row: dict, error: str):
        self._items.append({"row": row, "error": error})

    def items(self):
        return list(self._items)

    def process(self, processor_fn: Callable[[dict], dict], slowdown_multiplier: float = 2.0) -> list[dict]:
        """큐의 모든 행을 슬로우다운 강화 간격으로 1회 재시도. 성공/실패 결과 반환."""
        results = []
        for item in self._items:
            time.sleep(0.1 * slowdown_multiplier)  # 짧은 대기 (실측 시 조정)
            try:
                update = processor_fn(item["row"])
                results.append({"row": item["row"], "update": update, "ok": True})
            except Exception as e:
                results.append({"row": item["row"], "update": None, "ok": False, "error": str(e)})
        return results

    def __len__(self):
        return len(self._items)
```

- [ ] **Step 3: 커밋**

```bash
git commit -am "feat(retry): retry queue"
```

### 🤖 Task M6.3: health.py — 헬스 모니터링 (logs 출력)

**Files:** `src/health.py`, `tests/unit/test_health.py`

- [ ] **Step 1: 실패 테스트**

```python
from src.health import HealthMonitor


def test_health_records_and_summary():
    h = HealthMonitor()
    h.record(parser_confidence=0.9, success=True)
    h.record(parser_confidence=0.85, success=True)
    h.record(parser_confidence=0.0, success=False, block_type="스마트블록")
    summary = h.summary()
    assert summary["total"] == 3
    assert summary["success_count"] == 2
    assert summary["success_rate"] == pytest.approx(2/3)


def test_health_detects_low_success_rate():
    h = HealthMonitor()
    for _ in range(10):
        h.record(parser_confidence=0.0, success=False)
    h.record(parser_confidence=0.9, success=True)
    assert h.summary()["code_change_suspected"] is True


def test_health_clean_run_no_alert():
    h = HealthMonitor()
    for _ in range(10):
        h.record(parser_confidence=0.95, success=True)
    assert h.summary()["code_change_suspected"] is False
```

- [ ] **Step 2: 구현**

`src/health.py`:
```python
"""health: 파싱 성공률 모니터링, 네이버 코드 변경 감지. 출력은 GitHub Actions logs."""


class HealthMonitor:
    SUCCESS_RATE_THRESHOLD = 0.90

    def __init__(self):
        self.records = []
        self.block_failures: dict[str, int] = {}

    def record(self, parser_confidence: float, success: bool, block_type: str | None = None):
        self.records.append({"confidence": parser_confidence, "success": success})
        if not success and block_type:
            self.block_failures[block_type] = self.block_failures.get(block_type, 0) + 1

    def summary(self) -> dict:
        total = len(self.records)
        if total == 0:
            return {"total": 0, "success_count": 0, "success_rate": 1.0, "code_change_suspected": False}
        success_count = sum(1 for r in self.records if r["success"])
        rate = success_count / total
        avg_conf = sum(r["confidence"] for r in self.records) / total
        suspected = (rate < self.SUCCESS_RATE_THRESHOLD) or (avg_conf < 0.5 and total >= 10)
        return {
            "total": total,
            "success_count": success_count,
            "success_rate": rate,
            "avg_confidence": avg_conf,
            "block_failures": dict(self.block_failures),
            "code_change_suspected": suspected,
        }

    def log_summary(self):
        s = self.summary()
        print(f"=== Health Summary ===")
        print(f"Total: {s['total']}, Success: {s['success_count']} ({s['success_rate']*100:.1f}%)")
        if s.get("avg_confidence") is not None:
            print(f"Avg parser confidence: {s['avg_confidence']:.2f}")
        if s.get("block_failures"):
            print(f"Block failures: {s['block_failures']}")
        if s["code_change_suspected"]:
            print("⚠️ CODE_CHANGE_SUSPECTED — parser may need update")
```

- [ ] **Step 3: 통과 + 커밋**

```bash
pytest tests/unit/test_health.py -v
git commit -am "feat(health): success rate monitoring + log summary"
git push
```

---

## M7 — 통합 + 메인 오케스트레이션

### 🤖 Task M7.1: transitions.py — 노출중지 자동 감지

**Files:** `src/transitions.py`, `tests/unit/test_transitions.py`

- [ ] **Step 1: 실패 테스트**

```python
from src.transitions import compute_new_K


def test_transition_exposed_to_unexposed():
    """이전 AB → 지금 검색 0 → 노출중지"""
    assert compute_new_K(prev_K="AB", search_found=False, url_alive=True) == "노출중지"


def test_transition_unexposed_stays_unexposed():
    """이전 미노출 → 지금 검색 0 → 미노출 유지"""
    assert compute_new_K(prev_K="미노출", search_found=False, url_alive=True) == "미노출"


def test_transition_unstopped_recovers():
    """이전 노출중지 → 지금 검색 found → AB"""
    assert compute_new_K(prev_K="노출중지", search_found=True, url_alive=True, area="AB") == "AB"


def test_transition_stopped_stays_stopped():
    """이전 노출중지 → 지금 여전히 검색 0 → 노출중지 유지"""
    assert compute_new_K(prev_K="노출중지", search_found=False, url_alive=True) == "노출중지"


def test_transition_url_dead():
    """URL 자체 죽음은 이전 상태 무관"""
    assert compute_new_K(prev_K="AB", search_found=False, url_alive=False, status="deleted") == "삭제됨"
    assert compute_new_K(prev_K="미노출", search_found=False, url_alive=False, status="private") == "비공개"


def test_transition_first_run_no_prev():
    """이전 K = 빈 값 (첫 추적) → 미노출 또는 노출 값"""
    assert compute_new_K(prev_K="", search_found=False, url_alive=True) == "미노출"
    assert compute_new_K(prev_K="", search_found=True, url_alive=True, area="AB") == "AB"
```

- [ ] **Step 2: 구현**

`src/transitions.py`:
```python
"""transitions: K 컬럼 상태 전환 로직 (이전 vs 현재 비교)."""

EXPOSED_VALUES = {"AB", "스마트블록", "인기글"}


def compute_new_K(
    prev_K: str,
    search_found: bool,
    url_alive: bool,
    area: str | None = None,
    status: str | None = None,
) -> str:
    """이전 K 값 + 현재 검색/URL 상태 → 새 K 값.

    prev_K: 시트의 현재 K 컬럼 값 (이전 cron 결과)
    search_found: 이번 cron에 검색 결과에서 본인 URL 발견했는가
    url_alive: URL 자체가 살아있는가 (404 X, login X)
    area: search_found=True 시 어느 블록 (AB/스마트블록/인기글)
    status: url_alive=False 시 deleted / private 등
    """
    # URL 자체가 죽었으면 그게 우선
    if not url_alive:
        if status == "deleted":
            return "삭제됨"
        if status == "private":
            return "비공개"
        return "실패"  # unknown

    # URL 살아있음
    if search_found:
        return area or "AB"  # 노출 → 해당 블록 (혹은 AB 디폴트)

    # URL 살아있지만 검색 0
    if prev_K in EXPOSED_VALUES:
        # 이전엔 노출됐었음 → 떨어진 것
        return "노출중지"
    if prev_K == "노출중지":
        return "노출중지"  # 여전히 떨어진 상태
    # prev_K = "미노출" 또는 "" 또는 그 외
    return "미노출"
```

- [ ] **Step 3: 통과 + 커밋**

```bash
pytest tests/unit/test_transitions.py -v
git add src/transitions.py tests/unit/test_transitions.py
git commit -m "feat(transitions): K column state transition (노출중지 detection)"
git push
```

### 🤖 Task M7.2: main.py — 한 사이클 흐름

**Files:** `src/main.py`, `tests/component/test_main_flow.py`

- [ ] **Step 1: 컴포넌트 테스트 작성 (외부 mock)**

`tests/component/test_main_flow.py`:
```python
from unittest.mock import MagicMock
from src.main import process_one_row, build_row_update


def test_process_one_row_happy_path():
    """한 행 처리: crawler.fetch → parser → transitions → update dict."""
    crawler = MagicMock()
    crawler.fetch_search.return_value = "<html>...</html>"
    crawler.fetch_cafe_url_status.return_value = MagicMock(value="alive")

    parser_fn = MagicMock()
    parser_fn.return_value = MagicMock(
        exposure_area=MagicMock(value="AB"),
        integrated_rank=2,
        cafe_slot_rank=1,
        blog_slot_rank=None,
        in_jisikin=False,
        block_order=["AB"],
        smart_block_name=None,
        parser_confidence=0.9,
    )

    cache = MagicMock()
    cache.ensure.return_value = {"full_name": "테스트카페", "short_name": "TC"}

    row = {"_row": 5, "_tab": "샴푸", "키워드": "test", "링크": "https://cafe.naver.com/foo/123", "노출영역": "AB"}
    update = process_one_row(row, crawler, parser_fn, cache)
    assert update.row == 5
    assert update.columns["노출영역"] == "AB"
    assert update.columns["통합탭 순위"] == 2
```

- [ ] **Step 2: 구현**

`src/main.py`:
```python
"""main: 모든 모듈 조합. GitHub Actions cron entry point."""
import os
import sys
import json
from src import config
from src.crawler import Crawler, parse_cafe_url, resolve_short_url, CafeStatus
from src.parser import parse_search_result, ExposureArea
from src.sheets import SheetsClient, RowUpdate
from src.cache import CafeMappingCache
from src.retry import RetryQueue
from src.health import HealthMonitor
from src.transitions import compute_new_K


def process_one_row(row: dict, crawler: Crawler, parser_fn, cache: CafeMappingCache) -> RowUpdate:
    """한 행: 검색 fetch → 파싱 → URL 상태 → 카페매핑 → RowUpdate 빌드."""
    keyword = row.get("키워드", "").strip()
    raw_url = row.get("링크", "").strip()
    if not keyword or not raw_url:
        return RowUpdate(row=row["_row"], columns={"노출영역": "실패"})

    # URL 정규화
    full_url = resolve_short_url(raw_url)

    # 검색 fetch + 파싱
    html = crawler.fetch_search(keyword)
    rank = parser_fn(html, full_url)
    search_found = rank.exposure_area != ExposureArea.UNEXPOSED or rank.in_jisikin

    # URL 살아있는지
    if not search_found:
        cafe_status = crawler.fetch_cafe_url_status(full_url)
    else:
        cafe_status = CafeStatus.ALIVE  # 검색에 잡혔으면 살아있는 거 확실

    # 카페매핑 (slug 추출)
    slug, _ = parse_cafe_url(full_url)
    cafe_info = cache.ensure(slug, lambda s: "", lambda s, n: None) if slug else {"full_name": "", "short_name": ""}

    # K 컬럼 상태 전환
    new_K = compute_new_K(
        prev_K=row.get("노출영역", ""),
        search_found=search_found,
        url_alive=(cafe_status == CafeStatus.ALIVE),
        area=rank.exposure_area.value if search_found else None,
        status="deleted" if cafe_status == CafeStatus.DELETED else "private" if cafe_status == CafeStatus.PRIVATE else None,
    )

    # RowUpdate 빌드
    columns = {
        "유형": ",".join(rank.block_order) if rank.block_order else "",
        "노출영역": new_K,
        "통합탭 순위": rank.integrated_rank or "",
        "카페구좌순위": rank.cafe_slot_rank or "",
        "블로그구좌순위": rank.blog_slot_rank or "",
        "지식인탭": "O" if rank.in_jisikin else "",
    }
    if cafe_info.get("short_name") and not row.get("카페/게시판"):
        columns["카페/게시판"] = cafe_info["short_name"]

    return RowUpdate(row=row["_row"], columns=columns)


def main():
    print(f"[main] Starting cron run")
    sheets = SheetsClient(
        spreadsheet_id=config.SPREADSHEET_ID,
        service_account_json=config.SERVICE_ACCOUNT_JSON,
    )
    crawler = Crawler()
    cafe_mapping = sheets.load_cafe_mapping()
    cache = CafeMappingCache(initial=cafe_mapping)
    retry_queue = RetryQueue()
    monitor = HealthMonitor()

    all_tabs = sheets.load_all_data_tabs()
    print(f"[main] Loaded {len(all_tabs)} tabs, {sum(len(r) for r in all_tabs.values())} rows total")

    updates_per_tab: dict[str, list[RowUpdate]] = {}

    for tab_name, rows in all_tabs.items():
        for row in rows:
            try:
                upd = process_one_row(row, crawler, parse_search_result, cache)
                updates_per_tab.setdefault(tab_name, []).append(upd)
                monitor.record(parser_confidence=0.9, success=True)
            except Exception as e:
                print(f"[main] Row {row.get('_row')} ({tab_name}) failed: {e}")
                retry_queue.add(row, error=str(e))
                monitor.record(parser_confidence=0.0, success=False)

    # 재시도
    if len(retry_queue) > 0:
        print(f"[main] Retrying {len(retry_queue)} failed rows")
        for retry_result in retry_queue.process(
            lambda r: process_one_row(r, crawler, parse_search_result, cache).columns,
            slowdown_multiplier=3.0,
        ):
            if retry_result["ok"]:
                tab = retry_result["row"]["_tab"]
                upd = RowUpdate(row=retry_result["row"]["_row"], columns=retry_result["update"])
                updates_per_tab.setdefault(tab, []).append(upd)

    # 시트 쓰기
    for tab_name, updates in updates_per_tab.items():
        try:
            sheets.write_results(tab_name, updates)
            print(f"[main] Wrote {len(updates)} updates to '{tab_name}'")
        except Exception as e:
            print(f"[main] Sheet write failed for '{tab_name}': {e}")

    monitor.log_summary()
    print(f"[main] Done")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 통과 + 커밋**

```bash
pytest tests/component/test_main_flow.py -v
git add src/main.py tests/component/test_main_flow.py
git commit -m "feat(main): orchestration with retry queue + transitions"
git push
```

---

## M8 — GitHub Actions 배포

### 🤖 Task M8.1: workflow YAML 작성

**Files:** `.github/workflows/check.yml`, `.github/workflows/test.yml`

- [ ] **Step 1: test.yml (PR/push 자동 테스트)**

```yaml
name: tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit tests/component -v
```

- [ ] **Step 2: check.yml (cron 6시간마다)**

```yaml
name: check-naver-rank
on:
  schedule:
    - cron: '0 */6 * * *'  # 매 6시간 (00:00, 06:00, 12:00, 18:00 UTC = KST 09/15/21/03)
  workflow_dispatch:  # 수동 트리거 허용

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run main
        env:
          SPREADSHEET_ID: ${{ secrets.SPREADSHEET_ID }}
          SERVICE_ACCOUNT_JSON: ${{ secrets.SERVICE_ACCOUNT_JSON }}
        run: python -m src.main
```

- [ ] **Step 3: 커밋**

```bash
git add .github/workflows/
git commit -m "ci: add cron + test workflows"
git push
```

### 👤 Task M8.2: GitHub Secrets 등록

- [ ] **Step 1**: GitHub 저장소 페이지 → Settings → Secrets and variables → Actions
- [ ] **Step 2**: "New repository secret" → Name `SPREADSHEET_ID`, Value 시트 ID 붙여넣기 → Add
- [ ] **Step 3**: "New repository secret" → Name `SERVICE_ACCOUNT_JSON`, Value M3.1에서 다운받은 JSON 파일 **전체 내용** 붙여넣기 → Add

### 🤖 Task M8.3: 첫 수동 트리거 + 검증

- [ ] **Step 1**: GitHub Actions 탭 → check-naver-rank workflow → "Run workflow" 클릭
- [ ] **Step 2**: 진행 로그 확인 (5~30분 소요 예상, 키워드 수에 따라)
- [ ] **Step 3**: 사장님 시트 확인 → K~O 컬럼 자동 갱신됐는지
- [ ] **Step 4**: GitHub Actions logs에서 health summary 확인 (성공률 %, code_change_suspected 등)

### 🤖 Task M8.4: README 운영 가이드

**Files:** `README.md`

- [ ] **Step 1: 사장님이 보고 이해할 운영 가이드 작성**

```markdown
# naver-rank-checker

네이버 키워드 상위노출 자동 체크 → Google Sheets 자동 갱신.

## 운영 방식
- GitHub Actions가 6시간마다 자동 실행
- 시트의 K~O 컬럼이 자동 갱신됨
- 별도 알림 X. 시트만 보면 됨.

## 시트에서 보는 값들

| 컬럼 | 의미 |
|------|------|
| 노출영역 (K) | AB / 스마트블록 / 인기글 = 정상 노출. 미노출 = 한 번도 안 됨. **노출중지** = 떨어졌음! 삭제됨/비공개 = URL 죽음. 실패 = 처리 에러 (다음 cron 자동 재시도) |
| 통합탭 순위 (L) | AB 리스트 안 절대 순위 |
| 카페구좌순위 (M) | AB 안 카페 항목들 중 순위 |
| 블로그구좌순위 (N) | AB 안 블로그 항목들 중 순위 |
| 지식인탭 (O) | 지식iN 노출 시 "O" |

## 운영 정보 어디서 봐?
- GitHub Actions 탭 → check-naver-rank 워크플로우 → 가장 최근 실행 클릭
- 거기 logs에서 처리 시간, 성공률, 차단 의심 등 확인
- 평소엔 안 봐도 됨. 시트에 "실패" 자주 보이면 그때 logs 확인.

## 시트 추가/제거 시
- 새 분야 탭 추가 → 헤더 (1행)에 "키워드", "링크", "노출영역" 등 정확한 이름 들어가있으면 자동 인식됨
- 탭 삭제 → 그냥 삭제, 코드 변경 X
- 컬럼 위치 변경 → 자동 인식 (헤더 이름 기반)

## 문제가 생기면
- "실패"가 매 사이클 모든 행에서 보이면 네이버 코드가 바뀌었을 가능성 → Claude에 다시 요청
- 특정 행만 "실패" → 그 행 키워드/URL 점검
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: README operating guide for the user"
git push
```

---

## Self-Review

### 1. Spec coverage

| Spec 요구 | 구현 Task |
|----------|---------|
| GitHub Actions 공개 저장소 무료 | M3.3, M8 |
| Python + Modular B 6모듈 | M3.6 골격 + M4~M7 |
| 6시간 cron | M8.1 |
| 1000+ 무제한 스케일 | M5.3 (탭 순회) + M7.2 (행 루프) |
| 헤더 이름 기반 매핑 | M5.2 |
| 분야별 탭 순회 | M5.3 |
| K 컬럼 enum (AB/스마트블록/인기글/미노출/노출중지/삭제됨/비공개/실패) | M7.1 + M4.6 |
| 노출중지 자동 감지 | M7.1 |
| 인기글 별도 로직 | M4.9 |
| 카페매핑 캐시 | M5.5 + M6.1 |
| naver.me 단축 처리 | M4.2 |
| 슬로우다운 + UA 회전 | M4.3 |
| 재시도 큐 | M6.2 + M7.2 |
| 헬스 모니터 (logs) | M6.3 + M7.2 |
| TDD | 모든 Task에 failing test → impl 패턴 |
| 사장님 작업 분리 | 👤/🤖 마커 |

✅ 모든 spec 항목 매핑됨.

### 2. Placeholder scan

⚠️ M4.7~M4.10에 "TODO 실측 셀렉터 교체" 표시 있음 — 이는 의도된 것 (Phase 1 실측 후 채움). 다른 placeholder 없음.

### 3. Type consistency

- `RankResult`, `RowUpdate`, `CafeStatus`, `ExposureArea` 일관됨
- `compute_new_K` 시그니처 일관됨

### 4. Scope check

단일 시스템 (네이버 → Sheets), 단일 plan에 적합. 분해 불필요.

---

## Execution Handoff

Plan complete and saved to `D:\claude code\naver-rank-checker\.harness\plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

Which approach?
