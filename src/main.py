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
import gzip
import json
import os
import random
import sys
import time
from collections import Counter
from typing import Optional

from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON, NAVER_SLOWDOWN_BASE_SEC, NAVER_SLOWDOWN_MAX_SEC, CAFE_WHITELIST
from src.crawler import Crawler, SlowdownController, CrawlerError, CafeStatus, CircuitBreakerOpen, parse_cafe_url, resolve_short_url
from src.health import HealthMonitor
from src.parser import parse_search_result
from src.retry import RetryQueue
from src.sheets import (
    SheetsClient, RowUpdate,
    rank_result_to_columns,
    HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK,
)
from src.transitions import compute_new_K


def _carea_filter(tab_name: str) -> bool:
    """사장님 분야 탭 필터 — '카외' 끝 탭만."""
    return tab_name.endswith("카외")


def _process_row(
    row: dict,
    crawler: Crawler,
    health: HealthMonitor,
    all_known_links: Optional[set] = None,  # D-026 Phase C+D (2026-05-16): 빈 link 자동 채움 logic 활용
    url_alive_cache: Optional[dict] = None,  # 호환성 유지 — 미사용 (T-M10.5 폐기)
) -> Optional[dict]:
    """한 행 처리 → 새 컬럼 dict 또는 None (skip).

    D-029 (2026-05-18 — D-026 정정) 사장님 컨벤션:
    - 빈 link 행 + all_known_links 매치 = K="중복노출(매치 구좌)" + HEADER_LINK 자동 채움
      (예: AB 구좌 매치 → "중복노출(AB)" / 스마트블록 매치 → "중복노출(스마트블록)")
    - 빈 link 행 + all_known_links 매치 X = K="미노출"
    - link 있는 행 + 검색 노출 = K=area (AB/스마트블록/인기글) — Pass 2 가 양방향 갱신 가능
    - link 있는 행 + 검색 미노출 + 삭제 텍스트 검출 = K="삭제"
    - link 있는 행 + 검색 미노출 + 텍스트 검출 X = transitions.compute_new_K (= 누락 / 미노출 / 삭제 보존)

    Returns:
        새 column dict (시트 write 용) 또는 None (skip).
        D-029: 빈 link 매치 시 = cols["_matched_area"] (메타 키) 저장 = Pass 2 양방향 갱신용.

    Raises:
        CrawlerError: 차단/네트워크 실패. retry queue 처리 대상.
    """
    keyword = (row.get("키워드") or "").strip()
    link = (row.get("링크") or "").strip()
    prev_K = (row.get(HEADER_AREA) or "").strip()

    # 키워드 빈 행 = skip
    if not keyword:
        return None

    # D-026 Phase C+D (2026-05-16): 빈 link 행 = 키워드 검색 + 다른 행 우리 link 매치 시 자동 채움
    # D-029 (2026-05-18): 매치 구좌 명시 = "중복노출(AB)" / "중복노출(스마트블록)" / "중복노출(인기글)"
    if not link:
        # all_known_links 없음 (= 호출자가 구성 X) = 종전 동작 (미노출 표기)
        if not all_known_links:
            return {
                HEADER_AREA: "미노출",
                HEADER_L: "",
                HEADER_M: "",
                HEADER_JISIKIN: "",
            }

        # 키워드 검색 + parser (target_url=None + link_set 매치)
        html = crawler.fetch_search(keyword)
        result = parse_search_result(html, target_url=None, link_set=all_known_links)

        if result.matched_url:
            # D-029: 매치 구좌 = result.exposure_area.value (= "AB" / "스마트블록" / "인기글")
            # parser 가 매치한 구좌 = parse_search_result 가 AB→SMART_BLOCK→POPULAR 분기 매치 후 그 enum 설정.
            matched_area = result.exposure_area.value  # "AB" / "스마트블록" / "인기글"
            # 보수적 fallback: 매치 area 가 노출 3종 외 시 (= 이상 case) = "중복노출" 단일 (D-026 호환)
            if matched_area in {"AB", "스마트블록", "인기글"}:
                new_K = f"중복노출({matched_area})"
            else:
                new_K = "중복노출"
            cols = rank_result_to_columns(
                block_order=result.block_order,
                exposure_area=new_K,
                integrated_rank=result.integrated_rank,
                cafe_slot_rank=result.cafe_slot_rank,
                in_jisikin=result.in_jisikin,
            )
            cols[HEADER_AREA] = new_K
            cols[HEADER_LINK] = result.matched_url  # D-026 자동 채움 (sheets.py 빈 link 행만 허용)
            # D-029 Pass 2 양방향 갱신용 메타 키 — sheets.write_results 가 mapping 없는 키 자동 skip
            cols["_matched_area"] = matched_area
            health.record(
                parser_confidence=result.parser_confidence,
                success=True,
                block_type=new_K,
            )
            return cols

        # 빈 link 행 + 매치 X = "미노출"
        health.record(parser_confidence=0.0, success=True, block_type=None)
        return {
            HEADER_AREA: "미노출",
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

    search_found = result.exposure_area.value != "미노출"

    # D-026 Phase E+F (2026-05-16): 검색 미노출 + link 있음 = 삭제 텍스트 검출
    # 사장님 명시 = "게시글이 삭제되었습니다" exact substring 검출만 → K="삭제"
    # 로그인 페이지 / 404 / 네트워크 fail = UNKNOWN (= 정상 가정 = transitions 자연 처리)
    deletion_detected = False
    if not search_found:
        try:
            status = crawler.fetch_cafe_url_status(link)
            deletion_detected = (status == CafeStatus.DELETED)
        except Exception:
            # 텍스트 검출 실패 = 보수적 = 미검출 (= prev_K 보존)
            deletion_detected = False

    # 사장님 컨벤션 K 결정 (D-026 Phase B+E+F)
    new_K = compute_new_K(
        prev_K=prev_K,
        search_found=search_found,
        url_alive=True,  # T-M10.5 폐기 후 = 항상 True
        area=result.exposure_area.value if search_found else None,
        deletion_detected=deletion_detected,
    )

    # health 누적
    # D-026 Phase A+C+D (2026-05-16): 스마트블록 부활 + 중복노출 정합 = block_type 화이트리스트 확장.
    # D-029 (2026-05-18): 중복노출(구좌) 3종 추가 = block_type 화이트리스트 확장.
    health.record(
        parser_confidence=result.parser_confidence,
        success=True,
        block_type=new_K if new_K in {
            "AB", "스마트블록", "인기글",
            "중복노출", "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",
        } else None,
    )

    # 시트 컬럼 dict 변환 (시트 "링크" 컬럼 = 기존 link 행 = 자동 갱신 X = D-023 가드)
    cols = rank_result_to_columns(
        block_order=result.block_order,
        exposure_area=new_K,
        integrated_rank=result.integrated_rank if search_found else None,
        cafe_slot_rank=result.cafe_slot_rank if search_found else None,
        in_jisikin=result.in_jisikin,
    )
    return cols


def _d029_apply_pass2_duplicate(tab_updates: dict[str, list["RowUpdate"]]) -> int:
    """D-029 Pass 2 양방향 "중복노출(구좌)" 갱신 (2026-05-18 — D-026 정정).

    Pass 1 (= _process_row) 결과 누적 후 = 같은 link 가 여러 행에 매치된 case 검출.
    검출 시 = 빈 link 행 + 원본 link 행 모두 K="중복노출(매치 구좌)" 갱신.

    사장님 시점 정합 (5-18 명확 의도):
    - 사례: "도브바디스크럽" 키워드 행 (빈 link, "일본도브바디스크럽" 행 link 매치)
            + "일본도브바디스크럽" 키워드 행 (그 link 의 원본, 인기글 노출)
    - 갱신 후: 양쪽 K = "중복노출(인기글)" — 사장님 시점 = "이 link 가 어디 구좌 노출"
              + "여러 키워드 노출됨" 즉시 인지.

    알고리즘:
    1) tab_updates 순회 → (link → [(tab, row_idx_in_list, matched_area), ...]) map 구성.
       - 빈 link 행 자동 채움 = cols[HEADER_LINK] + cols["_matched_area"] 키 활용
       - 원본 link 행 = parser 결과 (= AB / 스마트블록 / 인기글) + 행 dict 의 "링크" 값
    2) 같은 link 가 2+ 매치 = 중복 검출.
    3) 그 link 가진 모든 RowUpdate K = "중복노출(매치 구좌)" 갱신.

    Args:
        tab_updates: {tab_name: [RowUpdate, ...]} — Pass 1 결과 누적.

    Returns:
        갱신된 RowUpdate 수 (= 사장님 가시성 = log 용).

    Note:
        tab_updates 안 RowUpdate.columns 가 in-place 갱신됨 (= 시트 write 직전 단계).
        "_matched_area" 메타 키 = 갱신 후 cols 에서 제거 (sheets.write_results 가 자동 skip
        하지만 명시적 cleanup 으로 노이즈 차단).
    """
    # 1) link → [(tab, row, matched_area, cols), ...] map 구성
    # cols 직접 참조 = 갱신 시 in-place 수정 = 시트 반영 보장.
    link_to_matches: dict[str, list[tuple[str, int, str, dict]]] = {}
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            cols = upd.columns
            current_K = cols.get(HEADER_AREA, "")

            # 케이스 A: 빈 link 자동 채움 행 = cols[HEADER_LINK] + cols["_matched_area"] 존재
            link_val: Optional[str] = None
            matched_area: Optional[str] = None
            if HEADER_LINK in cols and cols.get("_matched_area"):
                link_val = cols[HEADER_LINK]
                matched_area = cols["_matched_area"]
            # 케이스 B: 원본 link 행 = current_K = 노출 3종 (= 검색 노출, link 매치 완료)
            elif current_K in {"AB", "스마트블록", "인기글"}:
                # 이 행의 link = sheets._row + 원 row dict 의 "링크" 값.
                # cols 에 link 없으므로 = 원본 row 메타 추적 X = link 추출 불가 case.
                # 다만 spec 가 row 메타 보존 = upd.row + tab_name 으로 매치 결정 어려움.
                # 대안 = upd.columns 자체에 link 정보 보존 X → 외부에서 row dict 전달 의무.
                # 본 helper = tab_updates 만 처리 = link 추출 불가 = case B skip.
                # 사장님 시트 양방향 갱신 = 빈 link 자동 채움 시 = 원본 link 매치된 다른 행 검출 필요.
                # 해결: case B 행 cols 에 "_row_link" 메타 보존 (= run_cycle 에서 _process_row 후 주입).
                link_val = cols.get("_row_link")
                if link_val:
                    matched_area = current_K
                else:
                    link_val = None  # link 추적 불가 = skip

            if link_val and matched_area:
                link_to_matches.setdefault(link_val, []).append(
                    (tab_name, upd.row, matched_area, cols)
                )

    # 2) 2+ 매치 link = 중복 검출 + 갱신
    updated_count = 0
    for link_val, matches in link_to_matches.items():
        if len(matches) < 2:
            continue  # 단일 매치 = D-029 대상 X (= 기존 K 유지)

        # 매치 구좌 = 모든 매치 area 중 첫 등장 (= 노출 3종 우선, 이미 sub-enum 이면 그대로 활용 추후)
        # 사장님 사례: 모든 매치 = 같은 link → 같은 link 의 검색 노출 area = 일관됨 가정.
        # 보수적 = 첫 매치 area 사용 (= AB / 스마트블록 / 인기글 중 하나).
        areas = [m[2] for m in matches if m[2] in {"AB", "스마트블록", "인기글"}]
        if not areas:
            continue  # 매치 area 가 노출 3종 외 (= 이상 case) = skip
        new_K = f"중복노출({areas[0]})"

        for _tab, _row, _area, cols in matches:
            old_K = cols.get(HEADER_AREA, "")
            cols[HEADER_AREA] = new_K
            updated_count += 1
            print(f"  [D-029-PASS2] {_tab} row={_row} K: {old_K!r} → {new_K!r} (link={link_val[:70]})")

    # 3) cleanup — "_matched_area" / "_row_link" 메타 키 제거 (write 시 noise 차단)
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            upd.columns.pop("_matched_area", None)
            upd.columns.pop("_row_link", None)

    if updated_count > 0:
        print(f"[D-029-PASS2] 양방향 중복노출(구좌) 갱신: {updated_count} 행")
    return updated_count


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
    # T-M90 (D-027 보강 2026-05-17) architect Opus C1 fix: CAFE_WHITELIST 미설정 시 = log 안 명시.
    # 사장님 secrets 미등록 시 = 빈 set = D-026 자동 채움 silent 무력화 위험 mitigation.
    if not CAFE_WHITELIST:
        print("[T-M90] ⚠️ CAFE_WHITELIST_SLUGS 환경변수 미설정 — D-026 자동 채움 비활성")
    client = SheetsClient(spreadsheet_id=SPREADSHEET_ID, service_account_json=SERVICE_ACCOUNT_JSON)
    crawler = Crawler(slowdown=SlowdownController(base=NAVER_SLOWDOWN_BASE_SEC, max_=NAVER_SLOWDOWN_MAX_SEC))
    health = HealthMonitor()
    retry_queue = RetryQueue()
    d024_skipped_rows = 0  # D-024 (2026-05-14): except 시 시트 보존 skip 카운트 (사장님 가시성)

    # 1. 시트 read
    data = client.load_all_data_tabs(tab_filter=_carea_filter)
    print(f"대상 탭 {len(data)}개: {list(data.keys())}")

    # 1.5. T-M81 (D-027 2026-05-17): 백업 자동화 — run_cycle 시작 시 시트 K/L/M/링크/유형 전체 read → .harness/backups/{run_id}.json 저장.
    # 사장님 사고 시 = scripts/restore_backup.py {run_id}.json = 즉시 복원. shadow mode 폐기 정합 (= 시트 즉시 갱신 + 사고 시 백업 복원).
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    try:
        backup_run_id = os.environ.get("GITHUB_RUN_ID", "local")
        backup_ts = datetime.now(kst).strftime("%Y%m%dT%H%M%S")
        backup_dir = ".harness/backups"
        os.makedirs(backup_dir, exist_ok=True)
        # T-M90 (D-027 보강 2026-05-17) architect Opus m1 fix: JSON → gzip 압축 (~2.5MB → ~150KB).
        # 근거: artifact retention × cron 빈도 × 30일 = ~300MB 누적 = GitHub free tier 500MB 근접 위험.
        backup_path = f"{backup_dir}/{backup_run_id}_{backup_ts}.json.gz"
        backup_payload = {
            "timestamp": datetime.now(kst).isoformat(),
            "run_id": backup_run_id,
            "spreadsheet_id": SPREADSHEET_ID,
            "tabs": {tab_name: list(rows) for tab_name, rows in data.items()},
        }
        with gzip.open(backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_payload, f, ensure_ascii=False, indent=2)
        print(f"[T-M81 백업] {backup_path} 저장 (탭 {len(data)}, 행 {sum(len(r) for r in data.values())}) [gzip]")
    except Exception as e:
        # 백업 실패 = log + 진행 (= cron 자체 중단 X). 사장님 가시성 = summary 안 표시.
        print(f"[T-M81 백업] 실패 = {e} (cron 진행)")

    # cookie warmup — Crawler 인스턴스 생성 직후 네이버 메인 1회 fetch
    # T-M26 (2026-05-12): Cold session 차단 회피. warmup 실패해도 cron 계속 진행.
    crawler.warmup()

    # D-026 Phase C+D (2026-05-16): all_known_links 구성 = 전체 시트 link union (CAFE_WHITELIST slug 만)
    # 빈 link 행 처리 시 = 이 set 안 link 와 검색 결과 매치 시 = K="중복노출" + link 자동 채움.
    # T-M25 화이트리스트 필터 정합 (= 외주 카페 link 자동 제외).
    all_known_links: set = set()
    for tab_rows in data.values():
        for r in tab_rows:
            row_link = (r.get(HEADER_LINK) or "").strip()
            if not row_link:
                continue
            # naver.me 단축 URL = resolve 비용 ↑ + 차단 위험 = skip (= 사장님 작업 후 풀 URL 입력 가정)
            if "naver.me" in row_link:
                continue
            slug, _ = parse_cafe_url(row_link)
            if slug and slug in CAFE_WHITELIST:
                all_known_links.add(row_link)
    print(f"[D-026] all_known_links 구성: {len(all_known_links)} link (CAFE_WHITELIST 필터)")

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
                # D-029 Pass 2 용 메타 — link 있는 행 = _row_link 주입 (= 양방향 갱신 매치 키).
                # 사장님 시점 = 같은 link 가 다른 키워드 행에 매치된 case 검출 = link 키 정합 필수.
                # naver.me 단축 URL = 이미 _process_row 안에서 resolve_short_url 호출 후 검색 진행.
                # 하지만 row dict 의 "링크" = 원본 단축 URL = 다른 행의 매치 link 와 직접 매치 X.
                # 다만 사장님 시트 = 빈 link 행 자동 채움 시 full URL 입력 → naver.me 매치 case 희박.
                # 보수적 = row dict 의 "링크" 그대로 사용 (= 사장님 시트 link 와 동일).
                row_link = (row.get("링크") or "").strip()
                if row_link and "_row_link" not in cols:
                    cols["_row_link"] = row_link
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
                # D-024 (2026-05-14): 예외 시 K="삭제" 자동 적용 = 폐기 (T-M10.5 학습 정합).
                # 사장님 시트 보존 우선 = updates 추가 X = 다음 cron 자연 재처리.
                # retry_queue 추가 = T-M11 정합 (전체 cycle 안 1회 재시도).
                # circuit_breaker 카운터 = health.record 로 유지 (차단 누적 검출).
                # critic Opus 발견 Major 1: except Exception silent K="삭제" = D-023 화이트리스트 우회.
                print(f"  [ROW-SKIP] [{tab_name}] 행 {row.get('_row')} 예외 = 시트 보존 (D-024 정합): {e}")
                health.record(parser_confidence=0.0, success=False)
                retry_queue.add(row, error=str(e))
                d024_skipped_rows += 1
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

    # 3.5. D-029 Pass 2 양방향 "중복노출(구좌)" 갱신 (2026-05-18 — D-026 정정)
    # 사장님 5-18 명확 의도: 같은 link 가 여러 키워드 매치 시 = 빈 link 행 + 원본 link 행 모두 K="중복노출(구좌)"
    # 사례: "도브바디스크럽" (빈 link, 매치) + "일본도브바디스크럽" (원본 link, 인기글 노출)
    #       → 양쪽 K = "중복노출(인기글)"
    # 알고리즘:
    # 1) Pass 1 결과 누적 → link → [(tab, row, matched_area), ...] map
    # 2) 같은 link 가 2+ 행에 매치 = 중복노출 검출
    # 3) 그 link 가진 모든 RowUpdate K = "중복노출(매치 구좌)" 갱신
    _d029_apply_pass2_duplicate(tab_updates)

    # 4. 시트 batch_update (탭별 1 호출)
    total_cells = 0
    for tab_name, updates in tab_updates.items():
        if updates:
            n = client.write_results(tab_name, updates)
            total_cells += n
            print(f"  [{tab_name}] {len(updates)} 행 / {n} 셀 갱신")

    # 4.5. T-M37: 매 탭에 cron 갱신 timestamp 기록 (사장님 시점 차이 인지)
    # (datetime import = 1.5 백업 block 안 이미 함수 scope import. 재사용.)
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
    summary["d024_skipped_rows"] = d024_skipped_rows  # D-024 (2026-05-14): 예외 시 시트 보존 skip 카운트
    # T-M90 (D-027 보강 2026-05-17) architect Opus C1 fix: 사장님 가시성 = secrets 미설정 시 issue #1 댓글 명시 의무.
    summary["all_known_links_count"] = len(all_known_links)
    summary["cafe_whitelist_size"] = len(CAFE_WHITELIST)
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
