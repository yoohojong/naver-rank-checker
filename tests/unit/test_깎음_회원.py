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
    assert got == [{"이름": "니조랄", "댓글수": 3, "글수": 2, "함께민제품": ["안티트로"]}]


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
