# CLAUDE.md — naver-rank-checker 프로젝트

## 새 세션 진입 시 즉시 자동 실행 (이 파일이 있으면 Claude가 자동 로드)

**1단계 — 컨텍스트 복원**:
1. `.harness/README.md` 읽기 — 프로젝트 한눈에
2. `.harness/tasks.md` 읽기 — 진척도 + 다음 작업
3. `.harness/PROTOCOL.md` 읽기 — 멀티 Claude 협업 규칙
4. 필요하면 `.harness/spec.md`, `.harness/plan.md`, `.harness/decisions.md` 추가 로드

**2단계 — 다음 task 자동 잡기**:
1. `tasks.md`에서 status=pending + deps 모두 completed인 task 찾기
2. `mkdir .harness/claims/T-{id}/` 시도 → 성공하면 claim
3. info.txt 작성 (session_id, claimed_at)
4. `plan.md`의 해당 task 상세 읽고 실행 (TDD 패턴)
5. 완료 후: tasks.md 갱신 → claims 폴더 삭제 → (git initialized면) commit

**3단계 — 사용자에게 보고**:
"M{번호}.{번호} 완료. 다음 ready: T-{id}. 진행할까요?"

## 사장님이 다음 세션에서 사용할 마법의 문장

이 중 하나만 입력하면 자동 이어감:

```
다음 task 진행
```

또는 더 명시적:

```
naver-rank-checker .harness 읽고 다음 task 이어가
```

또는 여러 task 자동 진행:

```
다음 ready task 전부 자동 진행. 사장님 작업 task 만나면 멈추고 가이드 출력.
```

## 프로젝트 한 줄 요약

네이버 키워드 상위노출 자동 체크 → Google Sheets 자동 갱신. GitHub Actions 6시간 cron, 무료 운영.

## 핵심 위치

- 코드: `src/` (10개 모듈)
- 테스트: `tests/unit/`, `tests/component/`
- 하네스: `.harness/`
- claims: `.harness/claims/T-{id}/` (mkdir 원자적 lock)

## 사용자 (사장님) 정보

- 비개발자, 코드 직접 수정 X
- 외주본 33만원 (프로그램88) 안정성 부족 → 자체 제작 결정
- 구조: 분리 + 효율 + 단호한 결정 선호 (취향 polling 금지)

## ⚠️ T-M13 학습 (2026-05-12) — 영구 룰

**사장님 의도 박을 때 — 모호 시점 = 우리 결정 박지 X**:

1. **"OR" 시그널** = 사장님 메시지 박힌 "이거 하던가 저거 하던가" / "둘 다 가능" / "상관없어" 박힐 때:
   - 우리 단호 결정 박지 X (사장님 페르소나 = 단호 박지만 **모호 의도 시점은 예외**).
   - **사장님 1줄 결정 박음 의무** ("ㅇ" / "B" / "잠깐").
2. **사장님 시트 컨벤션 변경 (마케터 작업 흐름 / 새 동작 / 스키마 영향)** 박을 때:
   - 1차 = sample 박음 또는 사장님 OK 받음.
   - 832 행 자동 적용 X.
3. **비즈니스 컨텍스트 (마케터 시점)**:
   - 작업자 빈 + 링크 빈 row = **마케팅 예정 (사장님 기획 단계)** = 박지 X.
   - 작업자 박힌 + 링크 박힌 row = **진짜 작업 row** = 박음.
   - K=AB 박혀있어도 = 사장님 시트의 "C 컬럼 (사장님 의도 박은 거)" 박혀있는 거 = 우리가 박는 K 와 분리.

**근거**: 2026-05-12 T-M10 박은 게 사장님 의도 정합 X. 사장님 시트 832 행 link 빈 row 에 잘못된 K/L/M 박힘. T-M13 revert + 사장님 시트 정리 박음. (`.harness/decisions.md` D-018)
