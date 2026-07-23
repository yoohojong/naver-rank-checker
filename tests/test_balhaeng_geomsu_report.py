# -*- coding: utf-8 -*-
"""발행 검수 보고문·종료코드 회귀 테스트.

이 판단들은 사장님이 받는 텔레그램 문구를 그대로 결정한다. 전에는 검사가 0개라
'전건 보류인데 이유가 (?)인 경고'·'고쳐야 함 0인데 목록엔 5건' 같은 것이 그냥 나갔다.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _모듈():
    """curl_cffi·검수기 없이 순수 함수만 불러온다(네트워크·시트 접근 없음)."""
    sys.modules.setdefault("curl_cffi", types.SimpleNamespace(requests=None))
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "geomsu", ROOT / "scripts" / "balhaeng_geomsu.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _모듈()


def 글(키워드, 판정, 치명=(), 주의=(), 작업자=""):
    지적 = ([{"등급": "치명", "내용": c} for c in 치명]
            + [{"등급": "주의", "내용": w} for w in 주의])
    return ({"keyword": 키워드, "작업자": 작업자, "url": f"u/{키워드}"},
            {"판정": 판정, "지적": 지적})


def 요약(결과들, 실패들=(), 건너뜀=(), 시간초과=(), 시트오류=""):
    return {"결과들": list(결과들), "실패들": list(실패들), "건너뜀": list(건너뜀),
            "시간초과": list(시간초과), "시트오류": 시트오류,
            "수": Counter(r["판정"] for _, r in 결과들)}


def test_머리줄_숫자가_아래_목록과_어긋나지_않는다():
    """'고쳐야 함 0' 이라 써 놓고 목록에 5건을 늘어놓던 오류."""
    본문 = G.보고문(요약([글(f"k{i}", "보류", 주의=["감정자음"]) for i in range(5)]), "")
    assert "고쳐야 함 0" in 본문
    assert "고쳐야 할 글" not in 본문
    assert "사람이 한번 봐야 할 글" in 본문


def test_전건_보류면_같은이유_경고를_내지_않는다():
    """치명이 0건이라 사유 집합이 비는데 '전부 같은 이유(?)'라고 단정하던 오탐."""
    본문 = G.보고문(요약([글(f"k{i}", "보류", 주의=["감정자음"]) for i in range(6)]), "")
    assert "같은 이유로 걸렸습니다" not in 본문


def test_불합격과_보류가_섞이면_같은이유_경고를_내지_않는다():
    결과 = ([글(f"a{i}", "불합격", 치명=["글자수: 400 (기준 520~870)"]) for i in range(4)]
            + [글("b", "보류", 주의=["감정자음"])])
    assert "같은 이유로 걸렸습니다" not in G.보고문(요약(결과), "")


def test_전건이_한_이유로_불합격이면_기준을_의심하라고_알린다():
    결과 = [글(f"a{i}", "불합격", 치명=["글자수: 400 (기준 520~870)"]) for i in range(5)]
    본문 = G.보고문(요약(결과), "")
    assert "같은 이유로 걸렸습니다" in 본문 and "글자수" in 본문


def test_이유가_여럿이면_기준_의심_경고는_없다():
    결과 = [글("a", "불합격", 치명=["글자수: 400 (기준 520~870)"]),
            글("b", "불합격", 치명=["댓글 [6] 금칙어 — 대학병원+피부과 붙여쓰기"]),
            글("c", "불합격", 치명=["줄: 40 (기준 17~34)"]),
            글("d", "불합격", 치명=["글자수: 401 (기준 520~870)"]),
            글("e", "불합격", 치명=["[제품명] 을 안 바꿈"])]
    assert "같은 이유로 걸렸습니다" not in G.보고문(요약(결과), "")


def test_작업자가_비어도_공백이_두칸_되지_않는다():
    본문 = G.보고문(요약([글("두피염", "불합격", 치명=["글자수"])]), "")
    assert "· 두피염 — 글자수" in 본문


def test_작업자가_있으면_이름이_보인다():
    본문 = G.보고문(요약([글("두피염", "불합격", 치명=["글자수"], 작업자="이한별")]), "")
    assert "· 두피염 (이한별) — 글자수" in 본문


def test_검사_못한_것들이_보고에서_사라지지_않는다():
    본문 = G.보고문(요약([글("a", "합격")], 실패들=[{"keyword": "x"}],
                        건너뜀=[("탭", "y")] * 3, 시간초과=[{}] * 7), "")
    assert "글을 못 읽은 것 1건" in 본문
    assert "검사 못 한 글 3건" in 본문
    assert "시간이 모자라 못 본 글 7건" in 본문


def test_시트에_못_썼으면_보고에_적힌다():
    본문 = G.보고문(요약([글("a", "합격")], 시트오류="권한이 없습니다"), "")
    assert "시트에 쓰지 못했습니다" in 본문 and "권한이 없습니다" in 본문


def test_전부_통과하면_그렇게_말한다():
    본문 = G.보고문(요약([글("a", "합격"), 글("b", "합격")]), "")
    assert "고칠 글 없음" in 본문


def test_긴_목록은_열두건까지만_보이고_나머지는_건수로():
    결과 = [글(f"k{i}", "불합격", 치명=[f"이유{i}"]) for i in range(30)]
    본문 = G.보고문(요약(결과), "")
    assert "외 18건" in 본문


@pytest.mark.parametrize("값,기대", [("", 60), ("12", 12), ("이상한값", 60), ("0", 60)])
def test_숫자칸이_이상해도_죽지_않는다(값, 기대, monkeypatch):
    monkeypatch.setenv("GEOMSU_LIMIT", 값)
    assert G._숫자("GEOMSU_LIMIT", 60) == (기대 if 값 != "0" else 1)


def test_사람말로_흔한고장을_한국어로_바꾼다():
    assert "GitHub Secrets" in G.사람말로(KeyError("SPREADSHEET_ID"))
    assert "서비스 계정" in G.사람말로(Exception("403 PERMISSION_DENIED"))


def test_알림_발송이_실패하면_거짓을_돌려준다(monkeypatch):
    """토큰 만료를 눈치 못 채고 매일 초록불로 끝나던 구멍."""
    가짜 = types.SimpleNamespace(
        send_telegram=lambda t: False,
        split_message=lambda t: [t],
        PER_CHAT_INTERVAL_SEC=0)
    monkeypatch.setitem(sys.modules, "src.notify", 가짜)
    assert G.알림보내기("아무거나") is False


def test_알림_한통이라도_가면_참이다(monkeypatch):
    가짜 = types.SimpleNamespace(
        send_telegram=lambda t: True,
        split_message=lambda t: [t, t],
        PER_CHAT_INTERVAL_SEC=0)
    monkeypatch.setitem(sys.modules, "src.notify", 가짜)
    assert G.알림보내기("아무거나") is True
