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
- 컬럼: 노출영역 / L / M / 지식인탭만 갱신. 유형(C)은 type-preview artifact만 만들고 컨펌 전 write 금지.
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
from src.audit import audit_sheet_rows, build_update_trace, filter_invalid_updates, write_jsonl
from src.sheets import (
    SheetsClient, RowUpdate,
    rank_result_to_columns,
    HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK, HEADER_TYPE,
    HEADER_KEYWORD, HEADER_LAST_CHECKED_INPUT_KEY, HEADER_LAST_CHECKED_AT,
    HEADER_RAW_AREA, HEADER_RAW_L, HEADER_RAW_M, HEADER_RAW_JISIKIN,
    STALE_DISPLAY_K,
)
from src.transitions import compute_new_K, compute_new_K_with_stamp, parse_K_with_stamp, SYSTEM_K_VALUES
from src.type_preview import (
    TypePreviewCollector,
    apply_final_k_area_to_preview_rows,
    audit_type_preview_writes,
    build_type_preview_error_row,
    build_type_preview_row,
    html_status_from_html,
    summarize_type_preview,
    write_type_preview_artifact,
    write_type_preview_summary_artifact,
)
from src.stale_preview import (
    build_stale_preview_rows,
    summarize_stale_preview,
    write_stale_preview_artifact,
    write_stale_preview_summary_artifact,
)


def _format_today_kst_stamp(dt) -> str:
    """D-030 (2026-05-18): KST datetime → 사장님 결정 시점 형식 "M/D HH:MM" (= 0-padding 제거).

    사장님 결정 (= AskUserQuestion 답 1) 정합: "5/10 03:00" (= 시각까지).

    Note:
        OS 무관 호환 = strftime "%-m" (Linux) / "%#m" (Windows) 분기 회피 = 직접 int.
        예: 2026-05-10 03:00 KST → "5/10 03:00".
    """
    return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"


def _carea_filter(tab_name: str) -> bool:
    """사장님 분야 탭 필터 — '카외' 끝 탭만."""
    return tab_name.endswith("카외")


STALE_OUTPUT_CLEANUP_COLUMNS = frozenset({HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN})


def _clean_cell(value: object) -> str:
    return str(value or "").strip()


def _blank_input_stale_output_cleanup(row: dict) -> Optional[dict]:
    """Return a K/L/M/O clearing update for fully blank input rows.

    D-034: If a user/input row is blank but previous system output remains,
    clear only the system-owned columns. User-owned A-J/N cells stay untouched.
    """
    for column, value in row.items():
        if column.startswith("_") or column in STALE_OUTPUT_CLEANUP_COLUMNS:
            continue
        if _clean_cell(value):
            return None

    k_base, _ = parse_K_with_stamp(_clean_cell(row.get(HEADER_AREA, "")))
    if k_base not in SYSTEM_K_VALUES:
        return None

    if not any(_clean_cell(row.get(column, "")) for column in STALE_OUTPUT_CLEANUP_COLUMNS):
        return None

    return {
        HEADER_AREA: "",
        HEADER_L: "",
        HEADER_M: "",
        HEADER_JISIKIN: "",
    }


def _detect_ghost_stale_rows(rows: list) -> list:
    """T-M9.2 (2026-06-12, D-047): 행 복사로 들어온 숨김 시스템 칸 잔해(유령 값) 행 검출.

    배경: 마케터가 기존 행을 통째로 복사해 신규 행을 만들면 숨김 칸(마지막검사입력키/
    raw_*/마지막검사시각)까지 복사되어 "검사한 적 있는 척"하는 유령 값이 생긴다
    (2026-06-12 사건 — 07:52 백업에서 신규 30행 실증).

    잔해 판정 (Codex 태클 Major 5·6 반영 — 보수적):
    - 키워드/링크 있는 행만 대상 (입력 없는 행 = 사장님 수동 메모 영역 = 보호)
    - (a) 마지막검사입력키 빈칸인데 raw_* 또는 마지막검사시각이 남아있음
      (정상적으로 검사된 행은 항상 입력키+raw+시각이 한 묶음으로 기록됨.
       단 마이그레이션 backfill 의 "migration" 시각은 잔해 아님 = 제외)
    - (b) raw_노출영역 base 가 정확히 STALE_DISPLAY_K — 시스템이 raw 에 절대 쓰지 않는 값
      (사장님 수동 K 값("확인중" 등)은 transitions 보존 경로로 raw 에 합법 진입 가능 = 제외)
    """
    ghosts = []
    for row in rows:
        row_num = row.get("_row")
        if not row_num or int(row_num) < 2:
            continue
        keyword = _clean_cell(row.get(HEADER_KEYWORD, ""))
        link = _clean_cell(row.get(HEADER_LINK, ""))
        if not keyword and not link:
            continue
        last_key = _clean_cell(row.get(HEADER_LAST_CHECKED_INPUT_KEY, ""))
        raw_values = [
            _clean_cell(row.get(header, ""))
            for header in (HEADER_RAW_AREA, HEADER_RAW_L, HEADER_RAW_M, HEADER_RAW_JISIKIN)
        ]
        checked_at = _clean_cell(row.get(HEADER_LAST_CHECKED_AT, ""))
        ghost_orphan_output = (not last_key) and (
            any(raw_values) or (bool(checked_at) and checked_at != "migration")
        )
        raw_base, _ = parse_K_with_stamp(_clean_cell(row.get(HEADER_RAW_AREA, "")))
        ghost_stale_marker_in_raw = raw_base == STALE_DISPLAY_K
        if ghost_orphan_output or ghost_stale_marker_in_raw:
            ghosts.append(int(row_num))
    return ghosts


def _add_type_preview(collector: Optional[TypePreviewCollector], preview_row: dict) -> None:
    if collector is not None:
        collector.add(preview_row)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_confirmed_type_updates(type_preview_rows: list[dict]) -> dict[str, list[RowUpdate]]:
    """Convert approved preview candidates into C-column-only RowUpdates."""
    updates: dict[str, list[RowUpdate]] = {}
    for preview in type_preview_rows:
        if preview.get("would_update") is not True:
            continue
        if preview.get("html_status") != "ok":
            continue
        suggested_type = str(preview.get("suggested_type") or "").strip()
        tab_name = str(preview.get("tab") or "").strip()
        row_num = preview.get("row")
        if not suggested_type or not tab_name or not row_num:
            continue
        updates.setdefault(tab_name, []).append(
            RowUpdate(row=int(row_num), columns={HEADER_TYPE: suggested_type})
        )
    return updates


def _process_row(
    row: dict,
    crawler: Crawler,
    health: HealthMonitor,
    all_known_links: Optional[set] = None,  # D-026 Phase C+D (2026-05-16): 빈 link 자동 채움 logic 활용
    url_alive_cache: Optional[dict] = None,  # 호환성 유지 — 미사용 (T-M10.5 폐기)
    today_stamp: Optional[str] = None,  # D-030 (2026-05-18): "5/18 03:00" — K 시점 통합
    type_preview_collector: Optional[TypePreviewCollector] = None,
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
    prev_K_full = (row.get(HEADER_AREA) or "").strip()  # D-030: full K (= base + 시점 가능)
    prev_K_base, _ = parse_K_with_stamp(prev_K_full)  # D-030: base 만 추출 (= 기존 logic 호환)

    # D-030 (2026-05-18): today_stamp 기본값 = 호출 측 미전달 시 함수 안 KST 자동 (= test 호환).
    if today_stamp is None:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        today_stamp = _format_today_kst_stamp(datetime.now(kst))

    # 키워드 빈 행 = skip
    if not keyword:
        return None

    # D-026 Phase C+D (2026-05-16): 빈 link 행 = 키워드 검색 + 다른 행 우리 link 매치 시 자동 채움
    # D-029 (2026-05-18): 매치 구좌 명시 = "중복노출(AB)" / "중복노출(스마트블록)" / "중복노출(인기글)"
    if not link:
        # all_known_links 없음 (= 호출자가 구성 X) = 종전 동작 (미노출 표기)
        # D-030: K 통합 표기 = "미노출 (5/18 03:00~)" (= 사장님 결정 = 미노출 명시 일관)
        if not all_known_links:
            cols = {
                HEADER_AREA: compute_new_K_with_stamp(prev_K_full, "미노출", today_stamp),
                HEADER_L: "",
                HEADER_M: "",
                HEADER_JISIKIN: "",
            }
            _add_type_preview(
                type_preview_collector,
                build_type_preview_row(
                    row=row,
                    result=None,
                    columns=cols,
                    html_status="not_fetched",
                    reason="link_empty_no_known_links",
                ),
            )
            return cols

        # 키워드 검색 + parser (target_url=None + link_set 매치)
        html = crawler.fetch_search(keyword)
        html_status = html_status_from_html(html)
        try:
            result = parse_search_result(html, target_url=None, link_set=all_known_links)
        except Exception as e:
            _add_type_preview(
                type_preview_collector,
                build_type_preview_error_row(
                    row=row,
                    html_status="parse_failed",
                    reason=f"parse_failed: {e}",
                ),
            )
            raise

        if result.matched_url:
            # D-029: 매치 구좌 = result.exposure_area.value (= "AB" / "스마트블록" / "인기글")
            # parser 가 매치한 구좌 = parse_search_result 가 AB→SMART_BLOCK→POPULAR 분기 매치 후 그 enum 설정.
            matched_area = result.exposure_area.value  # "AB" / "스마트블록" / "인기글"
            # 보수적 fallback: 매치 area 가 노출 3종 외 시 (= 이상 case) = "중복노출" 단일 (D-026 호환)
            if matched_area in {"AB", "스마트블록", "인기글"}:
                new_K_base = f"중복노출({matched_area})"
            else:
                new_K_base = "중복노출"
            # D-030: K 통합 표기 = base + today 시점 (= 새 발견 = 새 시점 기록)
            new_K_full = compute_new_K_with_stamp(prev_K_full, new_K_base, today_stamp)
            cols = rank_result_to_columns(
                block_order=result.block_order,
                exposure_area=new_K_full,
                integrated_rank=result.integrated_rank,
                cafe_slot_rank=result.cafe_slot_rank,
                in_jisikin=result.in_jisikin,
            )
            cols[HEADER_AREA] = new_K_full
            cols[HEADER_LINK] = result.matched_url  # D-026 자동 채움 (sheets.py 빈 link 행만 허용)
            # D-029 Pass 2 양방향 갱신용 메타 키 — sheets.write_results 가 mapping 없는 키 자동 skip
            cols["_matched_area"] = matched_area
            health.record(
                parser_confidence=result.parser_confidence,
                success=True,
                block_type=new_K_base,  # health = base 만 (= 시점 무관)
            )
            _add_type_preview(
                type_preview_collector,
                build_type_preview_row(row=row, result=result, columns=cols, html_status=html_status),
            )
            return cols

        # 빈 link 행 + 매치 X = "미노출 (시점~)"
        health.record(parser_confidence=0.0, success=True, block_type=None)
        cols = {
            HEADER_AREA: compute_new_K_with_stamp(prev_K_full, "미노출", today_stamp),
            HEADER_L: "",
            HEADER_M: "",
            HEADER_JISIKIN: "",
        }
        _add_type_preview(
            type_preview_collector,
            build_type_preview_row(row=row, result=result, columns=cols, html_status=html_status),
        )
        return cols

    # naver.me 단축 URL 해석
    if "naver.me" in link:
        link = resolve_short_url(link)

    # 검색 + parser (target_url 단독 매치만)
    html = crawler.fetch_search(keyword)
    html_status = html_status_from_html(html)
    try:
        result = parse_search_result(html, link)
    except Exception as e:
        _add_type_preview(
            type_preview_collector,
            build_type_preview_error_row(
                row=row,
                html_status="parse_failed",
                reason=f"parse_failed: {e}",
            ),
        )
        raise

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

    # 사장님 컨벤션 K 결정 (D-026 Phase B+E+F) — base 만 (= 시점 X)
    new_K_base = compute_new_K(
        prev_K=prev_K_base,  # D-030: base 만 전달 (= 시점 제거)
        search_found=search_found,
        url_alive=True,  # T-M10.5 폐기 후 = 항상 True
        area=result.exposure_area.value if search_found else None,
        deletion_detected=deletion_detected,
    )

    # D-030 (2026-05-18): K 통합 표기 (= base + 시점)
    new_K_full = compute_new_K_with_stamp(prev_K_full, new_K_base, today_stamp)

    # health 누적
    # D-026 Phase A+C+D (2026-05-16): 스마트블록 부활 + 중복노출 정합 = block_type 화이트리스트 확장.
    # D-029 (2026-05-18): 중복노출(구좌) 3종 추가 = block_type 화이트리스트 확장.
    # D-030 (2026-05-18): health = base 만 (= 시점 무관)
    health.record(
        parser_confidence=result.parser_confidence,
        success=True,
        block_type=new_K_base if new_K_base in {
            "AB", "스마트블록", "인기글",
            "중복노출", "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",
        } else None,
    )

    # 시트 컬럼 dict 변환 (시트 "링크" 컬럼 = 기존 link 행 = 자동 갱신 X = D-023 가드)
    # D-030: exposure_area = full K (= base + 시점)
    cols = rank_result_to_columns(
        block_order=result.block_order,
        exposure_area=new_K_full,
        integrated_rank=result.integrated_rank if search_found else None,
        cafe_slot_rank=result.cafe_slot_rank if search_found else None,
        in_jisikin=result.in_jisikin,
    )
    _add_type_preview(
        type_preview_collector,
        build_type_preview_row(row=row, result=result, columns=cols, html_status=html_status),
    )
    return cols


def _d029_apply_pass2_duplicate(
    tab_updates: dict[str, list["RowUpdate"]],
    today_stamp: Optional[str] = None,  # D-030 (2026-05-18): "5/18 03:00" 시점 결합
) -> int:
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
    # D-030 (2026-05-18): today_stamp 기본값 = 호출 측 미전달 시 함수 안 KST 자동.
    if today_stamp is None:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        today_stamp = _format_today_kst_stamp(datetime.now(kst))

    # 1) link → [(tab, row, matched_area, cols), ...] map 구성
    # cols 직접 참조 = 갱신 시 in-place 수정 = 시트 반영 보장.
    link_to_matches: dict[str, list[tuple[str, int, str, dict]]] = {}
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            cols = upd.columns
            current_K_full = cols.get(HEADER_AREA, "")
            # D-030 (2026-05-18): base 추출 (= 시점 제거 후 case B 분기 판정)
            current_K_base, _ = parse_K_with_stamp(current_K_full)

            # 케이스 A: 빈 link 자동 채움 행 = cols[HEADER_LINK] + cols["_matched_area"] 존재
            link_val: Optional[str] = None
            matched_area: Optional[str] = None
            if HEADER_LINK in cols and cols.get("_matched_area"):
                link_val = cols[HEADER_LINK]
                matched_area = cols["_matched_area"]
            # 케이스 B: 원본 link 행 = current_K_base = 노출 3종 (= 검색 노출, link 매치 완료)
            # D-030: base 비교 (= 시점 무관)
            elif current_K_base in {"AB", "스마트블록", "인기글"}:
                # 이 행의 link = sheets._row + 원 row dict 의 "링크" 값.
                # cols 에 link 없으므로 = 원본 row 메타 추적 X = link 추출 불가 case.
                # 다만 spec 가 row 메타 보존 = upd.row + tab_name 으로 매치 결정 어려움.
                # 대안 = upd.columns 자체에 link 정보 보존 X → 외부에서 row dict 전달 의무.
                # 본 helper = tab_updates 만 처리 = link 추출 불가 = case B skip.
                # 사장님 시트 양방향 갱신 = 빈 link 자동 채움 시 = 원본 link 매치된 다른 행 검출 필요.
                # 해결: case B 행 cols 에 "_row_link" 메타 보존 (= run_cycle 에서 _process_row 후 주입).
                link_val = cols.get("_row_link")
                if link_val:
                    matched_area = current_K_base  # D-030: base 만 사용
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
        new_K_base = f"중복노출({areas[0]})"

        for _tab, _row, _area, cols in matches:
            old_K_full = cols.get(HEADER_AREA, "")
            # D-030 (2026-05-18): K 통합 표기 (= base + 시점)
            # prev_K_full = old_K_full = base 동일 시 시점 보존 / base 전환 시 today 시점 기록.
            new_K_full = compute_new_K_with_stamp(old_K_full, new_K_base, today_stamp)
            cols[HEADER_AREA] = new_K_full
            updated_count += 1
            print(f"  [D-029-PASS2] {_tab} row={_row} K: {old_K_full!r} → {new_K_full!r} (link={link_val[:70]})")

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
    type_preview = TypePreviewCollector()
    type_preview_write_confirmed = _env_truthy("TYPE_PREVIEW_WRITE_CONFIRMED")
    type_preview_write_allow_bulk = _env_truthy("TYPE_PREVIEW_WRITE_ALLOW_BULK")
    stale_formula_mode_enabled = _env_truthy("STALE_OUTPUT_FORMULA_MODE")
    recheck_stale_only_enabled = _env_truthy("RECHECK_STALE_ONLY")
    if type_preview_write_confirmed:
        print("[TYPE-PREVIEW] confirmed C-column write enabled")
    if type_preview_write_allow_bulk:
        print("[TYPE-PREVIEW] bulk-change guard override enabled")
    if stale_formula_mode_enabled:
        print("[STALE-FORMULA] K/L/M/O formula mode enabled")
    if recheck_stale_only_enabled:
        print("[RECHECK-STALE-ONLY] stale_input rows only")
    d024_skipped_rows = 0  # D-024 (2026-05-14): except 시 시트 보존 skip 카운트 (사장님 가시성)

    # 1. 시트 read
    data = client.load_all_data_tabs(tab_filter=_carea_filter)
    print(f"대상 탭 {len(data)}개: {list(data.keys())}")

    # 1.5. T-M81 (D-027 2026-05-17): 백업 자동화 — run_cycle 시작 시 시트 K/L/M/링크/유형 전체 read → .harness/backups/{run_id}.json 저장.
    # 사장님 사고 시 = scripts/restore_backup.py {run_id}.json = 즉시 복원. shadow mode 폐기 정합 (= 시트 즉시 갱신 + 사고 시 백업 복원).
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    # D-030 (2026-05-18): today_kst_stamp = "M/D HH:MM" 형식 (= 사장님 결정 = "5/10 03:00" 정합)
    # cron 시작 시점 = 모든 행 K 시점 기록의 단일 기준 (= 832 행 마이그레이션 = 오늘 자동 기록).
    today_kst_stamp = _format_today_kst_stamp(datetime.now(kst))
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    artifact_ts = datetime.now(kst).strftime("%Y%m%dT%H%M%S")
    trace_path = f".harness/traces/{run_id}_{artifact_ts}_row-trace.jsonl"
    prewrite_audit_path = f".harness/audits/{run_id}_{artifact_ts}_prewrite-invariant.jsonl"
    postwrite_audit_path = f".harness/audits/{run_id}_{artifact_ts}_post-write-audit.jsonl"
    typewrite_audit_path = f".harness/audits/{run_id}_{artifact_ts}_type-write-audit.jsonl"
    type_preview_path = f".harness/type-previews/{run_id}_{artifact_ts}_type-preview.jsonl"
    type_preview_summary_path = f".harness/type-previews/{run_id}_{artifact_ts}_type-preview-summary.md"
    stale_preview_path = f".harness/stale-previews/{run_id}_{artifact_ts}_stale-preview.jsonl"
    stale_preview_summary_path = f".harness/stale-previews/{run_id}_{artifact_ts}_stale-preview-summary.md"
    try:
        backup_dir = ".harness/backups"
        os.makedirs(backup_dir, exist_ok=True)
        # T-M90 (D-027 보강 2026-05-17) architect Opus m1 fix: JSON → gzip 압축 (~2.5MB → ~150KB).
        # 근거: artifact retention × cron 빈도 × 30일 = ~300MB 누적 = GitHub free tier 500MB 근접 위험.
        backup_path = f"{backup_dir}/{run_id}_{artifact_ts}.json.gz"
        backup_payload = {
            "timestamp": datetime.now(kst).isoformat(),
            "run_id": run_id,
            "spreadsheet_id": SPREADSHEET_ID,
            "tabs": {tab_name: list(rows) for tab_name, rows in data.items()},
        }
        with gzip.open(backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_payload, f, ensure_ascii=False, indent=2)
        print(f"[T-M81 백업] {backup_path} 저장 (탭 {len(data)}, 행 {sum(len(r) for r in data.values())}) [gzip]")
    except Exception as e:
        # 백업 실패 = log + 진행 (= cron 자체 중단 X). 사장님 가시성 = summary 안 표시.
        print(f"[T-M81 백업] 실패 = {e} (cron 진행)")

    # 아카이브 날짜는 사이클 시작 시각으로 한 번만 정한다(1.6·4.7 이 같은 블록을 쓰게).
    archive_date_started = datetime.now(kst).strftime("%Y-%m-%d")
    summary_archive_warn: list = []

    # 상위노출 실적 일별 아카이빙 — **1차(안전망)**. ARCHIVE_ENABLED truthy 일 때만.
    # 공개 repo 라 데이터는 repo 아닌 비공개 시트 탭에만 남긴다. 날짜별 멱등(하루 1벌).
    # best-effort: 아카이빙 실패가 cron 을 죽이지 않도록 try/except 로 격리.
    # ★여기 기록은 아직 이번 크롤 결과가 안 들어간 '직전 상태'다. 사이클이 중간에 죽어도
    #   그날 기록이 남게 하는 안전망일 뿐이고, 진짜 그날 값은 4.7(사이클 끝)에서 덮어쓴다.
    if _env_truthy("ARCHIVE_ENABLED"):
        try:
            from src.archive import build_archive_rows, append_daily_archive
            archive_date = archive_date_started
            archive_rows = build_archive_rows(data, archive_date)
            archive_result = append_daily_archive(client, archive_rows, archive_date)
            if archive_result.get("error"):
                print(f"[아카이브] 실패 = {archive_result['error']} (cron 진행)")
            else:
                print(
                    f"[아카이브] {archive_result['rows_written']} 행 기록 "
                    f"(date={archive_result['date']}, 탭생성={archive_result['created_tab']})"
                )
        except Exception as e:
            print(f"[아카이브] 실패 = {e} (cron 진행)")

    stale_formula_setup_summary = {"tabs": 0, "headers_added": 0, "rows_backfilled": 0, "formula_rows": 0}
    if stale_formula_mode_enabled:
        for tab_name, rows in data.items():
            setup = client.ensure_stale_formula_mode(tab_name, rows)
            stale_formula_setup_summary["tabs"] += 1
            stale_formula_setup_summary["headers_added"] += int(setup.get("headers_added", 0) or 0)
            stale_formula_setup_summary["rows_backfilled"] += int(setup.get("rows_backfilled", 0) or 0)
            stale_formula_setup_summary["formula_rows"] += int(setup.get("formula_rows", 0) or 0)
        # Reload after formula/header migration so preview, backup-adjacent audits,
        # and crawler context all see the current formula-mode sheet shape.
        data = client.load_all_data_tabs(tab_filter=_carea_filter)
        print(
            "[STALE-FORMULA] setup "
            f"tabs={stale_formula_setup_summary['tabs']} "
            f"headers_added={stale_formula_setup_summary['headers_added']} "
            f"rows_backfilled={stale_formula_setup_summary['rows_backfilled']} "
            f"formula_rows={stale_formula_setup_summary['formula_rows']}"
        )

    # T-M9.2 (D-047): 행 복사 잔해 소독 — 유령 검사값 초기화 후 이번 run 에서 정상 재검사.
    # read 직후 즉시 수행 = 행 번호 어긋남 창 최소화. 숨김 시스템 칸만 초기화 (D-023 정합).
    ghost_sanitized_rows = 0
    if stale_formula_mode_enabled:
        for tab_name, rows in data.items():
            ghost_rows = _detect_ghost_stale_rows(rows)
            if not ghost_rows:
                continue
            try:
                cleared = client.clear_stale_formula_cells(tab_name, ghost_rows)
                ghost_sanitized_rows += len(ghost_rows)
                print(f"[D-047-GHOST-CLEAR] [{tab_name}] 복사 잔해 {len(ghost_rows)} 행 숨김 칸 초기화 ({cleared} 셀)")
            except Exception as e:
                # 소독 실패 = cron 중단 X (어차피 write 단계 재배치가 올바른 값으로 덮음)
                print(f"[D-047-GHOST-CLEAR] [{tab_name}] 초기화 실패 = {e} (cron 진행)")

    # D-032: post-write audit baseline. 기존 시트 debt 는 artifact/comment 에 남기되,
    # 이번 run 이 새로 만들었거나 건드린 행만 workflow 실패 조건으로 본다.
    pre_write_sheet_issues = audit_sheet_rows(data)
    pre_write_issue_keys = {(issue.get("tab"), issue.get("row")) for issue in pre_write_sheet_issues}
    if pre_write_sheet_issues:
        print(f"[D-032-PRE-AUDIT] 기존 시트 불가능 조합 {len(pre_write_sheet_issues)}건 (baseline)")

    # D-039: input-fingerprint stale-output preview. Preview-only:
    # no hidden columns, formulas, raw-output columns, or visible K/L/M/O writes.
    stale_preview_rows = build_stale_preview_rows(data)
    stale_preview_summary = summarize_stale_preview(stale_preview_rows)
    try:
        write_stale_preview_artifact(stale_preview_path, stale_preview_rows)
        write_stale_preview_summary_artifact(stale_preview_summary_path, stale_preview_rows, stale_preview_summary)
        print(
            f"[STALE-PREVIEW] {stale_preview_path} 저장 "
            f"({len(stale_preview_rows)} rows, mask={stale_preview_summary.get('stale_preview_would_mask_rows', 0)})"
        )
    except Exception as e:
        print(f"[STALE-PREVIEW] 저장 실패 = {e} (cron 진행)")
        stale_preview_rows = []
        stale_preview_summary = summarize_stale_preview(stale_preview_rows)

    processing_data = data
    recheck_stale_only_targets = {
        (str(row.get("tab") or "").strip(), int(row.get("row")))
        for row in stale_preview_rows
        if row.get("freshness_status") == "stale_input" and row.get("tab") and row.get("row")
    }
    if recheck_stale_only_enabled:
        processing_data = {
            tab_name: [
                row for row in rows
                if (tab_name, int(row.get("_row"))) in recheck_stale_only_targets
            ]
            for tab_name, rows in data.items()
        }
        processing_data = {tab_name: rows for tab_name, rows in processing_data.items() if rows}
        print(f"[RECHECK-STALE-ONLY] target rows={len(recheck_stale_only_targets)} tabs={list(processing_data.keys())}")

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
    row_context: dict[tuple[str, int], dict] = {}
    circuit_breaker_tripped = False  # 2026-05-11 architect Major 1 fix
    # 운영 3 (2026-05-18): 네이버 차단 검출 카운터 — 사장님 메일 알림 강화.
    # CircuitBreakerOpen raise 시 = 그 시점 누적 연속 차단 + circuit_breaker_blocks += 1.
    # 다음 cron 자동 회복 시도 정합 (= cron 빈도 6h = 최대 24시간 = 4회 자동 회복 윈도우).
    circuit_breaker_blocks = 0
    for tab_name, rows in processing_data.items():
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
            if row.get("_row") is not None:
                row_context[(tab_name, row["_row"])] = row
            try:
                cleanup_cols = _blank_input_stale_output_cleanup(row)
                if cleanup_cols is not None:
                    updates.append(RowUpdate(row=row["_row"], columns=cleanup_cols))
                    continue

                cols = _process_row(
                    row,
                    crawler,
                    health,
                    all_known_links=all_known_links,
                    url_alive_cache=url_alive_cache,
                    today_stamp=today_kst_stamp,
                    type_preview_collector=type_preview,
                )
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
                # 운영 3 (2026-05-18): 사장님 메일 알림 강화 = circuit_breaker_blocks 카운트.
                print(f"❌ [{tab_name}] {e}")
                type_preview.add(build_type_preview_error_row(
                    row=row,
                    html_status="blocked",
                    reason=f"blocked: {e}",
                ))
                circuit_breaker_tripped = True
                circuit_breaker_blocks += 1
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
            cols = _process_row(
                row,
                crawler,
                health,
                all_known_links=all_known_links,
                url_alive_cache=url_alive_cache,
                today_stamp=today_kst_stamp,
                type_preview_collector=type_preview,
            )
            return cols
        retry_results = retry_queue.process(retry_processor, slowdown_multiplier=2.0)
        for r in retry_results:
            tab = r["row"].get("_tab", "")
            if tab not in tab_updates:
                continue
            if r["ok"] and r["update"] is not None:
                cols = r["update"]
                row_link = (r["row"].get("링크") or "").strip()
                if row_link and "_row_link" not in cols:
                    cols["_row_link"] = row_link
                row_context[(tab, r["row"]["_row"])] = r["row"]
                tab_updates[tab].append(RowUpdate(row=r["row"]["_row"], columns=cols))
            else:
                # 2026-05-11 D-017 fix: 재시도도 실패 = K 보존 (시트에 기록하지 않음).
                # 이전 (critic 2026-05-08): "삭제" 기록 — 사장님 작업자 혼란 (차단≠진짜 삭제).
                # 사장님 시트 손상 사례 후 폐기. 다음 cron 자연 재처리.
                print(f"  [SKIP-PRESERVE] row={r['row'].get('_row')} kw={r['row'].get('키워드')!r}: retry 실패, K 보존")
                error_text = str(r.get("error", ""))
                html_status = "blocked" if any(
                    token in error_text.lower()
                    for token in ("blocked", "rate", "429", "차단", "limited")
                ) else "parse_failed"
                reason_prefix = "blocked" if html_status == "blocked" else "parse_failed"
                type_preview.add(build_type_preview_error_row(
                    row=r["row"],
                    html_status=html_status,
                    reason=f"{reason_prefix}: {error_text}",
                ))

    # 3.5. D-029 Pass 2 양방향 "중복노출(구좌)" 갱신 (2026-05-18 — D-026 정정)
    # 사장님 5-18 명확 의도: 같은 link 가 여러 키워드 매치 시 = 빈 link 행 + 원본 link 행 모두 K="중복노출(구좌)"
    # 사례: "도브바디스크럽" (빈 link, 매치) + "일본도브바디스크럽" (원본 link, 인기글 노출)
    #       → 양쪽 K = "중복노출(인기글)"
    # 알고리즘:
    # 1) Pass 1 결과 누적 → link → [(tab, row, matched_area), ...] map
    # 2) 같은 link 가 2+ 행에 매치 = 중복노출 검출
    # 3) 그 link 가진 모든 RowUpdate K = "중복노출(매치 구좌)" 갱신
    _d029_apply_pass2_duplicate(tab_updates, today_stamp=today_kst_stamp)
    attempted_update_keys = {
        (tab_name, upd.row)
        for tab_name, updates in tab_updates.items()
        for upd in updates
    }

    # 3.5.5. 유형(C) 1차 preview artifact. 시트 C열 write 금지, JSONL artifact 만 생성.
    # suggested_type = 키워드 검색 결과 최상단 대표 구좌. k_area = 내 링크의 실제 K 상태.
    type_preview_rows = apply_final_k_area_to_preview_rows(type_preview.rows(), tab_updates)
    type_preview_summary = summarize_type_preview(type_preview_rows)
    try:
        write_type_preview_artifact(type_preview_path, type_preview_rows)
        print(f"[TYPE-PREVIEW] {type_preview_path} 저장 ({len(type_preview_rows)} rows)")
    except Exception as e:
        print(f"[TYPE-PREVIEW] 저장 실패 = {e} (cron 진행)")
        type_preview_rows = []
        type_preview_summary = summarize_type_preview(type_preview_rows)

    # 3.6. D-032: pre-write invariant gate + row-level trace artifact.
    # 빈 link 행이 plain AB/스마트블록/인기글 + L/M 으로 쓰이는 불가능 조합은 시트 반영 전 격리한다.
    filtered_updates, prewrite_invariant_issues = filter_invalid_updates(tab_updates, row_context)
    if prewrite_invariant_issues:
        print(f"[D-032-INVARIANT] 시트 write 전 불가능 조합 {len(prewrite_invariant_issues)}건 격리")
        for issue in prewrite_invariant_issues[:10]:
            print(
                f"  [D-032-INVARIANT] {issue.get('tab')} row={issue.get('row')} "
                f"kw={issue.get('keyword')!r} K={issue.get('k_full')!r} L={issue.get('L')!r} M={issue.get('M')!r}"
            )
    try:
        write_jsonl(prewrite_audit_path, prewrite_invariant_issues)
        trace_rows = build_update_trace(tab_updates, row_context, prewrite_invariant_issues)
        write_jsonl(trace_path, trace_rows)
        print(f"[D-032-TRACE] {trace_path} 저장 ({len(trace_rows)} rows)")
    except Exception as e:
        print(f"[D-032-TRACE] 저장 실패 = {e} (cron 진행)")
    tab_updates = filtered_updates

    # 4. 시트 batch_update (탭별 1 호출)
    kst_iso = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
    total_cells = 0
    stale_formula_mode_cells = 0
    # T-M9.1/9.3 (D-047): 재배치 통계 누적 (모든 탭 합산) — summary + issue 가시성
    stale_relocation_stats = {
        "relocation_miss_rows": 0,
        "relocation_conflict_keys": 0,
        "relocation_fanout_rows": 0,
    }
    for tab_name, updates in tab_updates.items():
        if updates:
            if stale_formula_mode_enabled:
                n = client.write_stale_formula_results(
                    tab_name,
                    updates,
                    row_context=row_context,
                    checked_at=kst_iso,
                    stats_out=stale_relocation_stats,
                )
                stale_formula_mode_cells += n
            else:
                n = client.write_results(tab_name, updates)
            total_cells += n
            print(f"  [{tab_name}] {len(updates)} 행 / {n} 셀 갱신")

    type_preview_write_cells = 0
    type_preview_write_rows = 0
    type_preview_write_requested_rows = 0
    type_preview_write_blocked_by_bulk_guard = False
    type_tab_updates: dict[str, list[RowUpdate]] = {}
    if type_preview_write_confirmed:
        # 교착 완전봉인(2026-07-01): bulk-guard 는 count(>100) 또는 ratio(>50%)로 트립한다.
        #   · count 만(정상 대량변경, 예: 날짜롤오버 '중복노출' 재분류 ~12~15%)으로 트립된 건 flush 허용.
        #     이유: would_update 행은 이미 전부 html_status==SAFE(정상 페이지) 필터를 통과 → 구조적으로 안전.
        #     C열을 영구 차단하면 backlog(100칸+)가 안 빠져 매 run 재트립 = 교착(9연속 빨강의 근원).
        #   · ratio>50%(대부분 행이 유형 변경 = 파서 catastrophe 신호)로 트립됐으면 그대로 차단(안전브레이크 유지).
        #     진짜 파서 드리프트는 이 ratio 가드 + K분포 anomaly(detect_k_anomaly) 로 계속 잡힌다.
        bulk_tripped = bool(type_preview_summary.get("type_preview_bulk_guard_triggered"))
        update_ratio = float(type_preview_summary.get("type_preview_update_ratio", 0.0))
        catastrophe = update_ratio > 0.50   # = TYPE_PREVIEW_BULK_MAX_UPDATE_RATIO
        if bulk_tripped and not type_preview_write_allow_bulk and catastrophe:
            type_preview_write_blocked_by_bulk_guard = True
            print(f"[TYPE-PREVIEW] bulk-change guard: 변경비율 {update_ratio:.0%} > 50% (파서 이상 의심) → C-column write skipped")
        else:
            if bulk_tripped and not type_preview_write_allow_bulk:
                print(f"[TYPE-PREVIEW] bulk-change guard: count 트립이나 비율 {update_ratio:.0%} ≤ 50% (정상 대량변경) → C열 flush(교착 방지)")
            type_tab_updates = _build_confirmed_type_updates(type_preview_rows)
            for tab_name, updates in type_tab_updates.items():
                if updates:
                    type_preview_write_requested_rows += len(updates)
                    n = client.write_type_results(tab_name, updates)
                    type_preview_write_cells += n
                    type_preview_write_rows += n
                    print(f"  [TYPE-WRITE:{tab_name}] {len(updates)} rows requested / {n} cells updated")
    else:
        print("[TYPE-PREVIEW] C-column write disabled; preview-only")

    # T-M37(cron 갱신 timestamp) 비활성화 (D-058): write_timestamp 가 1행 16열에 기록했으나
    # 사장님 시트에선 16열 = 지식인탭 → 매 cron 지식인 헤더가 "cron 갱신: 날짜"로 손상됨
    # ('지식인 0개' 오답의 구조적 뿌리). 신선도는 텔레그램 보고 + 마지막검사시각으로 충분 → 기록 제거.

    # 4.6. D-032: post-write audit — 실제 시트 상태에서 불가능 조합 재확인.
    post_write_audit_issues: list[dict] = []
    post_write_blocking_issues: list[dict] = []
    type_preview_write_audit_issues: list[dict] = []
    post_write_audit_error = ""
    post_write_data: dict = {}   # 아래 read 가 실패해도 이름이 살아있게(4.7 아카이브가 참조)
    try:
        post_write_data = client.load_all_data_tabs(tab_filter=_carea_filter)
        post_write_audit_issues = audit_sheet_rows(post_write_data)
        post_write_blocking_issues = [
            issue for issue in post_write_audit_issues
            if (issue.get("tab"), issue.get("row")) not in pre_write_issue_keys
            or (issue.get("tab"), issue.get("row")) in attempted_update_keys
        ]
        write_jsonl(postwrite_audit_path, post_write_audit_issues)
        if post_write_audit_issues:
            preexisting_count = len(post_write_audit_issues) - len(post_write_blocking_issues)
            print(
                f"[D-032-POST-AUDIT] 실제 시트 불가능 조합 {len(post_write_audit_issues)}건 "
                f"(blocking={len(post_write_blocking_issues)}, preexisting={preexisting_count})"
            )
            for issue in post_write_audit_issues[:10]:
                print(
                    f"  [D-032-POST-AUDIT] {issue.get('tab')} row={issue.get('row')} "
                    f"kw={issue.get('keyword')!r} K={issue.get('k_full')!r} L={issue.get('L')!r} M={issue.get('M')!r}"
                )
        else:
            print("[D-032-POST-AUDIT] 불가능 조합 0건")

        if type_preview_write_confirmed and not type_preview_write_blocked_by_bulk_guard:
            type_preview_write_audit_issues = audit_type_preview_writes(type_preview_rows, post_write_data)
            write_jsonl(typewrite_audit_path, type_preview_write_audit_issues)
            if type_preview_write_audit_issues:
                print(f"[TYPE-WRITE-AUDIT] C열 write 불일치 {len(type_preview_write_audit_issues)}건")
                for issue in type_preview_write_audit_issues[:10]:
                    print(
                        f"  [TYPE-WRITE-AUDIT] {issue.get('tab')} row={issue.get('row')} "
                        f"kw={issue.get('keyword')!r} expected={issue.get('suggested_type')!r} "
                        f"actual={issue.get('actual_type')!r}"
                    )
            else:
                print("[TYPE-WRITE-AUDIT] C열 write 불일치 0건")
    except Exception as e:
        post_write_audit_error = str(e)
        print(f"[D-032-POST-AUDIT] 실패 = {e} (cron 진행, summary 에 기록)")

    # 4.7. 상위노출 실적 아카이빙 — **이번 사이클 결과가 반영된 뒤** 다시 기록.
    #
    # ★왜 두 번 쓰나 (2026-07-23 수정)
    #   아카이브는 원래 사이클 '시작' 지점(위 1.6)에서만 기록했다. 그 시점 시트는 아직
    #   이번 크롤 결과가 안 들어간 **직전 사이클 상태**다. 하루 마지막 cron(18:07)이
    #   그날 블록을 12:07 상태로 덮어쓰고 끝나므로, 그날의 마지막 크롤 결과는 그날
    #   기록에 영영 안 들어간다. 실측(2026-07-23): 이력 노출 155 vs 실제 시트 163,
    #   396행 중 52행 불일치·8행은 노출/미노출 판정 자체가 뒤집힘 → 대시보드의
    #   '오늘 상위노출/누락'이 반나절 옛 숫자였다.
    #   이제 시작 기록은 '사이클이 중간에 죽어도 그날 기록은 남는다'는 안전망으로만 두고,
    #   여기서 post_write_data(쓰기 후 실제 시트)로 같은 날짜 블록을 덮어써 최신화한다.
    #   날짜별 멱등이라 행이 늘지 않는다(같은 날짜 블록을 새로 넣고 옛것을 지운다).
    if _env_truthy("ARCHIVE_ENABLED"):
        if post_write_data:
            try:
                from src.archive import append_daily_archive, build_archive_rows
                # ★1.6 이 쓴 날짜를 그대로 재사용한다. 여기서 now() 를 다시 부르면
                #   사이클이 자정을 넘겼을 때 1.6 은 어제 블록, 4.7 은 오늘 블록에 써서
                #   어제가 '크롤 전 상태'로 굳는다(독립검토 LOW-1).
                archive_date = archive_date_started
                rows_after = build_archive_rows(post_write_data, archive_date)
                res_after = append_daily_archive(client, rows_after, archive_date)
                if res_after.get("error"):
                    print(f"[아카이브:사이클끝] 실패 = {res_after['error']} (시작 시점 기록 유지)")
                elif res_after.get("skipped"):
                    # 0행 = 헤더가 바뀌었거나 읽기가 반쯤 실패한 것. 성공처럼 지나가면 안 된다.
                    print(f"[아카이브:사이클끝] ⚠️ {res_after['skipped']}")
                    summary_archive_warn.append(res_after["skipped"])
                else:
                    if res_after.get("skipped_delete"):
                        print(f"[아카이브:사이클끝] ⚠️ {res_after['skipped_delete']}")
                        summary_archive_warn.append(res_after["skipped_delete"])
                    print(f"[아카이브:사이클끝] {res_after['rows_written']} 행으로 갱신 "
                          f"(date={archive_date}, 이번 크롤 결과 반영)")
            except Exception as e:
                print(f"[아카이브:사이클끝] 실패 = {e} (시작 시점 기록 유지)")
        else:
            # post-write audit 이 실패해 시트를 다시 못 읽은 경우. 옛 상태로 덮어쓰면
            # 오히려 더 나빠지므로 아무것도 하지 않고 그 사실만 남긴다.
            print("[아카이브:사이클끝] 건너뜀 — 쓰기 후 시트를 못 읽음(시작 시점 기록 유지)")

    # 4.9. 경쟁사 이력 적재 + 랭킹 갱신 (2026-07-23, COMPETITOR_TRACK_ENABLED 일 때만).
    # 비공개 시트 탭 2개(경쟁사_이력 / 경쟁사_랭킹)만 건드린다 — 사장님 작업 탭은 손대지 않는다.
    # best-effort: 실패해도 순위 검사 결과와 cron 을 죽이지 않는다.
    # 5. K 분포 + 처리 시간 집계 (사장님 알림용 풍부 summary)
    # D-030 (2026-05-18): K 분포 = base 만 (= 시점 제거 = anomaly 감지 정합 + 일관성)
    k_distribution: Counter = Counter()
    total_rows_with_link = 0
    for tab, updates in tab_updates.items():
        for upd in updates:
            total_rows_with_link += 1
            k_val_full = upd.columns.get(HEADER_AREA, "") or "미노출"
            k_val_base, _ = parse_K_with_stamp(k_val_full)
            k_distribution[k_val_base or "미노출"] += 1

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
    summary["circuit_breaker_blocks"] = circuit_breaker_blocks  # 운영 3 (2026-05-18): 네이버 차단 검출 카운트 = 사장님 메일 알림 강화
    summary["d024_skipped_rows"] = d024_skipped_rows  # D-024 (2026-05-14): 예외 시 시트 보존 skip 카운트
    # T-M90 (D-027 보강 2026-05-17) architect Opus C1 fix: 사장님 가시성 = secrets 미설정 시 issue #1 댓글 명시 의무.
    summary["all_known_links_count"] = len(all_known_links)
    summary["cafe_whitelist_size"] = len(CAFE_WHITELIST)
    summary["prewrite_invariant_violations"] = len(prewrite_invariant_issues)
    summary["post_write_audit_violations"] = len(post_write_blocking_issues)
    summary["post_write_audit_total_issues"] = len(post_write_audit_issues)
    summary["post_write_audit_preexisting_issues"] = max(0, len(post_write_audit_issues) - len(post_write_blocking_issues))
    summary["row_trace_path"] = trace_path
    summary["prewrite_audit_path"] = prewrite_audit_path
    summary["post_write_audit_path"] = postwrite_audit_path
    summary["type_preview_path"] = type_preview_path
    summary["type_preview_summary_path"] = type_preview_summary_path
    summary.update(type_preview_summary)
    summary["stale_preview_path"] = stale_preview_path
    summary["stale_preview_summary_path"] = stale_preview_summary_path
    summary.update(stale_preview_summary)
    summary["type_preview_write_confirmed"] = type_preview_write_confirmed
    summary["type_preview_write_allow_bulk"] = type_preview_write_allow_bulk
    summary["type_preview_write_blocked_by_bulk_guard"] = type_preview_write_blocked_by_bulk_guard
    summary["type_preview_write_requested_rows"] = type_preview_write_requested_rows
    summary["type_preview_write_rows"] = type_preview_write_rows
    summary["type_preview_write_cells"] = type_preview_write_cells
    summary["type_preview_write_audit_path"] = typewrite_audit_path
    summary["type_preview_write_audit_violations"] = len(type_preview_write_audit_issues)
    summary["stale_formula_mode_enabled"] = stale_formula_mode_enabled
    summary["stale_formula_mode_cells_written"] = stale_formula_mode_cells
    summary["stale_formula_mode_setup"] = stale_formula_setup_summary
    # T-M9.1~9.3 (D-047): 동시 편집 면역 가시성
    summary["relocation_miss_rows"] = stale_relocation_stats["relocation_miss_rows"]
    summary["relocation_conflict_keys"] = stale_relocation_stats["relocation_conflict_keys"]
    summary["relocation_fanout_rows"] = stale_relocation_stats["relocation_fanout_rows"]
    summary["ghost_sanitized_rows"] = ghost_sanitized_rows
    summary["recheck_stale_only_enabled"] = recheck_stale_only_enabled
    summary["recheck_stale_only_target_rows"] = len(recheck_stale_only_targets)
    summary["type_preview_bulk_guard_overridden"] = (
        type_preview_write_confirmed
        and type_preview_summary.get("type_preview_bulk_guard_triggered", False)
        and type_preview_write_allow_bulk
    )
    try:
        write_type_preview_summary_artifact(
            type_preview_summary_path,
            type_preview_rows,
            summary,
            write_confirmed=type_preview_write_confirmed,
            bulk_write_allowed=type_preview_write_allow_bulk,
        )
        print(f"[TYPE-PREVIEW] {type_preview_summary_path} 저장 (human-readable)")
    except Exception as e:
        print(f"[TYPE-PREVIEW] summary 저장 실패 = {e} (cron 진행)")
    summary["archive_warnings"] = summary_archive_warn
    if summary_archive_warn:
        summary["code_change_suspected"] = True   # 아카이브가 조용히 반쪽이 되면 알림
    summary["github_run_id"] = run_id
    summary["github_run_url"] = f"https://github.com/yoohojong/naver-rank-checker/actions/runs/{run_id}"
    if post_write_audit_error:
        summary["post_write_audit_error"] = post_write_audit_error
    if circuit_breaker_tripped:
        summary["code_change_suspected"] = True  # cron 조기 종료 = 알림 trigger
    if prewrite_invariant_issues or post_write_blocking_issues:
        summary["code_change_suspected"] = True  # D-032: 불가능 조합은 사장님 확인 필요
    if type_preview_write_blocked_by_bulk_guard or type_preview_write_audit_issues:
        summary["code_change_suspected"] = True

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
    # GitHub Actions exit code:
    #   0 = 정상.
    #   2 = '코드/사이트 변경 의심'(bulk-guard hold·K분포 이상 등). Actions 빨강 → 사장님 알림.
    #       단 이건 '결정적'(재실행해도 같은 결과)이므로 self-heal 이 재시도하면 안 됨(2.5~4h 헛돌이 방지).
    #       → rank-check.yml self-heal 이 rc=2 는 재시도 생략. 실제 크래시(rc=1 등)만 1회 재시도.
    #   1(또는 그 외 비0) = 예기치 못한 크래시 → self-heal 1회 재시도 대상.
    # ⚠️ 순위 데이터(K/L/M/O)는 이 체크 '전에' 이미 시트에 기록됨 → rc=2 여도 순위 갱신은 정상.
    if s.get("code_change_suspected"):
        sys.exit(2)
    sys.exit(0)
