# -*- coding: utf-8 -*-
"""경쟁 제품 추출 — 실물에서 잘못 잡힌 것들을 그대로 잠근다.

2026-07-23 시트 '경쟁사' 에 이런 게 경쟁 제품으로 올라갔다:
    약국에서(30회) · 못할정도였는데 샴푸(30회) · 꾸준히 · 공감 · 지금 · 제품 · 있는데 · 바디 워시
아래 테스트는 그 문장들을 원문 그대로 넣는다. 다시 새면 여기서 걸린다.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.collect_comment_brands import (  # noqa: E402
    build_table, candidates_from_title, confirmed_rows, should_skip_write)
from src import brand_verdicts, comment_brand_llm  # noqa: E402
from src.comment_brand import (  # noqa: E402
    extract_candidates, is_inflected, looks_like_candidate, normalize_name)


def keys(text):
    return {k for _, k, _ in extract_candidates(text)}


# 실물 댓글 원문 (2026-07-23 시트 '댓글 예시' 열에서 그대로 가져옴)
쓰레기_실물 = [
    ("ㅃ,얀 샴푸 진짜 좋아요 저는 동네 약국에서 추천해줘서 바꾸고 1달만에 나았네요.", "약국에서"),
    ("방심하면 도로 올라오긴 해서 꾸준히 쓰는 게 중요하더라구요", "꾸준히"),
    ("처음엔 괜찮다가 다시 가려워지는 거 공감이요  샴푸 유목민 생활 너무 오래 했어요", "공감"),
    ("두피균클렌저가 어떤걸까요???..제품 추천도 해주세요ㅠㅠㅠㅠ", "제품"),
    ("조카가 아토피 있는데 이거 쓰는거 같긴 하더라구요", "있는데"),
    ("겉피부 각질만 녹이는 일반 샴푸들이랑 다르게 못할정도였는데 샴푸", "못할정도였는데"),
    ("지성 두피라서 오후만 되면 기름 돌고 떡지는 느낌이 금방 올라와서 샴푸를 바꿔봤어요", "올라와서"),
    ("저도 샴푸 유목민 생활 1년 넘게 했어요. 두피 당기기 시작하면 샴푸 바꿀 시기 같더라고요", "시작하면"),
    ("요즘 두피가 예민해져서 샴푸 바꾸는 것도 겁났는데", "예민해져서"),
    ("맥단ㅂi 탈모샴푸 4개씩 쟁겨놓고 쓰고있어요", "쟁겨놓고"),
]


@pytest.mark.parametrize("text,junk", 쓰레기_실물)
def test_문장조각은_후보가_아니다(text, junk):
    assert junk not in keys(text), f"'{junk}' 가 다시 제품 후보로 잡혔다"


def test_종류_이름은_제품이_아니다():
    for word in ("샴푸", "탈모샴푸", "바디워시", "지루성두피염샴푸", "치료용", "바디"):
        assert not looks_like_candidate(word), f"'{word}' 는 브랜드가 아니라 종류다"


def test_바디워시_앞의_브랜드가_살아남는다():
    # 전에는 '워시' 가 '바디워시' 보다 먼저 잡혀 '바디' 만 남고 브랜드가 사라졌다.
    assert "다시꽃" in keys("지금은 다시꽃 바디워시를 사용하고 있습니다")
    assert "바디" not in keys("지금은 다시꽃 바디워시를 사용하고 있습니다")


def test_진짜_브랜드는_계속_잡힌다():
    assert "닥터이노브" in keys("저는 닥터이노브 쓰고 있어요. 지성 두피라서요")
    assert "니조랄" in keys("저는 니조랄 샴푸 쓰다가 요즘은 다른 거 알아보는 중이에요")
    assert "맥단" in keys("맥단ㅂi탈모샴푸 쓰는데 식약처 인증 제품이라서 믿고 써요")
    assert "아윤채" in keys("아윤채는요?")


def test_글자_숨긴_이름을_잡는다():
    # 실물(2026-07-23): 안티트로는 매번 다르게 글자를 흐트러뜨린다. 다섯 표기가 한 이름으로 모여야 한다.
    실물 = [
        "안티ㅣ트로 샴푸라고 하고 병원보단 온라인이 더싸요!",
        "이름은 안티트ㅡ로 샴푸인데(문제 생길까봐 곧 펑할게요)",
        "안ㅌ티트로 저도 남편이랑 피부과 추천으로 사용중인데",
        "안티트ㄹ로 저도 언니네랑 피부과 추천으로 사용중인데",
    ]
    for t in 실물:
        assert "안티트로" in keys(t), f"못 잡음: {t[:20]}"


def test_별표로_가린_이름도_잡는다():
    assert "안티트" in keys("윗분 말씀하신 안티트* 샴푸 남편이랑 같이 사용중인데")


def test_흐트러진_표기를_정식_브랜드명_한개로_묶는다():
    # 사장님 요구(2026-07-23): "본질적으로 어떤 브랜드인지 파악해서 브랜드명 한개만 남겨서".
    mentions = [
        {"표시": "안티트", "키": "안티트", "종류": "제품", "댓글": "안티트* 샴푸 써요", "키워드": "두피여드름"},
        {"표시": "안티ㅣ트로", "키": "안티트로", "종류": "샴푸", "댓글": "안티ㅣ트로 샴푸요", "키워드": "두피각질"},
        {"표시": "안ㅌ티트로", "키": "안티트로", "종류": "제품", "댓글": "안ㅌ티트로 쓰는데", "키워드": "두피각질"},
    ]
    verdicts = {"안티트": {"제품": True, "이름": "안티트"},
                "안티트로": {"제품": True, "이름": "안티트로샴푸"}}
    unified = {"안티트": "안티트로", "안티트로샴푸": "안티트로"}
    rows = confirmed_rows(mentions, verdicts, unified)
    assert len(rows) == 1
    assert rows[0]["제품"] == "안티트로" and rows[0]["횟수"] == 3 and rows[0]["키워드수"] == 2


def test_이름묶기_결과에_없는_이름은_무시(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    reply = {"choices": [{"message": {"content": json.dumps(
        {"묶음": [{"대표": "안티트로", "별칭": ["안티트", "듣도보도못한것"]}]}, ensure_ascii=False)}}]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: reply)
    got = comment_brand_llm.unify(["안티트", "안티트로", "맥단비"])
    assert got["안티트"] == "안티트로"
    assert "듣도보도못한것" not in got      # 지어낸 이름은 버린다


def test_기호로_흐트러뜨린_것도_모인다():
    # '뽀.ㅇ얀' 이 '뽀얀' 으로 모여야 우리 제품 빼기가 샌 곳 없이 걸린다.
    assert "뽀얀" in keys("저는 뽀.ㅇ얀샴푸 써요")


def test_브랜드_끝_글자를_조사로_먹지_않는다():
    # '안티ㅣ트로 샴푸' 의 '로' 를 조사로 알고 떼면 '안티트' 가 된다.
    assert "안티트" not in keys("안티ㅣ트로 샴푸 쓰는 중이에요")


def test_활용형_꼬리_판별():
    for w in ("약국에서", "있는데", "꾸준히", "올라와서", "비슷하다고", "어떨까", "좋네요"):
        assert is_inflected(w), f"'{w}' 는 활용형이다"
    for w in ("닥터이노브", "니조랄", "다시꽃", "센카", "루미퓸", "아크시톨"):
        assert not is_inflected(w), f"'{w}' 는 브랜드인데 활용형으로 걸렸다"


def test_흐트러뜨린_글자_정리는_그대로():
    assert normalize_name("모zi젠") == "모젠"
    assert normalize_name("뽀ㅇ얀") == "뽀얀"


# ── 판정 없으면 표에 넣지 않는다 (이번 사고의 핵심) ──────────────────────────

def test_판정_못받은_후보는_표에_없다():
    mentions = [{"표시": "약국에서", "키": "약국에서", "종류": "제품", "댓글": "동네 약국에서 추천"},
                {"표시": "닥터이노브", "키": "닥터이노브", "종류": "제품", "댓글": "닥터이노브 써요"}]
    assert confirmed_rows(mentions, {}) == []          # 판정표가 비면 표도 빈다


def test_판정된_제품만_표에_들어간다():
    mentions = [{"표시": "약국에서", "키": "약국에서", "종류": "제품", "댓글": "동네 약국에서 추천"},
                {"표시": "닥터이노브", "키": "닥터이노브", "종류": "제품", "댓글": "닥터이노브 써요"}]
    verdicts = {"약국에서": {"제품": False, "이름": ""},
                "닥터이노브": {"제품": True, "이름": "닥터이노브"}}
    rows = confirmed_rows(mentions, verdicts)
    assert [r["제품"] for r in rows] == ["닥터이노브"]


def test_같은_브랜드는_한_줄로_모인다():
    # '맥단' 과 '맥단탈모샴푸' 는 판정에서 둘 다 '맥단비' 다 — 표에 두 줄로 남으면 안 된다.
    mentions = [{"표시": "맥단ㅂi", "키": "맥단", "종류": "샴푸", "댓글": "맥단ㅂi 써요", "키워드": "탈모샴푸"},
                {"표시": "맥단탈모샴푸", "키": "맥단탈모샴푸", "종류": "샴푸", "댓글": "맥단 탈모샴푸요",
                 "키워드": "비듬샴푸"}]
    verdicts = {"맥단": {"제품": True, "이름": "맥단비"},
                "맥단탈모샴푸": {"제품": True, "이름": "맥단비"}}
    rows = confirmed_rows(mentions, verdicts)
    assert len(rows) == 1
    assert rows[0]["제품"] == "맥단비" and rows[0]["횟수"] == 2 and rows[0]["키워드수"] == 2


def test_우리_제품은_판정된_이름으로도_빠진다():
    # 판정이 엉뚱한 후보에 우리 이름을 달아도('스테로이드'→'뽀얀') 경쟁 표에 들어가면 안 된다.
    mentions = [{"표시": "스테로이드", "키": "스테로이드", "종류": "제품", "댓글": "스테로이드 연고도 써봤는데"}]
    assert confirmed_rows(mentions, {"스테로이드": {"제품": True, "이름": "뽀얀"}}) == []


def test_판정이_뚫려도_종류_이름은_막힌다():
    mentions = [{"표시": "샴푸", "키": "샴푸", "종류": "제품", "댓글": "샴푸 써요"}]
    assert confirmed_rows(mentions, {"샴푸": {"제품": True, "이름": "샴푸"}}) == []


def test_댓글_반이상_못읽으면_시트를_덮지_않는다():
    # ★새 구조(2026-07-24): 막는 잣대 = 못 읽은 묶음 / 검색 막힘 비율.
    assert should_skip_write({"묶음": 10, "못읽은묶음": 8, "확정제품": 5}) is True
    assert should_skip_write({"묶음": 10, "못읽은묶음": 1, "확정제품": 5}) is False


def test_검색_반이상_막히면_무검증이라_덮지_않는다():
    # 네이버가 대량 차단 → verified 가 무검증으로 다 통과 → 그런 표는 안 덮는다.
    assert should_skip_write({"검색확인": 20, "검색막힘": 18, "확정제품": 5}) is True
    assert should_skip_write({"검색확인": 20, "검색막힘": 2, "확정제품": 5}) is False


def test_확정이_하나도_없으면_덮지_않는다():
    assert should_skip_write({"언급": 300, "확정제품": 0}) is True
    assert should_skip_write({"언급": 300, "확정제품": 12}) is False


def test_돌릴게_없던_run_은_정상():
    assert should_skip_write({}) is False
    assert should_skip_write({"묶음": 0, "언급": 0}) is False


# ── 한 탭에 다 담기 (사장님 2026-07-24: "여러개로 나누지 말고 아예 한 시트에") ──────

def _today_row(brand="안티트로", n=12, product="샴푸"):
    return {"제품군": product, "경쟁사": brand, "횟수": n, "키워드수": 3,
            "키워드들": ["두피각질", "두피여드름", "비듬샴푸"],
            "글들": ["https://cafe.naver.com/a/1", "https://cafe.naver.com/b/2"],
            "댓글 예시": "안ㅌ티트로 쓰는데 좋아요"}


def test_한_탭에_경쟁사_한_줄로_담긴다():
    table = build_table([], [_today_row()], "2026-07-24")
    head, row = table[0], table[1]
    assert head[:4] == ["제품군", "경쟁사", "최근7일 합계", "추세"]
    assert "2026-07-24" in head                      # 날짜가 열로 펼쳐진다
    assert head[-4:] == ["나온 키워드 수", "나온 키워드", "글 링크", "댓글 예시"]
    assert row[1] == "안티트로" and row[2] == 12 and row[3] == "신규"
    assert "두피각질" in row[head.index("나온 키워드")]
    assert row[head.index("글 링크")].count("http") == 2


def test_어제_기록_위에_오늘을_얹는다():
    어제표 = build_table([], [_today_row(n=8)], "2026-07-23")
    오늘표 = build_table(어제표, [_today_row(n=12)], "2026-07-24")
    head, row = 오늘표[0], 오늘표[1]
    assert row[head.index("2026-07-24")] == 12
    assert row[head.index("2026-07-23")] == 8        # 어제 값이 살아 있다
    assert row[2] == 20                              # 합계
    assert row[3] == "▲ +4"                          # 늘었다


def test_줄었으면_내림표시_안나오면_표에서_내린다():
    어제표 = build_table([], [_today_row(n=10), _today_row("맥단비", 5)], "2026-07-23")
    오늘표 = build_table(어제표, [_today_row(n=3)], "2026-07-24")
    head = 오늘표[0]
    brands = {r[1]: r for r in 오늘표[1:]}
    assert brands["안티트로"][3] == "▼ -7"
    assert brands["맥단비"][head.index("2026-07-24")] == 0   # 오늘은 0, 기록은 남는다


def test_이레_넘게_안나오면_표에서_사라진다():
    표 = build_table([], [_today_row(n=4)], "2026-07-01")
    for day in range(2, 10):
        표 = build_table(표, [], f"2026-07-{day:02d}")
    assert len(표) == 1                               # 머리줄만 남는다


# ── 판정 저장 ───────────────────────────────────────────────────────────────

def test_사장님_판정은_LLM이_못_덮는다(tmp_path):
    path = str(tmp_path / "v.json")
    cached = {"다시꽃": {"제품": True, "이름": "다시꽃", "판정": brand_verdicts.HUMAN,
                       "판정일": "2026-07-23"}}
    merged = brand_verdicts.merge(cached, {"다시꽃": {"제품": False, "이름": ""}},
                                  today="2026-07-24")
    assert merged["다시꽃"]["제품"] is True
    assert brand_verdicts.save(merged, path)
    assert json.loads(Path(path).read_text(encoding="utf-8"))["다시꽃"]["판정"] == brand_verdicts.HUMAN


def test_판정파일_없으면_빈것으로_시작(tmp_path):
    assert brand_verdicts.load(str(tmp_path / "없다.json")) == {}


# ── 언어모델 판정 ───────────────────────────────────────────────────────────

def test_키_없으면_전부_미판정(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    got, stat = comment_brand_llm.judge([{"키": "닥터이노브", "표시": "닥터이노브", "예시": ""}])
    assert got == {} and stat["미판정"] == 1        # 지어내지 않는다


def test_판정_결과_읽기(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    reply = {"choices": [{"message": {"content": json.dumps(
        {"판정": [{"n": 1, "제품": True, "이름": "맥단비"}, {"n": 2, "제품": False}]},
        ensure_ascii=False)}}]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: reply)
    items = [{"키": "맥단", "표시": "맥단ㅂi", "예시": "맥단ㅂi 탈모샴푸 써요"},
             {"키": "약국에서", "표시": "약국에서", "예시": "동네 약국에서 추천해줘서"}]
    got, stat = comment_brand_llm.judge(items)
    assert got["맥단"] == {"제품": True, "이름": "맥단비"}
    assert got["약국에서"]["제품"] is False
    assert stat["미판정"] == 0


def test_번호가_밀리면_후보_글자로_바로잡는다(monkeypatch):
    # 실측(2026-07-23): 번호가 밀려 '스테로이드' 가 옆 후보의 이름('뽀얀')을 달고 제품이 됐다.
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    reply = {"choices": [{"message": {"content": json.dumps(
        {"판정": [{"n": 1, "후보": "일리윤", "제품": True, "이름": "일리윤"},
                 {"n": 2, "후보": "스테로이드", "제품": False}]}, ensure_ascii=False)}}]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: reply)
    items = [{"키": "스테로이드", "표시": "스테로이드", "예시": "스테로이드 연고"},
             {"키": "일리윤", "표시": "일리윤", "예시": "일리윤 바디워시"}]
    got, _ = comment_brand_llm.judge(items)
    assert got["일리윤"]["제품"] is True
    assert got["스테로이드"]["제품"] is False       # 번호가 아니라 이름으로 맞춰졌다


def test_모르는_후보_판정은_버린다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    reply = {"choices": [{"message": {"content": json.dumps(
        {"판정": [{"n": 1, "후보": "듣도보도못한것", "제품": True, "이름": "가짜"}]},
        ensure_ascii=False)}}]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: reply)
    got, stat = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got == {} and stat["미판정"] == 1


def test_답이_잘려도_읽히는_줄은_건진다(monkeypatch):
    # 답이 길어 잘리면 JSON 이 깨진다. 묶음 통째로 버리지 말고 온전한 줄은 살린다.
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    잘린답 = ('{"판정": [{"n":1,"후보":"일리윤","제품":true,"이름":"일리윤"},'
            ' {"n":2,"후보":"약국에')
    monkeypatch.setattr(comment_brand_llm, "_post",
                        lambda *a, **k: {"choices": [{"message": {"content": 잘린답}}]})
    items = [{"키": "일리윤", "표시": "일리윤", "예시": ""},
             {"키": "약국에서", "표시": "약국에서", "예시": ""}]
    got, stat = comment_brand_llm.judge(items)
    assert got["일리윤"]["제품"] is True
    assert "약국에서" not in got and stat["미판정"] == 1


def test_답_못받은_후보는_다시_묻는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return None                     # 첫 묶음 실패
        return {"choices": [{"message": {"content": json.dumps(
            {"판정": [{"n": 1, "후보": "일리윤", "제품": True, "이름": "일리윤"}]},
            ensure_ascii=False)}}]}

    monkeypatch.setattr(comment_brand_llm, "_post", fake_post)
    got, stat = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got["일리윤"]["제품"] is True     # 두 번째 바퀴에서 받아냈다
    assert stat["미판정"] == 0 and calls["n"] == 2


def test_한도초과면_기다렸다_다시_묻는다(monkeypatch):
    import urllib.error

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    calls, waited = {"n": 0}, []

    class _Resp:
        def __init__(self, data):
            self._d = data.encode("utf-8")

        def read(self):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                "u", 429, "too many", {"retry-after": "7"}, None)
        return _Resp(json.dumps({"choices": [{"message": {"content": '{"판정":[]}'}}]}))

    monkeypatch.setattr(comment_brand_llm.urllib.request, "urlopen", fake_urlopen)
    out = comment_brand_llm._post({}, timeout=1, sleep=waited.append)
    assert calls["n"] == 2 and waited == [7.0]      # 알려준 만큼 쉬고 다시
    assert out is not None


# ── 유료 판정기(Anthropic) ─────────────────────────────────────────────────

def _유료판정기_대신(monkeypatch, 답=None, stop_reason="end_turn"):
    """anthropic 꾸러미의 손님(Anthropic)만 가짜로 바꾼다 → 부른 횟수를 돌려준다."""
    import anthropic

    부른횟수 = {"n": 0}

    class _블록:
        type = "text"

        def __init__(self, text):
            self.text = text

    class _답:
        def __init__(self):
            self.content = [_블록(답 or "")]
            self.stop_reason = stop_reason

    class _메시지:
        def create(self, **kwargs):
            부른횟수["n"] += 1
            return _답()

    class _손님:
        def __init__(self, **kw):
            self.messages = _메시지()

    monkeypatch.setattr(anthropic, "Anthropic", _손님)
    return 부른횟수


def test_유료_열쇠가_있으면_유료로_판정한다(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-paid")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    부른횟수 = _유료판정기_대신(monkeypatch, 답=json.dumps(
        {"판정": [{"n": 1, "후보": "맥단비", "제품": True, "이름": "맥단비"}]},
        ensure_ascii=False))
    got, stat = comment_brand_llm.judge(
        [{"키": "맥단비", "표시": "맥단비", "예시": "맥단비 샴푸 써요"}])
    assert got["맥단비"] == {"제품": True, "이름": "맥단비"}
    assert stat["미판정"] == 0 and 부른횟수["n"] == 1


def test_무료가_못하면_유료로_넘어간다(monkeypatch):
    # 무료가 하루 한도에 걸려도 유료가 받쳐주면 그 날 표는 채워진다.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-paid")
    monkeypatch.setenv("GROQ_API_KEY", "test-free")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: None)   # 무료 실패
    _유료판정기_대신(monkeypatch, 답=json.dumps(
        {"판정": [{"n": 1, "후보": "일리윤", "제품": True, "이름": "일리윤"}]},
        ensure_ascii=False))
    got, stat = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got["일리윤"]["제품"] is True and stat["미판정"] == 0


def test_무료로_되는_날은_유료를_부르지_않는다(monkeypatch):
    # ★순서가 곧 돈이다 — 무료가 답하면 유료 호출은 0이어야 한다.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-paid")
    monkeypatch.setenv("GROQ_API_KEY", "test-free")
    부른횟수 = _유료판정기_대신(monkeypatch, 답="{}")
    reply = {"choices": [{"message": {"content": json.dumps(
        {"판정": [{"n": 1, "후보": "일리윤", "제품": True, "이름": "일리윤"}]},
        ensure_ascii=False)}}]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: reply)
    got, _ = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got["일리윤"]["제품"] is True
    assert 부른횟수["n"] == 0                      # 돈 쓰지 않았다


def test_유료_답이_잘려도_읽히는_줄은_건진다(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-paid")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    잘린답 = ('{"판정": [{"n":1,"후보":"일리윤","제품":true,"이름":"일리윤"},'
            ' {"n":2,"후보":"약국에')
    _유료판정기_대신(monkeypatch, 답=잘린답, stop_reason="max_tokens")
    got, stat = comment_brand_llm.judge(
        [{"키": "일리윤", "표시": "일리윤", "예시": ""},
         {"키": "약국에서", "표시": "약국에서", "예시": ""}])
    assert got["일리윤"]["제품"] is True
    assert "약국에서" not in got                   # 못 받은 건 지어내지 않는다
    assert stat["미판정"] == 1


def test_유료가_답하지_않으면_지어내지_않는다(monkeypatch):
    # 안전 판정으로 답을 거절하면(stop_reason=refusal) 빈칸으로 둔다.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-paid")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _유료판정기_대신(monkeypatch, 답="", stop_reason="refusal")
    got, stat = comment_brand_llm.judge([{"키": "일리윤", "표시": "일리윤", "예시": ""}])
    assert got == {} and stat["미판정"] == 1


# ── 상위노출 차지 (사장님 2026-07-23: "상위노출된 경쟁사 리스트업 + 횟수 체크") ──

def test_상위_구좌_글_제목에서_경쟁사를_뽑는다():
    got = candidates_from_title("맥단비 탈모샴푸 3개월 후기")
    assert any("맥단비" in c["표시"] for c in got)
    assert candidates_from_title("") == []


def test_상위노출_차지_횟수와_우리가_놓친_키워드를_센다():
    mentions = [
        # 같은 브랜드가 두 키워드의 상위 구좌를 차지했고, 그중 하나는 우리 글이 아예 없다.
        {"표시": "맥단비", "키": "맥단비", "종류": "제품", "댓글": "맥단비 탈모샴푸 후기",
         "키워드": "비듬샴푸", "원천": "상위노출", "우리놓침": True},
        {"표시": "맥단비", "키": "맥단비", "종류": "제품", "댓글": "맥단비 샴푸 써봄",
         "키워드": "두피각질", "원천": "상위노출", "우리놓침": False},
        # 댓글에서 나온 언급은 '상위노출 차지' 로 세지 않는다.
        {"표시": "맥단비", "키": "맥단비", "종류": "제품", "댓글": "맥단비 써요",
         "키워드": "지루성두피", "원천": "댓글", "우리놓침": True},
    ]
    rows = confirmed_rows(mentions, {"맥단비": {"제품": True, "이름": "맥단비"}})
    assert len(rows) == 1
    assert rows[0]["횟수"] == 1        # 날짜 열의 재료 = 댓글 언급만
    assert rows[0]["상위노출"] == 2    # 상위 구좌를 차지한 키워드 수
    assert rows[0]["놓친"] == 1        # 그중 우리 글이 아예 없던 키워드


def test_상위노출_열이_표에_들어간다():
    table = build_table([], [{**_today_row(), "상위노출": 4, "놓친": 3}], "2026-07-24")
    head, row = table[0], table[1]
    assert row[head.index("상위노출 차지")] == 4
    assert row[head.index("우리가 놓친")] == 3


def test_제목_언급은_횟수에_섞이지_않는다():
    # 날짜 열·추세의 재료인 '횟수' 에 제목까지 섞으면, 아무 일도 없었는데 "▲ 늘었다" 가 된다.
    mentions = [
        {"표시": "맥단비", "키": "맥단비", "종류": "제품", "댓글": "맥단비 써요",
         "키워드": "비듬샴푸", "원천": "댓글", "우리놓침": False},
        {"표시": "맥단비", "키": "맥단비", "종류": "제품", "댓글": "맥단비 탈모샴푸 후기",
         "키워드": "두피각질", "원천": "상위노출", "우리놓침": True},
    ]
    rows = confirmed_rows(mentions, {"맥단비": {"제품": True, "이름": "맥단비"}})
    assert rows[0]["횟수"] == 1          # 댓글만
    assert rows[0]["상위노출"] == 1      # 제목은 이쪽 열로만


def test_댓글에_없어도_상위_구좌를_차지하면_표에_남는다():
    # 사장님이 보자고 한 게 바로 이 경쟁사다 — 댓글 합계 0이라고 내리면 안 된다.
    row = {"제품군": "샴푸", "경쟁사": "맥단비", "횟수": 0, "상위노출": 3, "놓친": 2,
           "키워드수": 3, "키워드들": ["비듬샴푸"], "글들": [], "댓글 예시": ""}
    table = build_table([], [row], "2026-07-24")
    assert len(table) == 2
    head, out = table[0], table[1]
    assert out[head.index("상위노출 차지")] == 3 and out[head.index("우리가 놓친")] == 2
