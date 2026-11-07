# -*- coding: utf-8 -*-
"""경쟁사 = 실명 자리 제품 하나 · 종류 이름은 키워드 후보 · 우리 글은 뺀다 (2026-11-07).

사장님 원문(11-06): "경쟁사는 브랜드키워드가 정상이잖아? … 경쟁글이 깍아내린 제품은 이제 시장 조사할 때
나오는 대안들이락 보면 되는거잖아 … 오히려 키워드후보에 들어가야하는 녀석들임 … 결국 뽀얀샴푸가 경쟁사인거야."
실측: 우리 글(yongchondown/180474)의 키워드 박은 공감 댓글 7개가 '지성샴푸' 경쟁사 21회로 셌다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import collect_comment_brands as C  # noqa: E402
from src import brand_from_comments, brand_verdicts, comment_reads  # noqa: E402

글 = "https://cafe.naver.com/x/1?art=abc"
흐름 = [
    ("지성샴푸 추천 받아 써봤는데 저는 오후 되면 다시 기름져요..", False, ["지성샴푸"]),
    ("혹시 그 샴푸가 뭔지 저도 알 수 있을까요?", True, []),
    ("쪽지 보냈는데 저도 어떤 제품인지 알 수 있을까요 ㅠ", False, []),
    ("혹시 모르니까 몇시간 뒤에 삭제할게요. 제품 이름은 다.시꽃샴푸인데", False, ["다시꽃"]),
    ("저는 라우쉬도 괜찮았어요", False, ["라우쉬"]),
]
이름표 = {t: n for t, _, n in 흐름}


def _m(t, 차례, 글쓴이댓글=False, 키워드="지성샴푸", url=글, 키="k1"):
    return {"댓글": t, "키워드": 키워드, "글": url, "순위": 3, "구좌": "AB", "제목": "t",
            "글쓴이": "a", "글쓴이키": 키, "카페번호": "1", "원천": "댓글", "차례": 차례,
            "글쓴이댓글": 글쓴이댓글, "카페": "맘카페"}


def _가짜(monkeypatch, 보낸):
    def read_all(texts, max_batches=None):
        보낸.extend(texts)
        return ({j: 이름표.get(t, []) for j, t in enumerate(texts) if 이름표.get(t)},
                {"읽은자리": set(range(len(texts))), "깎음": {}, "종류": {}})
    monkeypatch.setattr(C.brand_from_comments, "read_all", read_all)
    monkeypatch.setattr(C.shop_probe, "verified", lambda names, stat=None: (list(names), []))


def _돌림(tmp_path, ms, 계정미는제품=None):
    붙은, v, stat = C.extract_brands(ms, verdict_path=str(tmp_path / "v.json"), today="2026-11-07",
                                     reads_path=str(tmp_path / "r.json"))
    out, 곁, 실 = C.실명만_남기기(ms, 붙은, 계정미는제품)
    return out, v, {**stat, **실}, 곁


def test_지성샴푸는_종류_이름으로_간다():
    for n in ["지성샴푸", "약산성바디워시", "남성바디워시", "각질제거바디워시", "지성"]:
        assert C.종류이름인가(n), n
        assert not C.is_real_brand(n), n
        assert not C.표에_남길_경쟁사인가(n), n
    for n in ["안티트로", "닥터포헤어", "다시꽃", "아토엠"]:
        assert not C.종류이름인가(n), n
        assert C.is_real_brand(n), n
    판정 = {"지성샴푸": {"제품": True, "이름": "지성샴푸", "판정": "LLM", "판정일": "2026-11-06"}}
    언급 = [{**_m("지성샴푸 추천 받아", i), "표시": "지성샴푸", "키": "지성샴푸", "종류": "제품"}
            for i in range(7)]
    assert C.confirmed_rows(언급, 판정) == []
    줄 = C.댓글_키워드후보([{"표시": "지성샴푸", "종류": "곁이름", "제품군": "샴푸", "글": 글}], set(), set())
    assert [(x["키워드"], x["발견경로"]) for x in 줄] == [("지성샴푸", "경쟁 글 댓글 종류 이름")]


def test_실명_자리의_제품_하나만_경쟁사(tmp_path, monkeypatch):
    _가짜(monkeypatch, [])
    ms = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름)]
    out, v, stat, 곁 = _돌림(tmp_path, ms)
    assert [(m["표시"], m["근거"], m["댓글"]) for m in out] == [("다시꽃", "실명 자리", 흐름[3][0])]
    assert sorted(m["표시"] for m in 곁) == ["라우쉬", "지성샴푸"]
    assert stat["실명자리글"] == 1


def test_흐름_없는_글은_경쟁사를_안_뽑는다(tmp_path, monkeypatch):
    _가짜(monkeypatch, [])
    ms = [_m(흐름[0][0], 0), _m(흐름[4][0], 1)]
    out, v, stat, 곁 = _돌림(tmp_path, ms)
    assert out == []
    assert sorted(m["표시"] for m in 곁) == ["라우쉬", "지성샴푸"]


def test_쪽지로_끝나면_계정_다른글_실명_아니면_이름모름(tmp_path, monkeypatch):
    _가짜(monkeypatch, [])
    ms = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름[:3])]
    out, *_ = _돌림(tmp_path, ms, 계정미는제품={"k1": ["다시꽃"]})
    assert [(m["표시"], m["근거"]) for m in out] == [("다시꽃", "다른 글 실명")]
    out, _, stat, _ = _돌림(tmp_path, ms, 계정미는제품={"k1": ["다시꽃", "라우쉬"]})
    assert out == [] and stat["이름모름글수"] == 1 and stat["이름모름글"] == ["https://cafe.naver.com/x/1"]
    out, _, stat, _ = _돌림(tmp_path, ms, 계정미는제품={"k1": ["뽀얀", "라우쉬"]})
    assert out == [] and stat["이름모름글수"] == 0       # 우리 제품을 미는 계정 = 우리 계정


def test_실명_자리_댓글은_빈_기억이면_한번만_다시_읽는다(tmp_path, monkeypatch):
    reads = {}
    for t, _, _ in 흐름:
        comment_reads.put(reads, t, [], "2026-11-06", 깎음=[])
    comment_reads.save(reads, str(tmp_path / "r.json"))
    보낸 = []
    _가짜(monkeypatch, 보낸)
    ms = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름)]
    out, *_ = _돌림(tmp_path, ms)
    assert 보낸 == [흐름[3][0]]
    assert [m["표시"] for m in out] == ["다시꽃"]
    보낸.clear()
    _돌림(tmp_path, ms)
    assert 보낸 == []


def test_종류_이름은_쇼핑에_안_보내고_종류로_판정한다(tmp_path, monkeypatch):
    물은 = []
    _가짜(monkeypatch, [])
    monkeypatch.setattr(C.shop_probe, "verified",
                        lambda names, stat=None: (물은.extend(names) or list(names), []))
    brand_verdicts.save({"지성샴푸": {"제품": True, "이름": "지성샴푸", "판정": "LLM",
                                    "판정일": "2026-11-06"}}, str(tmp_path / "v.json"))
    ms = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름)]
    _, v, _, _ = _돌림(tmp_path, ms)
    assert "지성샴푸" not in 물은
    assert v["지성샴푸"]["판정"] == "종류" and v["지성샴푸"]["제품"] is False
    brand_verdicts.save({"지성샴푸": {"제품": True, "이름": "지성샴푸", "판정": "사장님",
                                    "판정일": "2026-11-06"}}, str(tmp_path / "v.json"))
    _, v, _, _ = _돌림(tmp_path, ms)
    assert v["지성샴푸"]["판정"] == "사장님"           # 사람 판정은 못 덮는다


def test_우리_글은_art_열쇠가_달라도_뺀다():
    우리 = frozenset({"https://cafe.naver.com/yongchondown/180474?art=ZZZ",
                      "https://cafe.naver.com/ca-fe/cafes/123/articles/55", "https://naver.me/abc"})
    ms = [_m("a", 0, url="https://cafe.naver.com/yongchondown/180474?art=OTHER"),
          _m("b", 0, url="https://cafe.naver.com/yongchondown/180475"),
          _m("c", 0, url="https://cafe.naver.com/ca-fe/cafes/123/articles/55"),
          _m("d", 0, url="https://cafe.naver.com/other/56")]
    assert [m["댓글"] for m in C.우리글_빼기(ms, 우리)] == ["b", "d"]
    assert C.is_our_item("https://cafe.naver.com/yongchondown/180474", set(우리), set())
    탭 = [["키워드", "링크"], ["지성샴푸", "https://cafe.naver.com/yongchondown/180474?art=Q"], ["x", ""]]
    assert C.우리_링크_모으기([탭]) == {"https://cafe.naver.com/yongchondown/180474?art=Q"}


def test_키워드후보는_깎음_종류_곁을_가르고_우리것_이미가진것을_뺀다():
    언급 = [{"표시": "지성샴푸", "종류": "곁이름", "제품군": "샴푸"},
            {"표시": "니조랄", "종류": "깎음", "제품군": "샴푸"},
            {"표시": "스테로이드", "종류": "깎은종류", "제품군": "샴푸"},
            {"표시": "라우쉬", "종류": "곁이름", "제품군": "샴푸"},
            {"표시": "아토엠", "종류": "곁이름", "제품군": "샴푸"},
            {"표시": "뽀얀", "종류": "곁이름", "제품군": "샴푸"},
            {"표시": "니조랄", "종류": "깎음", "제품군": "샴푸"}]
    줄 = C.댓글_키워드후보(언급, {"라우쉬"}, set(), 오늘="2026-11-07")
    assert [(x["키워드"], x["발견경로"]) for x in 줄] == [
        ("지성샴푸", "경쟁 글 댓글 종류 이름"), ("니조랄", "깎인 대상"),
        ("스테로이드", "경쟁 글 댓글 종류 이름"), ("아토엠", "경쟁 글 댓글 곁 이름")]


def test_AI_규칙에_실명_자리와_종류_빼기가_있다():
    s = brand_from_comments.SYSTEM
    assert "삭제할게요" in s and "'지성샴푸 추천 받아 써봤는데'" in s
