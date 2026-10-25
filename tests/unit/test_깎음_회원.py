# -*- coding: utf-8 -*-
"""깎으려고 꺼낸 대안 제품 · 글쓴이 회원 여부 (2026-10-24 사장님).

원문: "이거는 니조랄 바이럴이 아니라 안티트로가 본인 바이럴 하기 위한 대안제거임.
       그런거 효과 없다고 하잖아 문맥보면 보통" → "아니 경쟁사 말한거임 경쟁사"
원문: "탈퇴멤버면 글 삭제 요청해야하고 탈퇴 아닌 멤버는 신고해야함" → '회원 아님' = "탈퇴임"
실측(10-24): 니조랄이 나온 글 8개의 댓글 원문 전부가 '그때뿐 · 효과 못 보고 · 자극 · 내성' 문맥.
"""
import json

from scripts import collect_comment_brands as ccb
from src import brand_from_comments as bfc
from src import comment_brand_llm, comment_reads


def _reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]}


# ── 판정기가 두 칸으로 받는다 ───────────────────────────────────────────────

def test_판정기는_깎은_이름을_돌려주는_이름에_넣지_않는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply(
        {"결과": [{"n": 1, "제품": ["어니스트맘"], "깎음": ["니조랄"]}]}))
    깎음 = {}
    got = bfc.read_batch(["니조랄 쓰고 머리뻑뻑해지는 건 어쩔 수 없어요! 어니스트맘 샴푸가 부드럽게"],
                         깎음=깎음)
    assert got == {0: ["어니스트맘"]}
    assert 깎음 == {0: ["니조랄"]}


def test_두_칸에_다_넣으면_깎음_쪽에_남긴다():
    민, 깎 = bfc.칸_나누기(["안티트로", "니조랄"], ["니조랄"], "니조랄 효과 없고 안티트로 추천")
    assert 민 == ["안티트로"] and 깎 == ["니조랄"]


def test_칸이_빠진_줄은_답한_것으로_치지_않는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply({"결과": [{"n": 1}]}))
    답한 = set()
    bfc.read_batch(["안티트로 좋아요"], 답한=답한)
    assert 답한 == set()


def test_깎음_칸도_환각을_거른다():
    민, 깎 = bfc.칸_나누기([], ["아로마티카"], "니조랄 써봤는데 그때뿐")
    assert 깎 == []


# ── 읽기 기억: 옛 항목은 다시 읽고, 다시 읽기 전에는 옛 이름을 쓴다 ─────────────

def test_옛_항목은_이름이_있을_때만_다시_읽는다():
    assert comment_reads.needs_reread({"이름": ["니조랄"], "깎음": None})
    assert not comment_reads.needs_reread({"이름": [], "깎음": None})
    assert not comment_reads.needs_reread({"이름": ["니조랄"], "깎음": []})


def test_옛_파일을_읽어도_깎음_칸을_지어_넣지_않는다(tmp_path):
    path = tmp_path / "reads.json"
    path.write_text(json.dumps({comment_reads.key_of("니조랄 그때뿐"):
                                {"이름": ["니조랄"], "날": "2026-10-20"}}), encoding="utf-8")
    e = comment_reads.get_full(comment_reads.load(str(path)), "니조랄 그때뿐")
    assert e == {"이름": ["니조랄"], "깎음": None}


def _가짜(monkeypatch, 돌려줄, 깎을, 보낸것):
    def fake_read_all(texts, **kw):
        보낸것.extend(texts)
        return 돌려줄(texts), {"댓글": len(texts), "묶음": 1, "못읽은묶음": 0, "탈": [],
                             "뽑은이름": 0, "예산사용": 1,
                             "읽은자리": set(range(len(texts))), "깎음": 깎을(texts)}
    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified", lambda names, stat=None: (list(names), {}))


def test_옛_항목을_다시_읽어_깎은_이름을_경쟁사_셈에서_뺀다(tmp_path, monkeypatch):
    reads_path, verdict_path = str(tmp_path / "r.json"), str(tmp_path / "v.json")
    옛글 = "니조랄 써봤는데 진짜 그때뿐이더라구요"
    (tmp_path / "r.json").write_text(json.dumps({comment_reads.key_of(옛글):
                                                 {"이름": ["니조랄"], "날": "2026-10-20"}}),
                                     encoding="utf-8")
    보낸것 = []
    _가짜(monkeypatch, lambda ts: {}, lambda ts: {ts.index(옛글): ["니조랄"]}, 보낸것)
    깎음언급 = []
    ms, _v, stat = ccb.extract_brands(
        [{"댓글": 옛글, "키워드": "지루성두피염샴푸", "글": "u1", "원천": "댓글"}],
        verdict_path=verdict_path, today="2026-10-24", reads_path=reads_path, 깎음언급=깎음언급)
    assert 보낸것 == [옛글]                       # 옛 항목을 다시 읽었다
    assert ms == []                               # 경쟁사 셈에 안 들어간다
    assert [m["키"] for m in 깎음언급] == ["니조랄"]
    assert stat["다시읽기대상"] == 1 and stat["다시읽음"] == 1
    e = comment_reads.get_full(comment_reads.load(reads_path), 옛글)
    assert e == {"이름": [], "깎음": ["니조랄"]}  # 새 모양으로 남았다


def test_새_댓글을_먼저_보낸다(tmp_path, monkeypatch):
    reads_path, verdict_path = str(tmp_path / "r.json"), str(tmp_path / "v.json")
    옛글, 새글 = "니조랄 그때뿐", "안티트로 정착"
    (tmp_path / "r.json").write_text(json.dumps({comment_reads.key_of(옛글):
                                                 {"이름": ["니조랄"], "날": "2026-10-20"}}),
                                     encoding="utf-8")
    보낸것 = []
    _가짜(monkeypatch, lambda ts: {}, lambda ts: {}, 보낸것)
    ccb.extract_brands([{"댓글": 옛글, "글": "u1"}, {"댓글": 새글, "글": "u2"}],
                       verdict_path=verdict_path, today="2026-10-24", reads_path=reads_path)
    assert 보낸것 == [새글, 옛글]


def test_다시_못_읽은_옛_항목은_옛_이름을_그대로_쓴다(tmp_path, monkeypatch):
    # 예산이 모자라 다시 못 읽은 날 경쟁사 표가 갑자기 비지 않게.
    reads_path, verdict_path = str(tmp_path / "r.json"), str(tmp_path / "v.json")
    옛글 = "안티트로 좋아요"
    (tmp_path / "r.json").write_text(json.dumps({comment_reads.key_of(옛글):
                                                 {"이름": ["안티트로"], "날": "2026-10-20"}}),
                                     encoding="utf-8")

    def fake_read_all(texts, **kw):
        return {}, {"댓글": len(texts), "묶음": 1, "못읽은묶음": 1, "탈": ["회차 예산 소진"],
                    "뽑은이름": 0, "예산사용": 1, "읽은자리": set()}
    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified", lambda names, stat=None: (list(names), {}))
    ms, _v, _s = ccb.extract_brands([{"댓글": 옛글, "글": "u1"}], verdict_path=verdict_path,
                                    today="2026-10-24", reads_path=reads_path)
    assert [m["키"] for m in ms] == ["안티트로"]


# ── 깎인 제품 묶기 ───────────────────────────────────────────────────────

def test_깎인_제품을_묶고_같은_글에서_민_제품을_붙인다():
    verdicts = {"니조랄": {"제품": True, "이름": "니조랄"},
                "안티트로": {"제품": True, "이름": "안티트로"},
                "뽀얀": {"제품": True, "이름": "뽀얀"}}
    깎 = [{"키": "니조랄", "표시": "니조랄", "글": "g1"},
          {"키": "니조랄", "표시": "니조랄", "글": "g1"},
          {"키": "니조랄", "표시": "니조랄", "글": "g2"},
          {"키": "뽀얀", "표시": "뽀얀", "글": "g3"}]          # 우리 제품은 싣지 않는다
    민 = [{"키": "안티트로", "표시": "안티트로", "글": "g1"}]
    got = ccb.깎인제품_집계(깎, 민, verdicts)
    # ★2026-10-25 기대값 3 → 2: g1 의 두 줄은 글도 댓글도 같다 — 키워드마다 다시 더해진 같은 댓글이다
    #   (니조랄 161 = 서로 다른 댓글 70 의 원인). 서로 다른 댓글로 센다. 옛 칸 이름은 그대로.
    옛칸 = [{k: x[k] for k in ("이름", "댓글수", "글수", "함께민제품")} for x in got]
    assert 옛칸 == [{"이름": "니조랄", "댓글수": 2, "글수": 2, "함께민제품": ["안티트로"]}]


# ── 회원 여부 ────────────────────────────────────────────────────────────

def test_회원_여부는_isCafeMember_로_가른다():
    f = ccb.CommentFetcher()
    f._club["abc"] = "111"
    for 값, 기대 in ((True, "회원"), (False, "탈퇴"), (None, "")):
        class 세션:
            def get(self, url, **kw):
                class R:
                    status_code = 200

                    @staticmethod
                    def json():
                        w = {"nick": "x"} if 값 is None else {"nick": "x", "isCafeMember": 값}
                        return {"result": {"article": {"writer": w}}}
                return R()
        f.s = 세션()
        assert f.회원여부("https://cafe.naver.com/abc/1?art=k") == 기대


def test_못_연_글은_확인_못_함():
    f = ccb.CommentFetcher()
    f._club["abc"] = "111"

    class 세션:
        def get(self, url, **kw):
            class R:
                status_code = 401
            return R()
    f.s = 세션()
    assert f.회원여부("https://cafe.naver.com/abc/1") == ""


def test_회원_기억은_7일_안이면_다시_묻지_않고_상한을_지킨다():
    물은 = []
    계정 = [{"카페번호": "1", "계정키": "a", "글들": ["u1"]},
            {"카페번호": "1", "계정키": "b", "글들": ["u2"]},
            {"카페번호": "1", "계정키": "c", "글들": ["u3"]},
            {"카페번호": "1", "계정키": "d", "글들": []}]
    기억 = {"1:a": {"회원": "탈퇴", "날": "2026-10-20"}}
    stat = ccb.회원_붙이기(계정, lambda g: 물은.append(g) or "회원", 기억, "2026-10-24", 상한=1)
    assert 물은 == ["u2"]
    assert [a["회원"] for a in 계정] == ["탈퇴", "회원", "", ""]
    assert stat == {"물음": 1, "기억": 1, "못물음": 2}
    assert 기억["1:b"] == {"회원": "회원", "날": "2026-10-24"}


def test_묵은_기억은_다시_묻는다():
    계정 = [{"카페번호": "1", "계정키": "a", "글들": ["u1"]}]
    기억 = {"1:a": {"회원": "회원", "날": "2026-10-10"}}
    ccb.회원_붙이기(계정, lambda g: "탈퇴", 기억, "2026-10-24")
    assert 계정[0]["회원"] == "탈퇴"


# ── GPT 검토 10-24 고침 ──────────────────────────────────────────────────

def test_다시_읽기_답에서_빠진_옛_항목은_지우지_않는다(tmp_path, monkeypatch):
    reads_path, verdict_path = str(tmp_path / "r.json"), str(tmp_path / "v.json")
    옛글 = "안티트로 좋아요"
    (tmp_path / "r.json").write_text(json.dumps({comment_reads.key_of(옛글):
                                                 {"이름": ["안티트로"], "날": "2026-10-20"}}),
                                     encoding="utf-8")

    def fake_read_all(texts, **kw):          # 묶음은 성공했는데 AI 답에 그 줄이 없다
        return {}, {"댓글": len(texts), "묶음": 1, "못읽은묶음": 0, "탈": [], "뽑은이름": 0,
                    "예산사용": 1, "읽은자리": set(range(len(texts))), "답한자리": set(), "깎음": {}}
    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified", lambda names, stat=None: (list(names), {}))
    ms, _v, stat = ccb.extract_brands([{"댓글": 옛글, "글": "u1"}], verdict_path=verdict_path,
                                      today="2026-10-24", reads_path=reads_path)
    assert [m["키"] for m in ms] == ["안티트로"]
    assert stat["다시읽음"] == 0
    e = comment_reads.get_full(comment_reads.load(reads_path), 옛글)
    assert e == {"이름": ["안티트로"], "깎음": None}, "다음 회차에 다시 읽게 옛 모양 그대로"


def test_판정기는_답한_줄을_알려준다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply(
        {"결과": [{"n": 2, "제품": [], "깎음": []}]}))
    답한 = set()
    bfc.read_batch(["안티트로 좋아요", "그냥 그래요"], 답한=답한)
    assert 답한 == {1}


def _줄(brand, n, product="샴푸"):
    return {"제품군": product, "경쟁사": brand, "횟수": n, "키워드수": 1, "키워드들": ["비듬샴푸"],
            "글들": ["https://cafe.naver.com/a/1"], "댓글 예시": ""}


def test_같은_날_다시_돌리면_오늘_칸은_새로_센_값이다():
    아까 = ccb.build_table([], [_줄("안티트로", 3), _줄("모리젠", 5)], "2026-10-24")
    지금 = ccb.build_table(아까, [_줄("안티트로", 3)], "2026-10-24")
    head = 지금[0]
    줄 = {r[1]: r for r in 지금[1:]}
    assert "모리젠" not in 줄 or 줄["모리젠"][head.index("2026-10-24")] == 0


def test_지난_날_셈은_오늘_안_나와도_그날_칸에_남는다():
    어제 = ccb.build_table([], [_줄("안티트로", 3), _줄("니조랄", 5)], "2026-10-23")
    오늘 = ccb.build_table(어제, [_줄("안티트로", 4)], "2026-10-24")
    head = 오늘[0]
    줄 = {r[1]: r for r in 오늘[1:]}
    assert 줄["니조랄"][head.index("2026-10-24")] == 0 and 줄["니조랄"][head.index("2026-10-23")] == 5


def test_회원_묻기가_실패해도_쉰다(monkeypatch):
    쉼 = []
    monkeypatch.setattr(ccb.time, "sleep", lambda s: 쉼.append(s))
    f = ccb.CommentFetcher()
    f._club["abc"] = "111"

    class 세션:
        def get(self, url, **kw):
            raise RuntimeError("끊김")
    f.s = 세션()
    assert f.회원여부("https://cafe.naver.com/abc/1") == ""


# ── GPT 3차 검토 고침 ──
def test_한_칸만_온_줄은_답한_것으로_치지_않는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply({"결과": [{"n": 1, "깎음": []}]}))
    답한 = set()
    bfc.read_batch(["안티트로 좋아요"], 답한=답한)
    assert 답한 == set()


def test_같은_번호가_두_번_와도_깎음이_이긴다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply({"결과": [
        {"n": 1, "제품": ["니조랄"], "깎음": []}, {"n": 1, "제품": [], "깎음": ["니조랄"]}]}))
    깎음 = {}
    got = bfc.read_batch(["니조랄 효과 없어요"], 깎음=깎음)
    assert got == {} and 깎음 == {0: ["니조랄"]}


def test_표기가_조금_달라도_깎음이_이긴다():
    민, 깎 = bfc.칸_나누기(["니조랄 샴푸", "안티트로"], ["니조랄"], "니조랄 샴푸 효과 없고 안티트로 추천")
    assert 민 == ["안티트로"] and 깎 == ["니조랄"]


# ── 2026-10-25 깎인 대상 넓히기(상표 + 종류 · 글쓴이 갈래 · 서로 다른 댓글 · 남기는 칸) ─────────
# 사장님 원문(10-25): "경쟁사 댓글은 그떄분이라고하는건 자기 제품 바이럴 하기 위해서 상징적인 제품들을
#   일부로 이용하는거에요 나중에 시장 조사할떄 대안이 무엇이 있나를 찾아봐야할떄 활용하는거는 무조건 필요해요"

_스테 = "피부과도 가보고 니조랄, 스테로이드 처방도 받아봤지만 그때 뿐이고 계속 다시 올라와요. 안티트로로 바꿨어요"


def test_판정기는_종류_칸을_따로_받는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply(
        {"결과": [{"n": 1, "제품": ["안티트로"], "깎음": ["니조랄"], "종류": ["스테로이드", "피부과", "연고"]}]}))
    깎음, 종류 = {}, {}
    got = bfc.read_batch([_스테], 깎음=깎음, 종류=종류)
    assert got == {0: ["안티트로"]} and 깎음 == {0: ["니조랄"]}
    assert 종류 == {0: ["스테로이드", "피부과"]}          # '연고' 는 원문에 없다 — 환각 거르기


def test_종류_칸이_안_온_답은_종류를_안_채운다(monkeypatch):
    # '안 봄'(칸 없음)과 '봤는데 없음'([])을 섞지 않는다 — 옛 모양 답이면 종류 dict 에 넣지 않는다.
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply(
        {"결과": [{"n": 1, "제품": ["안티트로"], "깎음": []}, {"n": 2, "제품": [], "깎음": [], "종류": []}]}))
    종류 = {}
    bfc.read_batch(["안티트로 좋아요", "그냥 그래요"], 종류=종류)
    assert 종류 == {1: []}


def test_종류_칸은_경쟁사_셈을_바꾸지_않는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    본 = {"n": 1, "제품": ["안티트로", "약산성샴푸"], "깎음": ["니조랄"]}
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply({"결과": [본]}))
    전 = bfc.read_batch(["니조랄 그때뿐 약산성샴푸 그때뿐 안티트로 정착"])
    monkeypatch.setattr(comment_brand_llm, "_post", lambda *a, **k: _reply(
        {"결과": [{**본, "종류": ["약산성샴푸"]}]}))
    후 = bfc.read_batch(["니조랄 그때뿐 약산성샴푸 그때뿐 안티트로 정착"], 종류={})
    assert 전 == 후 == {0: ["안티트로", "약산성샴푸"]}


def test_칸_나누기_옛_모양은_그대로다():
    assert bfc.칸_나누기(["안티트로"], ["니조랄"], "니조랄 별로 안티트로 좋아") == (["안티트로"], ["니조랄"])
    assert bfc.세칸_나누기(["안티트로"], ["니조랄"], None, "니조랄 별로 안티트로 좋아")[2] is None


def test_읽기_기억은_종류_칸_없음과_빈_목록을_가른다(tmp_path):
    reads = {}
    comment_reads.put(reads, "옛 모양", ["안티트로"], "2026-10-25", 깎음=[])
    comment_reads.put(reads, "봤는데 없음", [], "2026-10-25", 깎음=[], 종류=[])
    comment_reads.put(reads, "스테로이드 그때뿐", [], "2026-10-25", 깎음=[], 종류=["스테로이드"])
    p = str(tmp_path / "r.json")
    assert comment_reads.save(reads, p)
    다시 = comment_reads.load(p)
    assert comment_reads.get_종류(다시, "옛 모양") is None
    assert comment_reads.get_종류(다시, "봤는데 없음") == []
    assert comment_reads.get_종류(다시, "스테로이드 그때뿐") == ["스테로이드"]
    assert comment_reads.get_full(다시, "옛 모양") == {"이름": ["안티트로"], "깎음": []}   # 옛 모양 그대로


def test_종류는_깎음언급에_싣고_경쟁사_셈과_검색_확인에는_안_넣는다(tmp_path, monkeypatch):
    reads_path, verdict_path = str(tmp_path / "r.json"), str(tmp_path / "v.json")
    물은이름 = []

    def fake_read_all(texts, **kw):
        return ({0: ["안티트로"]},
                {"댓글": 1, "묶음": 1, "못읽은묶음": 0, "탈": [], "뽑은이름": 1, "예산사용": 1,
                 "읽은자리": {0}, "답한자리": {0}, "깎음": {0: ["니조랄"]}, "종류": {0: ["스테로이드"]}})
    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified",
                        lambda names, stat=None: (물은이름.extend(names) or list(names), {}))
    깎음언급 = []
    ms, _v, stat = ccb.extract_brands(
        [{"댓글": _스테, "키워드": "지루성", "글": "u1", "원천": "댓글"}],
        verdict_path=verdict_path, today="2026-10-25", reads_path=reads_path, 깎음언급=깎음언급)
    assert [m["키"] for m in ms] == ["안티트로"]                       # 경쟁사 셈은 그대로
    assert sorted((m["키"], m["종류"]) for m in 깎음언급) == [("니조랄", "깎음"), ("스테로이드", "깎은종류")]
    assert "스테로이드" not in 물은이름                                 # 종류는 검색 확인에 안 보낸다
    assert comment_reads.get_종류(comment_reads.load(reads_path), _스테) == ["스테로이드"]
    assert stat["종류언급"] == 1 and stat["종류칸없음"] == 0


def _v(*names, 아님=()):
    v = {n: {"제품": True, "이름": n} for n in names}
    v.update({n: {"제품": False, "이름": ""} for n in 아님})
    return v


def test_깎인_대상은_서로_다른_댓글과_서로_다른_글로_센다():
    # 같은 글 · 같은 댓글이 키워드 셋에 떴다(검색 화면이 키워드마다 다른 '?art=' 꼬리를 붙인다).
    깎 = [{"키": "니조랄", "표시": "니조랄", "글": f"https://cafe.naver.com/a/1?art={i}", "댓글": "니조랄 그때뿐",
           "키워드": f"k{i}"} for i in range(3)]
    got = ccb.깎인제품_집계(깎, [], _v("니조랄"))
    assert (got[0]["댓글수"], got[0]["글수"]) == (1, 1)


def test_글쓴이_갈래와_끌어온_경쟁_계정_수():
    v = _v("니조랄", "안티트로", "뽀얀")
    깎 = [{"키": "니조랄", "표시": "니조랄", "글": "g1", "댓글": "a", "글쓴이키": "k1"},   # 경쟁 글(안티트로)
          {"키": "니조랄", "표시": "니조랄", "글": "g2", "댓글": "b", "글쓴이키": "k2"},   # 경쟁 글(섞어 밈)
          {"키": "니조랄", "표시": "니조랄", "글": "g3", "댓글": "c", "글쓴이키": "k3"},   # 우리 글(뽀얀만)
          {"키": "니조랄", "표시": "니조랄", "글": "g4", "댓글": "d", "글쓴이키": "k4"}]   # 바이럴 아님
    민 = [{"키": "안티트로", "표시": "안티트로", "글": "g1"},
          {"키": "안티트로", "표시": "안티트로", "글": "g2"}, {"키": "뽀얀", "표시": "뽀얀", "글": "g2"},
          {"키": "뽀얀", "표시": "뽀얀", "글": "g3"}]
    x = ccb.깎인제품_집계(깎, 민, v)[0]
    assert x["글쓴이갈래"] == {"경쟁글": 2, "우리글": 1, "바이럴아님": 1}
    assert x["끌어온경쟁계정수"] == 2
    assert x["예시글"] == "g1"                                   # 예시는 경쟁 글에서 먼저


def test_제품_판정을_못_넘은_깎인_이름과_종류를_버리지_않는다():
    v = _v("니조랄", 아님=("크레오신티", "스테로이드"))
    깎 = [{"키": "크레오신티", "표시": "크레오신티", "글": "g1", "댓글": "a"},
          {"키": "스테로이드", "표시": "스테로이드", "글": "g2", "댓글": "b"},
          {"키": "두피 스케일링", "표시": "두피 스케일링", "글": "g3", "댓글": "c", "종류": "깎은종류"},
          {"키": "약산성샴푸", "표시": "약산성샴푸", "글": "g4", "댓글": "d", "종류": "깎은종류"},
          {"키": "뽀얀 샴푸", "표시": "뽀얀 샴푸", "글": "g5", "댓글": "e", "종류": "깎은종류"},   # 우리 것 — 안 실음
          {"키": "미판정이름", "표시": "미판정이름", "글": "g6", "댓글": "f"}]
    got = {x["이름"]: (x["종류"], x["종류갈래"], x["제품판정"]) for x in ccb.깎인제품_집계(깎, [], v)}
    assert got == {"크레오신티": ("상표", "", "아님"), "스테로이드": ("종류", "약·연고", ""),
                   "두피스케일링": ("종류", "시술", ""), "약산성샴푸": ("종류", "제품 종류", ""),
                   "미판정이름": ("상표", "", "미판정")}


def test_판정은_제품인데_이름이_종류말로_읽히는_상표도_남긴다():
    # 'TS샴푸' — 판정은 제품인데 한글만 남기면 '샴푸'(NOT_A_BRAND)라 경쟁사 표 길에서 지워진다.
    #   그래서 깎인 24개에서도 빠졌다(2026-10-25 원인 찾기). 깎인 대상에서는 남긴다.
    x = ccb.깎인제품_집계([{"키": "TS샴푸", "표시": "TS샴푸", "글": "g1", "댓글": "a"}], [], _v("TS샴푸"))
    assert [(r["이름"], r["종류"], r["제품판정"]) for r in x] == [("TS샴푸", "상표", "통과")]
    assert ccb.표시할_브랜드명({"키": "TS샴푸", "표시": "TS샴푸"}, _v("TS샴푸")) is None   # 경쟁사 셈은 그대로


def test_예시_댓글은_개인_정보를_지우고_120자_안이다():
    원문 = ("굿라이프님 저도 니조랄 써봤는데 그때뿐 010-1234-5678 카톡 abc123 연락주세요 "
            "https://open.kakao.com/o/xyz 메일 a.b@naver.com " + "가" * 200)
    s = ccb.개인정보_지우기(원문, 글쓴이="오렌지스카")
    for 남으면안됨 in ("굿라이프", "010-1234-5678", "abc123", "open.kakao.com", "a.b@naver.com"):
        assert 남으면안됨 not in s
    assert len(s) <= 120 and "니조랄 써봤는데 그때뿐" in s
    assert "오렌지스카" not in ccb.개인정보_지우기("오렌지스카 글 보고 왔어요", 글쓴이="오렌지스카")


def test_일부만_셈_표시는_갈래별로_붙는다():
    깎 = [{"키": "니조랄", "표시": "니조랄", "글": "g1", "댓글": "a"},
          {"키": "스테로이드", "표시": "스테로이드", "글": "g1", "댓글": "a", "종류": "깎은종류"}]
    got = {x["이름"]: x["일부만셈"] for x in ccb.깎인제품_집계(
        깎, [], _v("니조랄"), 셈상태={"다시안읽은옛댓글": 6106, "종류칸못본댓글": 0})}
    assert got == {"니조랄": True, "스테로이드": False}
    got = {x["이름"]: x["일부만셈"] for x in ccb.깎인제품_집계(깎, [], _v("니조랄"))}
    assert got == {"니조랄": False, "스테로이드": False}


def test_새_칸이_생겨도_옛_칸_이름은_그대로다():
    x = ccb.깎인제품_집계([{"키": "니조랄", "표시": "니조랄", "글": "g1", "댓글": "a"}], [], _v("니조랄"))[0]
    for 칸 in ("이름", "댓글수", "글수", "함께민제품", "종류", "끌어온경쟁계정수", "글쓴이갈래", "예시댓글",
              "예시글", "일부만셈"):
        assert 칸 in x
    assert not any("상징재" in 칸 for 칸 in x)


def test_같은_말이_깎음과_종류에_다_오면_상표_칸에만_둔다():
    민, 깎, 종 = bfc.세칸_나누기([], ["니조랄"], ["니조랄 샴푸", "스테로이드"], "니조랄 샴푸 스테로이드 다 그때뿐")
    assert 깎 == ["니조랄"] and 종 == ["스테로이드"]


def test_사람을_안_가리키는_님은_남긴다():
    s = ccb.개인정보_지우기("교수님이 약용샴푸는 단기 증상만 잡는다고 굿라이프님도 그러셨어요")
    assert "교수님이" in s and "굿라이프" not in s
