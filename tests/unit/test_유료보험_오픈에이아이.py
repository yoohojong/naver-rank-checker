# -*- coding: utf-8 -*-
"""무료가 막히면 **OpenAI** 로 넘어간다 — 2026-09-04.

★왜 이걸 붙였나: 유료 보험을 Anthropic 하나로 뒀는데 그 계정 잔액이 0원이라
(`Your credit balance is too low`) 보험이 통째로 죽어 있었다. 그 사이 무료는
한도(429)에 걸려, 댓글 16,379건 중 810/820 묶음을 못 읽었다.
살아 있는 열쇠가 이미 손에 있었는데(cafe-external/secrets/openai_key.txt)
쓰는 코드가 없었다 — '만들어 놓고 안 이은 자리' 가 또 하나였다.

보험은 **둘**이다: 하나가 죽어도 다른 하나가 받는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import comment_brand_llm as llm  # noqa: E402


def _답(글):
    return {"choices": [{"message": {"content": 글}, "finish_reason": "stop"}]}


def test_무료가_되면_유료는_안_부른다(monkeypatch):
    """순서가 곧 돈이다 — 잘 도는 날까지 돈을 쓰면 안 된다."""
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    부름 = []
    monkeypatch.setattr(llm, "_post", lambda *a, **k: _답("무료답"))
    monkeypatch.setattr(llm, "_openai_call",
                        lambda *a, **k: 부름.append("유료") or ("유료답", False))
    assert llm._call("s", "u", max_tokens=10, timeout=5,
                     sleep=lambda *_: None) == ("무료답", False)
    assert 부름 == []


def test_무료가_막히면_오픈에이아이가_받는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setattr(llm, "_post", lambda *a, **k: None)          # 무료 실패
    monkeypatch.setattr(llm, "_openai_post", lambda *a, **k: _답("오픈답"))
    got, _ = llm._call("s", "u", max_tokens=10, timeout=5, sleep=lambda *_: None)
    assert got == "오픈답"


def test_오픈에이아이도_막히면_앤트로픽까지_간다(monkeypatch):
    """보험이 둘이다 — 하나가 죽어도 다른 하나가 받는다."""
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setattr(llm, "_post", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_openai_post", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_anthropic_call", lambda *a, **k: ("앤트답", False))
    got, _ = llm._call("s", "u", max_tokens=10, timeout=5, sleep=lambda *_: None)
    assert got == "앤트답"


def test_열쇠가_없으면_조용히_물러난다(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm._openai_call("s", "u", max_tokens=10, timeout=5,
                            sleep=lambda *_: None) == (None, False)


def test_오픈에이아이_열쇠도_씻어서_쓴다(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "\ufeffsk-abc ")
    assert llm._openai_key() == "sk-abc"


def test_실패하면_사유를_남긴다(monkeypatch):
    """조용히 물러나면 다음에 또 깜깜이가 된다."""
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setattr(llm, "_openai_post", lambda *a, **k: None)
    사유 = []
    llm._openai_call("s", "u", max_tokens=10, timeout=5,
                     sleep=lambda *_: None, errors=사유)
    assert any("오픈" in x or "openai" in x.lower() for x in 사유), 사유
