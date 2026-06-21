"""integration_runner: 카페외부 원고 '재료' 자동 수집 오케스트레이터 (C3).

사장님 시트의 제품 탭(이름에 '카외' 포함)을 행별로 읽어 '키워드 분류'(단계)에 따라
수집 코어를 호출하고, 결과를 **수집 전용 스테이징 탭**에 쌓는다. 직원 수작업 0.

단계 라우팅:
  - '3 증상'         → 지식iN Open API(fetch_jisikin)  → '수집결과_지식인' 탭
  - '4 대안'/'5 브랜드' → Apify 스마트스토어 리뷰(fetch_reviews) → '수집결과_리뷰' 탭

스테이징 스키마(고정): [키워드 | 단계 | 제목 | 본문 | 수집일 | source_url | 적재완료]
  - 지식인: 제목=질문 제목, 본문=질문 요약(description)
  - 리뷰  : 제목=별점,      본문=리뷰 내용

설계 원칙(비개발 사장님 운영 → 안전 우선):
  ① 증분(표시기반) — 메인 시트 각 카외 행의 '수집상태' 칸이 채워진(이미 수집된) 행은 스킵,
                    빈 행만 수집. 수집 직후 그 행의 '수집상태' 칸에 '✅ YYYY-MM-DD 수집(N건)'
                    을 서비스계정으로 write-back. 날짜가 바뀌어도 재수집 안 함(과거 날짜기반의 약점 해소).
                    재개: 중간에 끊겨도 미표시(빈) 칸부터 자연 이어감. 사장님 가시화도 겸함.
  ② 격리       — 키워드 한 건이 실패해도 try/except 로 격리, 전체는 계속 진행.
  ③ 요약 반환  — 수집/실패/스킵 카운트를 담은 summary dict 반환(C9 모니터링·텔레그램용).
  ④ 안전 스킵  — 키워드/단계 미지정 행, 라우팅 대상 외 단계는 조용히 건너뜀(실패 아님).
  ⑤ 키 없으면 비활성 — 네이버 키 없으면 지식인 채널, APIFY 토큰 없으면 리뷰 채널 통째 스킵.
  ⑥ 주입식     — SheetsClient·fetch_* 전부 인자로 받아 테스트에서 mock 가능(실 API 호출 0).
  ⑦ 일괄 안전(500~1000개) — 표시 write-back 을 소규모 청크마다 flush 하여 중간 실패 시
                    재실행이 미표시분부터 이어가게. 스테이징 append 는 기존처럼 버퍼링 후 일괄.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

# 스테이징 탭 이름(수집 전용 — 사장님 입력 탭 '카외' 와 분리).
STAGING_TAB_JISIKIN = "수집결과_지식인"
STAGING_TAB_REVIEW = "수집결과_리뷰"

# 고정 스키마 — 지식인/리뷰 공통. (리뷰는 제목=별점, 본문=리뷰내용)
STAGING_HEADER = ["키워드", "단계", "제목", "본문", "수집일", "source_url", "적재완료"]

# 단계 라우팅 — 단계 문자열의 맨 앞 숫자로 판별(사장님이 "3 증상", "3증상" 등으로 적어도 견고).
STAGE_JISIKIN = {"3"}        # 증상
STAGE_REVIEW = {"4", "5"}    # 대안 / 브랜드

# 카외 제품 탭에서 읽는 컬럼 이름.
COL_KEYWORD = "키워드"
# 단계 칸 = 시트 실제 헤더 '키워드 분류'(bogwanham addClassifyColumn 이 만드는 이름).
# ⚠️ 과거 '키워드 분류(단계)'로 잘못 잡아 태깅해도 0건 수집되던 버그 수정(2026-06-21).
COL_STAGE = "키워드 분류"
# 헤더 변형(괄호/별칭)에도 견고하도록 후보 순차 탐색 + '분류' 포함 키 폴백.
_STAGE_HEADER_CANDIDATES = ("키워드 분류", "키워드 분류(단계)", "단계")
COL_LINK = "링크"  # 리뷰 단계용 상품 URL(있으면). 없으면 리뷰 스킵.
# 증분 표시 칸 = 메인 시트 '수집상태' 컬럼(bogwanham addCollectStatusColumn 이 만듦).
# 값이 채워진 행 = 이미 수집됨 → 스킵. 수집/갱신 직후 이 칸에 시점 문구를 서비스계정으로 write-back.
# 첫 수집·갱신 둘 다 이 한 칸에 기록한다(2026-06-21 병합 — 실제 자료는 보관함에 날짜별 보존).
COL_COLLECT_STATUS = "수집상태"
# ③ 갱신 요청 칸 = 메인 시트 '갱신' 컬럼('수집상태' 바로 오른쪽). 사장님이 아무 표시를 하면
# '수집상태'가 채워져 있어도 그 행을 재수집한다. 재수집 끝나면 이 칸을 비운다(clear_refresh_flags).
# ⚠️ 갱신은 기존 자료를 덮지 않고 새 자료를 '추가'만 한다(append-only — 동일 link 중복만 제외).
COL_REFRESH = "갱신"

# 표시 write-back 청크 크기 — 이 키워드 수마다 '수집상태' 칸 flush(재개 안전 ↔ API burst 균형).
COLLECT_STATUS_FLUSH_EVERY = 20


def _stage_value(row: dict) -> str:
    """행에서 단계 값을 견고하게 읽는다(헤더 이름 변형 방어)."""
    for k in _STAGE_HEADER_CANDIDATES:
        v = (row.get(k) or "").strip()
        if v:
            return v
    for k, v in row.items():
        if "분류" in str(k):
            s = str(v or "").strip()
            if s:
                return s
    return ""


def _stage_digit(stage: str) -> str:
    """단계 문자열의 맨 앞 숫자 1글자 반환('3 증상'→'3'). 숫자 없으면 ''."""
    s = (stage or "").strip()
    for ch in s:
        if ch.isdigit():
            return ch
    return ""


def _today_kst() -> str:
    """오늘 날짜(KST) 'YYYY-MM-DD'. 중복방지 키의 '수집일'."""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


def _already_collected(row: dict) -> bool:
    """메인 시트 행의 '수집상태' 칸이 채워졌으면(이미 수집됨) True.

    증분/재개의 핵심 판정 — 칸이 비어 있는 행만 수집 대상.
    """
    return bool((row.get(COL_COLLECT_STATUS) or "").strip())


def _refresh_requested(row: dict) -> bool:
    """③ 메인 시트 행의 '갱신' 칸에 사장님 표시가 있으면 True.

    '수집상태'가 채워져 있어도 갱신 표시가 있으면 그 행은 재수집 대상.
    """
    return bool((row.get(COL_REFRESH) or "").strip())


def _should_collect(row: dict) -> bool:
    """수집 대상 판정: '수집상태' 비어있음 OR '갱신' 칸 채워짐(③).

    - 신규(수집상태 빈칸) → 수집(기존 증분 동작 유지).
    - 갱신 표시 → '수집상태'가 채워져 있어도 재수집(append-only 추가).
    """
    return (not _already_collected(row)) or _refresh_requested(row)


def _format_collect_status(day: str, n: int) -> str:
    """'수집상태' 칸에 기록할 첫 수집 문구 — '✅ YYYY-MM-DD 수집(N건)'."""
    return f"✅ {day} 수집({n}건)"


def _format_refresh_status(day: str, n: int) -> str:
    """③ 갱신 재수집 후 '수집상태' 칸에 덮어쓸 문구 — '✅ M/D 갱신(+N건)'.

    신규 수집('✅ YYYY-MM-DD 수집(N건)')과 구분해 사장님이 '추가됐다'를 한눈에 알게 한다.
    첫 수집·갱신 모두 같은 '수집상태' 칸에 기록(2026-06-21 병합 — 실제 자료는 보관함에 보존).
    'YYYY-MM-DD' → 'M/D'(앞 0 제거). 파싱 실패 시 원본 날짜 그대로 사용(견고).
    """
    md = day
    try:
        dt = datetime.strptime(day, "%Y-%m-%d")
        md = f"{dt.month}/{dt.day}"
    except (ValueError, TypeError):
        pass
    return f"✅ {md} 갱신(+{n}건)"


def _flush_collect_status(client, tab_name: str, pending: list) -> None:
    """버퍼된 (행, 표시문구)들을 '수집상태' 칸에 write-back — 첫 수집·갱신 공용.

    첫 수집='✅ 날짜 수집(N건)', 갱신='✅ M/D 갱신(+N건)' 둘 다 이 한 칸에 기록(갱신은 시점 덮음).
    pending: [(row_int, status_str), ...]. write 실패는 로그만 — 수집/적재는 이미 끝났고
    미표시 행은 다음 실행에서 자연 재시도(재개)되므로 전체를 멈추지 않는다.
    """
    if not pending:
        return
    from src.sheets import HEADER_COLLECT_STATUS, RowUpdate
    updates = [RowUpdate(row=r, columns={HEADER_COLLECT_STATUS: s}) for r, s in pending]
    try:
        client.write_collect_status(tab_name, updates)
    except Exception as e:  # noqa: BLE001 — 표시 실패해도 수집은 유효(다음 실행이 재개).
        print(f"[표시실패] 탭 '{tab_name}' '수집상태' write-back 중 오류: "
              f"{type(e).__name__}: {e} — 다음 실행에서 재개됨")


def _flush_refresh_clear(client, tab_name: str, pending_refresh_rows: list) -> None:
    """③ 재수집(갱신)이 끝난 행들의 '갱신' 칸을 비운다.

    '수집상태' 표시를 새로 찍은 뒤(=재수집 완료 확정) 호출 → 그 행 '갱신' 표시만 clear.
    clear 실패는 로그만 — 다음 실행에서 그 행이 또 재수집될 뿐이라(append-only) 데이터 손실은 없다.
    """
    if not pending_refresh_rows:
        return
    try:
        client.clear_refresh_flags(tab_name, pending_refresh_rows)
    except Exception as e:  # noqa: BLE001 — clear 실패해도 데이터 안전(다음 실행이 또 갱신할 뿐).
        print(f"[갱신칸정리실패] 탭 '{tab_name}' '갱신' 칸 clear 중 오류: "
              f"{type(e).__name__}: {e} — 다음 실행에서 재시도됨")


def _existing_links_for_keyword(client, staging_tab: str, keyword: str, cache: dict) -> set:
    """④ 갱신 시 이미 스테이징에 적재된 그 키워드의 link 집합을 읽어 캐시한다(중복 추가 방지).

    - staging_tab 전체를 1회만 read 해 {키워드: {link, ...}} 로 캐시(키워드마다 재read 금지).
    - 빈 link 는 집합에 넣지 않는다 → 빈 link 끼리는 중복으로 보지 않고 모두 보존(④ 규칙).
    - read 실패/탭 없음 = 빈 집합(보수적: 중복 못 거르면 다 추가, 데이터 손실보다 중복이 안전).
    캐시 키 = staging_tab(탭 단위 1회 read). 같은 run 안에서 새 append 분은 캐시에 반영 안 되나,
    같은 키워드가 한 run 에 갱신 1회뿐이라 문제 없음(키워드는 시트 1행 = 1회 처리).
    """
    if staging_tab not in cache:
        by_keyword: dict[str, set] = {}
        try:
            records = client.read_tab_records(staging_tab)
        except Exception as e:  # noqa: BLE001 — read 실패 = 빈 캐시(중복 못 걸러도 append 는 안전).
            print(f"[갱신중복확인실패] 탭 '{staging_tab}' 기존 link read 오류: "
                  f"{type(e).__name__}: {e} — 중복확인 없이 진행")
            records = []
        for rec in records or []:
            kw = str(rec.get("키워드", "") or "").strip()
            lnk = str(rec.get("source_url", "") or "").strip()
            if kw and lnk:
                by_keyword.setdefault(kw, set()).add(lnk)
        cache[staging_tab] = by_keyword
    return cache[staging_tab].get(keyword, set())


def _flush_chunk(client, tab_name: str, chunk_jisikin: list, chunk_review: list,
                 pending_collect: list, pending_refresh_rows: list, summary: dict) -> None:
    """한 청크의 스테이징 행을 append → '수집상태' write-back → '갱신' clear(이 순서 = 원자성).

    - 적재 성공 ⟹ 첫 수집·갱신 행 모두 pending_collect 를 '수집상태' 칸에 표시(표시 찍힘 ⟹ 적재
                  완료 불변식, 재개 안전) + 그 청크 갱신 행들의 '갱신' 칸 clear(③).
                  첫 수집·갱신을 한 칸에 병합(2026-06-21) — 갱신은 시점 문구로 같은 칸을 덮는다.
    - 적재 실패 ⟹ 표시도 갱신칸 clear 도 안 함(다음 실행이 재개) + 그 청크 수집분 failed 환산.
    호출 측이 버퍼(리스트) 객체를 매 청크마다 새로 만들어 넘기므로 여기서는 비우지 않는다
    (MagicMock 이 append 인자를 참조로 보관 → 호출 후 clear 시 검증값이 사라지는 함정 회피).
    """
    try:
        if chunk_jisikin:
            client.append_staging_rows(STAGING_TAB_JISIKIN, STAGING_HEADER, chunk_jisikin)
        if chunk_review:
            client.append_staging_rows(STAGING_TAB_REVIEW, STAGING_HEADER, chunk_review)
    except Exception as e:  # noqa: BLE001 — append 실패 = 이 청크 수집분 failed 환산 + 표시 안 함.
        n = len(chunk_jisikin) + len(chunk_review)
        summary["failed"] += n
        summary["collected"] = max(0, summary["collected"] - n)
        print(f"[적재실패] 탭 '{tab_name}' 스테이징 append 오류: {type(e).__name__}: {e}")
        return
    # 적재 성공분만 write-back: 첫 수집·갱신 모두 '수집상태' 칸에 표시(갱신은 시점 문구로 덮음),
    # 그 뒤 갱신 행 '갱신' 칸 clear(완료 확정 후).
    _flush_collect_status(client, tab_name, pending_collect)
    _flush_refresh_clear(client, tab_name, pending_refresh_rows)


def run_collection(
    client,
    *,
    fetch_jisikin,
    fetch_reviews,
    enrich_jisikin=None,
    naver_client_id: str,
    naver_client_secret: str,
    apify_token: str,
    apify_actor_id: str,
    apify_input_field: str = "startUrls",
    apify_extra_input: dict | None = None,
    today: str | None = None,
    tab_filter=None,
) -> dict:
    """카외 탭 전수 수집 → 스테이징 적재. summary dict 반환.

    Args:
        client: SheetsClient (load_all_data_tabs / append_staging_rows / write_collect_status).
        fetch_jisikin: fetch_jisikin(keyword, *, client_id, client_secret) → [{title,link,description}].
        fetch_reviews: fetch_low_star_reviews(urls, *, apify_token, actor_id) → [{star,content,source,date}].
        naver_*: 네이버 Open API 키(없으면 지식인 채널 스킵).
        apify_*: Apify 토큰/액터(없으면 리뷰 채널 스킵).
        today: 'YYYY-MM-DD' (테스트 주입용). None 이면 오늘 KST.
        tab_filter: 탭 이름 → bool. None 이면 이름에 '카외' 포함 탭만.

    Returns:
        {"collected": int, "failed": int, "skipped": int, "tabs": int}
        - collected: 스테이징에 적재한 행 수.
        - failed:    fetch/append 예외로 처리 못 한 키워드 행 수.
        - skipped:   이미수집(수집상태 채워짐)·키/단계 미지정·라우팅 외·키 미설정·URL 없음으로 건너뛴 행 수.

    증분/재개(①):
        탭별로 처리하되, 한 탭 안에서 COLLECT_STATUS_FLUSH_EVERY 키워드마다 (a)그때까지의
        스테이징 행을 append 하고 (b)그 행들의 '수집상태' 칸을 write-back 한다. 순서 보장 =
        '수집상태' 표시가 찍힌 행 ⟹ 그 행 스테이징 적재 완료. 중간에 끊겨도 미표시 행만 다음
        실행에서 자연 재개된다. 표시 칸이 이미 채워진 행은 애초에 스킵(날짜 무관).
    """
    day = today or _today_kst()
    if tab_filter is None:
        tab_filter = lambda name: "카외" in name  # noqa: E731

    naver_on = bool(naver_client_id and naver_client_secret)
    apify_on = bool(apify_token)

    summary = {"collected": 0, "failed": 0, "skipped": 0, "tabs": 0}

    # ④ 갱신 시 기존 스테이징 link 중복 제외용 캐시(스테이징 탭당 1회 read). run 전체에서 공유.
    existing_link_cache: dict[str, dict] = {}

    data = client.load_all_data_tabs(tab_filter=tab_filter)
    summary["tabs"] = len(data)

    for tab_name, rows in data.items():
        # 탭별 청크 버퍼 — 채널별 스테이징 행 + 그 청크에서 표시할 (행, 문구).
        # 청크 경계에서 staging append 먼저 → status write-back 순으로 flush(원자성 보장).
        # flush 시 버퍼를 비우지 않고 '새 리스트로 교체'한다(append 인자 참조 보존).
        chunk_jisikin: list[list] = []
        chunk_review: list[list] = []
        pending_collect: list[tuple[int, str]] = []  # 첫 수집·갱신 행 모두 → '수집상태' 칸(병합).
        pending_refresh_rows: list[int] = []  # ③ 이 청크에서 재수집(갱신)한 행들 — flush 후 '갱신' 칸 clear.
        processed_in_chunk = 0

        for row in rows or []:
            keyword = (row.get(COL_KEYWORD) or "").strip()
            stage_raw = _stage_value(row)
            digit = _stage_digit(stage_raw)
            row_num = row.get("_row")
            # ③ 갱신 표시가 있으면 '수집상태'가 채워져 있어도 재수집(append-only 추가).
            refresh_flag_set = _refresh_requested(row)
            # 표시 라우팅: '수집상태'가 이미 채워진 행에서 갱신 표시 → 갱신(시점 문구로 같은 칸 덮음).
            #   엣지(수집상태 빈칸 + 갱신 표시 동시) = 첫 수집으로 처리(수집상태에 '수집' 문구).
            #   단, 사장님이 찍은 '갱신' 칸은 두 경우 모두 비운다(refresh_flag_set 기준 clear).
            is_refresh = refresh_flag_set and _already_collected(row)

            # ① 수집 대상 판정: '수집상태' 비어있음 OR '갱신' 칸 채워짐(③).
            #    둘 다 아니면(이미수집 + 갱신요청 없음) → 스킵(증분/재개 핵심).
            if not _should_collect(row):
                summary["skipped"] += 1
                continue

            # ④ 키워드 없음 / 단계 미지정 / 라우팅 대상 외 단계 → 조용히 스킵.
            if not keyword or not digit:
                summary["skipped"] += 1
                continue

            try:
                if digit in STAGE_JISIKIN:
                    if not naver_on:
                        summary["skipped"] += 1
                        continue
                    # 정확도순 100건 + 최신순 100건 수집 후 link 기준 중복제거(sim 우선).
                    # ★ 자동 쓰레기/품질 필터 없음 — 사장님 결정(2026-06-21): "광고 댓글 하나 섞였다고
                    #   글을 통째로 버리면 그 안 가치있는 진짜 내용까지 날아간다. 전부 추출하고 선별은 사람이 한다."
                    items_sim = fetch_jisikin(
                        keyword,
                        client_id=naver_client_id,
                        client_secret=naver_client_secret,
                        display=100,
                        sort="sim",
                    )
                    items_date = fetch_jisikin(
                        keyword,
                        client_id=naver_client_id,
                        client_secret=naver_client_secret,
                        display=100,
                        sort="date",
                    )
                    # link 기준 중복제거: sim 순서 유지, date 에서 신규분만 추가.
                    # (link 가 빈값이면 중복으로 보지 않고 모두 보존 — 빈 link끼리 합쳐지지 않게.)
                    seen_links: set[str] = set()
                    # ④ 갱신 행이면 이미 스테이징에 적재된 그 키워드 link 를 시작 집합으로(중복 추가 방지).
                    #    빈 link 는 제외 집합에 없으므로 빈 link끼리는 모두 보존(④ 빈 link 규칙).
                    if is_refresh:
                        seen_links |= _existing_links_for_keyword(
                            client, STAGING_TAB_JISIKIN, keyword, existing_link_cache)
                    merged: list[dict] = []
                    for it in (items_sim or []) + (items_date or []):
                        lnk = it.get("link", "")
                        if lnk and lnk in seen_links:
                            continue
                        if lnk:
                            seen_links.add(lnk)
                        merged.append(it)
                    # 본문 보강: detail 페이지에서 '질문 본문 + 답변 본문'을 긁어 body_full 채움.
                    #   description(검색 스니펫)은 짧은 요약이라 실제 질문·답변이 없다 → enrich.
                    #   주입식(⑥) — enrich_jisikin 미주입(None)이면 보강 생략(본문=description 폴백).
                    #   detail 실패/빈 값이면 enrich 가 body_full=description 로 폴백(회귀 안전).
                    #   enrich 자체가 통째로 실패해도(예외) description 폴백으로 격리(전체 비차단).
                    if enrich_jisikin is not None and merged:
                        try:
                            enrich_jisikin(merged)
                        except Exception as e:  # noqa: BLE001 — enrich 실패 시 description 폴백.
                            print(f"[본문보강실패] 키워드 '{keyword}': "
                                  f"{type(e).__name__}: {e} — description 으로 폴백")
                    new_rows = [
                        [
                            keyword, stage_raw,
                            it.get("title", ""),
                            it.get("body_full") or it.get("description", ""),
                            day, it.get("link", ""), "",
                        ]
                        for it in merged
                    ]
                    chunk_jisikin.extend(new_rows)
                    summary["collected"] += len(new_rows)
                    if row_num:
                        # 첫 수집·갱신 모두 '수집상태' 칸에 기록(병합). 갱신은 시점 문구로 같은 칸 덮음.
                        status = (_format_refresh_status(day, len(new_rows)) if is_refresh
                                  else _format_collect_status(day, len(new_rows)))
                        pending_collect.append((row_num, status))
                        if refresh_flag_set:
                            pending_refresh_rows.append(row_num)  # 사장님 '갱신' 표시 clear.
                    processed_in_chunk += 1

                elif digit in STAGE_REVIEW:
                    if not apify_on:
                        summary["skipped"] += 1
                        continue
                    urls = [u for u in [(row.get(COL_LINK) or "").strip()] if u]
                    if not urls:
                        # ⑤ 상품 URL 없으면 리뷰 수집 무의미 → 스킵.
                        summary["skipped"] += 1
                        continue
                    reviews = fetch_reviews(
                        urls,
                        apify_token=apify_token,
                        actor_id=apify_actor_id,
                        input_field=apify_input_field,
                        extra_input=apify_extra_input,
                    )
                    review_list = list(reviews or [])
                    # ④ 갱신 행이면 이미 적재된 그 키워드 source_url 과 중복인 리뷰는 제외(신규분만 추가).
                    #    빈 source 는 중복으로 보지 않고 모두 보존(④ 빈 link 규칙).
                    if is_refresh:
                        existing = _existing_links_for_keyword(
                            client, STAGING_TAB_REVIEW, keyword, existing_link_cache)
                        if existing:
                            review_list = [
                                rv for rv in review_list
                                if not (str(rv.get("source", "") or "").strip() in existing
                                        and str(rv.get("source", "") or "").strip())
                            ]
                    new_rows = [
                        [
                            keyword, stage_raw,
                            str(rv.get("star", "")), rv.get("content", ""),
                            day, rv.get("source", ""), "",
                        ]
                        for rv in review_list
                    ]
                    chunk_review.extend(new_rows)
                    summary["collected"] += len(new_rows)
                    if row_num:
                        # 첫 수집·갱신 모두 '수집상태' 칸에 기록(병합). 갱신은 시점 문구로 같은 칸 덮음.
                        status = (_format_refresh_status(day, len(new_rows)) if is_refresh
                                  else _format_collect_status(day, len(new_rows)))
                        pending_collect.append((row_num, status))
                        if refresh_flag_set:
                            pending_refresh_rows.append(row_num)  # 사장님 '갱신' 표시 clear.
                    processed_in_chunk += 1

                else:
                    # 1/2 정보 등 라우팅 대상 외 단계 → 스킵.
                    summary["skipped"] += 1

            except Exception as e:  # noqa: BLE001 — ② 키워드 단위 격리(전체는 계속).
                summary["failed"] += 1
                print(f"[수집실패] 탭 '{tab_name}' 키워드 '{keyword}' (단계 {stage_raw}): "
                      f"{type(e).__name__}: {e}")

            # ⑦ 일괄 안전: 청크 크기 도달 시 즉시 flush(적재→표시→갱신칸정리) → 중간 실패해도 재개 가능.
            if processed_in_chunk >= COLLECT_STATUS_FLUSH_EVERY:
                _flush_chunk(client, tab_name, chunk_jisikin, chunk_review,
                             pending_collect, pending_refresh_rows, summary)
                chunk_jisikin, chunk_review = [], []
                pending_collect, pending_refresh_rows = [], []
                processed_in_chunk = 0

        # 탭 끝 — 남은 청크 flush.
        _flush_chunk(client, tab_name, chunk_jisikin, chunk_review,
                     pending_collect, pending_refresh_rows, summary)

    return summary


def format_summary(summary: dict) -> str:
    """사람이 읽는 한 줄 요약(stdout + 텔레그램용). 비개발 사장님용 한글."""
    return (
        "[카페외부 재료수집] "
        f"수집 {summary.get('collected', 0)}건 / "
        f"실패 {summary.get('failed', 0)}건 / "
        f"스킵 {summary.get('skipped', 0)}건 "
        f"(대상 탭 {summary.get('tabs', 0)}개)"
    )


def main() -> int:
    """GitHub Actions(cafe-material-collect.yml) 진입점.

    - 환경변수에서 키 로드 → 키 없으면 해당 채널 자동 스킵(안전).
    - SPREADSHEET_ID/SERVICE_ACCOUNT_JSON 없으면 즉시 종료(시트 자체 불가).
    - 끝에 요약을 stdout + (가능하면) 텔레그램 전송.
    - 항상 0 반환(워크플로 비차단 — 실패는 요약으로 통보).
    """
    from src.config import (
        APIFY_ACTOR_ID,
        APIFY_INCLUDE_REVIEWS,
        APIFY_INPUT_FIELD,
        APIFY_MAX_REVIEW_PAGES,
        APIFY_TOKEN,
        NAVER_OPENAPI_CLIENT_ID,
        NAVER_OPENAPI_CLIENT_SECRET,
        SERVICE_ACCOUNT_JSON,
        SPREADSHEET_ID,
    )

    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("❌ SPREADSHEET_ID 또는 SERVICE_ACCOUNT_JSON 환경변수 누락 — 종료.")
        return 0

    if not (NAVER_OPENAPI_CLIENT_ID and NAVER_OPENAPI_CLIENT_SECRET):
        print("[integration_runner] ⚠️ 네이버 Open API 키 미설정 — 지식인 수집 비활성.")
    if not APIFY_TOKEN:
        print("[integration_runner] ⚠️ APIFY_TOKEN 미설정 — 리뷰 수집 비활성.")

    # 무거운 의존성(gspread/curl_cffi)은 main 실행 시에만 import(테스트 import 가벼움 유지).
    from src.jisikin_collect import enrich_jisikin, fetch_jisikin
    from src.review_collect import fetch_low_star_reviews
    from src.sheets import SheetsClient

    client = SheetsClient(
        spreadsheet_id=SPREADSHEET_ID,
        service_account_json=SERVICE_ACCOUNT_JSON,
    )

    print("=== 카페외부 재료수집 사이클 시작 ===")
    apify_extra = {
        "includeReviews": APIFY_INCLUDE_REVIEWS,
        "maxReviewPages": APIFY_MAX_REVIEW_PAGES,
    }
    summary = run_collection(
        client,
        fetch_jisikin=fetch_jisikin,
        fetch_reviews=fetch_low_star_reviews,
        enrich_jisikin=enrich_jisikin,
        naver_client_id=NAVER_OPENAPI_CLIENT_ID,
        naver_client_secret=NAVER_OPENAPI_CLIENT_SECRET,
        apify_token=APIFY_TOKEN,
        apify_actor_id=APIFY_ACTOR_ID,
        apify_input_field=APIFY_INPUT_FIELD,
        apify_extra_input=apify_extra,
    )

    line = format_summary(summary)
    print(line)

    # C9: 요약 텔레그램 전송(비차단 — secret 없으면 [SKIP]).
    try:
        from src.notify import send_report
        send_report(line)
    except Exception as e:  # noqa: BLE001
        print(f"[TELEGRAM][WARN] 요약 전송 실패: {type(e).__name__}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
