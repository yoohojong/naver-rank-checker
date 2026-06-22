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

import hashlib
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


def _existing_keywords(client, tab_name: str) -> set:
    """스테이징 탭에 이미 적재된 '키워드' 집합 — 수집일 무관(이어받기용).

    리뷰 전수수집(약 506개)은 한 run(GHA 60분)에 다 못 한다. 그래서 이미 한 번이라도
    적재된 키워드는 (어느 날 적재됐든) 다시 안 한다 = '미수집분 이어받기'.
    매 run 이 아직 안 한 키워드만 예산만큼 처리 → 여러 번 돌리면 506개 전부 누적.
    읽기 실패는 빈 집합(최악: 한 번 더 수집 — 데이터 손실은 없음).
    """
    try:
        records = client.read_tab_records(tab_name)
    except Exception:  # noqa: BLE001 — 읽기 실패해도 수집은 계속.
        return set()
    kws = set()
    for rec in records or []:
        kw = (rec.get("키워드") or "").strip()
        if kw:
            kws.add(kw)
    return kws


def _keyword_in_shard(keyword: str, shard) -> bool:
    """병렬(matrix) 분할용 — 키워드가 이 shard 몫인지 판정(결정적·disjoint).

    shard = (index, total). md5(키워드) % total == index 인 키워드만 True.
    같은 키워드는 어느 run 에서든 항상 같은 shard 로 가므로(해시 결정적),
    여러 matrix job 이 서로 겹치지 않는 키워드 집합을 나눠 갖는다(중복수집 0).
    shard 가 None 이거나 total<=1 이면 분할 없음(전부 True = 기존 단일 run 동작).
    """
    if not shard:
        return True
    index, total = shard
    if total <= 1:
        return True
    h = int(hashlib.md5(keyword.encode("utf-8")).hexdigest(), 16)
    return (h % total) == index


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
    review_keyword_budget: int = 0,
    review_shard=None,
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
        review_keyword_budget: 한 run 에서 처리할 '새 리뷰 키워드' 수 상한(이어받기/전수수집용).
            0(기본)이면 무제한(기존 동작). >0 이면 이번 run 에서 그 수만큼 새 키워드를 처리하면
            나머지 미수집 4·5단계 행은 스킵(다음 run 이 이어받음). 키워드당 약 2분 × 예산이
            GHA 50~55분 안에 끝나도록 사장님이 환경변수(REVIEW_KEYWORD_BUDGET)로 조정.
            이미 수집결과_리뷰에 적재된 키워드는 (수집일 무관) 항상 건너뜀 = 미수집분만 이어받음.
        review_shard: 병렬(matrix) 분할용 (index, total) 또는 None. 설정 시 4·5단계 키워드를
            md5 해시로 total 등분하고 그중 index 몫만 이 run 이 처리한다(나머지는 다른 matrix job).
            None(기본)이면 분할 없음 = 단일 run 동작. 506개를 N개 job 으로 나눠 동시 수집할 때 사용.
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

    summary = {
        "collected": 0, "failed": 0, "skipped": 0, "tabs": 0,
        # 이어받기 진행도(리뷰 채널): 이번 run 처리 키워드 수 / 누적 완료 / 전체 4·5단계 / 잔여.
        "review_keywords_this_run": 0,
        "review_keywords_done": 0,
        "review_keywords_total": 0,
        "review_keywords_remaining": 0,
    }

    data = client.load_all_data_tabs(tab_filter=tab_filter)
    summary["tabs"] = len(data)

    # 중복방지 키 — 스테이징 탭별 1회만 읽음(행마다 재조회 회피).
    seen_jisikin = _existing_keys(client, STAGING_TAB_JISIKIN)
    seen_review = _existing_keys(client, STAGING_TAB_REVIEW)

    # 이어받기: 리뷰 탭에 이미 적재된 키워드(수집일 무관)는 이번 run 에서 건너뜀(미수집분만 처리).
    # done_review 는 _existing_keys(seen_review)와 같은 read 를 재사용해 키워드만 추린 집합.
    done_review_keywords = {kw for (kw, _day) in seen_review if kw}
    # 진행도 보고용: run 시작 시점의 누적 완료 키워드 집합(스냅샷). 처리 중 done_review_keywords 는 늘어남.
    done_at_start = set(done_review_keywords)
    # 전체 4·5단계 고유 키워드 집합(이번 시트 read 기준) — 진행도/잔여 추산용.
    review_keyword_universe: set[str] = set()
    # 한 run 당 새로 처리한 리뷰 키워드 수(예산 소진 추적). budget<=0 이면 무제한.
    review_processed = 0
    review_budget = max(0, int(review_keyword_budget or 0))

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
                    # 진행도 추산: 채널 on/off·예산과 무관하게 전체 4·5단계 고유 키워드를 센다.
                    review_keyword_universe.add(keyword)
                    if not reviews_on:
                        # ⑤ 리뷰 채널 비활성 → 스킵.
                        summary["skipped"] += 1
                        continue
                    # 브랜드 한정(실증용): 화이트리스트 설정 시 '키워드'에 그 브랜드명을 포함한 행만.
                    #   비면 한정 없음(기존 동작). 대표 소수 브랜드만 1회 실증 → GHA timeout 회피.
                    if brand_whitelist and not any(b in keyword for b in brand_whitelist):
                        summary["skipped"] += 1
                        continue
                    # 병렬(matrix) 분할: 이 키워드가 이 shard 몫이 아니면 다른 job 이 처리 → 스킵.
                    #   N개 matrix job 이 키워드를 해시로 disjoint 분할 → 전체를 한 run 시간에 동시 수집.
                    if not _keyword_in_shard(keyword, review_shard):
                        summary["skipped"] += 1
                        continue
                    # 이어받기: 이 키워드가 리뷰 탭에 이미(어느 날이든) 적재됐으면 건너뜀(미수집분만).
                    if keyword in done_review_keywords:
                        summary["skipped"] += 1
                        continue
                    # 한 run 예산 소진(>0): 이번 run 새 키워드 수가 예산에 도달하면 나머지는 다음 run 으로.
                    if review_budget and review_processed >= review_budget:
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
                    # 이어받기 영속화: 저점리뷰 0건이어도 '시도함' 마커 1행을 남긴다.
                    #   목적 — 다음 run 의 _existing_keywords(시트 read)에 이 키워드가 잡혀 재시도 안 됨.
                    #   마커가 없으면 0건 키워드를 매 run 다시 긁느라 예산이 새 키워드로 진행 못 함(정체).
                    #   마커 행 = [키워드 | 단계 | "0건" | "" | 수집일 | "" | ""]. collected 로 세지 않음(0건이므로).
                    if not new_rows:
                        buf_review.append([keyword, stage_raw, "0건", "", day, "", ""])
                    buf_review.extend(new_rows)
                    seen_review.add((keyword, day))
                    # 이어받기/예산: 이번 run 에 처리한 키워드로 표시(0건 나와도 '처리함' = 다음 run 재시도 방지).
                    #   ⚠️ 0건이어도 done 처리 → 같은 빈 키워드를 매 run 재시도하느라 예산 낭비하는 무한정체 방지.
                    #   (저점리뷰가 0건인 키워드는 그 run 에 '시도했고 없었다'로 보고 다음 키워드로 진행.)
                    done_review_keywords.add(keyword)
                    review_processed += 1
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

    # 이어받기 진행도(리뷰 채널) — 사장님 보고용. 전체 4·5단계 중 몇 개 끝났고 몇 개 남았는지.
    total_review = len(review_keyword_universe)
    # 이번 run 시작 시점에 '이미 완료'였던 것 중 실제 4·5단계 universe 에 속한 것만 카운트(노이즈 제거).
    done_before = len(done_at_start & review_keyword_universe)
    done_now = done_before + review_processed
    summary["review_keywords_this_run"] = review_processed
    summary["review_keywords_total"] = total_review
    summary["review_keywords_done"] = min(done_now, total_review) if total_review else done_now
    summary["review_keywords_remaining"] = max(0, total_review - summary["review_keywords_done"])

    return summary


def format_summary(summary: dict) -> str:
    """사람이 읽는 한 줄 요약(stdout + 텔레그램용). 비개발 사장님용 한글.

    리뷰 전수수집(이어받기) 진행도가 있으면 둘째 줄에 '키워드 N/총M개 완료, 남은 K개' 를 덧붙인다.
    """
    line = (
        "[카페외부 재료수집] "
        f"수집 {summary.get('collected', 0)}건 / "
        f"실패 {summary.get('failed', 0)}건 / "
        f"스킵 {summary.get('skipped', 0)}건 "
        f"(대상 탭 {summary.get('tabs', 0)}개)"
    )
    total = summary.get("review_keywords_total", 0)
    if total:
        this_run = summary.get("review_keywords_this_run", 0)
        done = summary.get("review_keywords_done", 0)
        remaining = summary.get("review_keywords_remaining", 0)
        line += (
            f"\n[저점리뷰 이어받기] 이번 run 키워드 {this_run}개 처리 / "
            f"누적 {done}/{total}개 완료 / 남은 {remaining}개"
        )
    return line


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

    # 이어받기 예산: 한 run 처리할 새 리뷰 키워드 수 상한(GHA 50~55분 안전). 0=무제한.
    #   실측(2026-06-22, 키워드당 100건 목표): 성공 ~26~63s, 0건 ~8~10s, 평균 ~27s.
    #   → 한 run(50분)에 ~60개 처리 가능. 단일 run 기본 22는 보수값. matrix 분할 시 0(무제한) 권장.
    try:
        review_keyword_budget = max(0, int(os.environ.get("REVIEW_KEYWORD_BUDGET", "22")))
    except ValueError:
        review_keyword_budget = 22

    # 병렬(matrix) 분할: REVIEW_SHARD="i/N" (예: "3/12") 면 키워드를 N등분해 i 몫만 처리.
    #   matrix 워크플로(cafe-review-lowstar-matrix.yml)가 job 마다 다른 i 를 주입 → 전체 동시 수집.
    #   미설정/형식오류면 None(분할 없음 = 단일 run). i 는 0..N-1.
    review_shard = None
    shard_env = os.environ.get("REVIEW_SHARD", "").strip()
    if shard_env and "/" in shard_env:
        try:
            _i, _n = (int(x) for x in shard_env.split("/", 1))
            if _n > 1 and 0 <= _i < _n:
                review_shard = (_i, _n)
                print(f"[integration_runner] 🧩 matrix 분할 — shard {_i+1}/{_n} (이 job 은 {_n}분의 1만 수집).")
        except ValueError:
            review_shard = None
    # 키워드당 저점리뷰 목표 건수(직전 실증은 총 20건으로 적었음 → 상향). 사장님이 REVIEW_MAX 로 조정.
    try:
        review_max = max(1, int(os.environ.get("REVIEW_MAX", "40")))
    except ValueError:
        review_max = 40
    if reviews_on:
        budget_txt = "무제한" if review_keyword_budget == 0 else f"{review_keyword_budget}개/run"
        print(f"[integration_runner] 🔁 저점리뷰 이어받기 — 새 키워드 예산 {budget_txt}, "
              f"키워드당 목표 {review_max}건.")

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
        review_max=review_max,
        review_brand_whitelist=REVIEW_BRAND_WHITELIST,
        review_keyword_budget=review_keyword_budget,
        review_shard=review_shard,
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
