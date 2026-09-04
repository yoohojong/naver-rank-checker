# -*- coding: utf-8 -*-
"""무료 한도로 닫힌 문을 회차 내내 다시 두드리던 것 — 2026-09-05.

무슨 일이 있었나
  묶음 820개를 **하나하나마다** 무료에 먼저 물었다. 무료 한도가 이미 닫힌 뒤에도
  묶음마다 세 번씩 두드리고 알려준 만큼(최대 60초) 쉬고서야 유료로 넘어갔다.
  회차가 5시간 한계를 넘겨 취소됐고, 810/820 묶음이 안 읽혔다.

무엇을 지키나
  ① 잠깐 몰린 한 번으로는 유료로 넘어가지 않는다(돈이 샌다).
  ② 연속 세 묶음이 다시 두드려도 안 열리면 그 회차는 곧장 유료로 간다.
  ③ 무료가 한 번이라도 답하면 셈은 되돌아간다.
  ④ 거절당한 사유에는 상대가 **뭐라고 했는지**가 같이 남는다.
  ⑤ '닫혀서 건너뛴다' 는 안내를 진짜 한도로 잘못 세지 않는다.
"""
import io
import urllib.error

import pytest

from src import brand_from_comments as B
from src import comment_brand_llm as L


class 가짜거절(urllib.error.HTTPError):
    def __init__(self, code, 몸통=b"", 헤더=None):
        super().__init__("http://x", code, "no", 헤더 or {}, io.BytesIO(몸통))


@pytest.fixture(autouse=True)
def _문을_열고_시작(monkeypatch):
    L.무료문_열기()
    monkeypatch.setenv("GROQ_API_KEY", "열쇠")
    monkeypatch.setattr(L, "_groq_model", lambda: "어떤모델")
    yield
    L.무료문_열기()


def _한도만_돌려준다(monkeypatch, 몸통=b'{"error":"rate limit"}'):
    def 열기(req, timeout=None):
        raise 가짜거절(429, 몸통)
    monkeypatch.setattr(L.urllib.request, "urlopen", 열기)


def _잘_답한다(monkeypatch):
    class 답:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"ok"}}]}'
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda req, timeout=None: 답())


def test_한_묶음_한도로는_문을_안_닫는다(monkeypatch):
    """잠깐 몰린 것일 수 있다 — 여기서 유료로 넘기면 하루치 값이 돈으로 나간다."""
    _한도만_돌려준다(monkeypatch)
    L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert L.무료가_닫혔나() is False


def test_연속_세_묶음이_한도면_문을_닫는다(monkeypatch):
    _한도만_돌려준다(monkeypatch)
    for _ in range(L.무료_포기_횟수):
        L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert L.무료가_닫혔나() is True


def test_닫힌_뒤에는_아예_안_두드린다(monkeypatch):
    """이것이 5시간을 잡아먹던 자리다 — 부르지 않는 것까지 확인한다."""
    _한도만_돌려준다(monkeypatch)
    for _ in range(L.무료_포기_횟수):
        L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)

    두드림 = []
    monkeypatch.setattr(L.urllib.request, "urlopen",
                        lambda req, timeout=None: 두드림.append(1))
    사유 = []
    답, _ = L._groq_call("계", "글", max_tokens=10, timeout=1,
                        sleep=lambda s: None, errors=사유)
    assert 답 is None
    assert 두드림 == [], "닫힌 문을 또 두드렸다"
    assert L.무료_건너뜀_말 in 사유


def test_무료가_답하면_셈이_되돌아간다(monkeypatch):
    _한도만_돌려준다(monkeypatch)
    for _ in range(L.무료_포기_횟수 - 1):
        L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    _잘_답한다(monkeypatch)
    답, _ = L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert 답 == "ok"
    _한도만_돌려준다(monkeypatch)
    L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert L.무료가_닫혔나() is False, "성공했는데도 셈이 안 되돌아갔다"


def test_유료쪽_한도는_무료문을_안_건드린다(monkeypatch):
    """다른 집 문이 닫혔다고 우리 집 문을 닫으면 안 된다."""
    _한도만_돌려준다(monkeypatch)
    for _ in range(L.무료_포기_횟수 + 2):
        L._post({"model": "m"}, timeout=1, sleep=lambda s: None,
                url="https://api.openai.com/v1/chat/completions", key="다른열쇠")
    assert L.무료가_닫혔나() is False


def test_거절당한_사유에_상대_말이_같이_남는다(monkeypatch):
    """'HTTP 400' 한 줄뿐이면 왜 막혔는지 아무도 모른다 — 회차 셋을 그렇게 버렸다."""
    def 열기(req, timeout=None):
        raise 가짜거절(400, '{"error":{"message":"model not found"}}'.encode())
    monkeypatch.setattr(L.urllib.request, "urlopen", 열기)
    사유 = []
    L._post({"model": "m"}, timeout=1, tries=1, sleep=lambda s: None, errors=사유)
    assert 사유 and "400" in 사유[0]
    assert "model not found" in 사유[0], f"상대가 한 말이 안 남았다: {사유}"


def test_건너뛴다는_안내를_진짜_한도로_세지_않는다():
    """세면 유료로 잘 돌고 있는 묶음마다 10~60초씩 쉰다."""
    assert B.한도인가([L.무료_건너뜀_말]) is False
    assert B.한도인가(["HTTP 429 — rate limit"]) is True
    assert B.한도인가([L.무료_건너뜀_말, "HTTP 429"]) is True


# ── 검수 지적 반영 (2026-09-05) ────────────────────────────────
# ① 사유에 몸통을 붙이자 몸통 속 숫자가 한도로 잘못 세어졌다
# ② 닫은 문이 영영 안 열려 9/4 사고를 한 층 아래에서 되풀이했다
# ③ 무료 거절과 유료 거절이 글자로 구별되지 않았다

def test_몸통_속_숫자를_한도로_세지_않는다():
    """실제 벤더가 보내는 몸통들이다 — 셋 다 한도가 아니다."""
    아닌것 = [
        "무료:HTTP 400 — on tokens per minute (TPM): Limit 6000, Requested 6429",
        "무료:HTTP 400 — max_tokens must be less than or equal to 4296",
        "유료:HTTP 400 — Invalid model id for org_01k2m429ab7",
    ]
    for x in 아닌것:
        assert B.한도인가([x]) is False, x
    assert B.한도인가(["무료:HTTP 429 — rate limit reached"]) is True


def test_닫은_문도_한참_뒤엔_한_번_다시_본다():
    """★무료 한도는 대개 분 단위로 풀린다 — 안 열어 보면 남은 회차가 통째로 유료다."""
    L._무료문.update({"닫힘": True, "닫은때": 1000.0, "연속한도": 3})
    assert L.무료가_닫혔나(지금=1000.0 + L.무료_다시두드리기_초 - 1) is True
    assert L.무료가_닫혔나(지금=1000.0 + L.무료_다시두드리기_초) is False


def test_다시_본_문이_또_막히면_곧바로_닫힌다():
    """한 번 열어 보는 값은 묶음 하나여야 한다 — 또 820번 두드리면 안 고친 것이다."""
    L._무료문.update({"닫힘": True, "닫은때": 1000.0, "연속한도": 3})
    assert L.무료가_닫혔나(지금=1000.0 + L.무료_다시두드리기_초) is False
    L._무료문_기록(True, 지금=2000.0)
    assert L.무료가_닫혔나(지금=2000.0) is True


def test_시간초과는_한도가_아니라서_연속셈을_끊는다(monkeypatch):
    """429 → 시간초과 → 429 로도 '연속 3' 이 차면 문이 잘못 닫힌다."""
    _한도만_돌려준다(monkeypatch)
    L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert L._무료문["연속한도"] == 1

    def 끊김(req, timeout=None):
        raise TimeoutError("느림")
    monkeypatch.setattr(L.urllib.request, "urlopen", 끊김)
    L._groq_call("계", "글", max_tokens=10, timeout=1, sleep=lambda s: None)
    assert L._무료문["연속한도"] == 0, "시간초과가 한도 셈에 얹혔다"


def test_어느_문이_막았는지_사유에_적힌다(monkeypatch):
    """무료와 유료가 같은 규격이라 거절 글자가 똑같이 생겼다."""
    def 열기(req, timeout=None):
        raise 가짜거절(400, b'{"error":"nope"}')
    monkeypatch.setattr(L.urllib.request, "urlopen", 열기)
    무료사유, 유료사유 = [], []
    L._post({"model": "m"}, timeout=1, tries=1, sleep=lambda s: None, errors=무료사유)
    L._post({"model": "m"}, timeout=1, tries=1, sleep=lambda s: None,
            url=L._OPENAI_URL, key="다른열쇠", errors=유료사유)
    assert 무료사유[0].startswith("무료:")
    assert 유료사유[0].startswith("유료:")
