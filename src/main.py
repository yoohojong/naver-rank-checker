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

from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON, NAVER_SLOWDOWN_BASE_SEC, NAVER_SLOWDOWN_MAX_SEC
from src.crawler import Crawler, SlowdownController, CrawlerError, CircuitBreakerOpen, resolve_short_url
from src.health import HealthMonitor
from src.parser import parse_search_result
from src.retry import RetryQueue
from src.sheets import (
    SheetsClient, RowUpdate,
    rank_result_to_columns,
    HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN,
)
from src.transitions import compute_new_K


def _carea_filter(tab_name: str) -> bool:
    """사장님 분야 탭 필터 — '카외' 끝 탭만."""
    return tab_name.endswith("카외")


def _process_row(
    row: dict,
    crawler: Crawler,
    health: HealthMonitor,
    all_known_links: Optional[set] = None,  # 호환성 유지 — 미사용 (T-M14 폐기 2026-05-14)
    url_alive_cache: Optional[dict] = None,  # 호환성 유지 — 미사용 (T-M10.5 폐기)
) -> Optional[dict]:
    """한 행 처리 → 새 컬럼 dict 또는 None (skip).

    T-M14.* 전체 폐기 (2026-05-14): 사장님 진짜 의도 = target_url 단독 매치만.
    - 시트 link 자동 갱신 X
    - 다른 행 link fallback X
    - slug 매치 X

    Returns:
        새 column dict (시트 write 용) 또는 None (skip).

    Raises:
        CrawlerError: 차단/네트워크 실패. retry queue 처리 대상.
    """
    keyword = (row.get("키워드") or "").strip()
    link = (row.get("링크") or "").strip()
    prev_K = (row.get(HEADER_AREA) or "").strip()

    # 키워드 빈 행 = skip
    if not keyword:
        return None

    # link 빈 행 = 사장님 미작업 = 미노출 빈칸 표시
    if not link:
        return {
            HEADER_AREA: "",
            HEADER_L: "",
            HEADER_M: "",
            HEADER_JISIKIN: "",
        }

    # naver.me 단축 URL 해석
    if "naver.me" in link:
        link = resolve_short_url(link)

    # 검색 + parser (target_url 단독 매치만)
    html = crawler.fetch_search(keyword)
    result = parse_search_result(html, link)

    # T-M10.5 (2026-05-14): url_alive 검증 폐기 — 비로그인 환경 한계.
    # 네이버 카페 = 비로그인 접근 시 로그인 페이지 반환 = PRIVATE 오판정.
    # url_alive = 항상 True 고정.
    url_alive = True
    search_found = result.exposure_area.value != "미노출"

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
        success=True,
        block_type=new_K if new_K in {"AB", "인기글"} else None,
    )

    # 시트 컬럼 dict 변환 (시트 "링크" 컬럼 = 자동 갱신 X = new_link 미사용)
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

    # 1. 시트 read
    data = client.load_all_data_tabs(tab_filter=_carea_filter)
    print(f"대상 탭 {len(data)}개: {list(data.keys())}")

    # cookie warmup — Crawler 인스턴스 생성 직후 네이버 메인 1회 fetch
    # T-M26 (2026-05-12): Cold session 차단 회피. warmup 실패해도 cron 계속 진행.
    crawler.warmup()

    # T-M14 전체 폐기 (2026-05-14): link_set 구성 불필요.
    # all_known_links = 빈 set (호환성 유지 — _process_row 매개변수로 전달되나 미사용).
    all_known_links: set = set()

    # 2. 각 탭 + 행 처리
    # url_alive_cache: T-M10.5 폐기로 미사용. 호환성 유지용 빈 dict.
    url_alive_cache: dict[str, bool] = {}
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
                cols = _process_row(row, crawler, health, all_known_links=all_known_links, url_alive_cache=url_alive_cache)
                if cols is None:
                    continue  # link 빈 행 skip
                updates.append(RowUpdate(row=row["_row"], columns=cols))
            except CircuitBreakerOpen as e:
                # 5 차단 연속 — cron 조기 종료 + 지금까지 결과 시트 반영
                print(f"❌ [{tab_name}] {e}")
                circuit_breaker_tripped = True
                break
            except CrawlerError as e:
                # 2026-05-11 D-017 fix: 차단/네트워크 실패 → retry queue. 실패 시 K 보존 (시트에 기록하지 않음).
                # 이전 (critic 2026-05-08): 재시도 실패 → "삭제" 기록 — 사장님 작업자 혼란 (차단≠삭제).
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
            cols = _process_row(row, crawler, health, all_known_links=all_known_links, url_alive_cache=url_alive_cache)
            return cols
        retry_results = retry_queue.process(retry_processor, slowdown_multiplier=2.0)
        for r in retry_results:
            tab = r["row"].get("_tab", "")
            if tab not in tab_updates:
                continue
            if r["ok"] and r["update"] is not None:
                tab_updates[tab].append(RowUpdate(row=r["row"]["_row"], columns=r["update"]))
            else:
                # 2026-05-11 D-017 fix: 재시도도 실패 = K 보존 (시트에 기록하지 않음).
                # 이전 (critic 2026-05-08): "삭제" 기록 — 사장님 작업자 혼란 (차단≠진짜 삭제).
                # 사장님 시트 손상 사례 후 폐기. 다음 cron 자연 재처리.
                print(f"  [SKIP-PRESERVE] row={r['row'].get('_row')} kw={r['row'].get('키워드')!r}: retry 실패, K 보존")

    # 4. 시트 batch_update (탭별 1 호출)
    total_cells = 0
    for tab_name, updates in tab_updates.items():
        if updates:
            n = client.write_results(tab_name, updates)
            total_cells += n
            print(f"  [{tab_name}] {len(updates)} 행 / {n} 셀 갱신")

    # 4.5. T-M37: 매 탭에 cron 갱신 timestamp 기록 (사장님 시점 차이 인지)
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    kst_iso = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
    for tab_name in tab_updates.keys():
        client.write_timestamp(tab_name, kst_iso)

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

    # 6.5. T-M38: 이전 cron K 분포 vs 현재 anomaly 감지
    try:
        with open("cycle_summary.json", "r", encoding="utf-8") as f:
            prev_summary = json.load(f)
        prev_k = prev_summary.get("k_distribution", {})
        if health.detect_k_anomaly(prev_k, dict(k_distribution)):
            print("⚠️ K_DISTRIBUTION_ANOMALY — 이전 대비 K 분포 20% 이상 변동. 네이버 변경 또는 차단 의심.")
            summary["code_change_suspected"] = True
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # 첫 cron 또는 파일 없음 = 비교 불가, 무시

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
