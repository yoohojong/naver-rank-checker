# -*- coding: utf-8 -*-
"""열쇠에 눈에 안 보이는 글자가 붙어도 회차가 죽지 않는다.

왜 이 검사가 있나 (2026-09-04 실사고)
------------------------------------
경쟁사 표가 8/20 이후 15일째 멈췄다. 매일 밤 1시간 37분 동안 댓글을 다 모은 뒤,
마지막 판정 단계에서 통째로 죽고 모은 자료를 전부 버렸다. 원인 두 겹:

1. `ANTHROPIC_API_KEY` 값 맨 앞에 BOM(U+FEFF) 한 글자가 붙어 있었다.
   그 값이 요청 머리글에 그대로 실려 httpx 가 ascii 로 옮기다 터졌다.
   `.strip()` 은 BOM 을 못 지운다 — BOM 은 공백이 아니다.
2. 그 오류(UnicodeEncodeError)는 anthropic.APIError 가 아니라서 예외 그물을
   빠져나갔다. **판정기 한 곳의 고장이 회차 전체를 죽였다.**
   설계는 "무료 먼저, 막히면 유료" 인데 유료가 터지면 되돌아갈 곳이 없었다.

→ 열쇠는 씻어서 쓰고, 판정기 고장은 회차를 죽이지 않고 사유를 남긴다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import comment_brand_llm as llm  # noqa: E402

BOM = "\ufeff"


@pytest.mark.parametrize("더러운값", [
    BOM + "sk-키",           # BOM 앞에 (실사고 모양)
    "sk-키" + BOM,           # 뒤에
    "  sk-키\n",             # 공백·줄바꿈
    '"sk-키"',               # 따옴표째 붙여넣음
    "'sk-키'",
    "\u200bsk-키",           # 폭 0 공백
])
def test_유료열쇠는_씻어서_쓴다(monkeypatch, 더러운값):
    monkeypatch.setenv("ANTHROPIC_API_KEY", 더러운값)
    assert llm._anthropic_key() == "sk-키"


def test_무료열쇠도_씻어서_쓴다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", BOM + "gsk-키 ")
    assert llm._groq_key() == "gsk-키"


def test_씻은_열쇠는_머리글에_실을_수_있다(monkeypatch):
    """진짜 증상 재현 — 씻지 않으면 이 줄에서 실사고와 같은 오류가 난다.

    진짜 열쇠는 영문·숫자뿐이라 시험값도 그렇게 쓴다(한글을 넣으면 BOM 과 무관하게
    ascii 변환이 실패해 이 검사가 무엇을 재는지 흐려진다).
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", BOM + "sk-ant-abc123")
    llm._anthropic_key().encode("ascii")        # 안 씻으면 UnicodeEncodeError


def test_판정기가_예상못한_오류로_죽어도_회차는_안_죽는다(monkeypatch):
    """실사고 그대로 — 머리글 인코딩 오류는 APIError 가 아니다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-키")

    class 터지는손님:
        class messages:
            @staticmethod
            def create(**kw):
                raise UnicodeEncodeError("ascii", "\ufeff", 0, 1, "ordinal not in range(128)")

    monkeypatch.setattr(llm, "_anthropic_client", lambda key: 터지는손님)
    사유 = []
    got = llm._anthropic_call("s", "u", max_tokens=10, tries=1,
                              sleep=lambda *_: None, errors=사유)
    assert got == (None, False)
    assert 사유, "조용히 물러나면 다음에 또 깜깜이가 된다 — 사유를 남겨야 한다"
    assert any("유료" in x for x in 사유)


def test_손님을_만들다_죽어도_회차는_안_죽는다(monkeypatch):
    """열쇠가 이상해 손님(client) 만들기 자체가 터지는 경우."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-키")

    def 터짐(key):
        raise ValueError("열쇠 모양이 이상함")

    monkeypatch.setattr(llm, "_anthropic_client", 터짐)
    사유 = []
    assert llm._anthropic_call("s", "u", max_tokens=10, tries=1,
                               sleep=lambda *_: None, errors=사유) == (None, False)
    assert 사유


def test_유료가_터져도_무료가_답하면_그_답을_쓴다(monkeypatch):
    """_call 은 무료 먼저다. 유료 고장이 무료 성공을 가리면 안 된다."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-키")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "\ufeffsk-키")
    monkeypatch.setattr(llm, "_post", lambda *a, **k: {
        "choices": [{"message": {"content": "무료답"}, "finish_reason": "stop"}]})
    assert llm._call("s", "u", max_tokens=10, timeout=5,
                     sleep=lambda *_: None) == ("무료답", False)


# ── 2026-09-04 독립 검수 지적 반영 ──────────────────────────

def test_가운데_낀_글자도_지운다(monkeypatch):
    """양 끝만 벗기면 가운데 한 글자에 같은 사고가 다시 난다(검수 지적 #12).

    눈에 안 보이는 글자는 열쇠 안 어디에도 정당하게 들어갈 수 없다.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a" + BOM + "bc")
    assert llm._anthropic_key() == "sk-abc"
    llm._anthropic_key().encode("ascii")


def test_댓글_읽는_본_경로도_같은_열쇠를_쓴다(monkeypatch):
    """★검수 지적 #11 — 씻는 코드를 한 곳에 만들어 놓고 정작 본 경로가 안 썼다.

    `brand_from_comments` 가 댓글을 실제로 읽는 자리다. 규칙은 한 곳에만 두고
    쓰는 쪽이 그것을 부른다([[feedback_one-rule-one-place]]).
    """
    from src import brand_from_comments as bfc
    monkeypatch.setenv("GROQ_API_KEY", BOM + "gsk-abc ")
    assert bfc._api_key() == "gsk-abc"


def test_봇_말귀_알아듣는_곳도_같은_열쇠를_쓴다(monkeypatch):
    from src import llm_intent
    monkeypatch.setenv("GROQ_API_KEY", BOM + "gsk-abc")
    assert llm_intent._api_key() == "gsk-abc"
