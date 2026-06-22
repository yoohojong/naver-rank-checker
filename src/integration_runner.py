"""integration_runner: 카페외부 원고 '재료' 자동 수집 오케스트레이터 (C3).

사장님 시트의 제품 탭(이름에 '카외' 포함)을 행별로 읽어 '키워드 분류'(단계)에 따라
수집 코어를 호출하고, 결과를 **수집 전용 스테이징 탭**에 쌓는다. 직원 수작업 0.

단계 라우팅:
  - '3 증상'         → 지식iN Open API(fetch_jisikin)              → '수집결과_지식인' 탭
  - '4 대안'/'5 브랜드' → 네이버 저점리뷰(review_lowstar, Playwright) → '수집결과_리뷰' 탭

스테이징 스키마(고정): [키워드 | 단계 | 제목 | 본문 | 수집일 | source_url | 적재완료]
  - 지식인: 제목=질문 제목, 본문=질문 요약(description)
  - 리뷰  : 제목=별점,      본문=리뷰 내용

리뷰 경로(2026-06-22 교체): 과거 Apify(review_collect) 경로는 리뷰 본문이 Pro 유료잠금이라 0건이었다.
  → src/review_lowstar.fetch_low_star_reviews(Playwright 실브라우저)로 교체.
  입력은 '상품 URL'이 아니라 **키워드**다(review_lowstar 가 통합검색으로 상품 URL을 자동 확보).
  단, 시트 '링크' 칸에 상품 URL이 직접 적혀 있으면 그 URL을 우선 사용(키워드 검색 생략).

설계 원칙(비개발 사장님 운영 → 안전 우선):
  ① 중복방지   — 같은 키워드 + 같은 수집일이 스테이징 탭에 이미 있으면 그 키워드는 스킵.
  ② 격리       — 키워드 한 건이 실패해도 try/except 로 격리, 전체는 계속 진행.
  ③ 요약 반환  — 수집/실패/스킵 카운트를 담은 summary dict 반환(C9 모니터링·텔레그램용).
  ④ 안전 스킵  — 키워드/단계 미지정 행, 라우팅 대상 외 단계는 조용히 건너뜀(실패 아님).
  ⑤ 채널 토글  — 네이버 키 없으면 지식인 채널 비활성. 리뷰 채널은 reviews_on 플래그로 토글
                 (Playwright 는 토큰 불필요 — 기본 활성, 끄려면 reviews_on=False).
  ⑥ 주입식     — SheetsClient·fetch_* 전부 인자로 받아 테스트에서 mock 가능(실 수집 호출 0).
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
# 리뷰 단계: 시트 '링크' 칸에 상품 URL이 있으면 그 URL을 우선 사용(키워드 검색 생략).
# 없으면 키워드로 통합검색 → 상품 URL 자동 확보(review_lowstar). 즉, '링크'는 선택사항이다.
COL_LINK = "링크"


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


def _existing_keys(client, tab_name: str) -> set:
    """스테이징 탭의 (키워드, 수집일) 집합 — 중복방지용. 읽기 실패는 빈 집합."""
    try:
        records = client.read_tab_records(tab_name)
    except Exception:  # noqa: BLE001 — 읽기 실패해도 수집은 계속(최악: 중복 1회).
        return set()
    keys = set()
    for rec in records or []:
        kw = (rec.get("키워드") or "").strip()
        day = (rec.get("수집일") or "").strip()
        if kw:
            keys.add((kw, day))
    return keys


def run_collection(
    client,
    *,
    fetch_jisikin,
    fetch_reviews,
    naver_client_id: str,
    naver_client_secret: str,
    reviews_on: bool = True,
    review_max: int = 20,
    review_max_score: int = 3,
    review_brand_whitelist=(),
    today: str | None = None,
    tab_filter=None,
) -> dict:
    """카외 탭 전수 수집 → 스테이징 적재. summary dict 반환.

    Args:
        client: SheetsClient (load_all_data_tabs / read_tab_records / append_staging_rows).
        fetch_jisikin: fetch_jisikin(keyword, *, client_id, client_secret) → [{title,link,description}].
        fetch_reviews: review_lowstar.fetch_low_star_reviews(keyword_or_url, max_reviews, max_score)
            → [{score, content, product_name, date, source_url}]. 키워드(또는 상품 URL)로 통합검색→저점리뷰.
        naver_*: 네이버 Open API 키(없으면 지식인 채널 스킵).
        reviews_on: 리뷰 채널 토글. 기본 True(Playwright 는 토큰 불필요). False 면 리뷰 단계 전부 스킵.
        review_max: 리뷰 단계 키워드당 수집 목표 건수(fetch_reviews max_reviews 로 전달).
        review_max_score: 이 별점 이하만 수집(기본 3 = 저점 1~3점).
        review_brand_whitelist: 저점리뷰(4·5단계) 대상 브랜드 한정(2026-06-22 실증용).
            브랜드명 문자열 시퀀스. 비면(기본) 한정 없음(종전대로 단계 4·5 전부 — 기존 동작 보존).
            설정되면 '키워드'에 화이트리스트 브랜드명 중 하나라도 포함된 4·5단계 행만 리뷰 수집,
            나머지 4·5단계 행은 스킵(전수 수집 시 GHA 60분 timeout 회피 — 대표 소수만 1회 실증).
        today: 'YYYY-MM-DD' (테스트 주입용). None 이면 오늘 KST.
        tab_filter: 탭 이름 → bool. None 이면 이름에 '카외' 포함 탭만.

    Returns:
        {"collected": int, "failed": int, "skipped": int, "tabs": int}
        - collected: 스테이징에 적재한 행 수.
        - failed:    fetch/append 예외로 처리 못 한 키워드 행 수.
        - skipped:   키/단계 미지정·라우팅 외·중복·채널 비활성으로 건너뛴 행 수.
    """
    day = today or _today_kst()
    if tab_filter is None:
        tab_filter = lambda name: "카외" in name  # noqa: E731

    naver_on = bool(naver_client_id and naver_client_secret)

    # 저점리뷰 브랜드 한정(실증용). 정규화: 공백 제거 + 빈 값 제외. 비면 한정 없음.
    brand_whitelist = tuple(b.strip() for b in (review_brand_whitelist or ()) if b and b.strip())

    summary = {"collected": 0, "failed": 0, "skipped": 0, "tabs": 0}

    data = client.load_all_data_tabs(tab_filter=tab_filter)
    summary["tabs"] = len(data)

    # 중복방지 키 — 스테이징 탭별 1회만 읽음(행마다 재조회 회피).
    seen_jisikin = _existing_keys(client, STAGING_TAB_JISIKIN)
    seen_review = _existing_keys(client, STAGING_TAB_REVIEW)

    # 적재 버퍼 — 채널별로 모았다가 마지막에 한 번에 append(시트 호출 최소화).
    buf_jisikin: list[list] = []
    buf_review: list[list] = []

    for tab_name, rows in data.items():
        for row in rows or []:
            keyword = (row.get(COL_KEYWORD) or "").strip()
            stage_raw = _stage_value(row)
            digit = _stage_digit(stage_raw)

            # ④ 키워드 없음 / 단계 미지정 / 라우팅 대상 외 단계 → 조용히 스킵.
            if not keyword or not digit:
                summary["skipped"] += 1
                continue

            try:
                if digit in STAGE_JISIKIN:
                    if not naver_on:
                        summary["skipped"] += 1
                        continue
                    if (keyword, day) in seen_jisikin:
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
                    merged: list[dict] = []
                    for it in (items_sim or []) + (items_date or []):
                        lnk = it.get("link", "")
                        if lnk and lnk in seen_links:
                            continue
                        if lnk:
                            seen_links.add(lnk)
                        merged.append(it)
                    new_rows = [
                        [
                            keyword, stage_raw,
                            it.get("title", ""), it.get("description", ""),
                            day, it.get("link", ""), "",
                        ]
                        for it in merged
                    ]
                    buf_jisikin.extend(new_rows)
                    seen_jisikin.add((keyword, day))  # 같은 run 내 중복도 차단
                    summary["collected"] += len(new_rows)

                elif digit in STAGE_REVIEW:
                    if not reviews_on:
                        # ⑤ 리뷰 채널 비활성 → 스킵.
                        summary["skipped"] += 1
                        continue
                    # 브랜드 한정(실증용): 화이트리스트 설정 시 '키워드'에 그 브랜드명을 포함한 행만.
                    #   비면 한정 없음(기존 동작). 대표 소수 브랜드만 1회 실증 → GHA timeout 회피.
                    if brand_whitelist and not any(b in keyword for b in brand_whitelist):
                        summary["skipped"] += 1
                        continue
                    if (keyword, day) in seen_review:
                        summary["skipped"] += 1
                        continue
                    # 입력 = 키워드(review_lowstar 가 통합검색으로 상품 URL 자동 확보).
                    # 단, 시트 '링크' 칸에 상품 URL이 직접 적혀 있으면 그 URL을 우선 사용.
                    link = (row.get(COL_LINK) or "").strip()
                    target = link or keyword
                    reviews = fetch_reviews(
                        target,
                        max_reviews=review_max,
                        max_score=review_max_score,
                    )
                    new_rows = [
                        [
                            keyword, stage_raw,
                            str(rv.get("score", "")), rv.get("content", ""),
                            day, rv.get("source_url", ""), "",
                        ]
                        for rv in (reviews or [])
                    ]
                    buf_review.extend(new_rows)
                    seen_review.add((keyword, day))
                    summary["collected"] += len(new_rows)

                else:
                    # 1/2 정보 등 라우팅 대상 외 단계 → 스킵.
                    summary["skipped"] += 1

            except Exception as e:  # noqa: BLE001 — ② 키워드 단위 격리(전체는 계속).
                summary["failed"] += 1
                print(f"[수집실패] 탭 '{tab_name}' 키워드 '{keyword}' (단계 {stage_raw}): "
                      f"{type(e).__name__}: {e}")

    # 적재 — 버퍼가 비어 있으면 append 호출 안 함(빈 호출 방지).
    try:
        if buf_jisikin:
            client.append_staging_rows(STAGING_TAB_JISIKIN, STAGING_HEADER, buf_jisikin)
        if buf_review:
            client.append_staging_rows(STAGING_TAB_REVIEW, STAGING_HEADER, buf_review)
    except Exception as e:  # noqa: BLE001 — append 실패 시 수집분은 failed 로 환산.
        n = len(buf_jisikin) + len(buf_review)
        summary["failed"] += n
        summary["collected"] = max(0, summary["collected"] - n)
        print(f"[적재실패] 스테이징 append 중 오류: {type(e).__name__}: {e}")

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
        NAVER_OPENAPI_CLIENT_ID,
        NAVER_OPENAPI_CLIENT_SECRET,
        REVIEW_BRAND_WHITELIST,
        SERVICE_ACCOUNT_JSON,
        SPREADSHEET_ID,
    )

    if not SPREADSHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("❌ SPREADSHEET_ID 또는 SERVICE_ACCOUNT_JSON 환경변수 누락 — 종료.")
        return 0

    if not (NAVER_OPENAPI_CLIENT_ID and NAVER_OPENAPI_CLIENT_SECRET):
        print("[integration_runner] ⚠️ 네이버 Open API 키 미설정 — 지식인 수집 비활성.")

    # 리뷰 채널 토글(기본 활성 — Playwright 는 토큰 불필요). 'false' 면 리뷰 단계 전부 스킵.
    reviews_on = os.environ.get("CAFE_REVIEWS_ON", "true").strip().lower() != "false"
    if not reviews_on:
        print("[integration_runner] ⚠️ CAFE_REVIEWS_ON=false — 저점리뷰 수집 비활성.")
    if REVIEW_BRAND_WHITELIST:
        print(f"[integration_runner] 🔖 저점리뷰 브랜드 한정 ON — {', '.join(REVIEW_BRAND_WHITELIST)} "
              f"({len(REVIEW_BRAND_WHITELIST)}개) 포함 키워드만 수집.")

    # 무거운 의존성(gspread/playwright)은 main 실행 시에만 import(테스트 import 가벼움 유지).
    from src.jisikin_collect import fetch_jisikin
    from src.review_lowstar import fetch_low_star_reviews
    from src.sheets import SheetsClient

    client = SheetsClient(
        spreadsheet_id=SPREADSHEET_ID,
        service_account_json=SERVICE_ACCOUNT_JSON,
    )

    print("=== 카페외부 재료수집 사이클 시작 ===")
    summary = run_collection(
        client,
        fetch_jisikin=fetch_jisikin,
        fetch_reviews=fetch_low_star_reviews,
        naver_client_id=NAVER_OPENAPI_CLIENT_ID,
        naver_client_secret=NAVER_OPENAPI_CLIENT_SECRET,
        reviews_on=reviews_on,
        review_brand_whitelist=REVIEW_BRAND_WHITELIST,
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
