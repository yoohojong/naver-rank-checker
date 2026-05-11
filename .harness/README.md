# naver-rank-checker

**상태**: 🔄 구현 단계 M4 (~39% 진행, 2026-05-05 기준)
**시작**: 2026-05-05
**예상 완료**: 2026-05-12 (구현 1주 가정)
**코드 위치**: `D:\claude code\naver-rank-checker\`
**저장소**: (생성 예정) GitHub 공개 저장소
**배포**: GitHub Actions (cron 4회/일, 무료)

## 한 줄 목적
네이버 키워드 상위노출 자동 체크 + Google Sheets 자동 갱신, GitHub Actions 무료 운영.

## 배경
사장님(유호종)이 프로그램88에 33만원 외주받은 동일 도구가 안정성 떨어지고(php8ts.dll 백신 삭제 등), Google Sheets 자동 연동이 핵심 미충족 → 자체 제작 결정.

## 핵심 결정 (확정)
- 환경: **GitHub Actions 공개 저장소** (진짜 무료, 무제한)
- 언어: **Python**
- 구조: **Modular B** (crawler / parser / sheets / cache / retry / health)
- 갱신: **6시간마다 4회/일**
- 시트: **분야별 탭** + **헤더 이름 기반 매핑** (열 이동 강건성)
- 스케일: 1,000개+ (무제한) 키워드/URL 쌍
- 자동 추출: C 유형(탭 노출 순서), K 노출영역, L/M/N 순위, O 지식인탭, **카페명/게시판** (캐싱)
- 헬스체크: 네이버 코드 변경 자동 감지 → 시트 알림
- 실패율: 99%+ 목표 (재시도 큐, 5회 연속 실패만 알림)

## 🆕 다음 세션 핸드오프 (2026-05-11 T-M9.1 완료 시점)

**현재 상태**:
- T-M9.1 (curl_cffi 도입) ✅ 151/151 tests pass (23s)
- workflow **disabled** 유지 (사장님 시그널 후 enable)
- 사장님 시트 = 이전 시점 복원 ✅
- 사장님 PC self-hosted runner = online

**남은 fix**:
1. ~~curl_cffi 도입~~ ✅ **2026-05-11 T-M9.1** (requests → curl_cffi==0.15.0, Session impersonate="chrome131", RequestsError catch, test responses→mock 마이그레이션 동반)
2. **빈 결과 감지 + 재시도** (네이버 JS 렌더링 강화 대응, 2025-09~) — fix 1 cron evidence 후 결정
3. **사장님 새 cron 트리거 + 결과 evidence** — fix 1 효과 측정. workflow enable + 수동 dispatch → 70~90분 → 시트 같은 시점 비교

**사장님 다음 시그널 (객관적 최선 순)**:
- **"cron ㄱ"** → fix 1 효과 evidence 우선 (workflow enable + 수동 트리거). 사장님 시트 손상 위험 = D-017 retry 폐지 + circuit breaker 5회 차단 적용으로 ↓
- "fix 2 ㄱ" → 빈 결과 감지 먼저 (cron 안전성 ↑, 다만 evidence 없이 추측 fix 위험)
- "잠깐" → 사장님 추가 검토

**진짜 root cause 정리 (이번 세션)**:
- cron run 25647821456 손상 원인 = `main.py retry 실패 → K="삭제"` (critic 2026-05-08 결정 폐기)
- 차단 회피 = random slowdown + Session + Accept-Language + random.shuffle (curl_cffi 다음 세션)

**핵심 파일**:
- `.harness/decisions.md` D-017 (최신 결정)
- `.harness/tasks.md` 변경 이력 (이번 세션 모두 누적됨)
- `~/.claude/skills/second-brain/retro-log.md` 글로벌 메타 회고

**진척도**: 95% (운영 안정 검증 = 새 cron 결과 후)

---

## 다음 할 일
**T-M4.8 (스마트블록 파싱)** 또는 병렬로 **T-M5.1 (gspread 인증)** / **T-M6.* (cache/retry/health)**.
T-M4.7 (AB 리스트 파싱) 완료 — 부산맘 카페 1등 케이스 검증 완료.

## 핵심 파일
- `spec.md` — 사양/요구사항 (이 단계에서 확정 중)
- `plan.md` — 구현 계획 (writing-plans 결과, 다음 단계)
- `tasks.md` — 진행 트래킹 (가중치 마일스톤, 0~100%)
- `decisions.md` — 주요 결정 + 근거

## 🪄 새 세션에서 이어가는 법 (사장님 매뉴얼)

CLI에서 Claude 세션 시작 후, 한 줄 입력:

```
다음 task 진행
```

또는 프로젝트 CD 안 됐으면:

```
D:\claude code\naver-rank-checker .harness 읽고 다음 task 이어가
```

여러 task 자동 진행 원하면:

```
다음 ready task 전부 자동 진행. 사장님 작업 task 만나면 멈추고 가이드 출력.
```

→ 프로젝트 루트의 `CLAUDE.md` 파일이 Claude에 자동 로드되어, 어떤 세션이든 즉시 이 하네스 인지함.

## 멀티 Claude 작업 시 (병렬 OK)
1. 시작 전 이 README + tasks.md + PROTOCOL.md 읽고 컨텍스트 복원
2. tasks.md 의존성/병렬 표 보고 ready task 찾기
3. `mkdir .harness/claims/T-{id}/` 시도해서 claim (실패하면 다음 후보로)
4. 작업 → tasks.md 갱신 → claim 디렉토리 삭제 → git commit
5. 다음 ready task로 반복

**병렬 안전 규칙**: 다른 파일 작업하는 task만 동시 실행. 같은 파일 동시 수정은 충돌 위험.

상세는 `.harness/PROTOCOL.md` 참조.
