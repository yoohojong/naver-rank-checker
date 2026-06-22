"""integration_runner 단위 테스트 (SheetsClient·fetch_* 전부 mock — 키/네트워크 없이 행동 검증).

C3: 카외 제품 탭 → 단계별 수집(지식인/리뷰) → 스테이징 탭 적재.
검증 포인트:
  ① 단계 라우팅(3 증상→지식인, 4 대안/5 브랜드→리뷰)
  ② 중복방지(같은 키워드+오늘 수집일 이미 있으면 스킵)
  ③ 키워드별 try/except 격리(한 건 실패해도 전체 계속)
  ④ summary 카운트(수집/실패/스킵)
  ⑤ 키 없음/단계 미지정 행 건너뜀
"""
from unittest.mock import MagicMock

import pytest

from src import integration_runner as ir
from src.integration_runner import (
    STAGING_HEADER,
    STAGING_TAB_JISIKIN,
    STAGING_TAB_REVIEW,
    run_collection,
)


def _client_with(tabs, existing=None):
    """SheetsClient mock — load_all_data_tabs / read_tab_records / append_staging_rows.

    tabs: {탭이름: [row dict, ...]}  (카외 제품 탭)
    existing: {스테이징탭: [기존 record dict, ...]}  (중복방지 검증용)
    """
    existing = existing or {}
    client = MagicMock()
    client.load_all_data_tabs.return_value = tabs
    client.read_tab_records.side_effect = lambda tab: existing.get(tab, [])
    # append_staging_rows 는 append 한 행 수 반환(실제 코어 시그니처와 동일).
    client.append_staging_rows.side_effect = lambda tab, header, rows: len(rows)
    return client


def test_routes_symptom_keyword_to_jisikin():
    client = _client_with(
        {"두피.카외": [{"키워드": "두피 가려움", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    # title·description 합산 15자 이상이어야 is_junk 필터를 통과한다.
    fetch_j = MagicMock(return_value=[
        {"title": "두피 가려움의 원인", "description": "두피 가려움 증상 본문 내용입니다", "link": "L"}
    ])
    fetch_r = MagicMock()

    summary = run_collection(
        client,
        fetch_jisikin=fetch_j,
        fetch_reviews=fetch_r,
        naver_client_id="id",
        naver_client_secret="sec",
        today="2026-06-20",
    )

    # 2회 호출(sim + date)
    assert fetch_j.call_count == 2
    assert fetch_j.call_args_list[0].args[0] == "두피 가려움"
    assert fetch_j.call_args_list[0].kwargs["sort"] == "sim"
    assert fetch_j.call_args_list[1].kwargs["sort"] == "date"
    fetch_r.assert_not_called()
    # 지식인 스테이징 탭에 append 됐는지
    call = client.append_staging_rows.call_args
    assert call.args[0] == STAGING_TAB_JISIKIN
    assert call.args[1] == STAGING_HEADER
    row = call.args[2][0]
    # 스키마: [키워드 | 단계 | 제목 | 본문 | 수집일 | source_url | 적재완료]
    assert row[0] == "두피 가려움"
    assert row[1] == "3 증상"
    assert row[2] == "두피 가려움의 원인"
    assert row[3] == "두피 가려움 증상 본문 내용입니다"
    assert row[4] == "2026-06-20"
    assert row[5] == "L"
    assert summary["collected"] == 1
    assert summary["failed"] == 0
    assert summary["skipped"] == 0


@pytest.mark.parametrize("stage", ["4 대안", "5 브랜드"])
def test_routes_alternative_and_brand_to_reviews(stage):
    """4 대안/5 브랜드 → review_lowstar 로 키워드 기반 저점리뷰 수집('링크' 칸 없어도 동작)."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁상품", "키워드 분류(단계)": stage, "_row": 2}]}
    )
    fetch_j = MagicMock()
    # review_lowstar.fetch_low_star_reviews 반환 스키마: score/content/product_name/date/source_url
    fetch_r = MagicMock(return_value=[
        {"score": 1, "content": "최악", "product_name": "P", "date": "d",
         "source_url": "https://brand.naver.com/x/products/1"}
    ])

    summary = run_collection(
        client,
        fetch_jisikin=fetch_j,
        fetch_reviews=fetch_r,
        naver_client_id="id",
        naver_client_secret="sec",
        today="2026-06-20",
    )

    fetch_j.assert_not_called()
    fetch_r.assert_called_once()
    # 입력 = 키워드(URL 아님). review_lowstar 가 통합검색으로 URL 자동 확보.
    assert fetch_r.call_args.args[0] == "경쟁상품"
    assert fetch_r.call_args.kwargs["max_score"] == 3
    call = client.append_staging_rows.call_args
    assert call.args[0] == STAGING_TAB_REVIEW
    row = call.args[2][0]
    # 리뷰: 제목=별점(score), 본문=리뷰내용(content), source_url=상품 URL
    assert row[0] == "경쟁상품"
    assert row[1] == stage
    assert row[2] == "1"          # 별점 문자열
    assert row[3] == "최악"
    assert row[5] == "https://brand.naver.com/x/products/1"
    assert summary["collected"] == 1


def test_review_uses_link_when_present():
    """시트 '링크' 칸에 상품 URL이 있으면 키워드 대신 그 URL을 review_lowstar 에 넘긴다."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁상품", "키워드 분류(단계)": "4 대안",
                     "링크": "https://brand.naver.com/x/products/9", "_row": 2}]}
    )
    fetch_r = MagicMock(return_value=[])

    run_collection(
        client, fetch_jisikin=MagicMock(), fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec", today="2026-06-20",
    )

    fetch_r.assert_called_once()
    assert fetch_r.call_args.args[0] == "https://brand.naver.com/x/products/9"


def test_skips_duplicate_keyword_same_day():
    client = _client_with(
        {"x.카외": [{"키워드": "두피 가려움", "키워드 분류(단계)": "3 증상", "_row": 2}]},
        existing={STAGING_TAB_JISIKIN: [
            {"키워드": "두피 가려움", "수집일": "2026-06-20", "_row": 2}
        ]},
    )
    fetch_j = MagicMock(return_value=[{"title": "t", "description": "d", "link": "L"}])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    fetch_j.assert_not_called()                 # 이미 오늘 수집됨 → API 호출 X
    client.append_staging_rows.assert_not_called()
    assert summary["skipped"] == 1
    assert summary["collected"] == 0


def test_does_not_skip_same_keyword_different_day():
    """어제 수집은 오늘 수집을 막지 않는다(수집일 키가 다름)."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피 가려움", "키워드 분류(단계)": "3 증상", "_row": 2}]},
        existing={STAGING_TAB_JISIKIN: [
            {"키워드": "두피 가려움", "수집일": "2026-06-19", "_row": 2}
        ]},
    )
    fetch_j = MagicMock(return_value=[
        {"title": "두피 가려움 원인과 해결책", "description": "두피 가려움 증상 설명입니다", "link": "L"}
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    assert fetch_j.call_count == 2  # sim + date 2회 호출
    assert summary["collected"] == 1
    assert summary["skipped"] == 0


def test_failure_in_one_keyword_isolated():
    """한 키워드 fetch 실패해도 다음 키워드는 계속 처리된다."""
    client = _client_with(
        {"x.카외": [
            {"키워드": "터지는키워드", "키워드 분류(단계)": "3 증상", "_row": 2},
            {"키워드": "정상키워드", "키워드 분류(단계)": "3 증상", "_row": 3},
        ]}
    )

    def _fetch(keyword, **kwargs):
        if keyword == "터지는키워드":
            raise RuntimeError("지식iN Open API 오류 500")
        return [{"title": "정상키워드 관련 질문 제목", "description": "정상키워드 관련 설명 내용입니다", "link": "L"}]

    fetch_j = MagicMock(side_effect=_fetch)

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    # 터지는키워드: sim 호출 1회(예외) → date 호출 안 함(try/except 전체 감쌈)
    # 정상키워드: sim 1회 + date 1회 = 2회 → 총 3회
    assert fetch_j.call_count == 3
    assert summary["failed"] == 1
    assert summary["collected"] == 1


def test_skips_rows_without_keyword_or_stage():
    client = _client_with(
        {"x.카외": [
            {"키워드": "", "키워드 분류(단계)": "3 증상", "_row": 2},        # 키워드 없음
            {"키워드": "키워드만", "키워드 분류(단계)": "", "_row": 3},       # 단계 없음
            {"키워드": "기타단계", "키워드 분류(단계)": "1 정보", "_row": 4},  # 라우팅 대상 외 단계
        ]}
    )
    fetch_j = MagicMock()
    fetch_r = MagicMock()

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    fetch_j.assert_not_called()
    fetch_r.assert_not_called()
    assert summary["collected"] == 0
    # 키/단계 미지정·라우팅 대상 외 = 조용히 건너뜀(실패 아님)
    assert summary["failed"] == 0


def test_stage_header_variants_resolve():
    """시트 실제 헤더 '키워드 분류'(괄호 없음)와 변형 모두 단계로 인식 — 헤더 불일치 버그 회귀 방지."""
    for header in ("키워드 분류", "키워드 분류(단계)", "단계"):
        client = _client_with(
            {"x.카외": [{"키워드": "두피 가려움", header: "3 증상", "_row": 2}]}
        )
        # is_junk 필터 통과를 위해 title+description 합산 15자 이상.
        fetch_j = MagicMock(
            return_value=[{"title": "두피 가려움 관련 질문", "link": "l", "description": "두피 가려움 증상 설명"}]
        )
        summary = run_collection(
            client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
            naver_client_id="id", naver_client_secret="sec",
            today="2026-06-20",
        )
        assert fetch_j.called, f"헤더 '{header}' 에서 단계 인식 실패"
        assert summary["collected"] == 1


def test_jisikin_skipped_when_naver_key_missing():
    """네이버 키 없으면 지식인 채널 통째로 스킵(에러 아님)."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock()

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="", naver_client_secret="",     # 키 없음
        today="2026-06-20",
    )

    fetch_j.assert_not_called()
    assert summary["collected"] == 0
    assert summary["skipped"] == 1


def test_reviews_skipped_when_channel_off():
    """reviews_on=False 면 리뷰 채널 통째로 스킵(에러 아님). Playwright 는 토큰 불필요."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁", "키워드 분류(단계)": "4 대안", "_row": 2}]}
    )
    fetch_r = MagicMock()

    summary = run_collection(
        client, fetch_jisikin=MagicMock(), fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec",
        reviews_on=False,
        today="2026-06-20",
    )

    fetch_r.assert_not_called()
    assert summary["skipped"] == 1


def test_review_row_without_link_still_collects_by_keyword():
    """리뷰 단계에 '링크' 칸이 없어도 스킵하지 않는다 — 키워드로 통합검색해 수집(URL 자동 확보)."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁", "키워드 분류(단계)": "5 브랜드", "링크": "", "_row": 2}]}
    )
    fetch_r = MagicMock(return_value=[
        {"score": 2, "content": "별로", "product_name": "P", "date": "d",
         "source_url": "https://brand.naver.com/x/products/1"}
    ])

    summary = run_collection(
        client, fetch_jisikin=MagicMock(), fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    # '링크' 빈칸 → 키워드로 호출(URL 강제 요구 없음)
    fetch_r.assert_called_once()
    assert fetch_r.call_args.args[0] == "경쟁"
    assert summary["collected"] == 1
    assert summary["skipped"] == 0


def test_empty_fetch_result_counts_as_zero_collected_not_failed():
    """API 는 호출했지만 결과 0건 = 실패 아님(collected 0, 빈 append 호출 안 함)."""
    client = _client_with(
        {"x.카외": [{"키워드": "희귀키워드", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock(return_value=[])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    assert fetch_j.call_count == 2  # sim + date 2회 호출
    client.append_staging_rows.assert_not_called()
    assert summary["collected"] == 0
    assert summary["failed"] == 0


def test_format_summary_is_human_readable_korean():
    text = ir.format_summary({"collected": 5, "failed": 2, "skipped": 3, "tabs": 1})
    assert "수집" in text and "5" in text
    assert "실패" in text and "2" in text
    assert "스킵" in text and "3" in text


def test_multiple_jisikin_items_become_multiple_rows():
    client = _client_with(
        {"x.카외": [{"키워드": "두피", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    # is_junk 필터 통과를 위해 title+description 합산 15자 이상.
    fetch_j = MagicMock(return_value=[
        {"title": "두피 가려움 원인 질문", "description": "두피가 간지럽고 각질이 납니다", "link": "L1"},
        {"title": "두피 트러블 해결 방법", "description": "두피에 뭔가 생겼는데 어떻게 하죠", "link": "L2"},
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    rows = client.append_staging_rows.call_args.args[2]
    assert len(rows) == 2
    # collected = 적재된 키워드 단위(1) 가 아니라 행 수(2) 로 카운트
    assert summary["collected"] == 2


# ── 신규: 2회 호출 / link 중복제거 / filtered 카운트 ──────────────────────


def test_jisikin_fetched_twice_sim_and_date():
    """단계3 키워드마다 fetch_jisikin을 sim·date 각 1회씩 총 2회 호출한다."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피 탈모", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock(return_value=[])

    run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    assert fetch_j.call_count == 2
    calls = fetch_j.call_args_list
    assert calls[0].kwargs["sort"] == "sim"
    assert calls[0].kwargs["display"] == 100
    assert calls[1].kwargs["sort"] == "date"
    assert calls[1].kwargs["display"] == 100


def test_jisikin_link_dedup_sim_priority():
    """sim·date 결과에 같은 link가 있으면 sim 순서 유지, date 중복은 제거한다."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피 탈모", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    # sim: L1, L2 / date: L2(중복), L3(신규)
    sim_items = [
        {"title": "sim 결과 첫 번째 질문 제목", "description": "sim 결과 첫 번째 내용입니다", "link": "L1"},
        {"title": "sim 결과 두 번째 질문 제목", "description": "sim 결과 두 번째 내용입니다", "link": "L2"},
    ]
    date_items = [
        {"title": "date 중복 질문 제목입니다", "description": "date 중복 내용 설명입니다", "link": "L2"},  # 중복
        {"title": "date 신규 질문 제목입니다", "description": "date 신규 내용 설명입니다", "link": "L3"},  # 신규
    ]

    def _fetch(keyword, *, sort, **kwargs):
        return sim_items if sort == "sim" else date_items

    fetch_j = MagicMock(side_effect=_fetch)

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    rows = client.append_staging_rows.call_args.args[2]
    links = [r[5] for r in rows]
    # L1, L2, L3 — L2 중복 1건 제거됨
    assert links == ["L1", "L2", "L3"]
    assert summary["collected"] == 3


def test_jisikin_no_auto_filter_keeps_everything():
    """★ 자동 필터 없음(사장님 결정) — 광고성 글이 섞여 있어도 전부 적재(선별은 사람이)."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피 탈모", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    good_item = {"title": "두피 탈모 원인이 뭔가요", "description": "머리가 자꾸 빠져서 걱정됩니다", "link": "L1"}
    ad_item = {"title": "탈모 치료", "description": "010-1234-5678 상담 https://clinic.com", "link": "L2"}

    fetch_j = MagicMock(return_value=[good_item, ad_item])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        today="2026-06-20",
    )

    rows = client.append_staging_rows.call_args.args[2]
    assert len(rows) == 2                       # 둘 다 적재(필터 없음)
    assert [r[5] for r in rows] == ["L1", "L2"]
    assert summary["collected"] == 2
    assert "filtered" not in summary            # filtered 카운트 자체가 없음


def test_format_summary_basic_no_filter_wording():
    """요약 = 수집/실패/스킵/탭만 — 자동 필터 제거 후 '쓰레기' 문구 없음."""
    text = ir.format_summary({"collected": 5, "failed": 0, "skipped": 2, "tabs": 1})
    assert "수집 5건" in text
    assert "쓰레기" not in text
