# -*- coding: utf-8 -*-
"""한도(429)와 고장(404 등)을 갈라 센다 — 2026-09-04.

★왜: 차단기가 둘을 똑같이 세고 있었다. 429 는 "잠깐 기다려" 인데 404 는
"영영 안 됨" 이다. 같이 세면 **기다리면 될 일에 그날을 접는다.**
실측(2026-09-04 라이브): 댓글 16,379건 중 810/820 묶음을 못 읽었고 사유가
`HTTP 429` + `연속 5묶음 실패` 였다. 무료 한도는 분 단위로 풀리는데 5번 만에
접어 버려 하루에 10묶음밖에 못 읽었다.

고장은 여전히 빨리 접는다 — 8/19 에 퇴역 모델 404 로 1,304묶음을 헛호출하며
2시간을 태운 사고가 그래서 생긴 차단기다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import brand_from_comments as bfc  # noqa: E402


def _텍스트(n):
    return [f"댓글{i}" for i in range(n)]


def _적기(kw, 사유):
    """사유를 실제 목록에 적는다.

    ★`kw.get("errors") or []` 로 쓰면 **빈 목록이 거짓이라** 새 목록이 만들어져
    사유가 통째로 버려진다. 검사 자신이 조용히 아무것도 안 재게 되는 함정이다.
    """
    목록 = kw.get("errors")
    assert 목록 is not None, "read_all 이 사유 적을 자리를 안 넘겼습니다"
    목록.append(사유)


def test_한도는_고장으로_안_센다(monkeypatch):
    """429 만 계속 나면 5번에 접지 않고 더 버틴다."""
    부른수 = {"n": 0}

    def 가짜(chunk, **kw):
        부른수["n"] += 1
        _적기(kw, "HTTP 429")
        return None

    monkeypatch.setattr(bfc, "read_batch", 가짜)
    _got, stat = bfc.read_all(_텍스트(400), batch=20, sleep=lambda *_: None)
    assert 부른수["n"] > 5, f"429 인데 5번에 접었습니다({부른수['n']}번)"
    assert any("429" in x for x in stat["탈"]), stat["탈"]


def test_진짜_고장은_빨리_접는다(monkeypatch):
    """404 처럼 다시 해도 안 될 것은 5번에 접는다(8/19 사고 재발 방지)."""
    부른수 = {"n": 0}

    def 가짜(chunk, **kw):
        부른수["n"] += 1
        _적기(kw, "HTTP 404")
        return None

    monkeypatch.setattr(bfc, "read_batch", 가짜)
    _got, stat = bfc.read_all(_텍스트(400), batch=20, sleep=lambda *_: None)
    assert 부른수["n"] == 5, f"고장인데 {부른수['n']}번이나 불렀습니다"
    assert any("연속" in x for x in stat["탈"])


def test_한도에도_끝은_있다(monkeypatch):
    """영원히 기다리지는 않는다 — 한도 대기에도 상한이 있다."""
    부른수 = {"n": 0}

    def 가짜(chunk, **kw):
        부른수["n"] += 1
        _적기(kw, "HTTP 429")
        return None

    monkeypatch.setattr(bfc, "read_batch", 가짜)
    bfc.read_all(_텍스트(4000), batch=20, sleep=lambda *_: None)
    assert 부른수["n"] <= 40, f"한도인데 끝없이 부릅니다({부른수['n']}번)"


def test_한도_뒤_성공하면_셈이_풀린다(monkeypatch):
    차례 = {"n": 0}

    def 가짜(chunk, **kw):
        차례["n"] += 1
        if 차례["n"] <= 3:
            _적기(kw, "HTTP 429")
            return None
        return {0: ["안티트로"]}

    monkeypatch.setattr(bfc, "read_batch", 가짜)
    got, stat = bfc.read_all(_텍스트(200), batch=20, sleep=lambda *_: None)
    assert got, "한도가 풀린 뒤에는 읽어야 한다"
    assert stat["못읽은묶음"] == 3


def test_한도면_더_오래_쉰다(monkeypatch):
    """429 는 시간이 지나야 풀린다 — 곧바로 다시 부르면 또 429 다."""
    쉰시간 = []

    def 가짜(chunk, **kw):
        _적기(kw, "HTTP 429")
        return None

    monkeypatch.setattr(bfc, "read_batch", 가짜)
    bfc.read_all(_텍스트(200), batch=20, sleep=lambda s: 쉰시간.append(s))
    assert 쉰시간 and max(쉰시간) >= 10, f"거의 안 쉬었습니다: {쉰시간[:5]}"
