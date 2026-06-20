"""integration_runner 단위 테스트 (SheetsClient·fetch_* 전부 mock — 키/네트워크 없이 행동 검증).

C3: 카외 제품 탭 → 단계별 수집(지식인/리뷰) → 스테이징 탭 적재 + '자료조사' 칸 증분 표시.
검증 포인트:
  ① 단계 라우팅(3 증상→지식인, 4 대안/5 브랜드→리뷰)
  ② 증분(표시기반): '자료조사' 칸이 채워진 행은 스킵, 빈 행만 수집 → 수집 후 그 칸에 write-back
  ③ 키워드별 try/except 격리(한 건 실패해도 전체 계속)
  ④ summary 카운트(수집/실패/스킵)
  ⑤ 키 없음/단계 미지정 행 건너뜀
  ⑥ 재개: 적재 실패 시 표시 안 함(다음 실행이 빈 칸부터 이어감)
  ⑦ 일괄(대량 행): 청크마다 적재→표시 flush
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
from src.sheets import HEADER_COLLECT_STATUS


def _client_with(tabs, existing=None):
    """SheetsClient mock — load_all_data_tabs / append_staging_rows / write_collect_status.

    tabs: {탭이름: [row dict, ...]}  (카외 제품 탭)
    existing: (deprecated) 과거 스테이징 기반 중복방지 인자 — 새 로직에선 미사용(시그니처 호환만 유지).
    """
    client = MagicMock()
    client.load_all_data_tabs.return_value = tabs
    # append_staging_rows 는 append 한 행 수 반환(실제 코어 시그니처와 동일).
    client.append_staging_rows.side_effect = lambda tab, header, rows: len(rows)
    # write_collect_status 는 write 한 셀 수 반환(실제 코어 시그니처와 동일).
    client.write_collect_status.side_effect = lambda tab, updates: len(updates)
    return client


def _status_writes(client):
    """write_collect_status 로 기록된 모든 (row, status) 페어를 평탄화해 반환."""
    pairs = []
    for call in client.write_collect_status.call_args_list:
        tab, updates = call.args[0], call.args[1]
        for upd in updates:
            pairs.append((tab, upd.row, upd.columns[HEADER_COLLECT_STATUS]))
    return pairs


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
        apify_token="t",
        apify_actor_id="a~b",
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
    # 증분 표시: 수집 직후 그 행(_row=2)의 '자료조사' 칸에 write-back.
    writes = _status_writes(client)
    assert writes == [("두피.카외", 2, "✅ 2026-06-20 수집(1건)")]


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
    # 증분 표시: 리뷰 행도 수집 후 '자료조사' 칸에 write-back.
    assert _status_writes(client) == [("x.카외", 2, "✅ 2026-06-20 수집(1건)")]


def test_skips_row_already_collected_status_filled():
    """'자료조사' 칸이 이미 채워진 행은 스킵(증분) — API 호출도 표시 write-back 도 안 함."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피 가려움", "키워드 분류(단계)": "3 증상",
                     HEADER_COLLECT_STATUS: "✅ 2026-06-19 수집(12건)", "_row": 2}]},
    )
    fetch_j = MagicMock(return_value=[{"title": "t", "description": "d", "link": "L"}])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    fetch_j.assert_not_called()                 # 이미 수집됨 → API 호출 X
    client.append_staging_rows.assert_not_called()
    assert _status_writes(client) == []         # 표시 write-back 도 안 함
    assert summary["skipped"] == 1
    assert summary["collected"] == 0


def test_collects_again_regardless_of_date_when_status_empty():
    """날짜가 바뀌어도 '자료조사' 칸이 비어 있으면 수집한다(과거 날짜기반 약점 해소).

    예전 로직: 같은 키워드를 어제 수집했으면 오늘 또 수집(날짜 키가 달라). 약점 = 날짜만 바뀌면
    이미 받은 키워드를 무한 재수집. 새 로직: 표시 칸이 비었는지로만 판단 → 표시되면 다시는 안 함.
    여기선 '비어 있는' 행이므로 날짜와 무관하게 수집되고 표시가 새로 찍힌다.
    """
    client = _client_with(
        {"x.카외": [{"키워드": "두피 가려움", "키워드 분류(단계)": "3 증상",
                     HEADER_COLLECT_STATUS: "", "_row": 2}]},
    )
    fetch_j = MagicMock(return_value=[
        {"title": "두피 가려움 원인과 해결책", "description": "두피 가려움 증상 설명입니다", "link": "L"}
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    assert fetch_j.call_count == 2  # sim + date 2회 호출
    assert summary["collected"] == 1
    assert summary["skipped"] == 0
    assert _status_writes(client) == [("x.카외", 2, "✅ 2026-06-20 수집(1건)")]


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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
        # is_junk 필터 통과를 위해 title+description 합산 15자 이상.
        fetch_j = MagicMock(
            return_value=[{"title": "두피 가려움 관련 질문", "link": "l", "description": "두피 가려움 증상 설명"}]
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
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


# ── 신규: 증분-by-표시 / 재개 / 일괄(대량 행) ───────────────────────────────


def test_failure_keyword_gets_no_status_writeback():
    """fetch 실패한 키워드는 '자료조사' 표시를 받지 않는다(다음 실행이 빈 칸부터 재개)."""
    client = _client_with(
        {"x.카외": [
            {"키워드": "터지는키워드", "키워드 분류(단계)": "3 증상", "_row": 2},
            {"키워드": "정상키워드", "키워드 분류(단계)": "3 증상", "_row": 3},
        ]}
    )

    def _fetch(keyword, **kwargs):
        if keyword == "터지는키워드":
            raise RuntimeError("지식iN Open API 오류 500")
        return [{"title": "정상키워드 질문 제목", "description": "정상키워드 설명 내용입니다", "link": "L"}]

    fetch_j = MagicMock(side_effect=_fetch)

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    # 정상키워드(_row=3)만 표시됨, 실패한 _row=2 는 표시 X → 재실행 시 _row=2 만 이어감.
    writes = _status_writes(client)
    assert writes == [("x.카외", 3, "✅ 2026-06-20 수집(1건)")]
    assert summary["failed"] == 1
    assert summary["collected"] == 1


def test_empty_result_still_marks_status_to_avoid_reretry():
    """결과 0건이어도 '자료조사' 칸에 '(0건)' 표시 → 무한 재시도 방지(시도했음을 기록)."""
    client = _client_with(
        {"x.카외": [{"키워드": "희귀키워드", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock(return_value=[])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    client.append_staging_rows.assert_not_called()   # 적재할 행 없음
    assert _status_writes(client) == [("x.카외", 2, "✅ 2026-06-20 수집(0건)")]
    assert summary["collected"] == 0
    assert summary["failed"] == 0


def test_staging_append_failure_skips_status_for_resume():
    """청크 스테이징 append 실패 시 그 청크는 '자료조사' 표시 안 함(재개 불변식).

    표시가 찍힌 행 ⟹ 적재 완료. append 가 터지면 표시를 안 찍어 다음 실행이 다시 수집한다.
    """
    client = _client_with(
        {"x.카외": [{"키워드": "두피", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    client.append_staging_rows.side_effect = RuntimeError("Sheets append 503")
    fetch_j = MagicMock(return_value=[
        {"title": "두피 가려움 질문 제목", "description": "두피 증상 설명 내용입니다", "link": "L"}
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    # 적재 실패 → 표시 write-back 안 함 → 다음 실행 재개.
    client.write_collect_status.assert_not_called()
    assert summary["failed"] == 1          # 적재 실패분 failed 환산
    assert summary["collected"] == 0       # 적재 실패분 collected 차감


def test_status_writeback_uses_dedicated_method_not_write_results():
    """'자료조사' 표시는 write_collect_status 전용 경로로만 — write_results(K/L/M/O 가드) 안 씀."""
    client = _client_with(
        {"x.카외": [{"키워드": "두피", "키워드 분류(단계)": "3 증상", "_row": 2}]}
    )
    fetch_j = MagicMock(return_value=[
        {"title": "두피 질문 제목입니다", "description": "두피 증상 설명입니다", "link": "L"}
    ])

    run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    client.write_collect_status.assert_called()
    client.write_results.assert_not_called()


def test_bulk_chunked_flush_marks_each_row(monkeypatch):
    """일괄(대량 행): 청크 크기마다 적재→표시 flush. 모든 빈 행이 표시되고 합계가 맞는다."""
    # 청크 경계를 강제로 작게(3) 만들어 여러 번 flush 되게 한다.
    monkeypatch.setattr(ir, "COLLECT_STATUS_FLUSH_EVERY", 3)

    n = 10  # 청크 3 → 4번 flush(3+3+3+1)
    rows = [
        {"키워드": f"kw{i}", "키워드 분류(단계)": "3 증상", "_row": i + 2}
        for i in range(n)
    ]
    client = _client_with({"대량.카외": rows})
    fetch_j = MagicMock(return_value=[
        {"title": "질문 제목 예시입니다", "description": "본문 설명 내용입니다", "link": "L"}
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    writes = _status_writes(client)
    # 10개 행 모두 표시(중복 없이 _row 2..11), 각각 1건 수집.
    written_rows = sorted(r for _tab, r, _s in writes)
    assert written_rows == list(range(2, 12))
    assert all(s == "✅ 2026-06-20 수집(1건)" for _tab, _r, s in writes)
    # 여러 번 청크 flush 됐는지(1회가 아님).
    assert client.write_collect_status.call_count >= 2
    assert summary["collected"] == n
    assert summary["skipped"] == 0


def test_mixed_filled_and_empty_only_empty_collected():
    """일괄 중 일부 행만 미수집(빈 칸): 채워진 행은 스킵, 빈 행만 수집·표시(증분 정확)."""
    rows = [
        {"키워드": "이미함", "키워드 분류(단계)": "3 증상",
         HEADER_COLLECT_STATUS: "✅ 2026-06-10 수집(5건)", "_row": 2},
        {"키워드": "새거", "키워드 분류(단계)": "3 증상", HEADER_COLLECT_STATUS: "", "_row": 3},
        {"키워드": "또새거", "키워드 분류(단계)": "3 증상", "_row": 4},  # 칸 자체 없음 = 빈 것 취급
    ]
    client = _client_with({"x.카외": rows})
    fetch_j = MagicMock(return_value=[
        {"title": "질문 제목 예시입니다", "description": "본문 설명 내용입니다", "link": "L"}
    ])

    summary = run_collection(
        client, fetch_jisikin=fetch_j, fetch_reviews=MagicMock(),
        naver_client_id="id", naver_client_secret="sec",
        apify_token="t", apify_actor_id="a~b", today="2026-06-20",
    )

    written_rows = sorted(r for _tab, r, _s in _status_writes(client))
    assert written_rows == [3, 4]          # 빈 행 2개만 표시
    assert summary["skipped"] == 1         # 이미함 1개 스킵
    assert summary["collected"] == 2
