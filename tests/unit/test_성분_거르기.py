# -*- coding: utf-8 -*-
"""성분·약 일반명 거르기 — 제품 브랜드가 아니라 성분·약 이름이 경쟁사에 오른다.

사장님 2026-09-05: "경쟁사 추출한거 보니까 다 이상하다".
실측(data/brand_verdicts.json)에서 제품=true 로 잘못 오른 성분·약을 뺀다.

★사장님 원칙 "확실하지 않으면 빼지 마라 / 데이터 쌓이면 알게 된다" 를 지킨다 —
  브랜드로도 팔리는 애매한 것(판테놀·큐텐)은 넣지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import collect_comment_brands as C  # noqa: E402
from src import comment_brand_llm as L  # noqa: E402

# 실측(brand_verdicts)에서 제품=true 로 잘못 오른 명백한 일반 성분·약.
명백한_성분 = ["케라틴", "호호바", "티트리", "티트리오일", "징크피리치온", "유황", "칼라민"]


def test_명백한_성분은_경쟁사가_아니다():
    for x in 명백한_성분:
        assert not C.is_real_brand(x), f"{x} 은 일반 성분·약이라 경쟁 제품이 아니다"


def test_애매한_것은_빼지_않는다():
    """판테놀·큐텐은 제품명으로도 팔릴 수 있다 — 확실하지 않으면 빼지 않는다."""
    막힌것 = {C.normalize_name(x) for x in C.NOT_A_BRAND}
    assert C.normalize_name("판테놀") not in 막힌것
    assert C.normalize_name("큐텐") not in 막힌것


def test_진짜_브랜드는_그대로_통과한다():
    assert C.is_real_brand("안티트로")
    assert C.is_real_brand("더마렉신")


def test_판정기_지침에_성분이_적혀_있다():
    """판정기(LLM)도 성분을 제품=false 로 거르도록 지침에 적는다."""
    for x in ["케라틴", "호호바", "징크피리치온"]:
        assert x in L._SYSTEM, f"판정 지침에 {x} 가 없다"
