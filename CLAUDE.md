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
