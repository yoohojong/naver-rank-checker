# -*- coding: utf-8 -*-
"""남의 글을 훑을 때 **순위와 작성자**를 같이 남긴다.

사장님 프로세스(2026-09-04) 두 갈래가 여기서 갈린다:
  · 갈래 A(경쟁사) — "어떤 키워드에 몇위에 상위노출되어있는지 알 수 있지"
  · 갈래 B(키워드) — "그 글을 발행한 계정의 프로필을 들어가면 … 그 계정이
    바이럴하는 다른 키워드들을 추출할 수 있단 말이지"

순위는 검색 화면을 읽을 때 이미 손에 들어와 있었는데 버리고 있었다.
작성자는 대부분 댓글 안에 있다 — 바이럴 글은 글쓴이가 댓글로 대답하기 때문에
`isArticleWriter` 표식이 붙은 댓글이 거의 항상 있다. 없을 때만 글을 한 번 연다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import collect_comment_brands as C  # noqa: E402


class 가짜크롤:
    def fetch_search(self, kw):
        return "<html/>"


class 가짜댓글기:
    def __init__(self, 댓글, 글쓴이=None):
        self._c, self._w, self.연글 = 댓글, 글쓴이, []
        self.카페번호값 = ""

    def comments(self, url):
        return self._c

    def cafe_no(self, url):
        return self.카페번호값

    def writer(self, url):
        self.연글.append(url)
        return self._w or {}


def _글(rank=1, url="https://cafe.naver.com/abc/1", title="지루성두피염 해결"):
    from src.parser import SlotItem
    return SlotItem(area="AB", rank=rank, url=url, kind="cafe",
                    title=title, source_name="어떤카페")


def _돌리기(monkeypatch, items, fetcher):
    monkeypatch.setattr(C, "collect_slot_items", lambda html: items)
    monkeypatch.setattr(C.time, "sleep", lambda *_: None)
    return C.scan_keyword(가짜크롤(), "지루성두피염샴푸", our_links=set(),
                          our_slugs=set(), fetcher=fetcher, top_posts=4)


def test_순위와_구좌와_제목을_남긴다(monkeypatch):
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "댓쓴이"}}])
    got = _돌리기(monkeypatch, [_글(rank=3)], f)
    assert got, "댓글이 있으면 언급이 나와야 한다"
    m = got[0]
    assert m["순위"] == 3
    assert m["구좌"] == "AB"
    assert m["제목"] == "지루성두피염 해결"


def test_글쓴이는_댓글에서_공짜로_뽑는다(monkeypatch):
    """글쓴이가 댓글에 있으면 글을 다시 열지 않는다 — 요청 하나가 곧 시간이다."""
    f = 가짜댓글기([
        {"content": "저도 궁금해요", "writer": {"nick": "행인", "memberKey": "AAA"}},
        {"content": "안티트로 썼어요", "writer": {"nick": "바이럴이", "memberKey": "ZZZ"},
         "isArticleWriter": True},
    ])
    got = _돌리기(monkeypatch, [_글()], f)
    assert got[0]["글쓴이"] == "바이럴이"
    assert got[0]["글쓴이키"] == "ZZZ"
    assert f.연글 == [], "댓글에서 찾았으면 글을 열지 않아야 한다"


def test_댓글에_글쓴이가_없으면_글을_한_번_연다(monkeypatch):
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}],
                 글쓴이={"닉": "바이럴이", "키": "ZZZ", "카페번호": "123"})
    got = _돌리기(monkeypatch, [_글()], f)
    assert got[0]["글쓴이"] == "바이럴이"
    assert got[0]["글쓴이키"] == "ZZZ"
    assert got[0]["카페번호"] == "123"
    assert len(f.연글) == 1, "못 찾았을 때만, 딱 한 번 열어야 한다"


def test_글쓴이를_끝내_못_찾아도_언급은_남는다(monkeypatch):
    """작성자를 못 찾았다고 경쟁사 자료까지 버리면 안 된다 — 두 갈래는 따로 산다."""
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}], 글쓴이={})
    got = _돌리기(monkeypatch, [_글()], f)
    assert got and got[0]["댓글"]
    assert got[0]["글쓴이키"] == ""


def test_글쓴이_찾기는_순수함수다():
    찾기 = C.글쓴이_찾기
    assert 찾기([]) == {}
    assert 찾기([{"writer": {"nick": "행인", "memberKey": "A"}}]) == {}
    assert 찾기([{"writer": {"nick": "주인", "memberKey": "Z"}, "isArticleWriter": True}]) \
        == {"닉": "주인", "키": "Z"}


def test_지워진_댓글의_글쓴이는_안_쓴다():
    """지워진 댓글은 화면에 안 보인다 — 거기 남은 이름을 근거로 삼지 않는다."""
    assert C.글쓴이_찾기([{"writer": {"nick": "주인", "memberKey": "Z"},
                        "isArticleWriter": True, "isDeleted": True}]) == {}


# ── 2026-09-04 독립 검수 지적 반영 ──────────────────────────

def test_댓글에서_찾아도_프로필_주소가_나온다(monkeypatch):
    """★검수 지적 #3 — 성공할수록 프로필이 비고 실패해야 채워지던 것.

    카페번호는 댓글을 받을 때 이미 손에 들어와 있다(`_club` 에 담긴다).
    공짜인데 안 쓰고 있었다.
    """
    f = 가짜댓글기([{"content": "안티트로 써요",
                  "writer": {"nick": "바이럴이", "memberKey": "ZZZ"},
                  "isArticleWriter": True}])
    f.카페번호값 = "23335481"
    got = _돌리기(monkeypatch, [_글()], f)
    assert got[0]["카페번호"] == "23335481"
    assert f.연글 == [], "댓글에서 찾았으면 글을 열지 않아야 한다"
    assert C.프로필주소(got[0]["카페번호"], got[0]["글쓴이키"]).endswith("members/ZZZ")


def test_글을_열_때_검색에서_받은_열쇠를_같이_보낸다():
    """★검수 지적 #4 — 이 열쇠를 버리고 부르면 403 이다(2026-07-23 실측:
    1,106개 중 548개를 그렇게 놓쳤다). 댓글 받는 쪽은 붙이는데 여기만 빠져 있었다.
    """
    부른곳 = []

    class 가짜세션:
        headers: dict = {}

        def get(self, url, **kw):
            부른곳.append(url)

            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"result": {"article": {"writer": {"nick": "주인",
                                                              "memberKey": "K"}}}}
            return R()

    f = C.CommentFetcher()
    f.s = 가짜세션()
    f._club["abc"] = "111"
    got = f.writer("https://cafe.naver.com/abc/1?art=열쇠값")
    assert got["키"] == "K" and got["카페번호"] == "111"
    assert "art=열쇠값" in 부른곳[0], "검색에서 받은 열쇠가 빠졌습니다"


def test_댓글이_하나도_없어도_글_기록은_남는다(monkeypatch):
    """★검수 지적 #1의 짝 — 댓글을 못 연 글은 언급이 0건이라 그 계정이 통째로
    사라졌다. 순위·작성자는 이미 손에 있으므로 글 단위 기록을 하나 남긴다.
    """
    f = 가짜댓글기([], 글쓴이={"닉": "바이럴이", "키": "ZZZ", "카페번호": "111"})
    got = _돌리기(monkeypatch, [_글(rank=2)], f)
    assert len(got) == 1
    assert got[0]["원천"] == "글"
    assert got[0]["댓글"] == ""
    assert got[0]["순위"] == 2 and got[0]["글쓴이키"] == "ZZZ"


def test_글_기록은_댓글이_있으면_안_만든다(monkeypatch):
    """댓글이 있으면 그 언급들이 이미 순위·작성자를 들고 있다 — 겹쳐 세지 않는다."""
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}])
    got = _돌리기(monkeypatch, [_글()], f)
    assert [m["원천"] for m in got] == ["댓글"]


def test_옛_모양_댓글파일을_그대로_쓰면_알린다():
    """★모아둔 댓글을 다시 쓰는 길을 열면서 같이 막는 함정.

    2026-09-04 에 언급 모양이 바뀌었다(순위·구좌·글쓴이·카페번호 신설).
    그 전에 저장된 파일을 그대로 읽으면 크롤은 건너뛰는데 **계정 표가 조용히
    빈다.** '경쟁이 없다' 처럼 보이는 것이 이 저장소가 가장 자주 데인 자리다.
    """
    옛것 = {"샴푸": [{"댓글": "안티트로 써요", "키워드": "가", "글": "u1",
                   "카페": "어떤카페", "우리놓침": False, "원천": "댓글"}]}
    부족 = C.모양_모자란칸(옛것)
    assert "순위" in 부족 and "글쓴이키" in 부족


def test_새_모양이면_모자란_칸이_없다():
    새것 = {"샴푸": [{"댓글": "안티트로 써요", "키워드": "가", "글": "u1",
                   "카페": "어떤카페", "우리놓침": False, "원천": "댓글",
                   "순위": 2, "구좌": "AB", "제목": "가 후기",
                   "글쓴이": "바이럴이", "글쓴이키": "ZZZ", "카페번호": "111"}]}
    assert C.모양_모자란칸(새것) == []


# ── 사장님 정정 (2026-09-04): 뒤질 대상은 '우리보다 위' 다 ──────────
# "일단 우리가 카페외부 할 떄 우리가 카페 구좌 1등 아닌 키워드들의
#  우리보다 높이 있는 카페 들을 뒤져봐."

def _우리글(rank):
    return _글(rank=rank, url="https://cafe.naver.com/ours/9", title="우리 글")


def test_우리_순위와_우리보다_위인지를_같이_남긴다(monkeypatch):
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}])
    글들 = [_우리글(3), _글(rank=1, url="https://cafe.naver.com/abc/1"),
           _글(rank=5, url="https://cafe.naver.com/xyz/2")]
    monkeypatch.setattr(C, "is_our_item",
                        lambda u, a, b: "ours" in u)
    got = _돌리기(monkeypatch, 글들, f)
    자리 = {m["글"]: m for m in got}
    assert 자리["https://cafe.naver.com/abc/1"]["우리순위"] == 3
    assert 자리["https://cafe.naver.com/abc/1"]["우리보다위"] is True    # 1등 < 우리 3등
    assert 자리["https://cafe.naver.com/xyz/2"]["우리보다위"] is False   # 5등 > 우리 3등


def test_우리_글이_아예_없으면_전부_우리보다_위다(monkeypatch):
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}])
    got = _돌리기(monkeypatch, [_글(rank=4)], f)
    assert got[0]["우리순위"] == ""          # 없는 것을 0 으로 만들지 않는다
    assert got[0]["우리보다위"] is True


def test_우리가_1등이면_위에_아무도_없다(monkeypatch):
    """사장님: '우리가 카페 구좌 1등 아닌 키워드들' — 1등이면 뒤질 것이 없다."""
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}])
    글들 = [_우리글(1), _글(rank=2, url="https://cafe.naver.com/abc/1")]
    monkeypatch.setattr(C, "is_our_item", lambda u, a, b: "ours" in u)
    got = _돌리기(monkeypatch, 글들, f)
    assert all(m["우리보다위"] is False for m in got)


def test_구좌가_다르면_견줄_수_없다고_적는다(monkeypatch):
    """AB 3등과 인기글 1등은 견줄 수 없다 — 섞으면 거짓으로 '이겼다' 가 된다.
    '못 이겼다'(False) 도 아니고 '모른다'(빈칸) 다. 셋을 뭉개지 않는다.
    """
    f = 가짜댓글기([{"content": "안티트로 써요", "writer": {"nick": "행인"}}])
    우리 = _우리글(3)
    남 = _글(rank=1, url="https://cafe.naver.com/abc/1")
    남.area = "인기글"
    monkeypatch.setattr(C, "is_our_item", lambda u, a, b: "ours" in u)
    got = _돌리기(monkeypatch, [우리, 남], f)
    assert got[0]["우리보다위"] == "", "견줄 수 없으면 빈칸이지 False 가 아니다"
