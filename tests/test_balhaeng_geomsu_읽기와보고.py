# -*- coding: utf-8 -*-
"""발행 검수 — 글 읽기 주소 · 못 읽은 글의 시트 처리 · 보고를 보낼 날 (2026-10-21).

★9/23부터 네이버가 글 읽기 주소 v3 에 오류(500 · 9999)만 돌려줬다. 그 4주 동안
  ① 148건 전부 '글 없음(500)' — 삭제(404)와 서버 오류가 같은 말로 섞였고
  ② 못 읽은 글의 시트 행을 '수집실패'로 덮어써 살아 있는 글의 진짜 판정이 지워졌고
  ③ 검사일이 매일 새 날짜라 '검사일이 오래됨 = 멈춤' 신호가 죽었고
  ④ 보고 첫 줄이 "네이버가 막고 있을 수 있습니다"라 누가 고칠 일인지 안 보였다.
★사장님 10-21 "이상한 보고가 너무 많아 진짜" — 매일 보고(30일 29통)를
  '고칠 글이 새로 나온 날 · 읽는 방법이 막힌 날'로 줄인다.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _모듈():
    sys.modules.setdefault("curl_cffi", types.SimpleNamespace(requests=None))
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "geomsu_read", ROOT / "scripts" / "balhaeng_geomsu.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _모듈()


# ── 1. 글 읽기 주소 ─────────────────────────────────────────────────────
class 응답:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body or {}, text

    def json(self):
        return self._body


def _가짜요청(monkeypatch, 글응답, 댓글응답=None):
    부른 = []

    def get(url, **kw):
        부른.append(url)
        if "/comments/" in url:
            return 댓글응답 or 응답(200, {"result": {"comments": {"items": []}}})
        if "apis.naver.com" in url:
            return 글응답
        return 응답(200, text='g_sClubId = "10050813"')

    monkeypatch.setattr(G, "requests", types.SimpleNamespace(get=get))
    monkeypatch.setattr(G, "쉬기", lambda: None)
    return 부른


글 = {"url": "https://cafe.naver.com/cosmania/38470688?art=TOKEN1", "keyword": "두피 클렌징",
      "stage": 3, "product": "샴푸"}


def test_글은_v2_1_주소로_읽는다(monkeypatch):
    부른 = _가짜요청(monkeypatch, 응답(200, {"result": {"article": {
        "subject": "제목", "contentHtml": "<p>본문 한 줄</p>", "writer": {"nick": "글쓴이"}}}}))
    post = G.한건수집(dict(글))
    assert "_실패" not in post and post["title"] == "제목" and post["author"] == "글쓴이"
    주소 = next(u for u in 부른 if "/articles/38470688" in u and "/comments" not in u
                and "apis.naver.com" in u)
    assert "/cafe-articleapi/v2.1/cafes/10050813/articles/38470688" in 주소
    assert "useCafeId=true" in 주소 and "requestFrom=A" in 주소
    assert "art=TOKEN1" in 주소
    assert not any("/v3/" in u for u in 부른)


def test_삭제된_글만_글없음404로_적는다(monkeypatch):
    _가짜요청(monkeypatch, 응답(404, {"result": {"errorCode": "4003",
                                               "reason": "삭제되었거나 존재하지 않는 게시글입니다."}}))
    post = G.한건수집(dict(글))
    assert post["_실패"] == "글 없음(404)"
    assert G.삭제인가(post)


def test_4003이_아닌_404는_삭제로_보지_않는다(monkeypatch):
    """주소가 또 바뀌어 404 가 나면 살아 있는 글 전부를 '삭제'로 영영 빼 버린다 — 그걸 막는다."""
    _가짜요청(monkeypatch, 응답(404, {"errorCode": "404"}))
    post = G.한건수집(dict(글))
    assert "글 없음(404)" not in post["_실패"]
    assert not G.삭제인가(post)


def test_서버오류는_글없음이_아니라_못읽음이다(monkeypatch):
    _가짜요청(monkeypatch, 응답(500, {"errorCode": "9999", "errorMessage": "오류가 발생하였습니다."}))
    post = G.한건수집(dict(글))
    assert "글 없음" not in post["_실패"]
    assert "못 읽음" in post["_실패"] and "500" in post["_실패"]
    assert not G.삭제인가(post)


# ── 2. 못 읽은 글은 시트 행을 건드리지 않는다 ───────────────────────────
class 가짜탭:
    def __init__(self, 값들):
        self.값들 = [list(r) for r in 값들]
        self.바꾼것, self.더한것 = [], []

    def get_all_values(self):
        return self.값들

    def batch_update(self, 목록):
        self.바꾼것.extend(목록)

    def append_rows(self, 행들, **kw):
        self.더한것.extend(행들)


def _행(링크, 판정, 걸린것, 측정="글537", 검사일="2026-09-22"):
    return ["k", "", "", "", "", 링크, 판정, 걸린것, 측정, 검사일]


def test_삭제가_아닌_수집실패는_행과_검사일을_덮어쓰지_않는다():
    ws = 가짜탭([G.헤더, _행("u/살아있음", "불합격", "글자수: 400")])
    G.시트반영(ws, [], [{"url": "u/살아있음", "keyword": "k", "_실패": "글을 못 읽음(500 · 9999)"}])
    assert ws.바꾼것 == [] and ws.더한것 == []


def test_새_글도_못_읽었으면_행을_만들지_않는다():
    ws = 가짜탭([G.헤더])
    G.시트반영(ws, [], [{"url": "u/새글", "keyword": "k", "_실패": "Timeout"}])
    assert ws.더한것 == []


def test_삭제된_글은_예전처럼_수집실패_글없음404로_적는다():
    ws = 가짜탭([G.헤더, _행("u/지워짐", "불합격", "글자수")])
    G.시트반영(ws, [], [{"url": "u/지워짐", "keyword": "k", "_실패": "글 없음(404)"}])
    assert len(ws.바꾼것) == 1
    row = ws.바꾼것[0]["values"][0]
    assert row[G.헤더.index("판정")] == "수집실패"
    assert row[G.헤더.index("무엇이 걸렸나")] == "글 없음(404)"


# ── 3. 보고를 보낼 날 · 첫 줄 ───────────────────────────────────────────
def 결과(키워드, 판정, 치명=(), 주의=()):
    지적 = ([{"등급": "치명", "내용": c} for c in 치명]
            + [{"등급": "주의", "내용": w} for w in 주의])
    return ({"keyword": 키워드, "작업자": "", "url": f"u/{키워드}"},
            {"판정": 판정, "지적": 지적})


def 요약(결과들=(), 실패들=(), 지난판정=None, 시트오류=""):
    return {"결과들": list(결과들), "실패들": list(실패들), "건너뜀": [], "시간초과": [],
            "시트오류": 시트오류, "수": Counter(r["판정"] for _, r in 결과들),
            "지난판정": 지난판정 or {}, "누적삭제": 0, "죽은자리": []}


def test_고칠_글이_없는_날은_보내지_않는다():
    assert G.보고만들기(요약([결과("a", "합격"), 결과("b", "합격")]), "") is None


def test_전부터_걸려_있던_글만_있으면_보내지_않는다():
    요 = 요약([결과("a", "불합격", 치명=["글자수"])], 지난판정={"u/a": "불합격"})
    assert G.보고만들기(요, "") is None


def test_보류만_새로_나온_날은_보내지_않는다():
    assert G.보고만들기(요약([결과("a", "보류", 주의=["감정자음"])]), "") is None


def test_새로_걸린_불합격이_있으면_보낸다():
    본문 = G.보고만들기(요약([결과("새글", "불합격", 치명=["글자수: 400"])],
                            지난판정={"u/새글": "합격"}), "")
    assert 본문 and "· 새글 — 글자수: 400" in 본문


def test_읽는_방법이_막힌_날은_반드시_보내고_첫줄에_누가_고칠지_적는다():
    실패 = [{"keyword": f"k{i}", "url": f"u/{i}", "_실패": "글을 못 읽음(500 · 9999)"}
            for i in range(148)]
    본문 = G.보고만들기(요약([], 실패), "")
    assert 본문
    첫줄 = 본문.splitlines()[0]
    assert "읽는 방법이 막힘" in 첫줄 and "Claude가 고칠 일" in 첫줄
    assert "500" in 본문 and "148" in 본문
    assert "네이버가 막고 있을 수 있습니다" not in 본문


def test_삭제가_절반을_넘는_날은_삭제로_알린다():
    실패 = [{"keyword": f"k{i}", "url": f"u/{i}", "_실패": "글 없음(404)"} for i in range(10)]
    본문 = G.보고만들기(요약([결과("a", "합격")], 실패), "")
    assert 본문 and "삭제" in 본문.splitlines()[0]


def test_시트에_못_쓴_날은_보낸다():
    assert G.보고만들기(요약([결과("a", "합격")], 시트오류="권한 없음"), "")


def test_되살아난_판정은_새로_걸림으로_늘어놓지_않고_요약_한_통():
    """고친 뒤 첫 실행: 4주 동안 '수집실패'로 덮였던 글이 다시 채점된다."""
    되살 = ([결과(f"r{i}", "불합격", 치명=["글자수"]) for i in range(3)]
            + [결과(f"p{i}", "합격") for i in range(7)])
    지난 = {f"u/r{i}": "수집실패" for i in range(3)} | {f"u/p{i}": "수집실패" for i in range(7)}
    본문 = G.보고만들기(요약(되살, 지난판정=지난), "")
    assert 본문
    assert "되살아난 판정 10건" in 본문 and "그중 고칠 글 3건" in 본문
    assert "· r0" not in 본문            # 되살아난 글을 하나씩 늘어놓지 않는다


def test_되살아난_날에도_진짜_새로_걸린_글은_목록에_나온다():
    결과들 = [결과("r0", "불합격", 치명=["글자수"]), 결과("새글", "불합격", 치명=["키워드: 본문 0"])]
    본문 = G.보고만들기(요약(결과들, 지난판정={"u/r0": "수집실패"}), "")
    assert "· 새글" in 본문 and "· r0" not in 본문


# ── main: 안 보내는 날은 실패로 끝내지 않는다 ─────────────────────────────
def _main준비(monkeypatch, 요):
    보낸 = []
    monkeypatch.setattr(G, "SheetsClient", lambda *a: types.SimpleNamespace(
        spreadsheet=types.SimpleNamespace(url="")))
    monkeypatch.setattr(G, "검수하기", lambda *a: 요)
    monkeypatch.setattr(G, "알림보내기", lambda 본문: 보낸.append(본문) or True)
    monkeypatch.setattr(G, "_알림표시남기기", lambda: None)
    monkeypatch.setenv("SPREADSHEET_ID", "x")
    monkeypatch.setenv("SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GEOMSU_NOTIFY", "1")
    return 보낸


def test_고칠_글_없는_날은_보내지_않고_성공으로_끝난다(monkeypatch):
    보낸 = _main준비(monkeypatch, 요약([결과("a", "합격")]))
    assert G.main() == 0
    assert 보낸 == []


def test_새로_걸린_글이_있는_날은_보내고_성공으로_끝난다(monkeypatch):
    보낸 = _main준비(monkeypatch, 요약([결과("a", "불합격", 치명=["글자수"])]))
    assert G.main() == 0
    assert len(보낸) == 1


def test_읽는_방법이_막힌_날은_보내고_실패로_끝난다(monkeypatch):
    실패 = [{"keyword": "k", "url": f"u/{i}", "_실패": "글을 못 읽음(500 · 9999)"} for i in range(5)]
    보낸 = _main준비(monkeypatch, 요약([], 실패))
    assert G.main() == 1
    assert len(보낸) == 1 and "읽는 방법이 막힘" in 보낸[0].splitlines()[0]


# ── 같은 v3 글 읽기 주소를 쓰던 다른 자리 ─────────────────────────────────
@pytest.mark.parametrize("파일", ["scripts/balhaeng_geomsu.py", "scripts/collect_comment_brands.py",
                                  "scripts/collect_published_posts.py",
                                  "scripts/probe_cafe_article_access.py"])
def test_v3_글_읽기_주소가_남아_있지_않다(파일):
    본문 = (ROOT / 파일).read_text(encoding="utf-8")
    # v3 '글' 주소만 본다(주소가 /articles/{글} 에서 끝남). v3 '댓글' 주소(…/comments?)는
    # 지금도 정상이라 그대로 둔다(10/20 경쟁사 로그 '못 연 글 0개').
    줄들 = 본문.replace('"\n', "").replace("f\"", "")
    남은 = [m.group(0) for m in re.finditer(
        r"cafe-articleapi/v3/cafes/\{[^}]+\}\s*/articles/\{[^}]+\}(?!/comments)", 줄들)]
    assert not 남은, f"{파일}: {남은}"


# ── GPT 교차 검토 1차(2026-10-21) 지적을 못 박는다 ─────────────────────────
def test_절반이_안_돼도_못_읽은_글이_몰리면_보낸다():
    """한 카페만 막혀도(전체의 절반 미만) 조용해지면 안 된다."""
    결과들 = [결과(f"a{i}", "합격") for i in range(75)]
    실패 = [{"keyword": "k", "url": f"u/f{i}", "_실패": "글을 못 읽음(500 · 9999)"} for i in range(75)]
    본문 = G.보고만들기(요약(결과들, 실패), "")
    assert 본문 and "Claude가 볼 일" in 본문.splitlines()[0] and "75" in 본문.splitlines()[0]


def test_가끔_한두건_못_읽은_날은_보내지_않는다():
    결과들 = [결과(f"a{i}", "합격") for i in range(140)]
    실패 = [{"keyword": "k", "url": "u/f", "_실패": "Timeout"}]
    assert G.보고만들기(요약(결과들, 실패), "") is None


def test_시간이_모자라_다_못_본_날은_보낸다():
    요 = 요약([결과("a", "합격")])
    요["시간초과"] = [{}] * 149
    본문 = G.보고만들기(요, "")
    assert 본문 and "시간이 모자라 못 본 글 149건" in 본문


def test_삭제_머리줄의_숫자가_실제와_맞다():
    """성공 49 · 삭제 26 · 일시 오류 25 — '절반 이상 삭제'라고 쓰면 틀린 말이다."""
    결과들 = [결과(f"a{i}", "합격") for i in range(49)]
    실패 = ([{"keyword": "k", "url": f"u/d{i}", "_실패": "글 없음(404)"} for i in range(26)]
            + [{"keyword": "k", "url": f"u/t{i}", "_실패": "Timeout"} for i in range(25)])
    첫줄 = G.보고만들기(요약(결과들, 실패), "").splitlines()[0]
    assert "절반 이상이 카페에서 삭제" not in 첫줄
    assert "100건 중 26건" in 첫줄


def test_댓글_사이_경계를_넘어_키워드를_세지_않는다():
    """'…두피' 로 끝나는 댓글 + '클렌징…' 으로 시작하는 댓글을 붙여 한 번 더 세던 오류."""
    sys.path.insert(0, str(ROOT / "scripts" / "audit"))
    spec = importlib.util.spec_from_file_location("cg", ROOT / "scripts" / "audit" / "댓글_게이트검사.py")
    CG = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CG)
    칸 = ["A : 두피클렌징 두피클렌징 두피클렌징 두피클렌징 두피클렌징",
          "B : 저도 고민이에요 두피", "C : 클렌징 해 보세요"]
    fails, _ = CG.check("\n\n".join(칸), "두피 클렌징", "두피염", "샴푸", 공백무시=True)
    assert not any(f.startswith("[3]") for f in fails), fails


def test_검수탭을_일시적으로_못_읽으면_지난판정_없음으로_넘기지_않는다():
    """읽기 실패를 '탭 없음'으로 보면 전부터 걸린 글이 전부 '새로 걸림'으로 보고된다."""
    def worksheet(이름):
        raise RuntimeError("503 Service Unavailable")
    sc = types.SimpleNamespace(spreadsheet=types.SimpleNamespace(worksheet=worksheet))
    with pytest.raises(RuntimeError):
        G.이전기록(sc)


def test_검수탭이_정말_없으면_빈값이다():
    import gspread

    def worksheet(이름):
        raise gspread.exceptions.WorksheetNotFound(이름)
    sc = types.SimpleNamespace(spreadsheet=types.SimpleNamespace(worksheet=worksheet))
    assert G.이전기록(sc) == (set(), {}, [])


def test_키워드_분류가_비어_검사_못_한_글이_있으면_보낸다():
    """GPT 검토 2차: 단계가 없어 건너뛴 글은 시트에도 안 적혀, 보고마저 없으면 아무도 모른다."""
    요 = 요약([결과("a", "합격")])
    요["건너뜀"] = [("샴푸 카외", "k")] * 149
    본문 = G.보고만들기(요, "")
    assert 본문 and "검사 못 한 글 149건" in 본문
