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
    fetch_j = MagicMock(return_value=[{"title": "원인", "description": "본문", "link": "L"}])
    fetch_r = MagicMock()

    summary = run_collection(
        client,
        fetch_jisikin=fetch_j,
        fetch_reviews=fetch_r,
        naver_client_id="id",
        naver_client_secret="sec",
        apify_token="t",
        apify_actor_id="a~b",
        today="2026-06-20",
    )

    fetch_j.assert_called_once()
    assert fetch_j.call_args.args[0] == "두피 가려움"
    fetch_r.assert_not_called()
    # 지식인 스테이징 탭에 append 됐는지
    call = client.append_staging_rows.call_args
    assert call.args[0] == STAGING_TAB_JISIKIN
    assert call.args[1] == STAGING_HEADER
    row = call.args[2][0]
    # 스키마: [키워드 | 단계 | 제목 | 본문 | 수집일 | source_url | 적재완료]
    assert row[0] == "두피 가려움"
    assert row[1] == "3 증상"
    assert row[2] == "원인"
    assert row[3] == "본문"
    assert row[4] == "2026-06-20"
    assert row[5] == "L"
    assert summary["collected"] == 1
    assert summary["failed"] == 0
    assert summary["skipped"] == 0


@pytest.mark.parametrize("stage", ["4 대안", "5 브랜드"])
def test_routes_alternative_and_brand_to_reviews(stage):
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁상품", "키워드 분류(단계)": stage,
                     "링크": "https://smartstore.naver.com/x/products/1", "_row": 2}]}
    )
    fetch_j = MagicMock()
    fetch_r = MagicMock(return_value=[{"star": 1, "content": "최악", "source": "u1", "date": "d"}])

    summary = run_collection(
        client,
        fetch_jisikin=fetch_j,
        fetch_reviews=fetch_r,
        naver_client_id="id",
        naver_client_secret="sec",
        apify_token="t",
        apify_actor_id="a~b",
        today="2026-06-20",
    )

    fetch_j.assert_not_called()
    fetch_r.assert_called_once()
    # 리뷰는 URL 리스트로 호출
    assert fetch_r.call_args.args[0] == ["https://smartstore.naver.com/x/products/1"]
    call = client.append_staging_rows.call_args
    assert call.args[0] == STAGING_TAB_REVIEW
    row = call.args[2][0]
    # 리뷰: 제목=별점, 본문=리뷰내용
    assert row[0] == "경쟁상품"
    assert row[1] == stage
    assert row[2] == "1"          # 별점 문자열
    assert row[3] == "최악"
    assert row[5] == "u1"
    assert summary["collected"] == 1


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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
    fetch_j = MagicMock(return_value=[{"title": "t", "description": "d", "link": "L"}])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    fetch_j.assert_called_once()
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
        return [{"title": "t", "description": "d", "link": "L"}]

    fetch_j = MagicMock(side_effect=_fetch)

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    assert fetch_j.call_count == 2
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
        fetch_j = MagicMock(
            return_value=[{"title": "t", "link": "l", "description": "d"}]
        )
        summary = run_collection(
            client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
            naver_client_id="id", naver_client_secret="sec",
            apify_token="", apify_actor_id="", today="2026-06-20",
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    fetch_j.assert_not_called()
    assert summary["collected"] == 0
    assert summary["skipped"] == 1


def test_reviews_skipped_when_apify_token_missing():
    """APIFY 토큰 없으면 리뷰 채널 통째로 스킵(에러 아님)."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁", "키워드 분류(단계)": "4 대안",
                     "링크": "https://smartstore.naver.com/x/products/1", "_row": 2}]}
    )
    fetch_r = MagicMock()

    summary = run_collection(
        client, fetch_jisikin=MagicMock(), fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec",
        apify_token="", apify_actor_id="",               # 토큰 없음
        today="2026-06-20",
    )

    fetch_r.assert_not_called()
    assert summary["skipped"] == 1


def test_review_row_without_url_skipped():
    """리뷰 단계인데 상품 URL 이 없으면 스킵(스타트 URL 없으면 코어가 빈 결과 = 무의미)."""
    client = _client_with(
        {"x.카외": [{"키워드": "경쟁", "키워드 분류(단계)": "5 브랜드", "링크": "", "_row": 2}]}
    )
    fetch_r = MagicMock()

    summary = run_collection(
        client, fetch_jisikin=MagicMock(), fetch_reviews=fetch_r,
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    fetch_r.assert_not_called()
    assert summary["skipped"] == 1


def test_empty_fetch_result_counts_as_zero_collected_not_failed():
    """API 는 호출했지만 결과 0건 = 실패 아님(collected 0, 빈 append 호출 안 함)."""
    client = _client_with(
        {"x.카외": [{"키워드": "희귀키워드", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock(return_value=[])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    fetch_j.assert_called_once()
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
    fetch_j = MagicMock(return_value=[
        {"title": "t1", "description": "d1", "link": "L1"},
        {"title": "t2", "description": "d2", "link": "L2"},
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    rows = client.append_staging_rows.call_args.args[2]
    assert len(rows) == 2
    # collected = 적재된 키워드 단위(1) 가 아니라 행 수(2) 로 카운트
    assert summary["collected"] == 2
