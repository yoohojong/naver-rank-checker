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

    def comments(self, url):
        return self._c

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
