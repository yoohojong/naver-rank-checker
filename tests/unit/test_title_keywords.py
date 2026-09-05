# -*- coding: utf-8 -*-
"""제목 → 검색 키워드 판정(LLM). 가짜 LLM 응답으로 검사한다.

LLM 통로는 comment_brand_llm 것을 그대로 쓴다(새 통로를 만들지 않는다).
여기서는 그 통로에 넣을 판정 규칙과 응답 읽기를 검사한다.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import title_keywords as T  # noqa: E402


def _가짜call(제목별키워드: dict):
    """comment_brand_llm._call 모양의 가짜 — user 에 실린 제목을 읽어
    미리 정한 키워드를 JSON 으로 돌려준다. (content, 잘렸는지) 를 준다.
    """
    def call(system, user, *, max_tokens, timeout, sleep=None, errors=None):
        rows = []
        for line in user.splitlines():
            m = re.match(r"\s*(\d+)\.\s(.*)", line)
            if not m:
                continue
            n, 제목 = int(m.group(1)), m.group(2)
            rows.append({"n": n, "제목": 제목,
                         "키워드": list(제목별키워드.get(제목, []))})
        return json.dumps({"제목별": rows}, ensure_ascii=False), False
    return call


def test_제목마다_키워드를_돌려준다():
    call = _가짜call({
        "지루성 두피염 약국 가서 겨우 해결했네요 ㅠㅠ": ["지루성 두피염"],
        "등 여드름 미스트 추천": ["등 여드름"],
    })
    got = T.extract_keywords(
        ["지루성 두피염 약국 가서 겨우 해결했네요 ㅠㅠ", "등 여드름 미스트 추천"],
        call=call)
    assert got["지루성 두피염 약국 가서 겨우 해결했네요 ㅠㅠ"] == ["지루성 두피염"]
    assert got["등 여드름 미스트 추천"] == ["등 여드름"]


def test_잡음은_빈_목록으로_온다():
    call = _가짜call({
        "육아,커뮤니티": [],
        "머릿결이 뻣뻣한": [],
        "지루성 두피염 해결": ["지루성 두피염"],
    })
    got = T.extract_keywords(["육아,커뮤니티", "머릿결이 뻣뻣한", "지루성 두피염 해결"],
                             call=call)
    assert got["육아,커뮤니티"] == []
    assert got["머릿결이 뻣뻣한"] == []
    assert got["지루성 두피염 해결"] == ["지루성 두피염"]


def test_키워드는_많아야_두개():
    call = _가짜call({"제목": ["가", "나", "다", "라"]})
    got = T.extract_keywords(["제목"], call=call)
    assert len(got["제목"]) == 2


def test_같은_제목은_한_번만_묻는다():
    본제목 = []

    def call(system, user, *, max_tokens, timeout, sleep=None, errors=None):
        for line in user.splitlines():
            m = re.match(r"\s*\d+\.\s(.*)", line)
            if m:
                본제목.append(m.group(1))
        return json.dumps({"제목별": []}, ensure_ascii=False), False

    T.extract_keywords(["같은 제목", "같은 제목", "다른 제목"], call=call)
    assert 본제목.count("같은 제목") == 1
    assert "다른 제목" in 본제목


def test_열쇠가_없으면_빈_결과():
    """call 을 안 주면 진짜 통로를 쓰는데, 열쇠가 없으면 빈 dict 로 물러난다."""
    import src.comment_brand_llm as L
    실제 = L.available
    L.available = lambda: False
    try:
        assert T.extract_keywords(["아무 제목"]) == {}
    finally:
        L.available = 실제


def test_빈_입력은_빈_결과():
    assert T.extract_keywords([]) == {}
    assert T.extract_keywords(["", "  "]) == {}


def test_뭉뚱한_한낱말은_버리되_붙은말은_살린다():
    """★2026-09-06 실물 미리보기에서 '병원' 하나가 새어 나왔다. 낱말 하나만 오면 버리고,
    증상·부위와 붙은 것(두피염 병원)은 살린다."""
    import json
    from src import title_keywords as T
    def fake(system, user, **kw):
        return json.dumps({"제목별": [
            {"n": 1, "제목": "지루성 두피염 병원", "키워드": ["지루성 두피염", "병원"]},
            {"n": 2, "제목": "두피염 병원 추천", "키워드": ["두피염 병원", "추천", "병원"]},
        ]}), False
    r = T.extract_keywords(["지루성 두피염 병원", "두피염 병원 추천"], call=fake)
    assert r["지루성 두피염 병원"] == ["지루성 두피염"], r
    assert r["두피염 병원 추천"] == ["두피염 병원"], r   # 병원·추천 낱말은 빠짐
