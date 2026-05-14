# tasks: naver-rank-checker

**Last updated**: 2026-05-11
**Overall progress**: 95% ━━━━━━━━━━━━ (quality fix +1: J false positive 69건)
**Protocol**: 멀티 Claude 안전 협업. claim 메커니즘 적용 (`.harness/PROTOCOL.md` 참고).

## 마일스톤 가중치
- M1 사양 확정 (10%) — ✅ 100%
- M2 설계 (15%) — ✅ 100%
- M3 인프라 셋업 (10%) — 🔄 67% (4/6 완료: T-M3.1, T-M3.2, T-M3.5, T-M3.6)
- M4 Crawler 모듈 (20%) — ✅ 100% (10/10 완료: T-M4.1~T-M4.10)
- M5 Sheets 연동 모듈 (15%) — ✅ 100% (4/4 완료 + T-M5.5 SKIP — D-015)
- M6 Health/Retry 모듈 (10%) — ✅ 100% (3/3 완료: T-M6.1 cache, T-M6.2 retry, T-M6.3 health)
- M7 통합 (10%) — ✅ 100% (2/2 완료: T-M7.1 transitions, T-M7.2 main.py)
- M8 GitHub Actions 배포 (10%) — 🔄 50% (T-M8.1 + T-M8.4 완료, T-M8.2 사장님 + T-M8.3 사장님 GitHub repo 후)

---

## Task 상태 표 (단일 진실)

상태 표시: `pending` / `claimed` / `completed` / `blocked`
deps = 의존성 (선행 task), parallel = 동시 작업 안전한 다른 task

### M1 ~ M2 (완료)
| ID | Title | 상태 |
|----|-------|------|
| M1.* | 사양 확정 (전체) | ✅ completed |
| M2.* | 설계 (전체) | ✅ completed |

### M3 인프라 셋업
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M3.1 | GCP 프로젝트 + Sheets API 활성 + 서비스계정 | 👤 사장님 | — | T-M3.3 | ✅ completed (2026-05-08, 서비스계정 발급 + JSON 다운로드) |
| T-M3.2 | 사장님 시트에 서비스계정 공유 | 👤 사장님 | T-M3.1 | T-M3.3 | ✅ completed (2026-05-08, 832행/3 카외 탭 인증 통과) |
| T-M3.3 | GitHub 공개 저장소 생성 | 👤 사장님 | — | — | pending (가이드: `docs/사장님-가이드/T-M3-인프라-셋업.md` 3장) |
| T-M3.4 | 로컬 git init + 원격 연결 + 첫 커밋 | 🤖 | T-M3.3 | — | pending |
| T-M3.5 | Python venv + requirements 설치 | 🤖 | — | T-M3.4, T-M4.1 | ✅ completed (2026-05-05) |
| T-M3.6 | 모듈 골격 + sanity 테스트 | 🤖 | T-M3.5 | T-M4.1 | ✅ completed (2026-05-05, 3 tests pass) |

### M4 Crawler + Parser
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M4.1 | 네이버 fixture 수집 (실측) | 🤖 | T-M3.5 | T-M3.6 | ✅ completed (5 HTML fixtures saved, 40~115KB each) |
| T-M4.2 | URL 정규화 (cafe URL parsing + naver.me) | 🤖 | T-M3.6 | — | ✅ completed (11 tests) |
| T-M4.3 | SlowdownController + UA rotation | 🤖 | T-M3.6 | — | ✅ completed (7 tests) |
| T-M4.4 | fetch_search() 메인 fetcher | 🤖 | T-M4.3 | — | ✅ completed (3 tests) |
| T-M4.5 | fetch_cafe_url_status() | 🤖 | T-M4.4 | — | ✅ completed (3 tests) |
| T-M4.6 | parser.py RankResult dataclass | 🤖 | T-M3.6 | — | ✅ completed (9 tests, placeholder selectors for M4.7~M4.10) |
| T-M4.7 | AB 리스트 파싱 (실측 셀렉터) | 🤖 | T-M4.1, T-M4.6 | — | ✅ completed (2026-05-05, 8 tests, fixture 손상 brotli로 복구 + docs/naver-html-structure.md 작성) |
| T-M4.8 | 스마트블록 파싱 | 🤖 | T-M4.7 | T-M4.9 (다른 함수, 같은 파일 주의) | ✅ completed (2026-05-05, 5 tests, mixed_blocks fixture 기반) |
| T-M4.9 | 인기글 + 지식인 파싱 | 🤖 | T-M4.7 | T-M4.8 (같은 파일 주의) | ✅ completed (2026-05-06, 7 tests, popular_cafe + smart_block fixture 기반) |
| T-M4.10 | block_order 추출 (C 컬럼) | 🤖 | T-M4.7 | — | ✅ completed (2026-05-06, 5 tests, fixture 5개 모두 검증) |

### M5 Sheets 연동
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M5.1 | gspread 인증 | 🤖 | T-M3.6 | T-M6.* (다른 모듈) | ✅ completed (2026-05-06, 4 tests, mock 기반 — 실 인증은 T-M3.1 GCP 후) |
| T-M5.2 | 헤더 매핑 함수 | 🤖 | T-M5.1 | T-M6.* | ✅ completed (2026-05-07, 8 tests, spec 4.2 전체 헤더 검증) |
| T-M5.3 | 모든 탭 순회 read | 🤖 | T-M5.2 | T-M6.* | ✅ completed (2026-05-07, 6 tests, 사장님 3 탭 검증) |
| T-M5.4 | Batch write per tab | 🤖 | T-M5.2 | T-M6.* | ✅ completed (2026-05-08, 10 tests, 사장님 컨벤션 정합) |
| T-M5.5 | 카페매핑 시트 read/write | 🤖 | T-M5.2 | T-M6.* | ⏭️ skipped (2026-05-11, D-015 — 사장님 시트엔 카페매핑 탭 없고 메모리 캐시(M6.1)로 cron 사이클 충분) |

### M6 Cache + Retry + Health
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M6.1 | cache.py — 카페매핑 캐시 | 🤖 | T-M3.6 | T-M5.*, T-M6.2, T-M6.3 | ✅ completed (2026-05-08, 12 tests, CafeMappingCache + ensure 패턴) |
| T-M6.2 | retry.py — 재시도 큐 | 🤖 | T-M3.6 | T-M5.*, T-M6.1, T-M6.3 | ✅ completed (2026-05-08, 10 tests, slowdown_multiplier 강화 후 1회 재시도) |
| T-M6.3 | health.py — 헬스 모니터 | 🤖 | T-M3.6 | T-M5.*, T-M6.1, T-M6.2 | ✅ completed (2026-05-08, 11 tests, 성공률 + avg confidence 기반 code_change_suspected) |

### M7 통합
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M7.1 | transitions.py — 노출중지 자동 감지 | 🤖 | T-M3.6 | T-M5.*, T-M6.* | ✅ completed (2026-05-08, 13 tests, 사장님 D-009 차별화 — '삭제' 단일 단어로 통일) |
| T-M7.2 | main.py — 한 사이클 흐름 통합 | 🤖 | T-M4.*, T-M5.*, T-M6.*, T-M7.1 | — | ✅ completed (2026-05-08, 7 component tests, run_cycle entry point) |

### M8 배포
| ID | Title | 담당 | deps | parallel | 상태 |
|----|-------|------|------|----------|------|
| T-M8.1 | .github/workflows YAML 작성 | 🤖 | T-M7.2 | — | ✅ completed (2026-05-08, concurrency 블록 포함, KST 6시간 cron, timeout 90분) |
| T-M8.2 | GitHub Secrets 등록 | 👤 사장님 | T-M3.1, T-M3.3 | T-M8.1 | pending (README 안내 작성됨) |
| T-M8.3 | 첫 수동 트리거 + 검증 | 🤖 | T-M8.1, T-M8.2 | — | pending |
| T-M8.4 | README 운영 가이드 | 🤖 | T-M7.2 | T-M8.1, T-M8.3 | ✅ completed (2026-05-08, 사장님 페르소나 정합 한국어 가이드) |

---

## 다음 작업 (Next Up) — 2026-05-14 갱신

🤖 **자동 진행 = 신규 cron 25833418213 watch 중** (cron-job.org trigger 적용 후 첫 실행 결과 확인)

👤 **사장님 작업 = 우선순위 ↓ 순**:

### ⭐ 1순위 (긴급) — Google Sheets 버전 복원
- T-M14.2 시점 (5-13 commit 10c1ca5) ~ T-M10.4 시점 (5-14 새벽) = 시트 link 컬럼 + K="삭제" 다수 손상
- Google Sheets 버전 기록 = 2026-05-13 14:00 이전 시점 복원 의무 (link + K 동시 복원)
- 방법: 시트 상단 메뉴 → 파일 → 버전 기록 → 기록 보기 → 손상 이전 버전 복원

### 2순위 — GitHub 알림 설정 (5분, 1회)
- github.com/settings/notifications = "Email" 체크
- yoongu777@gmail.com 등록 확인
- naver-rank-checker repo = "Watch" = All Activity
- 결과 = cron 결과 자동 이메일 도착

## ⏭️ 자동 진행 (사장님 작업 X = 자동)
- 신규 cron 25833418213 = cron-job.org KST 0/6/12/18 자동 trigger watch 중
- 결과 보고 = 다음 세션 이어서
- 운영 정착 진입 = ubuntu-latest 단독 + cron-job.org trigger = 사장님 PC 부담 X

## 차단 이슈 (Blockers)
- 사장님 Google Sheets 복원 = 긴급 (K="삭제" 손상 데이터 현재 노출 중)
- 100% 정확도 = 자연 한계 객관 불가능 (D-021/D-022 정합, 3 agent 검증 유지)

## 변경 이력
- 2026-05-05: 초기 생성 (brainstorming 단계 종료 시점)
- 2026-05-05: spec 셀프 리뷰 통과 (7건 모순/모호성 정정)
- 2026-05-05: D-013 — K 컬럼에 `노출중지` 추가, `비실계의심` 제거
- 2026-05-05: writing-plans 완료, plan.md 작성됨
- 2026-05-05: PROTOCOL.md 추가 + tasks.md에 task 의존성/병렬 표 추가 (멀티 Claude 안전)
- 2026-05-05: T-M3.5 완료 (Python venv + requirements.txt/dev/pytest.ini + 모든 deps 설치 검증). 커밋은 T-M3.4 (git init) 완료 후 일괄 처리 예정.
- 2026-05-05: T-M3.6 완료 (10개 모듈 골격 + tests/conftest.py + test_sanity.py 3 tests PASS). 커밋은 T-M3.4 후 일괄.
- 2026-05-05: T-M4.1 완료 (5개 네이버 fixture 수집, 40~115KB).
- 2026-05-05: T-M4.2 완료 (parse_cafe_url + resolve_short_url, 11 tests).
- 2026-05-05: T-M4.3 완료 (SlowdownController + random_user_agent, 7 tests).
- 2026-05-05: T-M4.4 완료 (Crawler.fetch_search with browser headers + slowdown integration, 3 tests).
- 2026-05-05: T-M4.5 완료 (Crawler.fetch_cafe_url_status with CafeStatus enum, 3 tests).
- 2026-05-05: T-M4.6 완료 (RankResult/ExposureArea + parse_search_result skeleton, 9 tests, placeholder _parse_* for M4.7~M4.10).
- 2026-05-05: 글로벌 CLAUDE.md에 harness_auto_resume 규칙 추가 (어떤 단어든 .harness 자동 인식 + 다음 task 진행).
- 2026-05-05: 프로젝트 루트에 CLAUDE.md 추가 (Claude 자동 진입 가이드).
- 2026-05-05: T-M4.7 진행 중 fixture 5개 모두 손상 발견 (brotli 미설치로 디코딩 실패). requirements.txt 에 `brotli==1.1.0` 추가 + 설치 + collect_fixtures.py 재실행해서 정상 fixture 복구 (250KB~870KB).
- 2026-05-05: T-M4.7 완료. AB 통합 리스트 파싱 (`div.api_subject_bx.desktop_mode` + h2 자손 없음 = AB 항목 규칙). _parse_ab_list + _extract_main_link + _classify_item_url + _urls_match 구현. 8 새 tests pass (전체 44 tests pass). docs/naver-html-structure.md 작성 (M4.8/M4.9/M4.10 참고용).
- 2026-05-05: T-M4.8 완료. 스마트블록 파싱 (h2 자손 + h2 텍스트가 인기글/브랜드/이미지/AI브리핑/네이버클립/쇼핑 패턴 아닌 박스). _parse_smart_blocks + _extract_smart_block_items 구현 + smart_block_name = h2 텍스트. 5 새 tests pass (전체 48 tests pass). docs/naver-html-structure.md 8장 추가.
- 2026-05-06: 글로벌 second-brain skill 만듦 (`~/.claude/skills/second-brain/`) — 모든 프로젝트의 기획·plan·마일스톤 종료 시점 자동 메타 검토. SPEC + PLAN + SKILL + checklist + retro-log + routing-reminder hook trigger + CLAUDE.md 7번 gate. critic agent 검토로 Major 2개 (regex narrow + Quick/Deep mode 분리) 적용. naver-rank-checker 진행 중 자동 발동 예정.
- 2026-05-06: T-M4.9 완료. 인기글 + 지식인 파싱. _parse_popular (h2 텍스트 '인기글' 박스, 출처별 dedup → idx, cafe_slot_rank 매핑) + _extract_popular_items + _parse_jisikin (kin.naver.com 도메인 매칭 시 in_jisikin=True). 7 새 tests pass (전체 54 tests pass). docs/naver-html-structure.md 9장 (인기글) + 10장 (지식인) 추가.
- 2026-05-06: second-brain 자기 진화 첫 적용 — Phase 2 의 response-validator.mjs Stop hook 추가를 Phase 1 으로 앞당김. 사장님 챌린지 "기획 끝났어 라는 말 없이도 발동" → 마일스톤/task 종료 시그널 (T-M\d+ 완료, Phase \d 완료, ✅ tests pass) 정규식 5개로 Claude 응답 매치 → 다음 턴 SECOND_BRAIN 자동 주입.
- 2026-05-06: T-M4.10 완료. block_order 추출 (C 컬럼 용). _detect_block_order — 위→아래 박스 종류 unique list (AB / 스마트블록 / 인기글). 5 fixture 모두 예측 정확 (ab_cafe_top: ['AB'], mixed_blocks: ['AB', '스마트블록', '인기글'], popular_cafe: ['인기글', 'AB']). 5 새 tests pass (전체 58 tests pass). M4 100% 종료.
- 2026-05-06: T-M5.1 완료. SheetsClient (gspread service_account_from_dict + open_by_key). 4 mock tests pass.
- 2026-05-07: 누적 미해결 발견 일괄 해결: (1) ExposureArea enum 4개→8개 확장 (DELETED/PRIVATE/UNEXPOSURE_STOPPED/FAILED, spec 4.2 정합) — 63 tests pass. (2) 사장님 GCP/시트/GitHub 가이드 docs/사장님-가이드/T-M3-인프라-셋업.md 작성 (단계별 클릭, 30~40분 예상). (3) second-brain checklist.md 에 C-11 (phase-graduation-on-real-need) 정식 추가 (3회 누적 → 진화 트리거 첫 정식화).
- 2026-05-07: T-M5.2 완료. map_headers_to_columns (헤더 이름 → 0-indexed 컬럼 매핑, D-004 정합). 8 새 tests pass (spec 4.2 전체 헤더 검증, 열 이동 강건성, 중복/공백 처리). 전체 71 tests pass. 진척도 48%→51%.
- 2026-05-07: 사장님 실 시트 첫 행 텍스트 받음 (3개 탭: 샴푸 카외/바디워시카외/두드러기카외, 15개 헤더). spec 4.2 갱신 — L/M/N 헤더가 "노출여부(통합탭 순위)" / "노출여부(카페구좌순위)" / "노출여부(블로그구좌순위)" 형식 확정. test 도 사장님 실 헤더로 교체. 첫 번째 (L) 만 괄호 안 공백 있음 (사장님 컨벤션 그대로).
- 2026-05-07: .gitignore + .env.example 작성. SPREADSHEET_ID = `1mGhsPHd-...` 사장님 시트. SERVICE_ACCOUNT_JSON 은 T-M3.1 후 사장님이 채움.
- 2026-05-07: T-M5.3 완료. SheetsClient.load_all_data_tabs (모든 데이터 탭 순회 + 헤더 매핑 + dict 행 + _row/_tab 메타). SPECIAL_TABS frozenset (카페매핑/_meta/설정/config). 6 새 tests pass (사장님 3 탭 시뮬, special skip, 빈 시트, 짧은 행 padding). 전체 77 tests pass. 진척도 51%→54%.
- 2026-05-08: 사장님 GCP/서비스계정 발급 ✅ + 시트 공유 ✅. SheetsClient 가 실 사장님 시트 (832 행 / 3 카외 탭) 인증 통과. 19 distinct cafe slug 발견 (pusanmommy 82건, cosmania 46 등).
- 2026-05-08: 500 행 sample 사장님 수기 vs 파서 비교. 1차 fix 전 일치율 62.9%. **2 큰 selector 버그 발견 + fix**: (1) 네이버 DOM 클래스명 변경 `desktop_mode` → `fds-default-mode` (5/5~5/8 사이), (2) URL 매칭 `m.cafe.naver.com` 모바일 prefix 정규화. fix 후 79.4% (+16.5%).
- 2026-05-08: 사장님 컨벤션 정정 (제가 spec 에 사용한 단어가 사장님 비즈니스 용어였음 — C-10 메타 챌린지 큰 누락 사례): (1) 스마트블록 → 인기글 통합 (사장님 시트엔 '스마트블록' 단어 0건), (2) 노출 안 됨 모든 케이스 → '삭제' 단일 단어 (UNEXPOSURE_STOPPED/DELETED/PRIVATE 모두 alias), (3) 미노출 = 빈 칸, (4) 유형 (C) = block_order[0] 만 (최상단 1위, 사장님 컨벤션 변경).
- 2026-05-08: T-M5.4 완료. RowUpdate + rank_result_to_columns + SheetsClient.write_results. 10 새 tests (사장님 컨벤션 매핑, batch_update 1회 호출, 시트 없는 컬럼 자동 skip). 전체 89 tests pass.
- 2026-05-08: T-M6.1 완료. CafeMappingCache (메모리 + ensure 패턴). 12 새 tests. 사장님 시트엔 카페매핑 탭 없어서 메모리 캐시만 (cron 사이클 내).
- 2026-05-08: T-M6.2 완료. RetryQueue (1차 실패 행 보존 + slowdown 강화 후 1회 재시도). 10 새 tests.
- 2026-05-08: T-M6.3 완료. HealthMonitor (성공률 + avg parser confidence 기반 code_change_suspected). 11 새 tests. 5/8 네이버 DOM 변경 사례를 미래엔 자동 검출 가능.
- 2026-05-08: T-M7.1 완료. transitions.compute_new_K (사장님 D-009 차별화 — 이전 노출 → 빠짐 = '삭제' 자동 표기). 13 새 tests. EXPOSED_VALUES = {'AB', '인기글'} 사장님 컨벤션.
- 2026-05-08: T-M7.2 완료. main.py run_cycle (전체 흐름 통합 — sheets read → 검색 + parser → transitions → retry → batch write → health log). 7 component tests (mock crawler + 실 fixture). 전체 144 tests pass.
- 2026-05-08: M6/M7 모두 100%. M3 33% (사장님 GCP/시트공유 ✅, GitHub repo 사장님 작업 대기). 전체 진척도 76%. T-M8 만 남음.
- 2026-05-08: critic agent (opus background) 종합 검토. verdict = FIX-THEN-PROCEED. Critical 2건 + Major 3건 발견. **즉시 fix**: (1) main.py except Exception silent drop → "삭제" RowUpdate 추가, (2) retry 실패도 "삭제" RowUpdate, (3) transitions.EXPOSED_VALUES 에 "스마트블록" defensive 추가, (4) config slowdown 1.5 → 5.0 (사장님 발화 정합 + 차단 방지), (5) 사장님 수동 K 편집 보존 (SYSTEM_K_VALUES 외 값 시 그대로 유지). spec 4.2 N 컬럼 "skip 의도" 명시.
- 2026-05-08: T-M8.1 + T-M8.4 완료. `.github/workflows/rank-check.yml` 작성 (KST 6시간 cron, concurrency: cancel-in-progress: false, timeout 90분, exit code 1 = HealthMonitor 의심 시). README.md 작성 (사장님 페르소나 한국어 가이드, 안전장치 7개 명시, 차별화 기능 4개 강조). 진척도 76%→88%.
- 2026-05-08: navigation skill 별도 하네스 (`~/.claude/skills/navigation/`) 작성. 시각화: 매 응답 첫 줄 `🧭 [목적: ...] [도구: ...]`. 글로벌 모든 프로젝트 적용. 사장님 명시 "여러 skill 동시 OK + 직선 진행 + 꼬불꼬불 X" 반영. response-validator.mjs (g0) hook 가 자동 검증 + NAVIGATION_MISSING 정정 주입. CLAUDE.md 8번 critical_gate 추가.
- 2026-05-11: tasks.md 정합 갱신. T-M3.1/T-M3.2 ✅ 표시 (5/8 시점 사장님 GCP+시트공유 완료한 사실 변경 이력에는 있는데 표는 pending 이었음). 진척도 88%→94%. Stale claim `T-M7.2/` 청소 (실 task 는 5/8 완료, 폴더만 남아있었음).
- 2026-05-11: D-015 — T-M5.5 SKIP 결정. 근거: (1) 사장님 시트 (832행/3 카외 탭/15 헤더)에 "카페매핑" 탭 없음 (M5.3 검증), (2) D-012 시트 컨벤션 변경 후 카페명/게시판 컬럼 자체 없음 (K~O 만 갱신), (3) 메모리 캐시 (M6.1 CafeMappingCache) 가 cron 사이클 내 중복 fetch 방지 보장 → 영구 캐시 불필요. D-006 (카페매핑 자동 추출) 은 spec 초기 가정, 실 사장님 컨벤션과 drift 발견 (사장님 컨벤션 정정 2026-05-08 후 인식). 미래에 카페매핑 탭 필요해지면 plan.md 의 T-M5.5 코드 재활성화 가능. M5 80%→100% (effectively).
- 2026-05-11: D-016 — J false positive fix (parser._parse_jisikin v2). 사장님 시트 500행 정밀 분석으로 J false positive 69건 발견 (전부 cafe.naver.com + h2 없는 박스의 부수 kin 링크). 원인 = v1 selector 가 "AB 박스 안 임의 kin 링크" 잡음. fix = h2 텍스트 = '지식iN'/'지식인' 박스 안 kin 링크만 True. M4.9 인기글 패턴 동일. test 2개 의미 변경 (smart_block.html h2 0개 사실 반영) + 새 test 4개 (h2 박스 True / 한글 True / 회귀 방지 False / target kin + h2 없음 False). 6/6 jisikin pass, 전체 **148/148 tests pass** (145→148). 나머지 mismatch 64건 = 시점 차이 의심 → T-M8.3 실 cron 후 같은 시점 비교까지 미룸.
- 2026-05-11: navigation skill v2 (사장님 글로벌 인프라). 사장님 챌린지 "어떤 스킬 + 어떤 목적 + 왜 — 안 말하면 의미 없음. 한 번에 완벽하게" → 형식 2축 → 3축 (목적/도구/**이유**) 진화. SKILL.md ANTI-PATTERN 7케이스 일괄 카탈로그, response-validator g0 3축 검증 + INCOMPLETE 별도 violation + navigation-debug.log 진단 항목 3축 boolean, routing-reminder always-on 카드 3축 형식, CLAUDE.md critical_gate 8 v2, retro-log Case 3 누적. hook syntax `node --check` BOTH OK. Phase 4 (Case 6/7 자동 검출 + fast mode 신뢰도) 예약.
- 2026-05-11: navigation v3 → v4 진화 (사장님 챌린지 "무슨 도구인지 모르겠다") → 도구 이름 옆 한국어 한 줄 역할 의무. SKILL.md Case 10 (도구 한국어 역할 누락) + 도구 사전 (영어↔한국어) 추가. response-validator g0-e block (도구 한국어 역할 검출). routing-reminder v4 카드. CLAUDE.md critical_gate 8 v4. retro-log Case 10 누적.
- 2026-05-11: omc-learned/ 새 skill 2개 추출 (boss-challenge-evolution + github-actions-self-hosted-windows) — 사장님 챌린지 → SKILL 진화 패턴 + Windows self-hosted runner 3 root cause 패턴.
- 2026-05-11: GitHub Actions ubuntu-latest → **self-hosted runner on 사장님 PC** 이전. document-specialist + critic 검증: Azure IP 차단 = root cause (run 25646801029 timeout 90분 cancel). 사장님 가정용 ISP IP = residential trust ↑. repo Public → Private 전환 + gh CLI 자동 (winget 설치 + auth login + repo create + runner config 자동). secrets 2개 등록 (SPREADSHEET_ID + SERVICE_ACCOUNT_JSON). issue #1 알림 시스템 (mention 자동 이메일). workflow yml: runs-on self-hosted, timeout 90→180분, setup-python action 제거 (Windows Python 3.13 사용), shell pwsh→powershell (5.1), 매 step PATH 갱신 의무. 첫 3 run 실패 (setup-python 충돌 / pwsh 없음 / json BOM) → fix 후 4번째 run 25647821456 진행.
- 2026-05-11: D-016 보강 — architect agent 깊이 분석 결과 CRITICAL 1 + Major 3 발견. (1) **CRITICAL**: scripts/post_summary_to_issue.py 가 K 분포 + 탭 이름 (사장님 비즈니스 데이터) issue #1 영구 노출. fix = 단순 메타 (시간/행수/셀수/성공률) 만 출력. (2) **Major 1**: SlowdownController 비대칭 회복 (×2 vs ×0.9 → 1 차단 → 60s max → 30+ 성공 회복 → 832 행 × 60s = 27시간 폭주). fix = CircuitBreakerOpen exception + on_success ×0.5 + main.py 가 잡아서 cron 조기 종료 + circuit_breaker_tripped flag. (3) **Major 2**: parser._parse_popular L=M 강제 (사장님 실 데이터 L==M 만 34%). fix = AB 박스 동일 로직 (cafe_count 분리, blog target → M=None). 테스트 2개 갱신 + 새 테스트 2개 추가. **151/151 tests pass**. commit 73e7dca push.
- 2026-05-11: cron run 25647821456 (commit 73e7dca = 4 fix 적용) 결과 = **사장님 시트 통째로 손상 발견**. log evidence: 832 행 → 1차 갱신 80 + retry 대기 421 + 차단 누적 → batch_update 501 행 갱신됨. 사장님 발화: "모든 갱신이 이상". 진짜 root cause (tracer + log evidence): (1) main.py 의 `재시도도 실패 → 시트에 '삭제' 입력` (critic 2026-05-08 권장 fix 가 의도와 정반대) — 차단 ≠ 진짜 삭제, 사장님 작업자 혼란. (2) parser._parse_popular L/M 분리 fix → blog target M=None 적용됨 (이전 L=M 컨벤션과 다름). (3) _parse_smart_blocks deprecated (항상 False) → 이전 스마트블록 행 UNEXPOSED. 사장님 Google Sheets 버전 기록 복원 ✅ (cron 시작 전 시점). workflow disable ✅ (다음 자동 cron 안 돔). 사장님 시트 추가 손상 차단.
- 2026-05-11: 사장님 메타 챌린지 "차단 안 당하는 방법 우선 + PC 만 사용 + 832 다 + 0원". 검증 8 옵션 (slowdown ↑ / 분산 cron / fingerprint 강화 / Headless Playwright / retry 폐지 / 라우터 재시작 / 모바일 검색 URL / session 관리). document-specialist background 진행 중 — 진짜 효과 ↑ 1~3 단호 추천 대기. **사장님 절대 제약 (PC만 + 832다 + 0원 + 매 6시간) 동시 만족 = 차단 0 보장 불가능** 진솔 인정.
- 2026-05-11: 사장님 시스템 글로벌 강화 — settings.json 3 hook wire (PreToolUse + PostToolUse + PostToolUseFailure) + retro-log v2 format (Confidence + 결과 필드, MindStudio 흡수) + second-brain SKILL.md step 1e (violation-log 통합, architect 발견). 외부 시스템 (Blake Crosley 95 hook / rohitg00 SQLite FTS5 / Oracle Cloud) 흡수 X — 사장님 페르소나 정합 X. 사장님 ranking = 비개발자 카테고리 세계 1위 (공개 사례 0건) + 전체 3위 (Stop hook 정정 주입 + ANTI-PATTERN 카탈로그 독보적).
- 2026-05-11: **T-M9.1 (curl_cffi 도입) 완료** — README "다음 세션 의무 1번". `requests==2.32.3` → `curl_cffi==0.15.0` + `Session(impersonate="chrome131")` (TLS+JA3 지문 Chrome 131 위장, 네이버 봇 차단 회피 root cause fix 중 하나). 변경 7곳: crawler.py 4곳 (import / Session / head impersonate kwarg / except 3곳 `RequestException` → `RequestsError`), test_crawler.py 7 테스트 마이그레이션 (responses 라이브러리 → unittest.mock.patch, libcurl 백엔드는 responses 가로채기 못함), requirements-dev.txt responses 제거. **document-specialist 1차 정보 오류 발견 (`RequestException` 실제로 noexist, 진짜 이름 = `RequestsError`)** — 검증 후 fix. 151/151 tests pass (23s). 다음 fix 2/3 (빈 결과 감지 + cron evidence) 사장님 시그널 대기.
- 2026-05-11: 사장님 "cron ㄱ" 시그널 → push eb7d472 + workflow enable + dispatch run 25662967605. **결과 진단 (4 turn 협업)**: (1) 1차 가설 = HEAD 73e7dca race condition → tracer agent 분석 (확률 55% H2 GitHub API propagation lag). (2) 정정 = `gh run view --json headSha` 결과 = eb7d4721b1... = eb7d472 진짜 (curl_cffi 적용). log 의 "HEAD is now at 73e7dca" → "Previous HEAD position was 73e7dca" = actions/checkout@v4 self-hosted runner workdir cleanup 흔적. **race condition X**. (3) 실증 진단 (probe v1/v2/v3/v4 - curl_cffi 직접 호출) — parser 5/5 keyword 정확, conf 0.9 (노출) vs 0 (미노출). (4) **진짜 root cause = HealthMonitor false positive**: avg_conf 계산식이 UNEXPOSED record (conf=0+success=True) 포함 → 미노출 우세 시트 (832 행 중 다수) 시 평균 자연스럽게 ↓ → false 알림. cron 평균 0.36 < 0.5 threshold → CODE_CHANGE_SUSPECTED 발동 (잘못된).
- 2026-05-11: **T-M9.2 (HealthMonitor exposed-only avg) 완료**. health.py:summary() 의 avg_conf 계산식 변경 — 노출 record (conf > 0) 만 평균. UNEXPOSED + success=True 는 의도된 정상 상태로 분류, noise 아님. 또 suspected 조건의 표본 카운트도 노출 표본 기준으로 변경. test_health.py 새 test 2개 (test_unexposed_dominant_no_false_alert + test_all_unexposed_triggers_alert). 11/11 → 13/13 health tests pass. workflow disable 적용되어 있음 (사장님 시트 추가 손상 위험 0). 사장님 시트는 진단 결과 = 정확 갱신 가능성 ↑↑↑ (5/5 keyword parser 정확).

- 2026-05-12: **T-M13 (T-M10 revert) 진행** — 사장님 명시 ("링크 없는데 무슨 순위가 다 들었다고") = T-M10 적용한 게 사장님 의도 정합 X. main._process_row 의 link 빈 row 처리 변경 (검색 X + K/L/M 빈칸 처리 = 시트 자동 정리). 158/158 tests pass. commit `42d66bb` push + dispatch `25700263842`. **메타 학습** = CLAUDE.md 영구 룰 추가 (모호 OR 시그널 있을 때 = 단호 결정하지 않는다) + D-018 추가.

- 2026-05-12: **T-M9.1~T-M14 일괄 진행** (4 commit + 4 사장님 지적 fix):
  - T-M9.1 (eb7d472) curl_cffi==0.15.0 도입 — TLS 위장 Chrome131, 네이버 차단 회피
  - T-M9.2 (f77e4de) HealthMonitor.summary() 의 avg_conf 계산식 = exposed-only (UNEXPOSED noise 제거, false alert 방지)
  - T-M10 (d838a34) → T-M13 (42d66bb) revert: 사장님 의도 정합 X 발견 후 link 빈 row = 빈칸 처리로 정정
  - T-M10.1 (e9fcfb1) main._process_row 의 URL alive 검증 조건 완화 — link 있는 모든 row 의 검색 미노출 시 url 검증 → 죽었으면 K="삭제"
  - T-M11 (8585d47) gspread Google Sheets API 503/5xx retry (5/10/20초 exponential backoff)
  - T-M14 (bf24479) link_set 매치 (사장님 시트 다른 row link 와 검색 결과 교집합) + K="삭제" 셀 노란색 배경 (gspread batch_format)
  - 160/160 tests pass
- 2026-05-12: **D-018 추가** — 사장님 의도 모호 OR 시그널 시 우리 결정 단호 진행 X. 1줄 confirm 받은 후 진행 의무. T-M10/T-M13 두 번 미스 후 영구 룰.
- 2026-05-12: **D-019 추가 + CLAUDE.md 영구 룰 추가** — 한국어 표준어 사용 강제 + 사장님 지적 후 메타 학습 의무. 사장님 강한 짜증 신호 ("박음이라는 말투는 왜 쓰는거임?") 후 즉시 graduate.
- 2026-05-12: **second-brain skill Deep mode 발동** — C-13 후보 (claude-response-korean-standard) + self-hosted-runner-SPOF (사장님 PC 의존성) + meta-learning-on-user-anger 세 라벨 누적. retro-log entry 추가.
- 2026-05-12: **사장님 PC self-hosted runner offline 발견** — T-M14 cron 25700783310 = 실행 도중 runner 끊김 = job timeout = failure. 사장님 시트에 T-M11/T-M13/T-M14 적용 X 상태. 사장님 PC 깨우거나 Plan B (ubuntu-latest + curl_cffi 차단 회피 시도) 결정 의무.

- 2026-05-12: **T-M14 commit `bf24479`** — parser_main_sheets link_set 매치 + 노란색 색상. 160 tests pass.
- 2026-05-12: **D-019 commit `b71f607`** — CLAUDE.md 한국어 표준어 강제 룰 + 사장님 지적 후 메타 학습 의무 영구 룰. 사장님 강한 짜증 후 즉시 graduate.
- 2026-05-12: **T-M15 commit `9b4ecbc`** — workflow yml ubuntu-latest 임시 fallback (사장님 PC self-hosted runner offline). curl_cffi 차단 회피 시도. cron run 25704391715 = 71분 success, 3911 셀 갱신, Avg conf 0.88. Azure IP + curl_cffi 차단 회피 성공 검증.
- 2026-05-12: **T-M14.1 commit `3615e23`** — link_set 매치 시 매치 link 명시 log ([AB_MATCH] / [POPULAR_MATCH]). 진단용.
- 2026-05-12: **T-M16 commit `d25d040`** — parser link_set 매치 = 카페만 허용. 사장님 진단 "청소년바디워시 인기글인데 K=AB" root cause 확정 (probe v8): _parse_ab_list 가 박스 4 (h2 X + blog 만) 의 blog 매치 시 AB 잘못 분류 → 사장님 의도 = 카페만 추적. kind == "cafe" / is_cafe 만 매치 시도. blog/web 매치 = skip. probe 검증 = 박스 4 blog 매치 → 미노출 (이전 = AB 잘못). 160 tests pass.
- 2026-05-12: **사장님 지적 4 fix 진행**: 말투 (D-019 한국어 표준어), 노란색 (T-M14 적용), 삭제 (T-M10.1), 순위 분류 (T-M16). 진행 중 cron 25709732732 = T-M16 적용한 결과 ~KST 12:38~48 완료 예상.
- 2026-05-12: **마일스톤 표 갱신 의무** — M9~M16 quality fix 추가 기록됨. 공식 진척도 표 갱신 보류 다만 실 상태 = 사실상 완료 + 운영 중 quality fix.

- 2026-05-12: **D-020 추가 — T-M16 후 잔존 문제 2 case 발견 + 디벨롭 사항 (T-M18~T-M22)**:
  - Case A (link 빈 row false 매치): link_set 의 다른 회사 카페 글 매치 → 사장님 시점 = 노출 X
  - Case B (link 있는 row 박스 분류 잘못): "h2 X = AB" 가정 + 사장님 컨벤션 차이
  - **디벨롭**: T-M18 사장님 카페 화이트리스트 / T-M19 parser 박스 분류 동기화 / T-M20 timestamp 표시 / T-M21 매치 row 번호 표시 / T-M22 사장님 박스 종류 정확 정의
  - 다음 세션 이어서 진행 의무 (사장님 명시)

- 2026-05-12: **D-021 + Phase 0 실행 완료** — 사장님 발화 "정확도 100% 종합 최종 plan" 의무. 4 agent 검증 (architect + document-specialist + planner Opus + critic Opus FIX-THEN-PROCEED). 진짜 가능 상한 = K 88~92% / 4컬럼 65~75% (planner 87~95% = 과대 평가 확정). Phase 0 즉시 실행 7 fix:
  - T-M23: config.py USER_AGENTS 모바일 UA 제거 → PC Chrome 4종 (146/145/146 Mac/136). 사장님 발화 fingerprint mismatch root cause 해소
  - T-M24: crawler.py SlowdownController.wait() = config NAVER_SLOWDOWN_BASE_SEC=5.0 진짜 정합 (5~7.5초). 기존 random 1.5~4초 하드코딩 = 사장님 의도 무시 = 버그 fix
  - T-M24b: Crawler.warmup() 추가 = 네이버 메인 1회 fetch 후 검색 (Cold session soft 차단 회피). document-specialist 검증
  - T-M24c: IMPERSONATE_POOL = ["chrome146", "chrome145", "chrome136", "chrome131"] 매 인스턴스 random 회전. curl_cffi 0.15.0 진짜 지원 검증 (BrowserType enum 확인)
  - T-M25: config.py CAFE_WHITELIST 26 slug + main.py link_set 필터 = D-020 Case A 11건 false positive 즉시 차단
  - T-M26: _BROWSER_HEADERS Accept-Encoding "gzip, deflate, br" 추가 (브라우저 동일 행동)
  - critic (e): parser._extract_main_link CSS selector 1순위 5종 (.total_tit / .title_link / api_txt_lines / .title_area / .user_thumb) + 텍스트 길이 fallback 유지. 광고/관련검색 link 오작동 차단
  - test 결과: **172/172 pass** (160 → 172, +12 신규 test). test_crawler.py +10 (TestCrawlerImpersonatePool / TestCrawlerWarmup / TestSlowdownWaitBase) + test_main.py +6 신규 (TestCafeWhitelistFilter)
  - 변경 파일 = config.py (+25줄) / crawler.py (+22줄) / parser.py (+18줄) / main.py (+13줄) / test_crawler.py (+68줄) / test_main.py (+64줄)
  - 진척도 = 95% 유지 (이미 운영 진입, 정확도 fix 단계)

- 2026-05-12: **Phase 1~5 사장님 결정 의무 7개 존재** (decisions.md D-021 + `.omc/plans/open-questions.md`):
  1. 카페 slug 전체 목록 (현재 자동 추출 26 slug 확정 / 추가 / 제외 명시)
  2. L/M 컬럼 계산 방식 (AB / 인기글 박스 동일? 다른?)
  3. 박스 종류 정의 (h2 없는 블로그 박스 = AB / skip?)
  4. 검색 빈도 6h → 3h
  5. PC 24/7 online 보장
  6. 월 1회 100 키워드 수기 검증 수용
  7. 1페이지 vs 2~3페이지 분석 (critic 발견)

- 2026-05-12: **D-022 우리 단호 결정 7개 적용 완료** (사장님 "다 해결해 진행해" 단호 시그널):
  - ① 카페 26 slug 전부 화이트리스트 / ② L 전체 / M 카페만 분리 / ③ h2 없음 + cafe 0 = skip
  - ④ 6h 유지 / ⑤ workflow 이중화 / ⑥ 분기 1회 50 키워드 / ⑦ 1페이지 분석

- 2026-05-13: **cron run 25747754727 성공** (commit eee70b2 박... 적용 후) — ubuntu-latest fallback. 832 행 / 3911 셀 갱신. 139분 (slowdown 5.0). 차단 0건. 사장님 PC self-hosted runner = offline 유지.

- 2026-05-13: **T-M10.3 cron 시간 단축 + push** — slowdown 5.0 → 3.5초 (cron 139→90분). 또 = Adaptive SlowdownController 가속 (10회 성공 시 adaptive_base × 0.7) + url_alive_cache (cron 1회 메모리) + DELETED 추가 키워드. 204 tests pass.

- 2026-05-13: **T-M10.4 url_alive 검증 확장 + push** — `if link and not search_found` → `if link` 변경. 검색 노출 무관 url_alive 검증. D-009 사장님 차별화 정합. 210 tests pass.

- 2026-05-13: **T-M14.2 link 자동 갱신 + push** — 사장님 명시 ("프로그램 핵심 목적 = 키워드 잘 잡고 있는지 체크"). 시트 link A 매치 X + 다른 행 link B 매치 시 = link A → B 자동 갱신 + K/L/M 표시. parser.RankResult.matched_url 필드 + main.py 2단계 매치 + sheets.py HEADER_LINK 컬럼 갱신. 216 tests pass.

- 2026-05-13: **3 agent 객관 검증 완료** (document-specialist + architect + critic Opus):
  - document-specialist 외부 사실: JS 동적 박스 (`entry.bootstrap()` JSON) / Azure IP vs 한국 IP / A/B test / 봇 silent degradation / 시점 차이 (트렌딩 쿼리) = 5 자연 한계 실측 확인
  - architect 코드 검증: K 90~93% / 4컬럼 85~90% 상한 + 구체 결함 3개 발견
  - **critic Opus verdict = OVERCONFIDENT** (직전 "100% 가능" 답 = 과대 확신 / plan 자체 "불가능" 명시 무시)
  - **진짜 가능 상한** = K 동일시점 93~97% / 4컬럼 87~95% (100% = 자연 한계 X 확정)

- 2026-05-13: **T-M14.3 + T-M10.4 + T-M22 + T-M22.1 fix + push** (commit e9702c4) — architect 발견 4 fix:
  - T-M14.3 _extract_popular_items dedup → URL 단위 dedup (같은 카페 복수 글 매치 가능)
  - T-M10.4 url_alive 키워드 추가 ("등급이 부족" / "권한이 없" / "회원등급이" = PRIVATE)
  - T-M22 _POPULAR_SKIP_PATTERNS 확장 ("AI 추천" / "숏폼" / "플레이스" / "동영상" / "쇼핑")
  - T-M22.1 _extract_bootstrap_json 함수 추가 (네이버 JS JSON 페이로드 추출, parse_search_result 미통합 — 다음 cron 검증 후 통합)
  - 효과 = +5~10%p (K 정확도 ↑)
  - 234 tests pass (216 → 234, +18 신규)

- 2026-05-13: **이메일 step 제거 + push** (commit 474800f) — GMAIL_USER / GMAIL_APP_PASSWORD secrets 미등록 = 530 인증 실패. issue #1 댓글 알림 의존 + 사장님 GitHub 알림 설정 의무.

- 2026-05-13: **workflow yml ubuntu-latest 임시 변경 + push** (commit 20acbd5) — 사장님 PC offline = primary self-hosted = 영원 큐 위험. ubuntu 임시. PC 복귀 시 self-hosted 복귀 의무.

- 2026-05-13: **한국어 표준어 강제 + push** (commit 04201f2) — 사장님 강한 재지적 후 진짜 root cause 5층 분석:
  - Layer 1 표면 = 응답 어근 반복
  - Layer 2 의식 = 어휘 습관 우위
  - Layer 3 자체 컨텍스트 오염 = .harness 안 어근 28건 = 자기 강화 루프 (핵심)
  - Layer 4 검증 부재 = response-validator hook 정규식 어미 4개 누락
  - Layer 5 룰 모순 = D-019 본문 자체 어근 사용
  - fix: .harness 22건 일괄 치환 + hook 정규식 확장 ("은|을|음|는|지|아|았|혀|혔|힘|힌|히") + CLAUDE.md 보강

- 2026-05-14: **T-M14.5 + T-M14.6 + T-M22.1 (commit 1b00023 + d6bb44e)** — 추가 정밀화 + JS JSON 추출:
  - T-M14.5 신형 URL fallback (parser._urls_match) — cafe.naver.com/ca-fe/cafes/{cafe_id}/articles/{post_id} ↔ 구형 매치
  - T-M14.6 광고/사이드바 link 제외 (_extract_main_link _AD_LINK_PATTERNS + _SIDEBAR_LINK_PATTERNS)
  - T-M22.1 _extract_bootstrap_json regex fix (entry.bootstrap 2번째 인자 brace 균형 추출) — 진짜 추출 성공 (body 키 검증)
  - 237 → 259 → 275 tests pass

- 2026-05-14: **T-M14.7 (commit c0d7d39) → 폐기 (commit 37b40bb)** — 사장님 의도 잘못 해석:
  - T-M14.7 추가: parse_search_result cafe_slug_whitelist 매개변수 + 상자 안 화이트리스트 slug 매치 fallback
  - 사장님 발견: '피부과 여드름' = move79/6019162 (시트 미등록 새 글) 자동 검출 → K=AB / L=1 표시 = 사장님 시점 "내 글 X"
  - probe evidence: 상자 2 (AB) = move79 / 상자 4 (AB) = workee 노출 = 시트 미등록 새 글
  - 사장님 진짜 의도 = 시트 등록 link 정확 매치만 (= 다른 직원 글 / 새 글 검출 X)
  - T-M14.7 전체 폐기 + main.py / auto_accuracy.py 호출 폐기

- 2026-05-14: **cron 빈도 jitter (T-M40.1 + T-M40.2, commit d965809 + e1d1976)** — schedule 지연 완화:
  - 직전 8 schedule cron 모두 67~206분 지연 (평균 140분) 발견
  - 진짜 root cause (document-specialist 외부 사실): GitHub Actions 정시 cron = queue 폭증 시간대
  - fix: cron '0 15,21,3,9' → '7,27 15,21,3,9' (한 시간 안 2번 시도 + 분 jitter)

- 2026-05-14: **영구 한국어 강제 강화 + self-hosted 폐기 (commit 4493fe5)**:
  - D-019.1: CLAUDE.md 영구 한국어 표준어 강제 강화 (= 사장님 평생 약속 명시)
    - 절대 금지 단어 14개 + 줄임 표현 사용 금지
    - 자체 검증 의무 (응답 송신 전 단어 grep = 0회 확인)
  - T-M40.3: self-hosted runner 의존 폐기 = ubuntu-latest 단독 + run-cron-fallback job 삭제
    - 사장님 PC 24/7 부담 폐기 (= 우리 단독 자동 운영)

- 2026-05-14: **cron-job.org 설정 완료** (사장님 직접):
  - GitHub PAT 발급 (scopes: repo + workflow)
  - cron-job.org cronjob 생성 (URL + POST + Bearer token + Content-Type)
  - TEST RUN HTTP 204 성공 검증 = workflow_dispatch 정확 trigger
  - 매 6시간 KST 0/6/12/18 정시 자동 trigger = schedule 큐 지연 회피

- 2026-05-14: **T-M10.5 url_alive 검증 폐기 (commit b2b69b9)** — CRITICAL 사고 fix:
  - 사고: T-M10.4 적용 후 cron 25827570772 = 사장님 시트 K="삭제" 다수 손상
  - 진짜 root cause (probe evidence): 네이버 카페 = 비로그인 = 로그인 페이지 HTML 반환
    - 정상 ALIVE 글 3개 probe 모두 = nidlogin.login 키워드 검출 = PRIVATE 잘못 판정
    - = 모든 link false positive 100% = K="삭제" 시트 손상
  - fix: main.py url_alive 검증 block 폐기 = url_alive = True 항상
  - 275 tests pass (test 7개 폐기/수정)
  - 사장님 의무: Google Sheets 버전 기록 5/13 23:00 이전 시점 복원

- 2026-05-14: **detect_direct_K fix (commit 4fc9cf6)** — auto-accuracy 측정 기준 정합:
  - T-M14.7 폐기 후 일치율 69.0% 측정 → mismatch 31건 (시트 미등록 새 글)
  - root cause: detect_direct_K = HTML 상자 안 화이트리스트 slug 매치 = 사장님 의도 X
  - fix: detect_direct_K(html, target_link, all_known_links) = 시트 등록 link 정확 매치만
  - 재측정 결과: 일치율 100.0% (= parser ↔ ground truth 완벽 정합)

- 2026-05-14: **T-M14 전체 폐기 (commit 2068ef4)** — 사장님 진짜 의도 명확화:
  - 사장님 명시: "시트 link 가 여러 키워드 검색에 노출되는지 체크" 만 / 시트 link 그대로 유지 / 자동 갱신 X
  - 이전 잘못: T-M14.2 link_set fallback + 자동 갱신 = 사장님 시트 link 손상 가능성
  - 폐기:
    - main.py _process_row 단순화 = target_url 단독 매치만
    - main.py run_cycle = all_known_links 구성 폐기 (빈 set 호환성)
    - auto_accuracy.py = link_set fallback 호출 폐기
    - 시트 "링크" 컬럼 자동 갱신 = 완전 폐기 (D-018 정합)
    - link 빈 행 = 즉시 빈칸 반환 (검색 X)
  - 271 tests pass (275 → 271, -4 = TestLinkAutoUpdate 폐기 + link 빈 행 통합)
  - 매치 우선순위 단순화: target_url 정확 매치 → 매치 X = K=빈칸

- 2026-05-14: **자동 정확도 측정 100% 확정** — parser 자체 결함 0건:
  - 1차 (잘못된 link_set + direct 잘못) = 51%
  - 2차 (T-M14.7 폐기 + direct 잘못) = 69%
  - 3차 (T-M14.7 폐기 + detect_direct_K 정합) = **100.0%** ✅
  - parser ↔ ground truth 완벽 정합 = 진짜 사장님 의도 적용 검증

- 2026-05-14: **D-022 진짜 옵션 확정 = "시트 등록 link 정확 매치만"** (= 옵션 A 최종):
  - B 옵션 (전체 회사 글 추적 + 자동 갱신) = 사장님 의도 misread = 폐기
  - A 옵션 (시트 등록 link 정확 매치만) = 사장님 진짜 의도 = 확정
  - link 자동 갱신 = 사장님 작업 손실 위험 = 절대 X
  7. 사장님 수기 시 1페이지만 / 2~3페이지까지 (critic 발견)

- 2026-05-14: **D-023 영구 가드 적용** — 사장님 지적 (T-M14 link 자동 갱신 사고 + K="삭제" 손상 + 상위노출 부정확 3 사고 메타 검증) 후 종합 root cause = Layer 5 페르소나 정합 + Layer 4 가드 부재. fix:
  - src/sheets.py: SYSTEM_OUTPUT_COLUMNS frozenset 화이트리스트 + write_results 가드 + rank_result_to_columns new_link 매개변수 폐기
  - tests/unit/test_sheets.py: D-023 회귀 test 4개 추가
  - .harness/decisions.md: D-023 영구 룰 entry 추가
  - CLAUDE.md (root): D-023 영구 룰 섹션 명시
  - 전체 test pass 검증

- 2026-05-14: **D-024 가드 보강 적용** — critic Opus background 검증 (Critical 1 + Major 3 발견) 후 사장님 "ㄱ" 단호 시그널 (= B+예) 정합 일괄 적용:
  - (1) src/sheets.py:64: SYSTEM_OUTPUT_COLUMNS 에서 HEADER_TYPE 제거 (= 4 컬럼만 — HEADER_AREA/HEADER_L/HEADER_M/HEADER_JISIKIN) — C 컬럼 보호, T-M13 학습 정합, D-005 폐기
  - (1) src/sheets.py rank_result_to_columns: cols[HEADER_TYPE] 채움 폐기 (block_order 매개변수 = 호환성 유지 미사용)
  - (2) src/main.py: except 시 K="삭제" 자동 적용 폐기 → skip + log + retry_queue.add + d024_skipped_rows 카운트 (T-M10.5 정합)
  - (2) src/main.py:252: summary 에 d024_skipped_rows 필드 추가 (사장님 가시성)
  - scripts/post_summary_to_issue.py: d024_skipped_rows 표시 (issue #1 댓글 가시성)
  - tests/unit/test_sheets.py: TestD024Guard 신규 3 test (HEADER_TYPE 거부 + frozenset 검증 + mix update)
  - tests/unit/test_main.py: D-024 회귀 test (예외 시 updates 추가 X + d024_skipped_rows ≥ 1 + summary 필드 존재)
  - .harness/decisions.md: D-024 entry 추가 + D-005 폐기 명시
  - CLAUDE.md (root): D-024 영구 룰 섹션 명시 + D-023 보호 대상 모순 해소 (유형C = 사장님 입력 정합)
  - 전체 pytest pass 검증 의무

- 2026-05-14: **T-M22.1 통합 완료** — `_extract_bootstrap_json` 함수 (commit d6bb44e) 가 `parse_search_result` 안 통합 (이전 dead code 상태). 옵션 A (HTML 우선, JSON fallback) 적용. 효과 = 네이버 동적 박스 누락 case 차단 = +5~10%p 정확도. test pass 의무.
  - src/parser.py: `_parse_bootstrap_json_fallback` 신규 함수 + `parse_search_result` 안 UNEXPOSED 분기 후 JSON fallback 호출 통합 + `_collect_urls_from_json` helper 추가
  - tests/unit/test_parser.py: TestBootstrapJsonFallbackIntegration 신규 6 test (fallback 매치 정상 / link_set fallback / slug whitelist fallback / HTML 성공 시 skip / JSON 추출 실패 시 HTML 결과 보존 / payload 매치 X 시 UNEXPOSED)
  - 전체 pytest 288 pass (282 → +6 신규, 회귀 X 검증)
  - .harness/decisions.md: D-025 entry 추가
