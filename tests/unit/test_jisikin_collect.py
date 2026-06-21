"""jisikin_collect 단위 테스트 (HTTP 모킹 — 키/네트워크 없이 검증)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.jisikin_collect import (
    _clean,
    enrich_jisikin,
    fetch_jisikin,
    fetch_kin_detail,
)

_FIXTURE_KIN_DETAIL = (
    Path(__file__).resolve().parents[1] / "fixtures" / "naver" / "kin_detail_sample.html"
)


def test_clean_strips_tags_and_entities():
    assert _clean("<b>두피</b> 가려움 &amp; 각질") == "두피 가려움 & 각질"
    assert _clean("") == ""
    assert _clean(None) == ""


def test_fetch_parses_items_and_strips_tags():
    fake = {
        "items": [
            {
                "title": "<b>두피</b> 가려움 원인",
                "link": "https://kin.naver.com/qna/detail.naver?d1id=1&dirId=1&docId=1",
                "description": "<b>두피</b>가 너무 가려워요 ...",
            }
        ]
    }
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    with patch("src.jisikin_collect.requests.get", return_value=resp) as g:
        out = fetch_jisikin("두피 가려움", client_id="id", client_secret="sec")

    assert out == [
        {
            "title": "두피 가려움 원인",
            "link": "https://kin.naver.com/qna/detail.naver?d1id=1&dirId=1&docId=1",
            "description": "두피가 너무 가려워요 ...",
        }
    ]
    # 인증 헤더가 실제로 실렸는지 확인
    _, kwargs = g.call_args
    assert kwargs["headers"]["X-Naver-Client-Id"] == "id"
    assert kwargs["headers"]["X-Naver-Client-Secret"] == "sec"
    assert kwargs["params"]["query"] == "두피 가려움"


def test_empty_keyword_returns_empty_without_calling_api():
    with patch("src.jisikin_collect.requests.get") as g:
        assert fetch_jisikin("   ", client_id="id", client_secret="sec") == []
    g.assert_not_called()


def test_missing_key_raises():
    with pytest.raises(RuntimeError, match="NAVER_OPENAPI"):
        fetch_jisikin("두피", client_id="", client_secret="")


def test_non_200_raises():
    resp = MagicMock(status_code=401, text="Unauthorized")
    with patch("src.jisikin_collect.requests.get", return_value=resp):
        with pytest.raises(RuntimeError, match="401"):
            fetch_jisikin("두피", client_id="id", client_secret="sec")


def test_display_clamped_to_100():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"items": []}
    with patch("src.jisikin_collect.requests.get", return_value=resp) as g:
        fetch_jisikin("x", client_id="id", client_secret="sec", display=500)
    _, kwargs = g.call_args
    assert kwargs["params"]["display"] == 100


# ---------------------------------------------------------------------------
# fetch_kin_detail / enrich_jisikin — detail 페이지 '질문 본문 + 답변 본문' 추출
# (라이브 네트워크 의존 X — 실제 지식인 detail HTML 픽스처로 검증).
# ---------------------------------------------------------------------------

def _detail_resp(html_text: str, status: int = 200):
    """fetch_kin_detail 내부 requests.get 가 돌려줄 응답 mock."""
    resp = MagicMock(status_code=status)
    resp.text = html_text
    return resp


def test_fetch_kin_detail_extracts_question_and_answers():
    """실제 지식인 detail 픽스처에서 질문 본문 + 최소 1개 답변을 뽑고 보일러플레이트가 빠진다."""
    html_text = _FIXTURE_KIN_DETAIL.read_text(encoding="utf-8")
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp(html_text)) as g:
        out = fetch_kin_detail(
            "https://kin.naver.com/qna/detail.naver?d1id=7&dirId=70307&docId=492080444"
        )

    # 브라우저 UA + 리다이렉트 따라가기로 GET 했는지 확인.
    _, kwargs = g.call_args
    assert "Mozilla/5.0" in kwargs["headers"]["User-Agent"]
    assert kwargs["allow_redirects"] is True

    # 질문 본문 + 답변 추출.
    assert out, "detail 추출 결과가 비어 있으면 안 된다"
    assert out["question_body"], "질문 본문이 비어 있으면 안 된다"
    assert len(out["answers"]) >= 1, "최소 1개 답변이 추출돼야 한다"
    # 한글 본문이 실제로 들어 있다(스니펫이 아닌 본문).
    assert len(out["question_body"]) > 30
    assert any(len(a) > 30 for a in out["answers"])

    # 보일러플레이트가 빠졌는지(JUNK 토큰이 추출 텍스트에 없어야 한다).
    joined = out["question_body"] + " ".join(out["answers"])
    for junk in ("로그인", "지식iN 서비스", "고객센터", "신고", "저작권"):
        assert junk not in joined, f"보일러플레이트 '{junk}' 가 제거되지 않았다"


def test_fetch_kin_detail_empty_link_returns_empty_without_network():
    """빈 link 는 네트워크 호출 없이 빈 dict 반환."""
    with patch("src.jisikin_collect.requests.get") as g:
        assert fetch_kin_detail("") == {}
        assert fetch_kin_detail("   ") == {}
    g.assert_not_called()


def test_fetch_kin_detail_non_200_returns_empty():
    """차단/오류(비200)면 빈 dict — 예외 던지지 않는다(한 건 실패가 전체를 막으면 안 됨)."""
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp("x", status=403)):
        assert fetch_kin_detail("https://kin.naver.com/qna/detail.naver?docId=1") == {}


def test_fetch_kin_detail_network_exception_returns_empty():
    """네트워크 예외도 빈 dict 로 격리(예외 전파 금지)."""
    with patch("src.jisikin_collect.requests.get", side_effect=RuntimeError("boom")):
        assert fetch_kin_detail("https://kin.naver.com/qna/detail.naver?docId=1") == {}


def test_enrich_jisikin_builds_body_full_from_detail():
    """enrich 가 각 item 에 body_full(질문 본문 + [답변 N] ...)을 채운다."""
    html_text = _FIXTURE_KIN_DETAIL.read_text(encoding="utf-8")
    items = [{
        "title": "두피 가려움 질문",
        "link": "https://kin.naver.com/qna/detail.naver?docId=492080444",
        "description": "짧은 스니펫",
    }]
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp(html_text)):
        out = enrich_jisikin(items)

    body = out[0]["body_full"]
    assert body, "body_full 이 채워져야 한다"
    assert "[답변 1]" in body, "답변 마커가 포함돼야 한다"
    # description(스니펫)이 아니라 detail 본문이 들어갔다.
    assert body != "짧은 스니펫"
    assert len(body) > len("짧은 스니펫")


def test_enrich_jisikin_falls_back_to_description_on_detail_failure():
    """detail 추출 실패 시 body_full = description 폴백(회귀 안전)."""
    items = [{
        "title": "t",
        "link": "https://kin.naver.com/qna/detail.naver?docId=1",
        "description": "폴백되어야 하는 description 본문",
    }]
    # 비200 → fetch_kin_detail 이 {} → enrich 가 description 폴백.
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp("x", status=500)):
        out = enrich_jisikin(items)

    assert out[0]["body_full"] == "폴백되어야 하는 description 본문"


def test_enrich_jisikin_empty_description_fallback_is_empty():
    """detail 실패 + description 도 없으면 body_full 은 빈 문자열(예외 없이)."""
    items = [{"title": "t", "link": "https://kin.naver.com/qna/detail.naver?docId=1"}]
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp("x", status=500)):
        out = enrich_jisikin(items)
    assert out[0]["body_full"] == ""


def test_enrich_jisikin_respects_max_items():
    """max_items 초과분은 detail 호출 없이 description 폴백만 적용."""
    html_text = _FIXTURE_KIN_DETAIL.read_text(encoding="utf-8")
    items = [
        {"title": "a", "link": "L1", "description": "desc1"},
        {"title": "b", "link": "L2", "description": "desc2"},
    ]
    with patch("src.jisikin_collect.requests.get", return_value=_detail_resp(html_text)) as g:
        out = enrich_jisikin(items, max_items=1)

    # detail GET 은 첫 item 1건만.
    assert g.call_count == 1
    assert out[0]["body_full"] and out[0]["body_full"] != "desc1"
    # 둘째 item 은 폴백(description).
    assert out[1]["body_full"] == "desc2"


def test_enrich_jisikin_empty_list_returns_empty():
    """빈 입력은 빈 출력(네트워크 호출 없음)."""
    with patch("src.jisikin_collect.requests.get") as g:
        assert enrich_jisikin([]) == []
    g.assert_not_called()
