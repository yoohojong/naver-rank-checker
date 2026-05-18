# Decisions Log: naver-rank-checker

기록 형식: `[날짜] 결정: 무엇 / 근거: 왜 / 대안: 무엇을 안 골랐고 왜`

---

## 2026-05-05

### D-001: 외주본 그대로 안 쓰고 자체 제작
**결정**: 프로그램88 외주본(33만원) 두고 별도 자체 제작
**근거**: 외주본 안정성 부족 (백신 충돌, naver.me 미인식 등) + Google Sheets 자동연동 + 매시간 갱신 핵심 미충족
**대안 안 고른 이유**:
- 외주본에 추가 기능 의뢰 → 5만원/회 + 대기 + 코드 변경 시 같은 사이클 반복
- 기존 외주본 유지하면 Sheets 자동화 영영 안 됨

### D-002: 실행 환경 = GitHub Actions 공개 저장소
**결정**: GitHub Actions on public repo
**근거**: 진짜 무료 + 무제한 + 카드 등록 불필요 + 1000+ 무제한 스케일에서 6h 한도 안 닿음
**대안 안 고른 이유**:
- Railway: $5 크레딧 기반 = "사실상 무료"지만 사장님 "돈 내기 싫음" 강조
- Google Apps Script: 개인 구글 계정 일일 90분 한도 → 1000개급에서 빠듯
- Oracle Cloud Always Free: 진짜 평생 무료지만 Linux 서버 직접 관리 = 비개발자에게 가시밭길
- Cloudflare Workers: 30초 실행 한도 → 부적합

### D-003: 코드 구조 = Modular B (6개 모듈)
**결정**: src/ 아래 crawler / parser / sheets / cache / retry / health / main 분리
**근거**: 99%+ 견고성 + 코드 변경 자동 감지 헬스체크 + 무제한 스케일 + 사장님이 "여기만 수정" 요청 쉬움
**대안 안 고른 이유**:
- 단일 모놀리스(A): 견고성 약함, 1000+ 스케일에서 단일 파일 무거움
- Playwright 브라우저 자동화(C): 매 실행 Chrome 설치 1~2분 누적, 메모리 ↑, 디버깅 어려움. HTTP로 충분

### D-004: Sheets 매핑 = 헤더 이름 기반
**결정**: 코드는 1행 헤더에서 "키워드", "URL" 등 정확한 이름 찾아 매핑
**근거**: 사장님이 시트 열 이동/추가할 가능성 명시 → 고정 위치 매핑 시 코드 깨짐
**대안 안 고른 이유**:
- 고정 위치 (A=키워드 가정): 깨지기 쉬움
- config 시트 매핑: 사장님이 매핑 직접 관리해야 함 (복잡)

### D-005: C 유형 컬럼 자동 채움
**결정**: 프로그램이 매 실행마다 검색 결과 탭/블록 순서 추출해 C 컬럼 자동 갱신
**근거**: 1000개 매번 수동 입력 비현실. 어차피 K(노출영역) 판정하려면 페이지 구조 파싱 필수 = 마진 비용 0
**대안 안 고른 이유**:
- 수동 입력 유지: 사장님 부담
- 한 번만 자동, 이후 안 건드림: 네이버 검색 결과 변하면 stale

**폐기 — D-024 (2026-05-14)**: C 컬럼 = 사장님 의도 기록 (T-M13 학습 정합) = 자동 갱신 X. critic Opus 발견 Critical 1 정합.

### D-006: 카페명/게시판 자동 추출 + 캐싱
**결정**: 첫 발견 카페는 페이지 fetch해서 정식명 추출 → "카페매핑" 별도 시트에 저장 → 사장님이 짧은 이름만 추가 입력 → 이후 자동 적용
**근거**: 1000행 매 실행 fetch는 무리. 카페/게시판은 정적 정보 = 캐시 1회로 끝. 헤비함 무시 가능 수준
**대안 안 고른 이유**:
- 매번 fetch: 4000회/일 추가 요청 → 차단 위험
- 자동 줄임: "아이러브 부산맘" → "부산맘" 같은 줄임은 사람의 감각, 자동화 불가

### D-007: 인기글 별도 파싱 로직
**결정**: 통합탭(AB) 파싱과 별도 분기로 인기글 처리
**근거**: 사장님 명시 ("인기글은 별도 로직임")
**대안 안 고른 이유**:
- AB 안의 카페로 통합 처리: 사장님 워크플로우와 안 맞음

### D-008: 실패율 99%+ 목표 (100% 보장 X)
**결정**: 재시도 큐 + 슬로우다운으로 사실상 99.9% 도달, 100% 보장 안 함
**근거**: 무료 환경 + 단일 IP에서 100% 보장은 기술적으로 불가능. 유료 프록시 풀 쓰면 가능하지만 "돈 X" 제약과 충돌
**대안 안 고른 이유**:
- 유료 프록시: 비용 발생
- 100% 약속: 거짓말. 외주본도 100% 못 함

### D-009: 네이버 코드 변경 자동 감지
**결정**: 헬스체크 모듈이 파싱 성공률 90% 이하면 시트 비고에 자동 알림
**근거**: 외주본 대비 가장 큰 차별화. 5만원/회 유지보수 사이클 끊음
**대안 안 고른 이유**:
- 본인이 매번 시트 보고 알아챔: 인지 부담

### D-010: 하네스 위치 = per-project (.harness/ in project folder)
**결정**: `D:\claude code\naver-rank-checker\.harness\` 안에 spec/plan/tasks/decisions
**근거**: 단일 진실 원천, 백업/이동 시 한 폴더, 비개발자 멘탈 모델 단순, Git 친화적
**대안 안 고른 이유**:
- 중앙 집중 (`D:\claude code\harnesses\`): 코드/하네스 두 곳 관리, desync 위험, 멘탈 복잡

### D-014: 멀티 Claude 병렬 지원 (filesystem mkdir lock)
**결정**: 하네스에 `claims/` 디렉토리 + `PROTOCOL.md`. 각 task claim은 `mkdir .harness/claims/T-{id}/`로 원자적. 병렬 안전.
**근거**: 사장님 처음 의도가 "여러 Claude 동시에 같은 하네스 기반 작업"이었음. 단일 Claude 모드만 추천한 것은 사장님 의도와 어긋남. mkdir은 OS 수준에서 원자적 → 데이터베이스 등 인프라 추가 없이 안전한 lock 가능.
**구현**: 
- `.harness/claims/T-{task_id}/` 폴더 생성 = claim 성공
- 폴더 안 `info.txt` = 누가/언제 (디버깅용)
- 작업 완료 시 폴더 삭제
- tasks.md에 의존성/병렬 가능성 표 추가
**대안 안 고른 이유**:
- 단일 Claude만: 사장님 그림과 다름. 30개 task 의존성 사슬 있긴 하지만 병렬 가능 그룹도 명확히 존재 (인프라, 모듈별)
- 외부 큐 (Redis): 무료 운영 + 단순성 위배
- tasks.md 인라인 claim: 같은 파일 동시 쓰기 race 가능, mkdir보다 위험

### D-013: K 컬럼에 `노출중지` 추가, `비실계의심` 제거
**결정**: K 컬럼 enum에서 `비실계의심` 제거하고 `노출중지` 추가. `노출중지` = "이전에는 노출되었는데 지금은 안 나옴". 시트의 이전 K 값과 비교해서 자동 감지.
**근거**: `비실계의심`은 자동 단정 불가 (낮은 순위/저품질/인덱싱 지연 등 여러 원인이 같은 증상). 거짓 단정 위험. 반면 `노출중지`는 명확히 검증 가능한 사실 (이전 vs 현재 비교). 사장님이 "떨어진 것"을 아는 게 가장 유용.
**구현**: 추가 컬럼/외부 상태 X. 시트의 K 컬럼이 이미 이전 결과 보관 중이므로 sheets.py에서 read-then-write 패턴으로 무료 구현.
**대안 안 고른 이유**:
- 비실계의심 유지: 부정확 (여러 원인 통합) → 사장님 잘못된 판단 유발 가능
- 순위 변동 화살표 (옵션 2): 정보량 ↑이지만 노이즈 ↑. K의 `노출중지`만으로 핵심 신호 충분. L/M/N 숫자 직접 보면 등수 변동 인지 가능.

### D-012: 시트 출력 = K~O만, 알림은 GitHub Actions logs
**결정**: 데이터 시트에는 사장님 기존 K~O 컬럼만 갱신. 별도 메시지/알림/실패카운트는 시트에 X. K(노출영역)이 status를 enum으로 다 표현 (AB/스마트블록/인기글/미노출/삭제됨/비공개/비실계의심/실패)
**근거**: 사장님 명시 ("메시지를 엑셀에 남겨줄 필요는 없긴 한데"). 시트 깔끔 유지 + 운영 정보는 GitHub Actions logs로 충분 (필요 시만 확인)
**대안 안 고른 이유**:
- P/Q 컬럼 추가 (실패카운트/에러메시지): 사장님 의도와 반대, 시트 더럽힘
- A1 셀 헬스 알림: 시트 데이터 영역 침범
- 별도 알림 채널 (Telegram, email): 0원 운영 + 단순성 우선, 추후 필요 시 추가 가능
- 5회 연속 실패 추적: 영속 상태 필요 → 시트 컬럼 또는 외부 DB 필요 → 복잡도 ↑. 매 cron이 독립적이고 영구 실패는 패턴으로 인지 가능

### D-011: 메타 시스템 = 4-pillar (Slim CLAUDE.md + Smart hook + Stop hook + Per-project harness)
**결정**: 항상-on 풀텍스트 리마인더 폐기, 패턴 트리거 + 응답 검증으로 전환
**근거**: 사장님이 "왜 자꾸 안되지?" 반복 지적 → systematic-debugging Phase 1 결과 "텍스트 룰 + 판단 의존 = 슬립" 진단. 패턴 트리거 + Stop hook 검증이 진짜 enforcement
**대안 안 고른 이유**:
- 더 많은 텍스트 룰: 노이즈 증가, 슬립 패턴 동일
- 응답 차단(decision: block): 너무 공격적, 첫 버전은 정정 주입만

---

## 2026-05-11

### D-017: GitHub Actions self-hosted runner on 사장님 PC + 4 fix push + 결과 손상 발견 + 차단 회피 재검토
**결정**:
1. **인프라 이전**: GitHub Actions ubuntu-latest (Azure IP 차단) → **self-hosted runner on 사장님 PC** (Windows 11 Home, 가정용 ISP IP). repo Public→Private. workflow yml self-hosted 정합 (setup-python 제거 / shell powershell / PATH 갱신).
2. **4 fix push (commit 73e7dca)**:
   - CRITICAL: post_summary_to_issue.py 의 K 분포 + 탭 이름 (사장님 비즈니스 데이터) 제거 → 메타만
   - Major 1: SlowdownController CircuitBreakerOpen + on_success ×0.5 (27시간 폭주 위험 fix)
   - Major 2: _parse_popular L/M 분리 (AB 동일 로직, blog target → M=None)
   - tests 4 갱신 + 신규 → 151/151 pass
3. **cron run 25647821456 결과 = 사장님 시트 손상 발견 + workflow disable + 사장님 복원**.

**근거**:
- document-specialist (외부 사실): GitHub Actions Azure IP = anti-bot 표준 트리거. residential IP > datacenter IP base trust.
- critic (메타 챌린지): self-hosted 결정 ACCEPT-WITH-RESERVATIONS (PC 24/7 부담 ≠ critical).
- architect (구현 결함): 4 fix push 후 진짜 evidence (실 cron log) 확인 — 차단 누적 + retry "삭제" 입력됨 + L/M 분리 부작용.

**진짜 root cause (log evidence + tracer)**:
1. main.py 의 retry 실패 → K="삭제" 적용 logic = critic 2026-05-08 권장이었으나 **차단 ≠ 삭제** 의미 충돌. 사장님 작업자 혼란.
2. _parse_popular L/M 분리 → blog target M=None 적용됨 (이전 L=M 컨벤션과 다름).
3. _parse_smart_blocks deprecated (항상 False) → 이전 스마트블록 행 UNEXPOSED.

**미래 fix 의무 (사장님 결정 대기)**:
- main.py 의 retry 실패 → K 보존 (시트 갱신 안 함, 다음 cron 자연 재처리)
- L/M 분리 fix 진짜 효과 검증 (사장님 실 데이터 정합)
- _parse_smart_blocks 진짜 다시 활성 or popular 정합 검증

**대안 안 고른 이유 (사장님 절대 제약)**:
- Oracle Cloud Always Free: 데이터센터 IP = anti-bot 트리거 (GitHub Actions 와 같은 카테고리). Seoul capacity 부족. 가입 영문 + 카드 verification.
- 외주본 program88 33만원 재구매: D-001 사장님 자체 제작 결정 위반.
- 행 수 줄이기 (832 → 200): 사장님 명시 거절 ("832 다 필요").
- 유료 프록시: D-002 0원 운영 위반.

---

### D-016: J false positive fix (parser._parse_jisikin h2 narrow) + 나머지 mismatch 시점 차이 미루기
**결정**:
1. **J false positive 69건 즉시 fix** — _parse_jisikin 을 "h2 텍스트 = '지식iN'/'지식인' 박스 안 kin 링크" 로 narrow (M4.9 인기글 패턴 동일).
2. **나머지 mismatch (false negative 42 + false positive 11 + 분류 11 = 64건) 추가 fix 미루기** — T-M8.3 실 cron 후 같은 시점 비교까지 보류.

**근거**:
- 사장님 시트 500행 정밀 분석 (.harness/comparison-500-after-fix.json) 결과:
  - J false positive 69건 = **전부 cafe.naver.com 링크 + h2 없는 박스의 부수 kin 링크**. parser 의 명확한 시점 무관 버그. fix 명확.
  - 나머지 64건 mismatch = `_urls_match` 코드 점검 결과 query (`?art=`) 무시 정상 동작. path 다른 글이 노출됐다 = **사장님 수기 시점 vs 비교 시점 차이** (네이버 검색 결과 시간당 변동) 가능성 ↑.
  - 동일 키워드/링크 (pusanmommy/1443962) 가 두 행에 m=인기글/p=AB 와 m=인기글/p=AB 식으로 나옴 = 시점 차이 확정 신호.
- 사장님 수기에 parser 끼워맞추면 quality ↓ 위험. 진짜 fix 는 같은 시점 비교 (T-M8.3 실 cron 후) 가 정확.

**구현**:
- parser.py:_parse_jisikin → h2 텍스트 narrow (커밋 메시지: "fix(parser): jisikin false positive — h2 narrow to 지식iN box only").
- 기존 test 2개 (smart_block.html 의 임의 kin 링크 True 가정) → smart_block.html 의 h2 박스 0개 사실 반영, 의미 변경 (False).
- 새 unit test 4개 추가: h2='지식iN' 박스 True / 한글 '지식인' True / h2 없는 박스 부수 kin False (회귀 방지) / target kin URL + h2 없는 박스 False.
- 6/6 jisikin tests pass, 전체 148/148 tests pass (145 → 148, J v2 +3).

**대안 안 고른 이유**:
- false negative 42건 selector 강화: 사장님 수기 stale 가능성 ↑. 일방적 fix 위험. 같은 시점 비교 데이터 없음.
- AB↔인기글 분류 경계 fix: 동일 링크 m/p 교차 사례 = 시점 차이 확정. 코드 fix 보단 시점 일치 후 재비교.
- 사장님 수기 stale 만 가정하고 다 무시: J 같은 진짜 버그 놓침. 단일 케이스 분석 + 시점 무관 케이스만 fix.

**T-M8.3 검증 가이드** (사장님 GitHub repo 만든 후):
1. 실 cron 1회 수동 트리거
2. 그 직후 사장님이 다시 같은 키워드 500개 수기 검사
3. parser 결과 vs 같은 시점 수기 → 추가 fix 필요한 케이스 분리

---

### D-015: T-M5.5 (카페매핑 시트 read/write) SKIP
**결정**: T-M5.5 영구 skip. plan.md 의 코드 보존 (미래 재활성화용), tasks.md 표 ⏭️ skipped 표시.
**근거**:
1. 사장님 실 시트 검증 (2026-05-08): 832행 / 3 "카외" 탭 / 15개 헤더. "카페매핑" 탭 자체가 없고, K~O 컬럼 어디에도 카페명/게시판 정보 안 씀.
2. D-012 (시트 출력 = K~O만): 카페명/게시판은 K 컬럼 enum 값으로 충분 표현 → 별도 영구 매핑 불필요.
3. 메모리 캐시 (T-M6.1 CafeMappingCache) 가 cron 사이클 1회 안에서 중복 fetch 방지 보장. 한 cycle 안에서 같은 카페 100번 등장해도 fetch 1회. cron 사이클 간 캐시 안 됨 = OK (cycle 당 카페 종류 적음, 비용 무시 수준).
4. D-006 (카페매핑 자동 추출 + 캐싱) 은 spec 초기 가정. 2026-05-08 사장님 컨벤션 정정 후 spec drift 발견 — 사장님 시트엔 카페매핑 컬럼 자체 없음.
**대안 안 고른 이유**:
- 그래도 구현: 사장님 시트에 없는 탭에 쓰기 시도하면 의도치 않은 새 탭 생성 위험. 사장님 시트 오염 가능.
- 메모리 캐시 폐기: M6.1 이 이미 한 cycle 내 중복 fetch 방지로 가치 있음, 유지.
- 사장님께 "카페매핑 탭 만드시겠어요?" 묻기: 사장님은 시트 깔끔 + 자동화 우선. 도구가 운영 자료 더 늘리면 부담.
**미래 재활성화 조건**: 사장님이 카페명/축약명 자동 채움 요청하면 plan.md 의 T-M5.5 코드 그대로 가져다 쓰면 됨 (gspread WorksheetNotFound → add_worksheet 패턴).


## 2026-05-12

### D-018: T-M13 학습 — 사장님 의도 모호 시 우리 단호 결정 금지

**결정**: 사장님 메시지에 "OR" 시그널 (이거 하던가 저거 하던가 / 둘 다 가능 / 상관없어) 있을 때 = 우리가 단호 결정하지 않는다. 사장님 1줄 결정 받음 의무.

**근거**:
- 2026-05-12 T-M10 적용한 결과 (link 빈 row 도 검색 + 첫 카페 선택) = 사장님 의도 정합 X
- 사장님 직전 메시지 = "그냥 ... 박던가 ... 박던가" OR 있음
- 우리가 옵션 A 단호 선택함 = 832 행 link 빈 row 에 K/L/M 잘못 입력됨 = 사장님 시트 손상
- 진짜 사장님 의도 = link 빈 row = 마케팅 예정 (작업자 빈) = 처리 제외
- T-M13 revert + 사장님 시트 정리 진행

**영구 룰** (CLAUDE.md 추가):
1. "OR" 시그널 있을 때 = 사장님 1줄 결정 받은 후 진행
2. 사장님 시트 컨벤션 변경 (마케터 작업 흐름 / 새 동작 / 스키마 영향) = sample 제출 또는 사장님 OK 받음
3. 비즈니스 컨텍스트 (마케터 시점, 작업자 빈 = 예정) 깊이 이해한 후 결정

**대안 안 고른 이유**:
- 모호한 상황에 단호 결정 = 사장님 페르소나 정합 맞는 듯하지만 진짜 의도 파악 못할 risk ↑
- 사장님 매번 1줄 결정 = polling 느낌 가능하지만 모호 시점 = 안전 우선


### D-019: T-M14 메타 학습 — 한국어 표준어 강제 + 사장님 지적 후 메타 룰 의무

**결정**: Claude 응답 + 모든 문서에 한국어 표준어 사용 강제. "박" 동사 어근 사용 금지. 사장님 지적 후 단순 fix X — 메타 학습 영구 룰 추가 의무.

**근거**:
- 2026-05-12 KST 08~09 사장님 강한 짜증 신호: "박음이라는 말투는 왜 쓰는거임?" + "박음이라는 말도 쓰지 말라고 했지 지금 너 내가 말하는거 하나도 안지키고 있는데?"
- Claude 가 사장님 비개발자 한국어 말투 흉내 = 부적절 사용
- 사장님 직접 명시 후도 같은 응답 / 다음 응답에 또 사용 = 명시적 어김
- 메타 학습 누락 = D-018 룰 (사장님 지적 후 영구 룰 추가) 도 또 위반
- **사장님 4 지적 (말투 / 색상 / 삭제 / 순위) 종합**:
  - 말투: 매번 "박" 동사 사용 = 책임
  - 색상: T-M14 코드 적용됨 다만 cron 실패 (runner offline) = 사장님 시트 적용 X
  - 삭제: T-M10.1 적용된 cron log = "삭제" 매치 X (네이버 결과 link 다 살아있음 가능)
  - 순위: parser 정확 (Avg conf 0.88, probe 5/5)

**영구 룰** (CLAUDE.md 추가):
1. 한국어 표준어 사용 강제 (Claude 응답 + 모든 문서)
2. 사장님 지적 후 메타 학습 의무 (사과 → root cause → 영구 룰 → 재발 방지 → 코드 fix)
3. 1차 작업 후 사장님 의도 정합 검증 (sample 또는 confirm 받은 후 832 행 자동 적용)

**대안 안 고른 이유**:
- 단순 코드 fix = 같은 미스 반복 위험
- discipline 만 = 사장님 페르소나 정합 X (hook 자동 강제 의무, C-12 정합)

**재발 방지 메커니즘**:
- second-brain skill checklist.md 에 C-13 정식 등재 권장 (사장님 직접 강한 지적 = 즉시 graduate, C-11 정합)
- response-validator.mjs hook 에 "박" 어근 검출 정규식 추가 권장 (다음 turn 정정 주입)
- retro-log.md 에 누적 (2026-05-12 entry)


### D-020: T-M16 후 잔존 문제 2 case 발견 — 디벨롭 사항 종합

**결정**: T-M14/T-M16 fix 후도 사장님 검증 결과 = 2 case 잔존. 차후 디벨롭 사항 명시.

**발견된 잔존 문제** (2026-05-12 KST 13:00):

**Case A — link 빈 row 의 false 매치** (예: '민감성샴푸' → 인기글 L=2 M=1):
- probe v9 결과 = 박스 3 ("패션·미용 인기글") 에 다른 카페 link (baby8/fox5282 등) 들어있음
- 사장님 시트 link_set 안 다른 row 의 link = 우리 parser 매치 → K=인기글 표시
- 사장님 시점 = "내 카페 노출 X" → 매치된 카페 = 사장님 회사 카페 아님 (외주/타 마케터 카페 글)
- **root cause = link_set 의미 잘못. 사장님 시트의 모든 link = 사장님 회사 카페 가정 X. 다른 회사 카페도 들어있음**

**Case B — link 있는 row 의 박스 분류 잘못** (예: '닥터포헤어토닉' link=culturebloom/3171706 → AB L=7 M=3, 사장님 = 인기글):
- probe v9 시점 = culturebloom/3171706 = 박스 어디에도 없음 (시점 차이)
- 사장님 시점 = 인기글 박스에 들어있음. 우리 cron 시점 = AB 박스에 들어있음 (또는 우리가 잘못 분류)
- **root cause = parser 의 "h2 X = AB" 가정 + 사장님 컨벤션 차이 + 시점 변동**

### 디벨롭 사항 (T-M18 ~ T-M22)

**T-M18: 사장님 카페 화이트리스트 도입**
- link_set = 사장님 회사 카페 slug 화이트리스트만 매치 (예: pusanmommy, cosmania, iroid, mindy7857, multiroader 등 사장님 작업 cafe slug)
- 다른 카페 slug = 매치 X
- 또는 = `_carea_filter` 식으로 사장님 작업 cafe slug 정의 의무
- 우선순위 ↑

**T-M19: parser 박스 분류 사장님 컨벤션 동기화**
- "h2 X = AB" 가정 = 잘못 검증됨 (블로그 모음 / 광고 박스도 h2 X)
- 진짜 AB 박스 = 사장님 시점 정의 의무 (사장님 직접 화면 보고 "이 박스 = AB", "이 박스 = 인기글" 명시)
- 또는 = AB = 카페 link 들어있는 h2 X 박스 만
- 또는 = 네이버 특정 css class (예: fds-root-overflow-reset 등) 기반 분류

**T-M20: 시점 차이 동기화 + timestamp 시트 표시**
- cron 시점 ≠ 사장님 검증 시점 = 네이버 결과 변동 (1시간 단위)
- 시트 어딘가 (예: 메모 컬럼) 에 cron timestamp 추가 = 사장님 = "이 시점 결과" 인지 가능
- 사장님 검증 시점 = timestamp 확인 → "지금과 다른 시점" 정합 가능

**T-M21: link_set 매치 시 매치 row 번호 시트 표시**
- link 빈 row 매치 시 = K 컬럼에 "AB (행 47)" 식 표시
- 사장님 = 행 47 확인 → 그 link 확인 → 우리 카페 글인지 검증
- 다만 K 컬럼 형식 변경 = 다른 도구 영향 ↑

**T-M22: 사장님 시점 박스 종류 정확 정의 의무**
- 사장님 직접 네이버 결과 화면 보고 박스 종류 명시 (5개 박스 각각 = AB / 인기글 / 광고 / 기타)
- 사장님 컨벤션 정확 정의 → parser 동기화

**대안 안 고른 이유**:
- 단순 T-M14/T-M16 fix = 잔존 문제 (Case A/B) 해결 X
- link_set 매치 자체 비활성화 = 사장님 의도 "다른 키워드 노출 추적" 반영 X

**근거**:
- probe v9 직접 검증 (2026-05-12 KST 13:00)
- 사장님 명시 2 case (민감성샴푸 / 닥터포헤어토닉)


### D-021: 정확도 42% → 95% 종합 최종 plan (4 agent 검증 + Phase 0 실행)

**결정**: 사장님 발화 "정확도 100% 달성 + 모든 가능성" 의무 정합. 4 agent 종합 검증 (architect + document-specialist + planner Opus + critic Opus). Phase 0 즉시 실행, Phase 1~5 단계 진행.

**4 agent 검증 결과**:
- **architect**: 4컬럼 95% 불가능 / 70~75% 상한 확정 (사장님 컨벤션 자체 일관 X). 누락 root cause 2개 (parser 첫 페이지만 / `_extract_main_link` 휴리스틱 약함)
- **document-specialist**: Chrome131 = 구버전 (curl_cffi 0.15.0 진짜 지원 chrome146 최신). Cookie warmup 효과 ↑. 6시간 정시 cron = 봇 패턴
- **planner Opus**: 22 task / 6 Phase plan 작성. 50 가능성 발산 + P0~P3 수렴. 정확도 추정 Phase 5 K 93~97% / 4컬럼 87~95% (다만 critic = 과대 평가 확정)
- **critic Opus FIX-THEN-PROCEED**: planner 추정 15~20%p 과대 평가. 진짜 상한 = K 88~92% / 4컬럼 65~75% (동일 시점 기준). plan 보완 의무 7개 (CRITICAL 3 + MAJOR 4)

**정확도 진솔 답** (D-008 정합):
- 100% = 기술적 불가능 (시점 차이 + 네이버 개인화 + 사장님 수기 자체 오차)
- 진짜 가능 상한 = **K 88~92% / 4컬럼 65~75%** (Phase 5 정착 후, 동일 시점 기준)
- 가장 큰 fix 효과 = 사장님 L/M 컨벤션 1줄 확정 (4컬럼 +10%p ↑ 가능)

**Phase 0 즉시 실행 완료** (2026-05-12):
- T-M23: USER_AGENTS 모바일 UA 제거 → PC Chrome 4종 (146/145/146 Mac/136)
- T-M24: SlowdownController.wait() = config NAVER_SLOWDOWN_BASE_SEC=5.0 진짜 정합 (5~7.5초)
- T-M24b: Crawler.warmup() 추가 = 네이버 메인 1회 fetch 후 검색 (Cold session 차단 회피)
- T-M24c: IMPERSONATE_POOL = chrome146/145/136/131 매 인스턴스 random 회전
- T-M25: CAFE_WHITELIST 26 slug = main.py link_set 화이트리스트 필터 적용 (Case A false positive 11건 즉시 차단)
- T-M26: Accept-Encoding "gzip, deflate, br" 헤더 추가 (브라우저 동일 행동)
- critic (e) 발견 fix: `_extract_main_link` CSS selector 1순위 5종 + 텍스트 길이 fallback (광고/관련검색 link 오작동 차단)
- 172/172 tests pass (160 → 172, +12 신규 test)

**Phase 1~5 사장님 결정 의무** (3 결정 + 4 보조):
1. 카페 slug 전체 목록 (현재 자동 추출 26 slug = 사장님 확정 또는 추가/제외 명시 의무, 5분)
2. L/M 컬럼 계산 방식 = AB / 인기글 박스 동일? 다른? (사장님 1줄 결정, 2분)
3. 박스 종류 정의 = h2 없는 블로그 박스 = AB / skip? (사장님 직접 5 키워드 화면 보고 결정, 5분)
4. 검색 빈도 6h → 3h (Phase 0~3 안정 검증 후, 보조)
5. PC 24/7 online 보장 (인프라 의무)
6. 월 1회 100 키워드 수기 검증 수용 (선택)
7. 사장님 수기 시 = 1페이지만 보나 / 2~3페이지까지? (critic 발견)

**Phase 별 정확도 추정** (critic 교정 수치):
- 현재 = K 79.4% / 4컬럼 41.9%
- Phase 0 완료 = K 82~85% / 4컬럼 50~55% (차단 회피 + 화이트리스트)
- Phase 2+3 완료 = K 85~90% / 4컬럼 60~70% (사장님 컨벤션 확정 + parser 정밀화)
- Phase 5 정착 = K 88~92% / 4컬럼 65~75% (운영 안정 + 빈도 ↑)

**Phase 1~5 다음 단계** (사장님 답 받은 후):
- Phase 1: auto_compare 스크립트 + 사장님 10 키워드 동시 검증
- Phase 2: 사장님 컨벤션 3개 확정
- Phase 3: parser L/M 분리 fix + 박스 분류 fix
- Phase 4: timestamp 시트 표시 + anomaly 감지 + retry 강화 + workflow 이중화
- Phase 5: 월 모니터링 + 자동 알림 + 키워드 difficulty 점수

**근거**:
- comparison-500-after-fix.json 310행 직접 분석 (사장님 수기 vs parser)
- 4 agent 종합 검증 (architect + document-specialist + planner + critic)
- D-008 정합 (100% 보장 X 명시)
- 0원 운영 정합 (모든 옵션 무료 검증 완료)

**대안 안 고른 이유**:
- 단순 parser fix = root cause 4종 누락 위험 ↑
- 단일 agent 검증 = 사각지대 ↑ (4 agent = 객관성 ↑)
- 100% 약속 = 거짓말 (D-001 외주본도 X)
- 유료 프록시 / Playwright = 0원 위반


### D-022: 사장님 결정 7개 우리 단호 결정 (CLAUDE.md gate 6 정합)

**결정 (2026-05-12)**: 사장님 발화 "뭔소리야 다 해결해 진행해" = 단호 시그널 = 우리 단호 결정 의무 (옵션 polling X). 7 결정 객관 최선 기반 단호 확정.

**① 카페 화이트리스트** = 자동 추출 26 slug 전부 포함 (1행 slug 4개 = firenze / trotkingpjh / hawaiiphoto / guamfree 도 포함). 근거: 사장님 카페일 수 있으니 보수 우선. 외부 카페 link (baby8 등) 자동 제외 = D-020 Case A 해결.

**② L/M 컨벤션** = L = 박스 안 전체 항목 N번째 (cafe+blog+web 포함) / M = 박스 안 카페만 N번째. AB / 인기글 박스 동일 적용. 근거: comparison-500 = L≠M 82행 (65%) / L=M 44행 (35%) = L≠M 다수. parser 현재 동작 정합.

**③ 박스 종류 정의** = h2 없음 + cafe ≥ 1 = AB / h2 없음 + cafe 0 (blog 또는 web 만) = skip / h2 있음 + 인기글 키워드 X = 인기글 / h2 있음 + 광고/이미지/AI 키워드 = skip. 근거: D-020 Case B 11건 = "h2 없음 + blog 만 들어있는 박스 = AB" 잘못 분류 fix.

**④ 검색 빈도** = 6h 유지 (Phase 0 안정 검증 후 3h 전환 검토). 근거: 사장님 PC 24/7 부담 ↓ + 차단 위험 검증 후 의무.

**⑤ PC online** = workflow 이중화 (self-hosted 우선 / ubuntu fallback 자동). 근거: PC offline 시 자동 전환 = SPOF 해소.

**⑥ 월 모니터링** = 분기 1회 50 키워드 = 사장님 부담 최소. 근거: planner 추천 월 100 키워드 = 사장님 시간 부담 ↑. 분기 1회 50 = 정확도 추적 + 부담 ↓.

**⑦ 페이지 분석** = 1페이지만 (parser 현재 정합). 근거: 사장님 페르소나 = 빠른 + 정확 우선. 2~3 페이지 확장 = parser 시간 ↑ + 차단 위험 ↑ + 사장님 작업 시점 일치 X.

**Phase 1~5 일괄 진행 의무**: 우리 단호 결정 후 Phase 1 + Phase 3 박스 분류 fix + Phase 4 workflow 이중화 + Phase 5 자동 알림 일괄 진행. executor agent 위임.

**대안 안 고른 이유**:
- 사장님께 polling = "뭔소리야" 단호 거부 시그널 정합 X (CLAUDE.md gate 6 정합)
- 다른 결정 = comparison 데이터 정합 X 또는 사장님 부담 ↑

---

## 2026-05-14

### D-023: 사장님 시트 사용자 입력 컬럼 = 자동 갱신 절대 X (영구 룰)

**결정**: 사장님 시트 사용자 입력 컬럼 = 신성. 자동 갱신 절대 X. 시스템 출력 컬럼 (K / L / M / O + 유형 C, D-005 정합) 만 갱신 허용.

**근거**:
- T-M14.2 commit `10c1ca5` (2026-05-13) = 사장님 작업 link silent 덮어쓰기 사고
- 3 사고 메타 검증 (link 갱신 + K="삭제" 손상 + 상위노출 부정확) = Layer 5 (사장님 시트 신성성 인식 부재) + Layer 4 (가드 시스템 부재) 공통 root cause
- 사장님 시점: 시트 = 마케팅 작업 흔적 = 신성. 우리 시점: 시트 = 데이터 컨테이너 = 자유 갱신 가정 = 메타 페르소나 정합 결함

**구현**:
- src/sheets.py: SYSTEM_OUTPUT_COLUMNS frozenset 화이트리스트 + write_results 가드 (사용자 입력 컬럼 write 시 거부 + log) + rank_result_to_columns new_link 매개변수 폐기
- tests/unit/test_sheets.py: D-023 회귀 test 4개 (HEADER_LINK + 입력 컬럼 + 출력 컬럼 + mix)
- CLAUDE.md (root): D-023 영구 룰 섹션 명시

**대안 안 고른 이유**:
- 코드 코멘트만 추가: 코드 자체 가드 X = 미래 재발 가능
- runtime warning 후 write 진행: 사장님 데이터 손상 = 복원 비용 ↑↑
- 사장님 시트 별도 백업 컬럼: 시트 복잡도 ↑ + 사장님 페르소나 거부


### D-024: D-023 보강 — C 컬럼 보호 + main.py 예외 시 시트 보존 (영구 룰)

**결정 (2026-05-14)**: critic Opus 검증 후 사장님 단호 시그널 "ㄱ" (= B+예) 정합 일괄 적용.
(1) C 컬럼 (유형) = 사장님 의도 기록 = 자동 갱신 폐기 (T-M13 학습 정합, D-005 폐기)
(2) main.py 예외 시 K="삭제" 자동 적용 = 폐기 (T-M10.5 학습 정합, 시트 보존)

**근거**:
1. C 컬럼: CLAUDE.md (root) line 104 "K=AB 있어도 = 사장님 시트의 'C 컬럼 (사장님 의도 기록)' 존재 = 우리가 갱신하는 K 와 분리" 명시. D-005 (C 컬럼 자동 갱신) 과 정면 모순 미해소. D-023 SYSTEM_OUTPUT_COLUMNS 에 HEADER_TYPE 포함 = T-M14.2 동일 사고 패턴 (사장님 미지적뿐 = 미래 사고 위험). critic verdict = HIGH confidence.
2. main.py 예외: T-M10.5 학습 (2026-05-14 commit b2b69b9) = "비로그인 = 로그인 페이지 = PRIVATE 잘못 판정 832행 손상" 패턴 = "예측 못한 exception = K=삭제 자동" 패턴 동일 root cause. T-M10.5 학습 시점에 같이 폐기 의무였음. critic verdict = HIGH confidence.

**구현**:
- src/sheets.py:64: SYSTEM_OUTPUT_COLUMNS 에서 HEADER_TYPE 제거 (= 4 컬럼만 남음 — HEADER_AREA / HEADER_L / HEADER_M / HEADER_JISIKIN)
- src/sheets.py rank_result_to_columns: cols[HEADER_TYPE] 채움 logic 폐기 (block_order 매개변수 = 호환성 유지 미사용)
- src/main.py: except 시 K="삭제" 적용 폐기 → skip + log + retry_queue 추가 + d024_skipped_rows summary 카운트
- scripts/post_summary_to_issue.py: d024_skipped_rows 표시 (issue #1 가시성)
- tests/unit/test_sheets.py: TestD024Guard 신규 (3 test — HEADER_TYPE write 거부 + frozenset 검증 + mix update)
- tests/unit/test_main.py: D-024 회귀 test (예외 시 updates 추가 X + d024_skipped_rows ≥ 1 + summary 필드 존재)
- CLAUDE.md (root): D-024 영구 룰 섹션 명시
- D-005 본문 끝에 폐기 명시

**대안 안 고른 이유**:
- C 컬럼 자동 갱신 유지 (옵션 A): T-M14.2 동일 사고 패턴 = 사장님 미지적뿐 = 미래 사고 위험
- main.py 예외 K="삭제" 유지: T-M10.5 학습 무시 = 사고 패턴 재발
- 사장님 결정 polling: CLAUDE.md gate 6 정합 X (단호 결정 의무) + 직전 사장님 "ㄱ" 단호 시그널 수신 완료


### D-026: 스마트블록 부활 + K 8-enum (Phase A + B + C + D + E + F 일괄 적용, 2026-05-16)

**결정 (2026-05-16)**: 사장님 D-026 종합 plan Phase A+B+C+D+E+F 일괄 즉시 적용. 사장님 단호 시그널 = polling X = 즉시 진행.

**Phase C+D+E+F 추가 적용 범위** (2026-05-16):
1. **Phase C+D — 빈 link 자동 채움 + K="중복노출"**
   - `ExposureArea.DUPLICATE = "중복노출"` enum 신규 추가 (= 8 unique value)
   - `main.py _process_row`: 빈 link 행 + all_known_links 매치 → K="중복노출" + HEADER_LINK 자동 채움
   - `main.py run_cycle`: all_known_links 구성 부활 (= 전체 시트 link union, CAFE_WHITELIST 필터)
   - `transitions.compute_new_K`: EXPOSED_VALUES = {"AB", "스마트블록", "인기글", "중복노출"} 확장
   - `sheets.SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK` frozenset 신규 = 빈 link 행만 HEADER_LINK write 허용
   - `sheets.write_results`: 행 현재 link 값 read → 빈 link 행만 EMPTY_LINK 화이트리스트 사용, 기존 link 행 = D-023 가드 그대로
2. **Phase E+F — 삭제 텍스트 검출 + K="삭제"**
   - `crawler.fetch_cafe_url_status` 부활 (T-M10.5 reverse)
   - 검출 패턴: "게시글이 삭제되었습니다" (= 사장님 명시 exact substring) + 우산 패턴 "삭제된 게시물입니다" / "존재하지 않는 게시글"
   - 로그인 페이지 / 404 / 네트워크 fail = UNKNOWN (= 시트 보존, T-M10.5 학습 정합)
   - `compute_new_K(deletion_detected=...)` 인자 신규 = True → 즉시 K="삭제"
   - `main.py _process_row`: 검색 미노출 + link 있음 = fetch_cafe_url_status 호출 = deletion_detected 판정
3. **색상 5종**:
   - 삭제 = 노란 (T-M14 정합 유지)
   - 누락 = 오렌지 (= 떨어짐 경고)
   - 중복노출 = 파란 (= 신규 발견)
   - 미노출 = 옅은 회색
   - AB / 스마트블록 / 인기글 / 빈 = 흰색 (reset)
4. **위험 1 fix (사장님 시트 832 행 보호)**:
   - prev_K="삭제" + 검색 미노출 + 텍스트 검출 X → "삭제" 보존 (= 자동 "누락" 마이그레이션 X)
   - 근거: 사장님 시트 기존 "삭제" 값 = 진짜 삭제 = 보호 의무

**적용 범위** (Phase A+B 기존):

**적용 범위**:
1. **Phase A — 스마트블록 부활** (D-022 ① 폐기 정합)
   - `_parse_smart_blocks` 부활 (= 이전 deprecated `return False` 폐기)
   - 분류 규칙: h2 자손 있음 + skip 패턴 X + "인기글" 키워드 X = 스마트블록 박스
   - "인기글" 키워드 박스 = `_parse_popular` 책임 (= 분기 분리)
   - `_detect_block_order` 갱신 = "인기글" 키워드 + h2 = 인기글 / 그 외 h2 = 스마트블록
2. **Phase B — K 3-enum 도입** (사장님 컨벤션 명확화)
   - `ExposureArea` enum 갱신: AB / 스마트블록 / 인기글 / 미노출 / 누락 / 삭제 / 실패 (7개 unique value)
   - `DROPPED = "누락"` 신규 (= 박스 빠짐, 이전 노출 → 현재 X)
   - `UNEXPOSURE_STOPPED` / `PRIVATE` alias 폐기 (T-M10.5 학습 정합)
   - `compute_new_K` 3-분기: 검색 노출 / 누락 / 미노출
     - 검색 미노출 + prev_K in EXPOSED_VALUES → "누락"
     - 검색 미노출 + prev_K in {"미노출", ""} → "미노출"
     - 검색 미노출 + prev_K in {"누락", "삭제"} → "누락" 유지 (자연 회복 가능)
     - url_alive=False → "삭제" (Phase E 텍스트 검출 도입 후 진짜 활용)
   - `EXPOSED_VALUES = {"AB", "스마트블록", "인기글"}` (= 스마트블록 부활)
   - `SYSTEM_K_VALUES` 갱신 = 7개 + "" (= 사장님 수동 편집 보존)
   - `rank_result_to_columns` "미노출" 명시 표기 (= sheets.py:241 결함 fix)
     - 근거: 사장님 시점 빈 칸 = "조사 안 됨" 혼동 root cause fix

**근거**:
- 사장님 진짜 컨벤션 = AB / 스마트블록 / 인기글 별도 표기 (D-022 ① misread 폐기)
- 사장님 진짜 컨벤션 = 미노출 / 누락 / 삭제 분리 (D-022 ① "삭제" 단일 통합 misread 폐기)
- 사장님 plan d026-comprehensive.md 명시
- 사장님 단호 시그널 = polling X = 즉시 진행 의무

**구현**:
- src/parser.py:
  - `ExposureArea` enum 갱신 = 7 unique value (DROPPED 신규, alias 폐기)
  - `_parse_smart_blocks` 부활 (= 이전 deprecated False return 폐기)
  - `_parse_smart_blocks` 시그너처 갱신 = target_url / link_set / cafe_slug_whitelist 매개변수 추가 (= AB/POPULAR 정합)
  - `_detect_block_order` 갱신 = "인기글" 키워드 분기 + 스마트블록 fallback
  - `_parse_popular` 갱신 = "인기글" 키워드 명시 분기 (= 스마트블록 분기 분리)
  - `parse_search_result` 갱신 = _parse_smart_blocks 호출 시 link_set / cafe_slug_whitelist 전달
- src/transitions.py:
  - `EXPOSED_VALUES = {"AB", "스마트블록", "인기글"}` (= 스마트블록 부활)
  - `SYSTEM_K_VALUES` 갱신 = 7개 + ""
  - `compute_new_K` 3-분기 갱신 (= "누락" 신규)
- src/sheets.py:
  - `rank_result_to_columns` "미노출" 명시 표기 (= 빈 칸 X)
- src/main.py:
  - `_process_row` health.record block_type = `{"AB", "스마트블록", "인기글"}` 화이트리스트 확장
- tests/unit/test_parser.py: TestSmartBlockRevival 신규 7 test + 기존 TestParseSmartBlocks 부활 정합 갱신 + TestRankResult enum 검증 갱신
- tests/unit/test_transitions.py: TestK3EnumRegression 신규 10 test + 기존 TestComputeNewK 3-enum 정합 갱신
- tests/unit/test_sheets.py: D-026 회귀 4 test 신규 (미노출 명시 표기 / 빈칸 처리 X / 누락 표기 / 스마트블록 표기) + 기존 test 갱신
- tests/unit/test_main.py: D-026 정합 갱신 (= 미노출 명시 표기)
- tests/component/test_main_flow.py: D-026 정합 갱신 (= 누락 / 미노출 명시 표기)
- 전체 pytest 310 passed (288 → +22 신규/갱신, 회귀 X 검증)

**Phase C/D/E/F = 사장님 결정 의무 = 차후**:
- Phase C: D-026 빈 link 자동 채움 (= shadow mode 1 cycle 필수)
- Phase D: D-026 write 활성 (= 사장님 OK 후)
- Phase E: "삭제" 텍스트 검출 (= 사장님 fixture 1건 의무)
- Phase F: "삭제" write 활성 (= 사장님 OK 후)

**대안 안 고른 이유**:
- Phase A+B+C+D+E+F 일괄 적용 = HIGH 위험 = T-M14.2 / T-M10.5 동일 패턴 (= 832 행 손상 사고 재발)
- Phase A+B 만 적용 = LOW/MEDIUM 위험 = 회귀 test 의무 + 사장님 시점 명시 표기 변경
- 단순 코드 변경 = D-018 정합 X (= 사장님 의도 정합 검증 의무)


### D-022 ① 폐기 entry (= D-026 정합)

**결정 (2026-05-16)**: D-022 ① "사장님 컨벤션 = 모든 노출 박스 모두 인기글" = 잘못 misread = 폐기.

**근거**:
- 사장님 5-15 발화 정합 = AB / 스마트블록 / 인기글 별도 표기
- D-022 ① = 2026-05-08 사장님 컨벤션 정정 misread (= "스마트블록" 단어 0건 = 모든 박스 = 인기글) = 잘못
- 진짜 사장님 컨벤션 = h2 자손 박스 = "인기글" 키워드 박스 = 인기글 / 그 외 h2 박스 = 스마트블록

**대안 안 고른 이유**:
- D-022 ① 유지 = 사장님 시점 misread 잔존 = 사장님 데이터 잘못 분류 누적
- 사장님 명시 컨벤션 적용 = 정합 + 시점 정확화


### D-025: T-M22.1 통합 — JS JSON fallback (영구 적용)

**결정 (2026-05-14)**: `_extract_bootstrap_json` 함수가 `parse_search_result` 안 통합. 옵션 A (HTML 우선 + JSON fallback) 적용.

**근거**:
- T-M22.1 (commit d6bb44e) = 함수만 추가, 통합 X = dead code 상태였음
- D-021 plan = T-M22.1 통합 = +5~10%p 정확도 향상 예상
- 네이버 동적 박스 (`entry.bootstrap()` JSON payload) = HTML 정적 파싱 누락 case 다수

**구현**:
- src/parser.py: `_parse_bootstrap_json_fallback` 신규 함수 + `_collect_urls_from_json` helper 추가 + `parse_search_result` 안 UNEXPOSED 분기 후 fallback 호출 통합. 매치 우선순위 = target_url / link_set / cafe_slug_whitelist (HTML 분기와 정합). 신뢰도 = 0.75 (target/link_set 매치) / 0.70 (slug 매치).
- tests/unit/test_parser.py: TestBootstrapJsonFallbackIntegration 회귀 test 6개 신규 (fallback 매치 정상 / link_set fallback / slug whitelist fallback / HTML 성공 시 skip / JSON 추출 실패 시 HTML 결과 보존 / payload 매치 X 시 UNEXPOSED)
- .harness/tasks.md: 변경 이력 entry 추가
- 전체 pytest 288 pass (282 → +6 신규, 회귀 X 검증)

**대안 안 고른 이유**:
- 옵션 B (JSON 우선): HTML 파싱 100% 정확도 검증됨 (5-14 자동 정확도 측정) = JSON 우선 = 회귀 위험
- 옵션 C (union): 중복 매치 = 우선순위 결정 복잡 = D-018 모호 결정 회피
- 통합 안 함: D-021 plan 정합 X + dead code 누적

---

## 2026-05-17

### D-027: D-026 정정 — shadow mode 폐기 + 백업 자동화 + fixture URL 확정 (사장님 단호 시그널)

**결정 (2026-05-17)**: critic Opus 검증 후 사장님 단호 시그널 정합 일괄 정정:
1. **Shadow mode 폐기** = 시트 즉시 적용 (= 사장님 의도 "시트 계속 수정을 해야지")
2. **백업 자동화 의무 신규** = 매 cron 시작 시 = 시트 전체 read → `.harness/backups/{run_id}.json` 저장 + UNDO 스크립트 = 사장님 사고 시 즉시 복원 1분
3. **fixture URL 확정** = `https://cafe.naver.com/iroid/5407226` (= 사장님 본인 카페 진짜 삭제 글, 5-17 사장님 직접 제공)
4. **test 4 failure 즉시 fix** = ExposureArea / EXPOSED_VALUES / SYSTEM_K_VALUES / prev_K="삭제" 보존 정합
5. **Phase C/D/E 회귀 test 21개+ 추가** = 사장님 시트 손상 위험 자동 검증

**근거**:
- 사장님 5-17 명시 = "시트 계속 수정을 해야지.. 잘못 수정 한 경우를 대비해서 백업 플랜을 세우면 되는거잖아"
- shadow mode (= 1 cycle 검증 후 활성) = 사장님 의도 X (= 운영 정착 의도 정면 충돌)
- 안전 대체 메커니즘 = **백업 자동화** (= 사장님 사고 시점 = 즉시 복원 = T-M14.2 / T-M10.5 사고 패턴 회피)
- critic Opus 발견 Critical 3건 (shadow 누락 / fixture 0건 / test 4 failure) = (1)(2)(3)(4) 정합 해소
- D-018 정합 = 사장님 단호 시그널 = 우리 단호 진행 의무

**구현 (M10 마일스톤 = T-M80~T-M89)**:
- T-M80: fixture 다운로드 (iroid/5407226 HTML)
- T-M81: 백업 자동화 (main.py run_cycle 시작 시 + scripts/restore_backup.py)
- T-M82: UNDO 스크립트
- T-M83: test 4 failure fix
- T-M84: Phase C/D/E 회귀 test 21개+
- T-M85: crawler.fetch_cafe_url_status 정합 검증
- T-M86: workflow yml 백업 dir 생성 step
- T-M87: pytest 전체 pass
- T-M88: commit + push
- T-M89: 다음 cron 결과 검증

**대안 안 고른 이유**:
- shadow mode 유지: 사장님 의도 정면 충돌 (= 운영 정착 X)
- 백업 X = 시트 사고 시 사장님 수동 복원만: 사장님 의무 ↑ + 신성 시트 보호 ↓
- fixture X = "삭제" 자동 표기 폐기: 사장님 5-17 명시 X (= 진짜 삭제 의무 표기)
- test 4 failure 무시: workflow exit 1 = 사장님 메일 false alert = 신뢰 ↓

---

## 2026-05-18

### D-031: 우리 시스템 고착화 X + 사장님 confirm 후 진화 의무 (영구 룰, 2026-05-18 정정)

**결정**: 사장님 5-18 명시 "고착화되는 순간 끝, 계속 디벨롭되어야 해" + 사장님 5-18 정정 "진화하기 전에 나한테 물어봐" = 영구 룰 신규.

**룰** (= 사장님 정정 정합):
1. **진화 후보 검출** = 우리 = 필요한 시점 (= 사장님 지적 / 한계 발견 / 사고 사례) = 자연 타이밍
2. **사장님 confirm 의무** = 자동 진화 절대 X = AskUserQuestion + 진화 이유 명시 + ㄱ/굳이 X/잠깐 선택
3. **사장님 ㄱ 후만** 적용 (= 굳이 X / 잠깐 = 진화 X = 자원 낭비 회피)
4. retro-log 누적 = 매 발동마다 = 자동 (= 후보 라벨 누적 자체는 = OK)
5. navigation / second-brain skill 갱신 = 사장님 confirm 후만 진화

**근거**:
- 사장님 5-18 메타 지적 = "쓰던 명령어만 쓰는 듯" + "고착화 = 끝, 계속 디벨롭"
- 사장님 5-18 정정 = "진화하기 전에 나한테 물어봐 그러면 더 좋은 방향성이나 굳이 싶은 것들은 안 해도 되잖아"
- 자동 진화 = 사장님 의도 X 가능 = 자원 낭비 + 사장님 시점 X 진화 위험

**구현**:
- `.harness/decisions.md` D-031 정정 entry
- `CLAUDE.md` root = D-031 영구 룰 섹션 정정
- AskUserQuestion 도구 활용 = 진화 후보 + 이유 + 선택지 = 사장님 깔끔 confirm

**대안 안 고른 이유**:
- 자동 진화 = 사장님 5-18 정정 명시 위반
- 진화 X = 사장님 5-18 본 의도 (= 고착화 X) 위반
- = 두 의도 양립 정합 = 검출 자동 + confirm 의무 = 정합
