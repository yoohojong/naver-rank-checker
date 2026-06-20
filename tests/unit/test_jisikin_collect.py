"""jisikin_collect 단위 테스트 (HTTP 모킹 — 키/네트워크 없이 검증)."""
from unittest.mock import MagicMock, patch

import pytest

from src.jisikin_collect import _clean, fetch_jisikin


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
