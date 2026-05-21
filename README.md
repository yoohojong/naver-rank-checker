# naver-rank-checker

네이버 키워드 상위노출 자동 체크 + Google Sheets 자동 갱신. GitHub Actions 6시간 cron, 무료 운영.

## 한 줄 목적

사장님이 외주받은 33만원 도구 대체. **자체 제작 + 안정성 ↑ + 노출중지 자동 감지** (외주본엔 없던 차별화).

---

## 작동 방식 (사장님 입장)

1. 사장님이 Google Sheets 의 "샴푸 카외" / "바디워시 카외" / "두드러기 카외" 탭에 키워드 + 카페 글 링크 입력
2. **6시간마다 자동**으로:
   - 네이버 검색
   - 노출 영역 (AB / 스마트블록 / 인기글) 파악
   - 순위 자동 계산
   - 시트의 K/L/M/지식인탭 컬럼 자동 갱신
   - 유형(C) 후보는 `type-preview` artifact 로만 생성 (컨펌 전 C열 write 금지)
   - **노출됐다가 빠지면 K = "삭제"** 자동 표기 (사장님 즉시 인지)
3. 사장님이 시트만 보면 됨. 클릭 0번.

## 시트 컬럼 (사장님 컨벤션)

| 컬럼 | 의미 | 우리 시스템 |
|------|-----|------------|
| 작업일 / 작업자 / 유형 / 키워드 / MB / PC / 총합 / 작업아이디 / 카페·게시판 / 링크 | 사장님 운영 정보 | **건드리지 X** |
| 유형 (C) | 키워드 검색 결과 최상단 대표 구좌 타입 (AB / 스마트블록 / 인기글) | **1차 preview-only, 컨펌 전 write 금지** |
| 노출영역 (K) | 내 링크가 실제로 노출된 구좌/상태 (AB / 스마트블록 / 인기글 / 미노출 / 누락 / 삭제) | **자동 갱신** |
| 노출여부(통합탭 순위) (L) | 통합 검색 순위 | **자동 갱신** |
| 노출여부(카페구좌순위) (M) | 카페 항목 중 순위 | **자동 갱신** |
| 노출여부(블로그구좌순위) (N) | 사장님 삭제 예정 — 건드리지 X | **skip** |
| 지식인탭 (O) | 'O' or 빈 칸 | **자동 갱신** |

⚠️ 사장님이 K 컬럼에 직접 "확인중" 같은 단어 입력하면 우리 시스템 **보존** (덮어쓰기 X).

---

## 사장님 운영 가이드

### 첫 설정 (1회 only, 30~40분)

→ [docs/사장님-가이드/T-M3-인프라-셋업.md](docs/사장님-가이드/T-M3-인프라-셋업.md) 클릭만으로:
1. GCP 프로젝트 + Google Sheets API + 서비스 계정
2. 사장님 시트에 서비스 계정 이메일 공유
3. GitHub 공개 저장소 생성

### GitHub Secrets 등록 (1회)

저장소 → Settings → Secrets and variables → Actions → New repository secret:
- `SPREADSHEET_ID` = 사장님 시트 URL 의 `/d/` 와 `/edit` 사이 (예: `1AbC123_example...`)
- `SERVICE_ACCOUNT_JSON` = T-M3.1 다운로드한 JSON 파일 **전체 내용** 그대로
- `CAFE_WHITELIST_SLUGS` = 사장님 운영 카페 slug 콤마 구분 (예: `cosmania,pusanmommy,iroid,workee`)
  - T-M90 (D-027 보강 2026-05-17): repo Public 전환 후 사장님 카페 정보 노출 회피 의무.
  - 미설정 시 = 빈 set = D-026 link_set 매치 X = 빈 link 자동 채움 X (= 안전 default).

### Cron 자동 동작

매일 KST 00:00 / 06:00 / 12:00 / 18:00 자동 실행. 사장님 시트 갱신됨.

### 수동 실행

저장소 → Actions → "naver-rank-check" → "Run workflow" 버튼.

### Type preview confirmation

The workflow now uploads two files in the diagnostics artifact:
- `*_type-preview.jsonl`: raw machine-readable rows
- `*_type-preview-summary.md`: owner-readable review table

Use the summary markdown, not the raw JSONL. If the summary table looks right, comment:
`preview 확인했어. C열 write 허용 단계 진행해.`

### 사장님 새 키워드 추가

시트의 카외 탭에 한 행 추가:
- 키워드 + 링크 (cafe.naver.com URL) 필수
- 다음 cron 에 자동 처리

### 새 분야 탭 추가

탭 이름이 "**OO 카외**" 로 끝나면 자동 인식 (예: "비듬 카외", "여드름 카외"). 그 외 이름은 시스템이 건드리지 X.

---

## 기술 스택

- Python 3.13
- `requests` (brotli 포함) + `beautifulsoup4` + `lxml` — 네이버 검색
- `gspread` — Google Sheets API
- GitHub Actions — 무료 cron (public repo)

---

## 모듈 구조

```
src/
├── main.py           # entry point, run_cycle()
├── crawler.py        # 네이버 검색 + slowdown + brotli
├── parser.py         # AB / 인기글 / 지식인 파싱 (사장님 컨벤션)
├── sheets.py         # gspread + 헤더 매핑 + batch write
├── transitions.py    # K 컬럼 상태 전환 (노출중지 자동 감지)
├── cache.py          # 카페매핑 메모리 캐시
├── retry.py          # 1차 실패 행 재시도 큐
├── health.py         # 파싱 성공률 모니터 (selector 변경 자동 감지)
└── config.py         # 환경변수 로드
```

145 unit + component tests.

---

## 안전장치 (사장님 데이터 보호)

1. **화이트리스트**: "카외" 끝 탭만 처리. 사장님 운영 데이터 (계정/계좌 등) 탭은 절대 X.
2. **컬럼 매핑**: 헤더 이름 기반. 사장님이 컬럼 추가/이동해도 정확 매칭.
3. **수동 K 보존**: 사장님이 직접 적은 단어 (예: "확인중") 덮어쓰기 X.
4. **batch write**: 한 탭 1 API 호출. 중간 실패 시 일관성.
5. **Cron overlap 방지**: 이전 cron 미완료 시 다음 cron queue (concurrency: cancel-in-progress: false).
6. **재시도 큐**: 1차 실패 → 슬로우다운 2배 강화 후 1회 재시도. 그래도 실패면 시트에 "삭제" 표기 (사장님 인지).
7. **자동 모니터**: 파싱 성공률 < 90% 또는 confidence < 0.5 → GitHub Actions 빨강 (사장님 알림).

## 사장님 차별화 기능 (외주본 X)

- **노출중지 자동 감지**: 어제 AB 1등이었는데 오늘 빠지면 K = "삭제" 자동
- **시트 자동 갱신**: 매 6시간, 클릭 0번
- **selector 변경 자동 감지**: 네이버 DOM 바뀌면 (예: 2026-05-08 `desktop_mode` → `fds-default-mode`) HealthMonitor 가 자동 검출
- **0원 운영**: GitHub Actions 공개 저장소 무료, GCP free tier

## 문제 발생 시

1. GitHub Actions 빨강 → 사장님 이메일 알림
2. 저장소 → Actions → 최근 실행 클릭 → 로그 확인
3. "CODE_CHANGE_SUSPECTED" 메시지 = 네이버 변경 의심 (Claude 에게 보고)
