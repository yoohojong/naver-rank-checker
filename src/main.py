"""main: 모든 모듈 조합. GitHub Actions cron entry point.

사장님 production 흐름 (한 사이클):
1. SheetsClient 인증 + 카외 탭 3개 read
2. 각 행 (링크 있는 것만) → 네이버 검색 + parser
3. transitions.compute_new_K 로 사장님 컨벤션 K 결정 (이전 vs 현재)
4. 실패 행 retry queue → 1회 재시도
5. 시트 batch_update (탭별 1 API 호출)
6. health 요약 logs

사장님 컨벤션 (2026-05-08):
- 처리 대상: ".카외" 끝 탭만 (3개)
- 링크 빈 행: skip (작업자가 글 쓰기 전)
- 컬럼: 유형 / 노출영역 / L / M / 지식인탭 만 갱신. 그 외 (작업일/작업자/MB/PC/총합/작업아이디/카페게시판) 건드리지 X.
"""
import json
import os
import random
import sys
import time
from collections import Counter
from typing import Optional

from src.cache import CafeMappingCache
from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON, NAVER_SLOWDOWN_BASE_SEC, NAVER_SLOWDOWN_MAX_SEC
from src.crawler import Crawler, SlowdownController, CafeStatus, CrawlerError, CircuitBreakerOpen, resolve_short_url
from src.health import HealthMonitor
from src.parser import parse_search_result
from src.retry import RetryQueue
from src.sheets import (
    SheetsClient, RowUpdate,
    rank_result_to_columns,
    HEADER_AREA,
)
from src.transitions import compute_new_K


def _carea_filter(tab_name: str) -> bool:
    """사장님 분야 탭 필터 — '카외' 끝 탭만."""
    return tab_name.endswith("카외")


def _process_row(
    row: dict,
    crawler: Crawler,
    health: HealthMonitor,
) -> Optional[dict]:
    """한 행 처리 → 새 컬럼 dict 또는 None (skip).

    Returns:
        새 column dict (시트 write 용) 또는 None (link 빈 등으로 skip).

    Raises:
        CrawlerError: 차단/네트워크 실패. retry queue 처리 대상.
    """
    keyword = (row.get("키워드") or "").strip()
    link = (row.get("링크") or "").strip()
    prev_K = (row.get(HEADER_AREA) or "").strip()

    # 키워드 빈 행 = skip (작업자가 키워드도 안 박은 row)
    if not keyword:
        return None

    # 2026-05-12 T-M10: 링크 빈 row 도 검색 박음 (사장님 컨벤션).
    # 마케터 시점: K=AB/인기글 박혀있으면 "이미 누가 노출 박힘" = 추가 작업 X.
    # 링크 컬럼 = 안 건드림 (마케터 작업 영역). K/L/M/O 만 박음.
    target_url: Optional[str] = link if link else None

    # 단축 URL 해석 (link 있는 경우만)
    if link and "naver.me" in link:
        link = resolve_short_url(link)
        target_url = link

    # 검색 + parser
    html = crawler.fetch_search(keyword)
    result = parse_search_result(html, target_url)

    # url_alive — link 있는 경우만 (link 없으면 살아있는지 검증 의미 X).
    # 2026-05-12 T-M10.1 사장님 요구: 게시글 조회 시 "삭제됐다" 뜨는 케이스 = 무조건 K=삭제.
    # 이전: prev_K in {AB, 인기글} 조건 박혀서 첫 추적 (prev_K="") row 의 죽은 URL 못 잡음.
    # 변경: link 있음 + 검색 미노출 = 무조건 url alive 검증. compute_new_K(url_alive=False) → K="삭제".
    # 비용: HTTP 호출 832 × ~60% = ~500 추가. cron 시간 33분 → 50~75분 추정.
    url_alive = True
    search_found = result.exposure_area.value != "미노출"
    if link and not search_found:
        status = crawler.fetch_cafe_url_status(link)
        url_alive = status == CafeStatus.ALIVE

    # 사장님 컨벤션 K 결정
    new_K = compute_new_K(
        prev_K=prev_K,
        search_found=search_found,
        url_alive=url_alive,
        area=result.exposure_area.value if search_found else None,
    )

    # health 누적
    health.record(
        parser_confidence=result.parser_confidence,
        success=True,  # 검색 자체는 성공 (차단 시는 raise 됨)
        block_type=new_K if new_K in {"AB", "인기글"} else None,
    )

    # 시트 컬럼 dict 변환 (사장님 컨벤션)
    cols = rank_result_to_columns(
        block_order=result.block_order,
        exposure_area=new_K,
        integrated_rank=result.integrated_rank if search_found else None,
        cafe_slot_rank=result.cafe_slot_rank if search_found else None,
        in_jisikin=result.in_jisikin,
    )
    return cols


def run_cycle() -> dict:
    """한 cron 사이클 실행. logs 출력 + summary 반환.

    Returns:
        summary dict (테스트/외부 호출 용).
        2026-05-11: 풍부한 summary (K 분포, 처리 시간, 행 수) — Telegram/이메일 알림용.
        CI 환경 (GITHUB_ACTIONS=true) 에서는 cycle_summary.json 도 작성.
    """
    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("❌ SPREADSHEET_ID 또는 SERVICE_ACCOUNT_JSON 환경변수 누락. 종료.")
        return {"error": "missing_env"}

    cycle_start = time.time()
    print("=== naver-rank-checker cron 사이클 시작 ===")
    client = SheetsClient(spreadsheet_id=SPREADSHEET_ID, service_account_json=SERVICE_ACCOUNT_JSON)
    crawler = Crawler(slowdown=SlowdownController(base=NAVER_SLOWDOWN_BASE_SEC, max_=NAVER_SLOWDOWN_MAX_SEC))
    health = HealthMonitor()
    retry_queue = RetryQueue()
    cafe_cache = CafeMappingCache()  # 메모리 캐시 (cron 사이클 안에서만)

    # 1. 시트 read
    data = client.load_all_data_tabs(tab_filter=_carea_filter)
    print(f"대상 탭 {len(data)}개: {list(data.keys())}")

    # 2. 각 탭 + 행 처리
    tab_updates: dict[str, list[RowUpdate]] = {}
    circuit_breaker_tripped = False  # 2026-05-11 architect Major 1 fix
    for tab_name, rows in data.items():
        if circuit_breaker_tripped:
            print(f"[{tab_name}] circuit breaker open — skip")
            tab_updates[tab_name] = []
            continue
        updates: list[RowUpdate] = []
        # 2026-05-11 D-017 fix: 행 순서 random.shuffle = 자연 패턴 (document-specialist HIGH).
        # 832 행 항상 동일 순서 = 시계열 봇 패턴 = 차단 위험. 시드 X = 매 cron 다른 순서.
        rows = list(rows)
        random.shuffle(rows)
        print(f"\n[{tab_name}] {len(rows)} 행 처리 시작 (random shuffle)")
        for row in rows:
            try:
                cols = _process_row(row, crawler, health)
                if cols is None:
                    continue  # link 빈 행 skip
                updates.append(RowUpdate(row=row["_row"], columns=cols))
            except CircuitBreakerOpen as e:
                # 5 차단 연속 — cron 조기 종료 + 지금까지 결과 시트 반영
                print(f"❌ [{tab_name}] {e}")
                circuit_breaker_tripped = True
                break
            except CrawlerError as e:
                # 2026-05-11 D-017 fix: 차단/네트워크 실패 → retry queue. 실패 시 K 보존 (시트 안 박음).
                # 이전 (critic 2026-05-08): 재시도 실패 → "삭제" 박음 — 사장님 작업자 혼란 (차단≠삭제).
                # 사장님 시트 손상 사례 (cron 25647821456) 후 폐기.
                retry_queue.add(row, error=str(e))
                health.record(parser_confidence=0.0, success=False)
            except Exception as e:
                # 예측 못한 에러 → 시트에 "삭제" + logs (silent drop 방지, critic 2026-05-08 Critical 1)
                print(f"  [ERR] row={row.get('_row')} kw={row.get('키워드')!r}: {e}")
                health.record(parser_confidence=0.0, success=False)
                # 사장님 컨벤션: 노출 안 됨 = '삭제' 단일. exception 도 사장님 시점에 = '삭제'
                updates.append(RowUpdate(row=row["_row"], columns={HEADER_AREA: "삭제"}))
        tab_updates[tab_name] = updates
        print(f"  → 1차 처리: {len(updates)} 갱신, {len(retry_queue)} 재시도 대기")

    # 3. retry queue 처리 (slowdown 강화) — circuit breaker 시 skip
    if len(retry_queue) > 0 and not circuit_breaker_tripped:
        print(f"\n=== retry queue 처리: {len(retry_queue)} 행 ===")
        def retry_processor(row):
            cols = _process_row(row, crawler, health)
            return cols
        retry_results = retry_queue.process(retry_processor, slowdown_multiplier=2.0)
        for r in retry_results:
            tab = r["row"].get("_tab", "")
            if tab not in tab_updates:
                continue
            if r["ok"] and r["update"] is not None:
                tab_updates[tab].append(RowUpdate(row=r["row"]["_row"], columns=r["update"]))
            else:
                # 2026-05-11 D-017 fix: 재시도도 실패 = K 보존 (시트 안 박음).
                # 이전 (critic 2026-05-08): "삭제" 박음 — 사장님 작업자 혼란 (차단≠진짜 삭제).
                # 사장님 시트 손상 사례 후 폐기. 다음 cron 자연 재처리.
                print(f"  [SKIP-PRESERVE] row={r['row'].get('_row')} kw={r['row'].get('키워드')!r}: retry 실패, K 보존")

    # 4. 시트 batch_update (탭별 1 호출)
    total_cells = 0
    for tab_name, updates in tab_updates.items():
        if updates:
            n = client.write_results(tab_name, updates)
            total_cells += n
            print(f"  [{tab_name}] {len(updates)} 행 / {n} 셀 갱신")

    # 5. K 분포 + 처리 시간 집계 (사장님 알림용 풍부 summary)
    k_distribution: Counter = Counter()
    total_rows_with_link = 0
    for tab, updates in tab_updates.items():
        for upd in updates:
            total_rows_with_link += 1
            k_val = upd.columns.get(HEADER_AREA, "") or "미노출"
            k_distribution[k_val] += 1

    cycle_seconds = int(time.time() - cycle_start)

    # 6. health summary
    health.log_summary()
    summary = health.summary()
    summary["total_cells_written"] = total_cells
    summary["retry_queue_remaining"] = len(retry_queue)
    summary["total_rows_processed"] = total_rows_with_link
    summary["k_distribution"] = dict(k_distribution)
    summary["cycle_seconds"] = cycle_seconds
    summary["tabs_processed"] = list(tab_updates.keys())
    summary["circuit_breaker_tripped"] = circuit_breaker_tripped  # 2026-05-11 architect Major 1
    if circuit_breaker_tripped:
        summary["code_change_suspected"] = True  # cron 조기 종료 = 알림 trigger

    # 7. CI 환경 — cycle_summary.json 작성 (workflow yml 의 issue comment step 에서 읽음)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        try:
            with open("cycle_summary.json", "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print("  [CI] cycle_summary.json 작성됨")
        except Exception as e:
            print(f"  [CI] cycle_summary.json 작성 실패: {e}")

    print(f"\n=== cron 사이클 완료. 셀 갱신: {total_cells}, 재시도 큐 남음: {len(retry_queue)}, 시간: {cycle_seconds}s ===")
    return summary


if __name__ == "__main__":
    s = run_cycle()
    # GitHub Actions exit code: 코드 변경 의심 시 1 (Actions 빨강 → 사장님 알림)
    if s.get("code_change_suspected"):
        sys.exit(1)
    sys.exit(0)
