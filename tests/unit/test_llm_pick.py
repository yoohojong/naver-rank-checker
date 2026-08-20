# -*- coding: utf-8 -*-
"""llm_pick — 쓸 모델을 계정에 물어보고 고르는 관문.

왜 있나: 모델 이름을 코드에 박아두면 공급사가 그 모델을 내리는 날 조용히 404 가 난다.
실제로 두 번 당했다 — 2026-07-23 발행본_검수(llama-3.3-70b), 2026-08-16 Groq 가
llama-3.3-70b-versatile 퇴역 → 경쟁사-댓글 수집 사흘 전멸 + 텔레그램 봇 자연어 동반 사망.
같은 실수 두 번이면 규칙이 아니라 관문 — 이름을 아는 곳을 여기 하나로 모은다.
"""
import json
import urllib.error

import pytest

from src import comment_brand_llm, llm_intent, llm_pick

URL = "https://api.groq.com/openai/v1/chat/completions"


@pytest.fixture(autouse=True)
def _캐시_초기화():
    """모듈 캐시가 검사 사이에 새지 않게 — 순서에 따라 결과가 달라지면 안 된다."""
    llm_pick._cache.clear()
    yield
    llm_pick._cache.clear()


class _응답:
    def __init__(self, obj):
        self._d = json.dumps(obj, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _모델목록(monkeypatch, ids, calls=None):
    def fake(req, timeout=0):
        if calls is not None:
            calls.append(req.full_url)
        return _응답({"data": [{"id": i} for i in ids]})
    monkeypatch.setattr(llm_pick.urllib.request, "urlopen", fake)


def test_선호_목록_순서대로_고른다(monkeypatch):
    _모델목록(monkeypatch, ["whisper-large-v3", "openai/gpt-oss-20b", "openai/gpt-oss-120b"])
    assert llm_pick.pick(URL, "k") == "openai/gpt-oss-120b"


def test_제공사_접두사가_달라도_같은_모델로_알아본다(monkeypatch):
    # 'openai/gpt-oss-120b' 를 선호하는데 목록엔 다른 경로로 올라와 있어도 꼬리가 같으면 그 모델.
    _모델목록(monkeypatch, ["groq/gpt-oss-120b"])
    assert llm_pick.pick(URL, "k") == "groq/gpt-oss-120b"


def test_선호가_하나도_없으면_대화되는_첫번째(monkeypatch):
    _모델목록(monkeypatch, ["whisper-large-v3", "낯선-chat-7b"])
    assert llm_pick.pick(URL, "k") == "낯선-chat-7b"


def test_대화되는_모델이_없으면_기본값(monkeypatch):
    # '아무거나 첫 번째' 폴백이 음성 모델(whisper)을 집으면 400 만 난다 — 그럴 땐 기본값.
    _모델목록(monkeypatch, ["whisper-large-v3", "meta-llama/llama-prompt-guard-2-22m"])
    assert llm_pick.pick(URL, "k") == llm_pick.DEFAULT


def test_목록_조회가_실패하면_기본값(monkeypatch):
    def fake(req, timeout=0):
        raise urllib.error.URLError("no net")
    monkeypatch.setattr(llm_pick.urllib.request, "urlopen", fake)
    assert llm_pick.pick(URL, "k") == llm_pick.DEFAULT


def test_키가_없으면_묻지도_않고_기본값(monkeypatch):
    calls = []
    _모델목록(monkeypatch, ["openai/gpt-oss-120b"], calls)
    assert llm_pick.pick(URL, "") == llm_pick.DEFAULT
    assert calls == []


def test_한번_고르면_기억하고_forget_이_비운다(monkeypatch):
    calls = []
    _모델목록(monkeypatch, ["openai/gpt-oss-120b"], calls)
    llm_pick.pick(URL, "k")
    llm_pick.pick(URL, "k")
    assert len(calls) == 1                    # 두 번째는 묻지 않았다
    llm_pick.forget(URL)
    llm_pick.pick(URL, "k")
    assert len(calls) == 2                    # 비운 뒤에는 다시 묻는다


# ── 실전 배선: 404 를 맞으면 다시 골라 그 자리에서 이어간다 ─────────────────

def test_경쟁사_판정이_404_맞으면_모델_다시_골라_이어간다(monkeypatch):
    # 8/17~19 실사고 재현: 한낮 퇴역으로 어제까지 쓰던 모델이 404 — 멈추지 말고 갈아탄다.
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    llm_pick._cache[URL] = "떠난-모델"

    def fake(req, timeout=0):
        url = req.full_url
        if url.endswith("/models"):
            return _응답({"data": [{"id": "openai/gpt-oss-120b"}]})
        body = json.loads(req.data.decode("utf-8"))
        if body.get("model") == "떠난-모델":
            raise urllib.error.HTTPError(url, 404, "model gone", {}, None)
        return _응답({"choices": [{"message": {"content":
            '{"판정":[{"n":1,"후보":"일리윤","제품":true,"이름":"일리윤"}]}'}}]})

    monkeypatch.setattr(comment_brand_llm.urllib.request, "urlopen", fake)
    got, stat = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got["일리윤"]["제품"] is True      # 404 에서 죽지 않고 새 모델로 받아냈다
    assert stat["미판정"] == 0


def test_봇_질문분류가_404_맞으면_모델_다시_골라_이어간다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    llm_pick._cache[llm_intent._DEFAULT_BASE_URL] = "떠난-모델"

    def fake(req, timeout=0):
        url = req.full_url
        if url.endswith("/models"):
            return _응답({"data": [{"id": "openai/gpt-oss-120b"}]})
        body = json.loads(req.data.decode("utf-8"))
        if body.get("model") == "떠난-모델":
            raise urllib.error.HTTPError(url, 404, "model gone", {}, None)
        return _응답({"choices": [{"message": {"content":
            '{"intent":"summary","arg":null}'}}]})

    monkeypatch.setattr(llm_intent.urllib.request, "urlopen", fake)
    assert llm_intent.classify("전체 어때?", []) == ("summary", None)


def test_명시한_모델이_있으면_그대로_따른다(monkeypatch):
    # GROQ_MODEL 을 사장님이 secret 으로 박아두면 그게 위다 — 묻지도 갈아타지도 않는다.
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "내가-정한-모델")
    보낸모델 = []

    def fake(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        보낸모델.append(body.get("model"))
        return _응답({"choices": [{"message": {"content": '{"판정":[]}'}}]})

    monkeypatch.setattr(comment_brand_llm.urllib.request, "urlopen", fake)
    comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert 보낸모델 and all(m == "내가-정한-모델" for m in 보낸모델)
