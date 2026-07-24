# -*- coding: utf-8 -*-
"""AI 가 댓글 원문을 읽어 이름을 뽑는 새 구조(2026-07-24) 검사."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import brand_from_comments as bfc  # noqa: E402
from src import shop_probe  # noqa: E402


def _reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]}


def test_댓글에서_이름을_뽑는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(bfc, "_post", lambda *a, **k: _reply(
        {"결과": [{"n": 1, "제품": ["안티트로"]}, {"n": 2, "제품": []}]}))
    got = bfc.read_batch(["안ㅌ티트로 샴푸 써요", "그냥 잡담"])
    assert got == {0: ["안티트로"]}


def test_못_읽으면_None_판정_안함(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(bfc, "_post", lambda *a, **k: None)      # 호출 실패
    assert bfc.read_batch(["안티트로 써요"]) is None


def test_키_없으면_None(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert bfc.read_batch(["안티트로 써요"]) is None


def test_묶음_하나가_실패해도_나머지는_산다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return None if calls["n"] == 1 else _reply({"결과": [{"n": 1, "제품": ["맥단비"]}]})

    monkeypatch.setattr(bfc, "_post", fake)
    # 둘째 묶음 첫 댓글에 실제 '맥단비' 를 넣어야 환각 관문을 통과한다.
    texts = [f"댓글{i}" for i in range(bfc.BATCH)] + ["맥단비 샴푸 써요"]   # 두 묶음
    out, stat = bfc.read_all(texts)
    assert stat["못읽은묶음"] == 1 and stat["뽑은이름"] == 1


def test_검색_통과는_신호로_가른다(monkeypatch):
    # 잘린 이름(신호 낮음)은 걸리고, 진짜 이름(신호 높음)은 통과한다.
    점수 = {"터그루트": 2, "안티트로": 42, "맥단비": 52}
    monkeypatch.setattr(shop_probe, "signal", lambda n, **k: 점수.get(n, 0))
    통과, _ = shop_probe.verified(list(점수), pause=0, sleep=lambda *_: None)
    assert set(통과) == {"안티트로", "맥단비"}


def test_검색_못하면_살린다(monkeypatch):
    # 우리가 못 물어봤다고(-1) 남의 브랜드를 지우지 않는다.
    monkeypatch.setattr(shop_probe, "signal", lambda n, **k: -1)
    통과, _ = shop_probe.verified(["무엇이든"], pause=0, sleep=lambda *_: None)
    assert 통과 == ["무엇이든"]


# ── 환각 관문 (2026-07-24): 뽑은 이름이 실제 그 댓글에 있나 ──

def test_원문에_없는_이름은_거른다():
    # AI 가 '안ㅌ티트로' 를 읽다 '아로마티카' 를 연상해 뱉어도, 그 댓글엔 없으니 버린다.
    assert bfc.grounded("안티트로", "이름은 안ㅌ티트로 샴푸인데")
    assert not bfc.grounded("아로마티카", "이름은 안ㅌ티트로 샴푸인데")
    assert not bfc.grounded("려", "맥단ㅂi 탈모샴푸 쓰고 있는데")


def test_흐트러뜨린_표기도_원문으로_인정():
    # '맥단ㅂI' 에서 '맥''단' 이 잡혀 통과한다.
    assert bfc.grounded("맥단비", "맥단ㅂI 탈모샴푸")
    assert bfc.grounded("닥터그루트", "닥터그루트샴푸 말고도 여러개")


def test_한_글자_이름은_버린다():
    assert not bfc.grounded("려", "려 샴푸")   # 우연 매칭 위험


def test_read_batch_가_환각을_거른다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    # AI 가 댓글1엔 맞는 안티트로, 댓글2엔 없는 아로마티카를 뱉는다
    monkeypatch.setattr(bfc, "_post", lambda *a, **k: _reply({"결과": [
        {"n": 1, "제품": ["안티트로"]}, {"n": 2, "제품": ["아로마티카"]}]}))
    got = bfc.read_batch(["안ㅌ티트로 샴푸 써요", "그냥 두피 고민이에요"])
    assert got == {0: ["안티트로"]}      # 근거 없는 아로마티카는 빠진다
