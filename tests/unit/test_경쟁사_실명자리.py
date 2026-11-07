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


def _돌림(tmp_path, ms):
    붙은, v, stat = C.extract_brands(ms, verdict_path=str(tmp_path / "v.json"), today="2026-11-07",
                                     reads_path=str(tmp_path / "r.json"))
    out, 곁, 실 = C.실명만_남기기(ms, 붙은)
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


글2 = "https://cafe.naver.com/x/2?art=zzz"


def test_쪽지로_끝나면_같은_계정_다른_글의_실명_댓글_원문이_있을_때만(tmp_path, monkeypatch):
    _가짜(monkeypatch, [])
    쪽지뿐 = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름[:3])]
    # ① 다른 글이 없으면 — 이전 표의 '미는 제품' 값 같은 것으로 채우지 않고 이름 모름
    out, _, stat, _ = _돌림(tmp_path, 쪽지뿐)
    assert out == [] and stat["이름모름글"] == ["https://cafe.naver.com/x/1"]
    # ② 같은 계정의 다른 글(글2)에 실명 자리 댓글이 있으면 그 이름 + 그 글 주소·댓글 원문을 남긴다
    다른글 = [_m(t, i, w, url=글2) for i, (t, w, _) in enumerate(흐름[:2] + 흐름[3:4])]
    out, _, stat, _ = _돌림(tmp_path, 쪽지뿐 + 다른글)
    골 = [m for m in out if m["글"] == 글]
    assert [(m["표시"], m["근거"]) for m in 골] == [("다시꽃", "다른 글 실명")]
    assert 골[0]["근거글"] == "https://cafe.naver.com/x/2" and "다.시꽃샴푸" in 골[0]["근거댓글"]
    # ③ 다른 글 실명이 둘 이상이면 가릴 수 없다 → 이름 모름
    글3 = "https://cafe.naver.com/x/3"
    셋째 = [_m(t, i, w, url=글3) for i, (t, w, _) in enumerate(흐름[:2])] + [
        _m("저는 쪽지 받고 삭제할게요 제품은 라우쉬예요", 2, url=글3)]
    이름표["저는 쪽지 받고 삭제할게요 제품은 라우쉬예요"] = ["라우쉬"]
    out, _, stat, _ = _돌림(tmp_path, 쪽지뿐 + 다른글 + 셋째)
    assert not [m for m in out if m["글"] == 글] and 글 .split("?")[0] in stat["이름모름글"]


def test_현재_글_안의_비교_이름과_깎음_이름은_다른_글_실명이_아니다(tmp_path, monkeypatch):
    """F1 — 계정 글이 이 글 하나뿐이면 현재 글에서 읽힌 이름(비교·깎음)을 경쟁사로 복원하지 않는다."""
    _가짜(monkeypatch, [])
    ms = [_m(흐름[0][0], 0), _m("저는 라우쉬도 괜찮았어요", 1), _m(흐름[1][0], 2, True), _m(흐름[2][0], 3)]
    out, _, stat, 곁 = _돌림(tmp_path, ms)
    assert out == [] and stat["이름모름글수"] == 1
    assert "라우쉬" in [m["표시"] for m in 곁]


def test_다른_카페는_글번호가_같아도_우리_글이_아니다():
    우리 = frozenset({"https://cafe.naver.com/yongchondown/180474"})
    새 = "https://cafe.naver.com/ca-fe/cafes/999999/articles/180474"
    assert not C.is_our_item(새, set(우리), set())                       # 카페 대응 미확인 → 제외 안 함
    assert not C.is_our_item(새, set(우리), set(), {"yongchondown": "12345"})   # 다른 카페 번호 → 제외 안 함
    assert C.is_our_item(새.replace("999999", "12345"), set(우리), set(), {"yongchondown": "12345"})
    assert C.is_our_item("https://cafe.naver.com/yongchondown/180474?art=Q", set(우리), set())
    assert not C.is_our_item("https://cafe.naver.com/other/180474", set(우리), set())
    assert [m["댓글"] for m in C.우리글_빼기([_m("a", 0, url=새), _m("b", 0, url=새.replace("999999", "12345"))],
                                             우리, {"yongchondown": "12345"})] == ["a"]


def test_두_실행_진입이_같은_기준을_쓴다(tmp_path, monkeypatch):
    """F4 — --from-sheet 와 --keywords 가 같은 함수(기준대로_고르기)를 거친다."""
    import inspect
    _가짜(monkeypatch, [])
    ms = [_m(t, i, w) for i, (t, w, _) in enumerate(흐름)] + [
        _m("우리 글 댓글 쪽지", 0, url="https://cafe.naver.com/yongchondown/180474?art=Q")]
    out, v, stat, 곁 = C.기준대로_고르기(ms, frozenset({"https://cafe.naver.com/yongchondown/180474"}),
                                       verdict_path=str(tmp_path / "v.json"), today="2026-11-07",
                                       reads_path=str(tmp_path / "r.json"))
    assert [(m["표시"], m["근거"]) for m in out] == [("다시꽃", "실명 자리")]
    assert all("yongchondown" not in m["글"] for m in out + 곁)
    assert "기준대로_고르기(" in inspect.getsource(C.run_from_sheet)
    assert "기준대로_고르기(" in inspect.getsource(C.main)
    assert "extract_brands(all_mentions" not in inspect.getsource(C.main)


def test_새_시트_쓰기_증분은_들어_있지_않다():
    """F5 — 이번 판에서 뺀 새 쓰기 길. 없어져야 한다."""
    assert not hasattr(C, "_댓글후보탭_쓰기")
    import inspect
    assert "WRITE_COMMENT_CANDIDATES" not in inspect.getsource(C)


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
