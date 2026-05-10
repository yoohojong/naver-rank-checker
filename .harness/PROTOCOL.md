# Harness Protocol — 멀티 Claude 안전 협업

이 문서는 **여러 Claude 세션이 같은 하네스로 동시 작업**할 때 따라야 하는 규칙입니다.
순차(1개 Claude) 사용 시에도 동일 프로토콜을 따르면 안전.

## 핵심 메커니즘: filesystem mkdir lock

`mkdir` 시스템 콜은 **원자적**입니다. 두 프로세스가 동시에 같은 폴더 생성을 시도하면 정확히 한 쪽만 성공.
이걸로 task claim 충돌 방지.

## Claim 디렉토리 규칙

위치: `.harness/claims/T-{task_id}/`

- 폴더 존재 = 누군가 이 task 작업 중
- 폴더 안 `info.txt` = 누가/언제 claim했는지
- 폴더 삭제 = 작업 완료 또는 포기

## 세션 시작 프로토콜

새 Claude 세션이 하네스 작업을 시작할 때:

```
1. .harness/README.md 읽기 → 프로젝트 컨텍스트 복원
2. .harness/tasks.md 읽기 → 진척도 + "다음 작업" 확인
3. .harness/PROTOCOL.md 읽기 (이 파일) → 협업 규칙
4. 본인 세션 ID 결정 (예: 현재 시간 + 짧은 랜덤): session-2026-05-05-1830-A1
```

## Task Claim 알고리즘

```
def find_and_claim_next_task(session_id):
    # 1. tasks.md에서 "ready" task 목록 추출
    #    ready = pending 상태 + 모든 dependencies가 completed 상태
    ready_tasks = [t for t in tasks if t.status == "pending" and all_deps_done(t)]
    
    for task in ready_tasks:
        # 2. claim 시도 (mkdir 원자적)
        claim_dir = f".harness/claims/T-{task.id}/"
        try:
            mkdir(claim_dir, exist_ok=False)  # 실패하면 OSError
        except FileExistsError:
            # 다른 세션이 이미 claim. 다음 후보로.
            continue
        
        # 3. claim 성공. info.txt 작성
        write(f"{claim_dir}/info.txt", {
            "session_id": session_id,
            "task_id": task.id,
            "claimed_at": now_iso(),
            "expected_duration_min": task.estimated_min,
        })
        
        return task  # 작업 시작
    
    return None  # 진행 가능한 task 없음 (전부 claimed 또는 deps 미완)
```

## Task 완료 프로토콜

```
def mark_task_complete(task_id, session_id):
    # 1. tasks.md 업데이트 (mile별 진척도 갱신)
    update_tasks_md(task_id, status="completed", completed_at=now())
    
    # 2. 결과를 decisions.md에 기록 (선택, 큰 결정만)
    if task.had_significant_decision():
        append_decision(...)
    
    # 3. claim 디렉토리 삭제
    rmtree(f".harness/claims/T-{task_id}/")
    
    # 4. git commit
    git_commit(f"feat({module}): {task.title} (session: {session_id})")
```

## Stale Lock 청소

크래시한 세션의 claim 디렉토리는 자동 정리 안 됨. 다른 세션이 발견 시 청소:

```
def cleanup_stale_claims():
    for claim_dir in glob(".harness/claims/T-*"):
        info = read_json(f"{claim_dir}/info.txt")
        claimed_at = parse(info["claimed_at"])
        elapsed_min = (now() - claimed_at).total_seconds() / 60
        max_expected = info.get("expected_duration_min", 30)
        
        if elapsed_min > max_expected * 3:  # 3배 초과면 stale 의심
            print(f"[WARN] Stale claim detected: {claim_dir} (elapsed: {elapsed_min:.0f}min)")
            # 본인이 자동 청소하지 말고 사용자에게 보고
            # 사용자가 확인 후 수동으로 rmdir
```

## Task 의존성 표기 (plan.md)

각 task는 plan.md 안에 의존성 명시. 다음 형식 사용:

```markdown
### 🤖 Task M4.7: AB 리스트 파싱

**Dependencies**: T-M3.6 (모듈 골격), T-M4.1 (fixture 수집), T-M4.2 (URL 정규화)
**Parallel-safe with**: T-M4.3, T-M4.4 (서로 다른 파일/모듈)
**Estimated minutes**: 30
```

## 병렬 가능 task 그룹 (이번 프로젝트 분석 결과)

### 그룹 A: 인프라 동시 진행 가능
- T-M3.1 (👤 GCP 작업) + T-M3.3 (👤 GitHub 저장소) — 둘 다 사장님이 다른 탭에서 동시 진행 OK
- T-M3.5 (Python 환경) + T-M4.1 (fixture 수집) — 의존 없음

### 그룹 B: Crawler 모듈 안 동시 진행 가능
- T-M4.2 (URL 정규화) + T-M4.3 (SlowdownController) + T-M4.4 (fetch_search) — 다른 함수, 같은 파일이지만 영역 다름 (주의: 같은 파일 동시 편집은 충돌 가능, **다른 파일 작업은 안전**)
- T-M4.5 (cafe URL status) + T-M4.6 (RankResult 정의) — 다른 모듈

### 그룹 C: Sheets ↔ Cache/Retry/Health 동시
- T-M5.* (sheets.py) + T-M6.1 (cache.py) + T-M6.2 (retry.py) + T-M6.3 (health.py) — 모두 다른 파일

### 의존성 사슬 (병렬 X)
- M4.1 → M4.7~M4.10 (fixture 없으면 파서 못 만듬)
- M3.5 → M3.6 (env 없으면 모듈 못 임포트)
- M5/M6 → M7 (모듈 없으면 main 못 묶음)

## 권장 운영 시나리오

### 단순 운영 (1 Claude)
```
사장님: ".harness 읽고 다음 task 진행"
Claude: 다음 ready task 1개 claim → 실행 → 완료 → claim 해제 → 다음 task...
```

### 가속 운영 (2~3 Claude 병렬)
```
사장님: CLI 탭 3개 열고 각각 시작
탭 1: ".harness 읽고 다음 task 진행"
탭 2: ".harness 읽고 다음 task 진행"
탭 3: ".harness 읽고 다음 task 진행"

각 Claude가 독립적으로:
- ready task 후보 중 mkdir lock 시도
- 성공한 Claude만 작업 (다른 세션은 다음 후보로)
- 완료 후 lock 해제 → 다음 ready task로
```

## 충돌 방지 핵심 원칙

1. **다른 파일 작업하는 task만 병렬** (같은 파일 동시 수정은 git merge 충돌 위험)
2. **claim 받은 task만 작업** (mkdir 실패하면 양보)
3. **commit은 task 단위** (한 task 끝나면 즉시 commit, 다른 세션이 pull 가능)
4. **불확실하면 순차** (병렬은 효율, 정확성 우선)

## 시작하기

```
사장님: "다음 task 진행"

Claude (자동):
  1. README.md, tasks.md, PROTOCOL.md 읽음
  2. ready task 찾음
  3. claim 시도 + 성공
  4. plan.md에서 해당 task 상세 읽음
  5. 실행 (TDD 패턴)
  6. tasks.md 갱신, claim 해제, commit
  7. "M3.1 완료. 다음 ready: M3.3 또는 M4.1. 진행할까요?"
```
