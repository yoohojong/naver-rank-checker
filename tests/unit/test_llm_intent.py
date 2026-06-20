"""llm_intent 단위 테스트 (M12). 네트워크 0 (urlopen mock). 키 없으면 None 폴백."""
import json
from unittest import mock

from src import llm_intent
from src import qa_formatter as qa


class _FakeResp:
    def __init__(self, payload):
        self._d = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


# ── parse_response ────────────────────────────────────────────────
def test_parse_keyword():
    assert llm_intent.parse_response('{"intent":"keyword","arg":"비듬샴푸"}', ["샴푸 카외"]) == ("keyword", "비듬샴푸")


def test_parse_product_maps_to_real_tab():
    out = llm_intent.parse_response('{"intent":"product","arg":"샴푸"}', ["샴푸 카외", "바디워시 카외"])
    assert out == ("product", "샴푸 카외")


def test_parse_product_unknown_tab_returns_none_arg():
    assert llm_intent.parse_response('{"intent":"product","arg":"세제"}', ["샴푸 카외"]) == ("product", None)


def test_parse_non_arg_intent_drops_arg():
    assert llm_intent.parse_response('{"intent":"missing","arg":"뭔가"}', []) == ("missing", None)


def test_parse_invalid_intent_returns_none():
    assert llm_intent.parse_response('{"intent":"shell","arg":null}', []) is None


def test_parse_codefence_json():
    assert llm_intent.parse_response('```json\n{"intent":"summary","arg":null}\n```', []) == ("summary", None)


def test_parse_garbage_returns_none():
    assert llm_intent.parse_response("죄송해요 잘 모르겠어요", []) is None
    assert llm_intent.parse_response("", []) is None


# ── build_messages (질문 글만 전송, 시트 파생 데이터 0건) ─────────
def test_build_messages_question_only_no_sheet_data():
    msgs = llm_intent.build_messages("샴푸 요새 어때?")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == "샴푸 요새 어때?"   # 질문 글만, 탭명 등 미포함


# ── classify (네트워크 mock) ──────────────────────────────────────
def test_classify_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_intent.classify("아무 질문", ["샴푸 카외"]) is None


def test_classify_success(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(_chat('{"intent":"missing","arg":null}'))):
        assert llm_intent.classify("요새 빠진 거 있나?", ["샴푸 카외"]) == ("missing", None)


def test_classify_http_failure_returns_none(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("boom")):
        assert llm_intent.classify("질문", []) is None


def test_classify_sends_auth_and_no_sheet_data(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-key")
    cap = {}

    def fake_urlopen(req, timeout=None):
        cap["url"] = req.full_url
        cap["auth"] = req.get_header("Authorization")
        cap["ua"] = req.get_header("User-agent")
        cap["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(_chat('{"intent":"summary","arg":null}'))

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        llm_intent.classify("전체 어떤지 알려줘", ["샴푸 카외"])
    assert cap["auth"] == "Bearer secret-key"
    assert "api.groq.com" in cap["url"]
    assert cap["ua"] and "Mozilla" in cap["ua"]   # Cloudflare 1010 회피 UA 필수(회귀 가드)
    body_str = json.dumps(cap["body"], ensure_ascii=False)
    assert "전체 어떤지 알려줘" in body_str   # 질문은 전송
    assert "샴푸 카외" not in body_str          # 시트 파생 탭명은 미전송(Codex MAJOR fix)
    assert cap["body"]["model"] and cap["body"]["messages"]


def test_classify_model_override(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    cap = {}

    def fake_urlopen(req, timeout=None):
        cap["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(_chat('{"intent":"summary","arg":null}'))

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        llm_intent.classify("요약", [])
    assert cap["body"]["model"] == "llama-3.1-8b-instant"


# ── qa_formatter.classify_with_confidence (리팩토링 회귀) ─────────
def test_confidence_true_on_explicit_command():
    assert qa.classify_with_confidence("누락 알려줘", [])[2] is True
    assert qa.classify_with_confidence("순위", [])[2] is True
    assert qa.classify_with_confidence("샴푸", ["샴푸 카외"]) == ("product", "샴푸 카외", True)


def test_confidence_false_on_freetext_fallback():
    intent, arg, conf = qa.classify_with_confidence("샴푸 요새 잘 나오나 궁금", [])
    assert conf is False and intent == "keyword"


def test_classify_intent_backcompat_unchanged():
    assert qa.classify_intent("누락", []) == ("missing", None)
    assert qa.classify_intent("키워드 비듬샴푸", ["샴푸 카외"]) == ("keyword", "비듬샴푸")
    assert qa.classify_intent("")[0] == "unknown"
